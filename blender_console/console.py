"""
console.py — Blender AI 建模控制台 · 正式入口（替代 gn_console.py 原型）
=========================================================================

单一入口，产出的就是 M8-2 注册到 MCP 的底层工具。
整合 m1_core 数据层 + gn_adapter 编译层 + gn_verify 验证层 + M9-3 渲染 diff。

工单项覆盖：
  M1-1~8  数据层（m1_core 已交付，本模块消费）
  M2-1~5  验证层（本模块的 verify/verify_transition）
  M3-1~5  回退层（本模块的 checkpoint/revert/pop_layer/impact_preview）
  M4-7~8  Schema 校验 + 结构化错误
  M9-1    对话即前端：tool return format
  M9-3    渲染 diff 管线
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import bpy

from gn_adapter import GNAdapter, GNValidationError, ParamSpec
from gn_session import ATTR_NAME, read_face_attribution, stamp_attribution
from gn_verify import GeometryVerifier
from op_compiler import OPS, OpCompileError, compile_op, _gi, _go
from mat_compiler import MaterialConstraintError
from rig_compiler import RigConstraintError, compile_rig
from gn_artifact import GNArtifact
from render_diff import RenderDiffer
from m1_core import (CycleError, FlowDAG, LogOnly, ParamUpdate, PivotBlocked,
                     RevisionTable, SagaTag, SegmentCommits, SnapshotStore,
                     StepRecord, VersionedParams, WALLog, export_state)
from plan_schema import PlanSchema

__all__ = ["ConsoleResult", "Console", "ConsoleError"]


# ══════════════════════════════════════════════════════════════
# 统一返回格式（M9-1：对话即前端——AI 消费这个，不消费裸文本）
# ══════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class ConsoleResult:
    """每个操作的统一返回。M9-1：LLM 消费这个 dict，不消费裸文本。"""
    action: str                        # "compile" | "set_param" | "verify" | "checkpoint" | "revert" | "pop_layer" | "diff"
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    # B1 段落三件套：
    render_diff_b64: str = ""          # 渲染 diff 图（base64 PNG，空=无 diff 图）
    summary: str = ""                  # 一句"这段做了什么"
    refutable_assumption: str = ""     # 一条可反驳的假设（不是十条）
    # 结构化错误（M4-8）：
    error: dict[str, Any] | None = None

    def to_tool_return(self) -> dict[str, Any]:
        """M9-1：MCP 工具返回值的标准格式——LLM 直接消费。"""
        out: dict[str, Any] = {"action": self.action, "ok": self.ok}
        if self.summary:
            out["summary"] = self.summary
        if self.refutable_assumption:
            out["refutable_assumption"] = self.refutable_assumption
        if self.render_diff_b64:
            out["render_diff_b64"] = self.render_diff_b64
        if self.data:
            out["data"] = self.data
        if self.error:
            out["error"] = self.error
        return out


class ConsoleError(Exception):
    """带结构化信息的控制台异常。"""
    def __init__(self, result: ConsoleResult):
        self.result = result
        super().__init__(json.dumps(result.to_tool_return(), ensure_ascii=False))


# ══════════════════════════════════════════════════════════════
# Console：统一入口
# ══════════════════════════════════════════════════════════════
class Console:
    """Blender AI 建模控制台。

    用法（在 Blender Python 环境中）：
        ad = GNAdapter(bpy)
        con = Console(ad, obj)
        con.compile(spec)
        result = con.set_param("S2", "Handle_Thickness", 0.007)
        # result 是 ConsoleResult，直接序列化给 LLM
    """

    def __init__(self, ad: GNAdapter, obj: bpy.types.Object,
                 workdir: str | Path | None = None) -> None:
        self.ad = ad
        self.obj = obj
        self.bpy = ad.bpy
        self._workdir = Path(workdir) if workdir else None
        self.differ: RenderDiffer | None = None
        self.deps = self.bpy.context.evaluated_depsgraph_get()
        self.dag = FlowDAG()
        self.wal = WALLog(Path(workdir) / "events.jsonl" if workdir else None)
        # A1（2026-09-28）：快照内容寻址落盘——checkpoint 的恢复前置条件。
        # 无 workdir（内存模式）退化为进程内 dict，has/get/put 语义不变。
        self.snapshots = SnapshotStore(
            Path(workdir) / "snapshots" if workdir else None)
        self.table = RevisionTable(self.dag)
        self.vparams = VersionedParams()
        self.commits = SegmentCommits()
        self.verifier = GeometryVerifier(budget_faces=300_000, ground_z=-1.0)
        self.segments: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self.checkpoints: dict[str, dict[str, Any]] = {}
        self.thoughts: dict[str, dict[str, Any]] = {}
        self.overrides = 0
        self.pivots: list[str] = []
        self._deps_hint: dict[str, tuple[str, ...]] = {}
        self._specs: dict[str, dict[str, Any]] = {}
        # M4-9：归属簿记（与 gn_session 同一机制/同一属性名）
        self._seg_index: dict[str, int] = {}
        self.attribution: dict[int, str] = {}
        # M5：A/B 交互状态机（同一时刻至多一张待决 A/B 卡）
        self._ab: dict[str, Any] | None = None
        # M6：经验库 + 偏好学习（attach_experience 激活；缺省关闭零开销）
        self.library: Any | None = None
        self.pref: Any | None = None

    # ── 内部工具 ──────────────────────────────────────────────
    def _err(self, action: str, code: str, node: str,
             reason: str, suggestions: list[dict] | None = None) -> ConsoleResult:
        err = {"error_code": code, "failed_node": node, "reason": reason,
               "suggestions": suggestions or []}
        return ConsoleResult(action=action, ok=False, error=err)

    def _ok(self, action: str, summary: str = "",
            assumption: str = "", data: dict | None = None,
            diff_b64: str = "") -> ConsoleResult:
        return ConsoleResult(action=action, ok=True, summary=summary,
                             refutable_assumption=assumption,
                             render_diff_b64=diff_b64,
                             data=data or {})

    def _eval_stats(self) -> dict[str, float]:
        self.deps.update()
        ev = self.obj.evaluated_get(self.deps)
        m = ev.to_mesh()
        area = sum(p.area for p in m.polygons)
        xs = [v.co.x for v in m.vertices]
        ys = [v.co.y for v in m.vertices]
        zs = [v.co.z for v in m.vertices]
        st = {"faces": float(len(m.polygons)), "verts": float(len(m.vertices)),
              "area": round(area, 8),
              "bbox": [round(max(xs) - min(xs), 6), round(max(ys) - min(ys), 6),
                       round(max(zs) - min(zs), 6)] if xs else [0, 0, 0]}
        ev.to_mesh_clear()
        return st

    def _output_fp(self, st: dict[str, float]) -> str:
        blob = json.dumps({"a": st["area"], "b": st["bbox"]}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def invalidate(self) -> None:
        self.ad.invalidate(obj=self.obj)

    # ── 思维图 ────────────────────────────────────────────────
    def add_thought(self, tid: str, claim: str,
                    governs: dict[str, str] | None = None) -> None:
        self.thoughts[tid] = {"claim": claim, "governs": governs or {},
                              "status": "ACTIVE"}

    def set_deps(self, seg: str, deps: Sequence[str]) -> None:
        self._deps_hint[seg] = tuple(deps)

    # ── 编译核心（M4-3 转正；M3-6 起 compile/recompile 共用）──
    def _build_tree(self, name: str, clean: dict[str, Any],
                    build_hook: Callable | None = None):
        """clean spec → ("ok", tree, sid, defaults) | ("err", code, reason, suggestions)。

        compile 与 recompile 的单一事实源：树构建 + 参数提升 + op 编译 +
        结构化错误转换。schema 预校验由调用方各自负责（recompile 也要过）。
        build_hook 必须从**原始 spec** 取（`_build` 是下划线宿主钩子，
        compile 预校验前会从 clean 里剥掉——console_live 回归抓出的教训）。
        """
        tree = self.ad.new_group(name)
        sid: dict[str, str] = {}
        if clean.get("consumes_input"):
            sid["Incoming_Geometry"] = self.ad.promote_input(
                tree, ParamSpec("Incoming_Geometry", "GEOMETRY"))
        params = clean.get("parameters", [])
        defaults: dict[str, Any] = {}
        for p in params:
            pn = p["name"] if isinstance(p, dict) else p.name
            pt = p.get("type", "FLOAT") if isinstance(p, dict) else "FLOAT"
            pd = p.get("default", p.get("value", 0.0)) if isinstance(p, dict) else 0.0
            defaults[pn] = pd
            sid[pn] = self.ad.promote_input(
                tree, ParamSpec(pn, pt, pd,
                                p.get("min"), p.get("max"),
                                p.get("unit", ""), p.get("description", "")))
        self.ad.promote_output(tree, "Geometry", "GEOMETRY")

        # M4-3：AI 直出 op-JSON → 注册表编译器（结构保证 R12/D2）；
        # _build 仅是宿主侧测试钩子，两条路都没有 = 响亮失败
        if build_hook is not None and callable(build_hook):
            build_hook(self.ad, tree, sid)
        elif clean.get("op"):
            try:
                src = None
                if clean.get("consumes_input"):
                    src = (_gi(self.ad, tree), "Incoming_Geometry")
                out_node, out_sock = compile_op(self.ad, tree, clean, sid, src)
                self.ad.link(tree, out_node, out_sock,
                             _go(self.ad, tree), "Geometry")
            except OpCompileError as e:
                return ("err", e.code, e.reason, e.suggestions)
            except MaterialConstraintError as e:
                # M4-11：mat_compiler 物理约束失败 → 同一 M4-8 结构化通道
                return ("err", e.code, e.reason, e.suggestions)
        else:
            return ("err", "NO_GEOMETRY_SOURCE",
                    "spec 无 op 也无 _build——AI 必须直出 op-JSON（R12/D2）",
                    [{"action": "add_field", "target": "op",
                      "value": sorted(OPS)}])
        return ("ok", tree, sid, defaults)

    def compile(self, spec: dict[str, Any]) -> ConsoleResult:
        """从声明式 spec 编译段落。spec 是 dict（不是 SegmentSpec 对象）。"""
        action = "compile"
        name = spec.get("id", "")
        if not name:
            return self._err(action, "MISSING_ID", "$", "段落缺少 id")

        # M4-7：预校验（只校验声明式契约；下划线前缀 = 宿主侧钩子，不入契约）
        clean = {k: v for k, v in spec.items() if not k.startswith("_")}
        schema = PlanSchema(segment_names=[s.get("id", "") for s in self._specs.values()])
        issues = schema.validate({"sections": [clean]})
        errors = [i for i in issues if i.level == "error"]
        if errors:
            return self._err(action, "SCHEMA_FAIL", name,
                             "; ".join(str(e) for e in errors[:3]))

        tag = self._build_tree(name, clean, spec.get("_build"))
        if tag[0] == "err":
            _, code, reason, sug = tag
            return self._err(action, code, name, reason, sug)
        _, tree, sid, defaults = tag

        # M4-12b：段落级 rig_json（场景级资产，与 GN socket 流正交）——
        # GN 树编成后、落栈前编译 rig；失败走同一 M4-8 结构化通道（无半产物落栈）。
        # rig 幂等由 compile_rig 指纹自管（复用/重建）；recompile 不重触发 rig，
        # rig 变更走重新 compile（指纹变更 → wipe 重建）。
        rig_detail = None
        if clean.get("rig_json") is not None:
            try:
                rig_detail = compile_rig(bpy, clean["rig_json"])
            except RigConstraintError as e:
                return self._err(action, e.code, name, e.reason, e.suggestions)

        idx = self._seg_index.setdefault(name, len(self._seg_index) + 1)
        self.attribution[idx] = name
        stamp_attribution(tree, ATTR_NAME, idx)   # M4-9：树尾归属（挂栈前盖）

        mod = self.ad.attach(self.obj, tree, name)
        # M3-6：autogenerated 标记（5.2 modifier 不支持 IDProperty，probe 实锤
        # TypeError → 降级为保留名前缀约定）。前缀可存活 .blend 重载；
        # 艺术家改掉前缀 = 接管该产物，recompile 拒绝覆盖（NOT_AUTOGENERATED）。
        mod.name = f"AI_{name}"
        fp = self.ad.fingerprint(tree)[:16]

        deps = self._deps_hint.get(name, ())
        if not deps and self.order:
            prev_step = f"step:{self.order[-1]}"
            deps = (prev_step,)

        # （重构 M3-6 时抓出的原有潜伏 bug：genexpr 引用了 for 循环泄漏的
        #   pn——所有参数名都被记成最后一个参数名。现按真实名字记账。）
        step = StepRecord(
            step_id=f"step:{name}", seg=name, obj=self.obj.name,
            params=tuple((p["name"], p.get("value", 0)) if isinstance(p, dict)
                         else (str(p), 0)
                         for p in clean.get("parameters", [])),
            deps=deps, seed=0, revision=self.table.global_revision,
        )
        self.dag.add(step)

        # 参数域播种默认值（只补缺口）——回退需要"未写过的参数"也有值可滚回
        cur = self.vparams.get()
        fresh = {f"{name}.{pn}": v for pn, v in defaults.items()
                 if f"{name}.{pn}" not in cur}
        if fresh:
            self.vparams.set_many(fresh)

        rec = {"spec": spec, "tree": tree, "sid": sid, "mod": mod,
               "fingerprint": fp, "step_id": f"step:{name}",
               "artifact": GNArtifact(self.ad, tree, sid, name, spec),  # M4-2：产物可寻址单元
               "rig": rig_detail}   # M4-12b：段落 rig 资产对账面（None=无）
        self.segments[name] = rec
        if name not in self.order:
            self.order.append(name)

        self.wal.append("compile", {"seg": name, "fingerprint": fp})
        self._specs[name] = spec

        # W-7 接线（2026-09-29）：段交付 = 内容寻址 commit（m1_core A33）——
        # 同参数+同输出自动去重；revert/set_param 后重编译产出新 hash。
        # commits 是只增史册（Git 对象模型缩到段粒度），export_state 可读。
        self.commits.commit(name, dict(self.vparams.get()),
                            f"fp:{fp}", deps=deps)

        data = {"fingerprint": fp, "nodes": len(tree.nodes)}
        if rig_detail is not None:
            data["rig"] = {"metarig": rig_detail["metarig"], "rig": rig_detail["rig"],
                           "fingerprint": rig_detail["fingerprint"],
                           "deform_patched": rig_detail.get("deform_patched", False),
                           "reused": rig_detail["reused"]}
        return self._ok(action, f"编译 {name}（{len(tree.nodes)} 节点）", data=data)

    # ── M3-6 重编译（栈序恢复 + autogenerated 标记）───────────
    def recompile(self, name: str,
                  new_spec: dict[str, Any] | None = None) -> ConsoleResult:
        """重编译一个段落：只替换本段的 AI 标记 modifier，原索引放回。

        M3-6（d2-engine）：AI 产物一律打 `autogenerated` 标记——5.2 modifier
        不支持 IDProperty（probe 实锤），降级为保留名前缀 `AI_`（可存活
        .blend 重载）。重编译语义：
          * 只替换**标记项**：摘旧 → 新树 attach 落栈尾 → move 回旧位
            （照 gn_session B3 修法）——未标记项（艺术家手动加的 Subdivision
            等）相对顺序与原索引完整保留（删 i 位再插回 i 位，其余元素
            索引不变，机械可证）。
          * 前缀被摘 = 艺术家接管 → 拒绝覆盖（NOT_AUTOGENERATED，M4-8 结构化）。
          * 参数重放：vparams 已写值回填新 modifier；新增参数以默认值入账
            （只补缺口，已写参数不许被重编译重置——gn_session live 45/46 教训）。
          * gn_delta：新旧树 diff 留档（A33 跨版本 DAG 可 diff）。
        """
        action = "recompile"
        rec = self.segments.get(name)
        if not rec:
            return self._err(action, "SEG_NOT_FOUND", name, f"段落 {name!r} 不存在")
        mod = rec["mod"]
        if not str(mod.name).startswith("AI_"):
            return self._err(action, "NOT_AUTOGENERATED", name,
                             f"modifier {mod.name!r} 无 AI_ 标记（可能已被艺术家"
                             "接管）——拒绝 AI 重编译覆盖人工产物",
                             [{"action": "manual_review", "target": name,
                               "value": None}])
        new_spec = new_spec or rec["spec"]
        clean = {k: v for k, v in new_spec.items() if not k.startswith("_")}
        schema = PlanSchema(segment_names=[s.get("id", "") for s in self._specs.values()])
        issues = schema.validate({"sections": [clean]})
        errors = [i for i in issues if i.level == "error"]
        if errors:
            return self._err(action, "SCHEMA_FAIL", name,
                             "; ".join(str(e) for e in errors[:3]))

        old_idx = list(self.obj.modifiers).index(mod)     # B3：先记旧位
        old_tree = rec["tree"]
        self.obj.modifiers.remove(mod)

        tag = self._build_tree(name, clean, new_spec.get("_build"))
        if tag[0] == "err":
            _, code, reason, sug = tag
            return self._err(action, code, name, reason, sug)
        _, tree, sid, defaults = tag

        idx = self._seg_index.setdefault(name, len(self._seg_index) + 1)
        self.attribution[idx] = name
        stamp_attribution(tree, ATTR_NAME, idx)

        mod = self.ad.attach(self.obj, tree, name)
        mod.name = f"AI_{name}"                           # 标记随重编译延续
        new_idx = len(self.obj.modifiers) - 1
        if new_idx != old_idx:
            self.obj.modifiers.move(new_idx, old_idx)     # B3：移回旧位
        fp = self.ad.fingerprint(tree)[:16]

        # 参数重放：已写参数回填；新增参数以默认值入账（只补缺口）
        cur = self.vparams.get()
        reapplied: dict[str, Any] = {}
        for pn in sid:
            key = f"{name}.{pn}"
            if key in cur:
                self.ad.set_instance_input(mod, sid[pn], cur[key])
                reapplied[key] = cur[key]
        fresh = {f"{name}.{pn}": v for pn, v in defaults.items()
                 if f"{name}.{pn}" not in cur}
        if fresh:
            self.vparams.set_many(fresh)

        gn_delta = self.ad.diff(old_tree, tree)           # A33：新旧树 diff 留档
        self.segments[name] = {"spec": new_spec, "tree": tree, "sid": sid,
                               "mod": mod, "fingerprint": fp,
                               "step_id": f"step:{name}",
                               "artifact": GNArtifact(self.ad, tree, sid, name,
                                                      new_spec)}
        self._specs[name] = new_spec
        self.wal.append("recompile", {"seg": name, "mod_index": old_idx,
                                      "fingerprint": fp,
                                      "reapplied": reapplied,
                                      "gn_delta": gn_delta})
        return self._ok(action,
                        f"重编译 {name}：栈位 {old_idx} 保留，"
                        f"参数重放 {len(reapplied)} 项",
                        data={"mod_index": old_idx, "gn_delta": gn_delta,
                              "reapplied": reapplied, "fingerprint": fp})

    # ── 参数写入（M3/A28 backdating）──────────────────────────
    def set_param(self, seg: str, param: str, value: Any) -> ConsoleResult:
        rec = self.segments.get(seg)
        if not rec:
            return self._err("set_param", "SEG_NOT_FOUND", seg, f"段落 {seg!r} 不存在")
        sid = rec["sid"].get(param)
        if not sid:
            return self._err("set_param", "PARAM_NOT_FOUND", f"{seg}.{param}",
                             f"段落 {seg!r} 没有参数 {param!r}")

        old = self.vparams.get().get(f"{seg}.{param}")
        pu = ParamUpdate(seg, param, old, value)
        self.vparams.set_many({f"{seg}.{param}": pu.new})

        fp_src = {k: v for k, v in self.vparams.get().items() if k.startswith(seg + ".")}
        fp = json.dumps(fp_src, sort_keys=True, ensure_ascii=False, default=str)
        dirty = self.table.touch(seg, fp)
        self.ad.set_instance_input(rec["mod"], sid, pu.new)
        art = rec.get("artifact")   # M4-2：artifact.param_values 与 vparams 保持同源
        if art is not None:
            art.param_values[param] = pu.new
        self.wal.append("param", {"seg": seg, "param": param, "old": old, "new": pu.new})

        st = self._eval_stats()
        changed = self.table.report_output(seg, self._output_fp(st))

        return self._ok("set_param",
            f"{seg}.{param}: {old} → {pu.new}（{'几何变化' if changed else '输出未变'}）",
            data={"dirty": dirty, "changed": changed, "stats": st})

    # ── 验证（M2）─────────────────────────────────────────────
    def verify(self, label: str = "") -> ConsoleResult:
        st = self._eval_stats()
        import bpy as _bpy
        _bpy.context.view_layer.update()   # EXP-010：matrix_world 读数前强制刷新（deps.update 不刷原版对象矩阵）
        self.deps.update()
        ev = self.obj.evaluated_get(self.deps)
        m = ev.to_mesh()
        rep = self.verifier.check(m, self.obj)
        nf = len(m.polygons)
        ev.to_mesh_clear()
        self.wal.append("verify", {"label": label, "ok": rep.ok, "faces": nf})
        summary = f"verifier {'PASS' if rep.ok else 'FAIL'}: {nf} 面"
        if not rep.ok:
            summary += " | " + "; ".join(str(f) for f in rep.failures[:3])
        data = {"ok": rep.ok, "faces": nf,
                "failures": [str(f) for f in rep.failures]}
        if rep.ok:
            return self._ok("verify", summary, data=data)
        return ConsoleResult(action="verify", ok=False, data=data, summary=summary,
                             error={"error_code": "VERIFY_FAIL",
                                    "failed_node": label or "scene",
                                    "reason": summary,
                                    "suggestions": []})

    # ── GoodPoint（M3-2 / A14）───────────────────────────────
    def checkpoint(self, name: str, thought_refs: tuple[str, ...] = ()) -> ConsoleResult:
        """GoodPoint（A1/A2 修复 · 2026-09-28）：快照内容寻址落盘。

        mesh+params 序列化进 SnapshotStore（内容寻址去重）；WAL 行 kind 由
        "checkpoint" 改 "restore_point"（A2：与 WALLog.compact 边界
        "compaction_barrier" 拆分命名空间），payload 携带 snapshot_ref——
        快照不在盘上时 compact 拒绝折叠历史（A1 守卫）。
        诚实边界：崩溃后从 WAL+快照重建 console 的恢复 API 属后续工作，
        本修复保证状态不再只存进程内存。
        """
        t0 = time.perf_counter()
        self.deps.update()
        snap = self.ad.bpy.data.meshes.new_from_object(
            self.obj.evaluated_get(self.deps))
        dt = round((time.perf_counter() - t0) * 1000, 3)
        params = dict(self.vparams.get())
        ref = self.snapshots.put({"verts": [tuple(v.co) for v in snap.vertices],
                                  "polys": [tuple(p.vertices) for p in snap.polygons],
                                  "params": params})
        self.checkpoints[name] = {"mesh": snap, "params": params,
                                  "thought_refs": list(thought_refs),
                                  "snapshot_ref": ref}
        self.wal.append("restore_point",
                        {"name": name, "faces": len(snap.polygons),
                         "snapshot_ref": ref})
        return self._ok("checkpoint",
            f"GoodPoint {name}: {len(snap.polygons)} 面，{dt} ms")

    # ── 回退（M3）────────────────────────────────────────────
    def revert_to_checkpoint(self, name: str) -> ConsoleResult:
        if self.pivots:
            return self._err("revert", "PIVOT_BLOCKED", name,
                             f"已有 pivot（{self.pivots}），只许 forward recovery")
        cp = self.checkpoints.get(name)
        if not cp:
            return self._err("revert", "CHECKPOINT_NOT_FOUND", name, "锚点不存在")
        t0 = time.perf_counter()
        for key, val in cp["params"].items():
            seg_name, _, param_name = key.partition(".")
            rec = self.segments.get(seg_name)
            if rec and param_name in rec.get("sid", {}):
                self.ad.set_instance_input(rec["mod"], rec["sid"][param_name], val)
        self.ad.invalidate(obj=self.obj)
        self.deps.update()
        dt = round((time.perf_counter() - t0) * 1000, 3)
        st = self._eval_stats()
        return self._ok("revert",
            f"回退到 {name}：{dt} ms，{st['faces']} 面", data={"ms": dt, **st})

    def pop_layer(self) -> ConsoleResult:
        """物理删层（M3 原语）。2026-09-29 真机实验修复：此前只删 modifier+order.pop，
        DAG/segments/specs 残留孤儿步 → 后续 drop_segment 的叶子约束炸
        （step seg_b 有后继 seg_c——只许删叶子步）。清理对齐 drop_segment
        的机械部分（无 drop_segment WAL 行——账目语义归 drop_segment）。"""
        if self.pivots:
            return self._err("pop_layer", "PIVOT_BLOCKED", "",
                             "pivot 后只许 forward recovery")
        t0 = time.perf_counter()
        name = self.order[-1]
        rec = self.segments.get(name)
        self.obj.modifiers.remove(self.segments[name]["mod"])
        self.order.pop()
        if rec is not None:
            try:
                self.dag.remove(rec["step_id"])   # 2026-09-29：清孤儿步
            except Exception:                      # noqa: BLE001 步不存在时保持幂等
                pass
            self.segments.pop(name, None)
            self._specs.pop(name, None)
        self.ad.invalidate(obj=self.obj)
        self.deps.update()
        dt = round((time.perf_counter() - t0) * 1000, 3)
        st = self._eval_stats()
        return self._ok("pop_layer",
            f"删层 {name}：{dt} ms，{st['faces']} 面", data={"ms": dt, **st})

    def drop_segment(self, name: str) -> ConsoleResult:
        """打回段落（导演 override 的机械部分）：pop_layer（已含 modifier+DAG+
        segments/specs 全清理，2026-09-29）+ drop_segment 账目行。

        只许打回**最后提案**的段落（order[-1]，无后继——DAG 叶子约束同）。
        vparams 里该段的键保留（历史账目不抹；重提同名段时会被新值覆盖）。
        """
        rec = self.segments.get(name)
        if not rec:
            return self._err("drop_segment", "SEG_NOT_FOUND", name,
                             f"段落 {name!r} 不存在")
        if not self.order or self.order[-1] != name:
            return self._err("drop_segment", "NOT_LAST_SEGMENT", name,
                             f"只许打回最后提案的段落（当前最后：{self.order[-1] if self.order else '无'}）")
        pop = self.pop_layer()
        if not pop.ok:
            return pop
        self.wal.append("drop_segment", {"seg": name})
        return self._ok("drop_segment", f"已打回段落 {name}",
                        data={"ms": pop.data.get("ms")})

    def drop_part(self, part: str) -> ConsoleResult:
        """M7-2 子树回退：按 part 打回整个部件（逆提案序逐段下架，DAG 叶子约束自然满足）。"""
        segs = [n for n in self.order
                if (self._specs.get(n) or {}).get("part") == part]
        if not segs:
            return self._err("drop_part", "PART_NOT_FOUND", part,
                             f"part {part!r} 无段落（或已被打回）")
        removed = []
        for name in reversed(segs):        # 逆提案序 = 后代先下架（DAG remove 叶子约束）
            rec = self.segments[name]
            self.obj.modifiers.remove(rec["mod"])
            self.dag.remove(rec["step_id"])
            self.segments.pop(name, None)
            self._specs.pop(name, None)
            self.order.remove(name)
            removed.append(name)
        self.ad.invalidate(obj=self.obj)
        self.deps.update()
        self.wal.append("drop_part", {"part": part, "removed": removed})
        return self._ok("drop_part", f"已打回部件 {part}（{len(removed)} 段）",
                        data={"removed": removed})

    # ── 影响预览（M3-4）──────────────────────────────────────
    def impact_preview(self, seg: str) -> ConsoleResult:
        step = next((s for s in self.dag.all_steps() if s.seg == seg), None)
        if not step:
            return self._err("impact_preview", "SEG_NOT_FOUND", seg, f"段落 {seg!r} 不存在")
        desc = self.dag.descendants(step.step_id)
        downstream = sorted({self.dag.get(d).seg for d in desc} | {seg})
        may_fail = [s for s in downstream if self.segments[s]["spec"].get("consumes_input")]
        return self._ok("impact_preview",
            f"将重推 {len(downstream)} 段：{downstream}，其中 {len(may_fail)} 段可能失败",
            data={"will_replay": downstream, "may_fail": may_fail,
                  "n": len(downstream), "m": len(may_fail)})

    # ── M4-9 查询（与 GNSession.query_attribution 同一实现）──
    def query_attribution(self) -> dict[str, Any]:
        """面归属分布（机械反查：这块面是谁的决策）。"""
        self.deps.update()
        ev = self.obj.evaluated_get(self.deps)
        m = ev.to_mesh()
        out = read_face_attribution(m, ATTR_NAME, self.attribution)
        ev.to_mesh_clear()
        return out

    # ── M9-3 渲染 diff（B1 段落三件套之"图"）──────────────────
    def render_diff(self, label: str = "") -> ConsoleResult:
        """段落边界渲染 diff：同机位 Workbench 256px，红色高亮变化像素。

        首帧 = 基线（无 diff 图）；此后每帧 diff 相对上一帧（段落边界语义）。
        data 携带感知哈希/占比/方差/耗时（M2-3 谓词 + EXP-4 哈希分离度侧）；
        WAL 记 render 事件（北极星"反馈速度"采集点）。
        probe_render 实测：稳态 17ms/帧，确定性 0 像素差。
        """
        if self.differ is None:
            self.differ = RenderDiffer(
                self.bpy, self.obj,
                workdir=self._workdir or Path.cwd() / "_console_renders")
        f = self.differ.render_diff(label or f"frame_{f'{self.differ._frame_n + 1:03d}'}")
        geom_changed = None if f["changed_ratio"] is None else f["changed_ratio"] > 0
        preds = self.differ.check_predicates(f, geom_changed=geom_changed)
        all_ok = self.differ.ok(preds)
        # W-1 接线（2026-09-29）：呈现谓词 → NLG 带化判词（确定性模板，零幻觉）
        # ——视觉反馈环"读报告"侧的机制化；尺寸谓词由宿主按树 machine_spec
        #   评估后同格式并入（见 e2e_live.py 的 _evaluate_gate）。
        from nlg_bands import verdict_report
        pred_list = [{"predicate": k, **(v if isinstance(v, dict) else {"ok": bool(v)})}
                     for k, v in preds.items()]
        verdict = verdict_report(pred_list)
        self.wal.append("render", {"label": f["label"], "ms": f["ms"],
                                   "dhash": f["dhash"], "ahash": f["ahash"],
                                   "changed_ratio": f["changed_ratio"],
                                   "hamming": f["hamming"]})

        if f["changed_ratio"] is None:
            summary = f"基线帧：目标占比 {f['opaque_ratio']:.0%}，{f['ms']} ms"
            assumption = ""
        else:
            summary = (f"渲染 diff：{f['changed_ratio']:.1%} 像素变化"
                       f"（dHash hamming={f['hamming']}，{f['ms']} ms）")
            if f["changed_ratio"] == 0:
                assumption = ("画面零变化——该参数写入未产生可见几何变化："
                              "参数可能不影响几何、或被同值/backdating 截断")
            else:
                assumption = ""
        data = {k: f[k] for k in ("dhash", "ahash", "opaque_ratio", "luma_std",
                                  "ms", "changed_ratio", "changed_px",
                                  "hamming", "png_path", "predicates")}
        data["verdict"] = verdict                  # W-1 接线：NLG 带化判词随帧导出
        if all_ok:
            return self._ok("render_diff", summary, assumption,
                            data=data, diff_b64=f["diff_b64"])
        bad = [k for k, v in preds.items()
               if not (v["ok"] if isinstance(v, dict) else v)]
        return ConsoleResult(
            action="render_diff", ok=False, data=data,
            render_diff_b64=f["diff_b64"], summary=summary,
            refutable_assumption=assumption,
            error={"error_code": "RENDER_PREDICATE_FAIL",
                   "failed_node": "render_diff",
                   "reason": "渲染谓词失败：" + ", ".join(bad),
                   "suggestions": [{"action": "inspect_frame",
                                    "target": f["png_path"], "value": None}]})

    # ── M5 交互层：A/B 二选一（B2/B3/B4/M5-9/10/11）──────────
    def ab_prepare_spec(self, seg: str, variants: list[dict[str, Any]],
                        ai_preferred: int = 0, ai_reason: str = "") -> ConsoleResult:
        """R3 · spec 级 A/B：甲乙 = 两份**结构 spec**（同一段落的两种做法）。

        与参数级 ab_prepare 的差别：
          * 预览 = **树上换**（mod.node_group = 变体树，不动栈序、不落账），
            两帧渲染后还原原树——比 remove/attach 便宜且零栈序风险；
          * 变体树各自由 _build_tree 现编（编译失败 = 结构化拒绝，不出卡）；
          * commit 真写 = 走 recompile 全链（WAL/gn_delta/参数重放/schema 复验）；
          * 信号类型不同：spec 级 commit **不喂 PreferenceModel**（BT 学习的
            权重空间是参数值，结构变体塞进去会污染）——override 计数与
            library.record_override 照常（R15 人的 note 仍随载荷走）。
        """
        action = "ab_prepare_spec"
        if self._ab is not None:
            return self._err(action, "AB_ALREADY_PENDING", seg,
                             "已有待决 A/B 卡——先 ab_commit 再开下一张")
        rec = self.segments.get(seg)
        if not rec:
            return self._err(action, "SEG_NOT_FOUND", seg, f"段落 {seg!r} 不存在")
        if (not isinstance(variants, list) or len(variants) != 2
                or not all(isinstance(v, dict) and v for v in variants)):
            return self._err(action, "BAD_VARIANTS", seg,
                             "variants 必须是两个非空 spec 字典",
                             [{"action": "example", "target": "variants",
                               "value": '[{"op":"cylinder",...}, '
                                        '{"op":"cube",...}]'}])

        # 双变体先各自编译成树（失败响亮拒绝，不出卡）
        built = []
        for i, v in enumerate(variants):
            clean = {k: val for k, val in v.items() if not k.startswith("_")}
            tag = self._build_tree(seg, clean, v.get("_build"))
            if tag[0] == "err":
                _, code, reason, sug = tag
                return self._err(action, f"VARIANT_{i}_BUILD_FAIL", seg,
                                 f"变体 {i} 编译失败：{reason}", sug)
            built.append({"spec": clean, "tree": tag[1], "sid": tag[2]})

        if self.differ is None:
            self.differ = RenderDiffer(
                self.bpy, self.obj,
                workdir=self._workdir or Path.cwd() / "_console_renders")
        cur_mod = rec["mod"]
        orig_tree = cur_mod.node_group
        snap = self.ad.snapshot_instance_inputs(cur_mod)   # 换树前快照——
        frames = []                                        # 迁移会串值（R3 实测）
        try:
            for b in built:                       # 预览：树上换 + 显式写参（不落账）
                cur_mod.node_group = b["tree"]
                # 换树按 identifier 迁移 per-instance 值：跨树 Socket_N 索引
                # 撞车会让旧值串门（cube.Size 吃到 cylinder.Radius 的 0.045）
                # → 预览帧必须显式写 spec 声明值，不吃迁移残值
                for pname, ident in b["sid"].items():
                    val = next((p.get("value")
                                for p in b["spec"].get("parameters", [])
                                if p["name"] == pname), None)
                    if val is not None:
                        self.ad.set_instance_input(cur_mod, ident, val,
                                                   invalidate=False)
                self.ad.invalidate(obj=self.obj)
                frames.append(self.differ.render_preview(f"AB_{seg}"))
        finally:
            cur_mod.node_group = orig_tree        # 无条件还原原树
            self.ad.restore_instance_inputs(cur_mod, snap)   # 重放快照 → 零残留

        seed = int(time.perf_counter() * 1e6) % 1_000_000_007
        labels = ["甲", "乙"]
        random.Random(seed).shuffle(labels)
        label_of = {"0": labels[0], "1": labels[1]}
        ai_pref_label = label_of[str(int(ai_preferred))]
        self._ab = {"seg": seg, "kind": "spec", "variants": built,
                    "labels": label_of, "ai_preferred_label": ai_pref_label,
                    "ai_reason": ai_reason, "seed": seed}
        self.wal.append("ab_prepare", {"seg": seg, "seed": seed,
                                       "mapping": label_of, "kind": "spec",
                                       "ai_preferred_label": ai_pref_label,
                                       "ai_reason": ai_reason,
                                       "variants": [b["spec"] for b in built]})

        vdata: dict[str, Any] = {}
        for i, fr in enumerate(frames):
            lab = label_of[str(i)]
            vdata[lab] = {"spec": built[i]["spec"],
                          "png_b64": base64.b64encode(
                              Path(fr["png_path"]).read_bytes()).decode(),
                          "dhash": fr["dhash"], "png_path": fr["png_path"],
                          "ms": fr["ms"]}
        desc = "；".join(
            f"{label_of[str(i)]}={built[i]['spec'].get('op', '?')}"
            for i in (0, 1))
        return self._ok(action,
                        f"spec A/B 就绪（{seg}）：{desc}。同机位已渲染；"
                        "映射封存。ab_commit：choice ∈ 甲/乙/reroll。",
                        data={"seg": seg, "kind": "spec", "variants": vdata,
                              "choices": ["甲", "乙", "reroll"],
                              "confidence_range": [5, 95]})

    def ab_prepare(self, seg: str, variants: list[dict[str, Any]],
                   ai_preferred: int = 0, ai_reason: str = "") -> ConsoleResult:
        """生成参数级 A/B 两变体：同机位渲染、甲/乙 洗牌标签、映射封存。

        variants：[{"Handle_Thickness": 0.006}, {"Handle_Thickness": 0.012}]
          ——参数级变体；预览**不落账**（set_instance_input 直写，不走
          set_param/vparams/WAL），commit 才走真写（B6 人/AI 通路分离）。
        ai_preferred：AI 自己声明的偏好下标（0/1）。控制台**不打分**（R5），
          只记录 AI 的声明；ai_reason 默认折叠（M5-11）——prepare 的返回里
          不出现，commit 揭晓时才随 reveal 返回。
        B4 先预测再揭晓：返回里没有 甲/乙 ↔ variant 的映射（映射进 WAL）。
        M5-9：commit 的 choice ∈ {甲, 乙, reroll}；M5-10：confidence 5–95。
        B3：人选了非 AI 偏好 → 自动 override 计数（唯一健康指标）。
        R15：A/B 原始信号**不经人的语言化不回流生成**——commit 的 WAL 载荷
          带 note 字段（人的语言），M6-6 偏好学习只许消费带 note 的记录。
        """
        action = "ab_prepare"
        if self._ab is not None:
            return self._err(action, "AB_ALREADY_PENDING", seg,
                             "已有待决 A/B 卡——先 ab_commit 再开下一张")
        rec = self.segments.get(seg)
        if not rec:
            return self._err(action, "SEG_NOT_FOUND", seg, f"段落 {seg!r} 不存在")
        if (not isinstance(variants, list) or len(variants) != 2
                or not all(isinstance(v, dict) and v for v in variants)):
            return self._err(action, "BAD_VARIANTS", seg,
                             "variants 必须是两个非空 {参数名: 值} 字典",
                             [{"action": "example", "target": "variants",
                               "value": '[{"Handle_Thickness": 0.006}, '
                                        '{"Handle_Thickness": 0.012}]'}])
        for i, v in enumerate(variants):
            for p in v:
                if p not in rec["sid"]:
                    return self._err(action, "PARAM_NOT_FOUND", f"{seg}.{p}",
                                     f"段落 {seg!r} 没有参数 {p!r}")
        if ai_preferred not in (0, 1):
            return self._err(action, "BAD_AI_PREFERRED", seg,
                             "ai_preferred 只能是 0 或 1（变体下标）")

        if self.differ is None:
            self.differ = RenderDiffer(
                self.bpy, self.obj,
                workdir=self._workdir or Path.cwd() / "_console_renders")
        cur = self.vparams.get()          # B7 播种保证已声明参数都在账上
        keys = sorted({p for v in variants for p in v})
        orig = {p: cur[f"{seg}.{p}"] for p in keys}
        frames = []
        for v in variants:                # 预览：直写 per-instance，不走账
            for p, val in v.items():
                self.ad.set_instance_input(rec["mod"], rec["sid"][p], val)
            self.ad.invalidate(obj=self.obj)
            frames.append(self.differ.render_preview(f"AB_{seg}"))
        for p, val in orig.items():       # 还原预览现场（commit 才落真写）
            self.ad.set_instance_input(rec["mod"], rec["sid"][p], val)
        self.ad.invalidate(obj=self.obj)

        seed = int(time.perf_counter() * 1e6) % 1_000_000_007
        labels = ["甲", "乙"]
        random.Random(seed).shuffle(labels)      # labels[i] = 变体 i 的标签
        label_of = {"0": labels[0], "1": labels[1]}   # 键用字符串：内存态 == JSONL 回读态
        ai_pref_label = label_of[str(int(ai_preferred))]
        self._ab = {"seg": seg, "variants": variants, "labels": label_of,
                    "ai_preferred_label": ai_pref_label, "ai_reason": ai_reason,
                    "orig": orig, "seed": seed}
        self.wal.append("ab_prepare", {"seg": seg, "seed": seed,
                                       "mapping": label_of, "kind": "param",
                                       "ai_preferred_label": ai_pref_label,
                                       "ai_reason": ai_reason,
                                       "variants": variants})

        vdata: dict[str, Any] = {}
        for i, fr in enumerate(frames):
            lab = label_of[str(i)]
            vdata[lab] = {"params": variants[i],
                          "png_b64": base64.b64encode(
                              Path(fr["png_path"]).read_bytes()).decode(),
                          "dhash": fr["dhash"], "png_path": fr["png_path"],
                          "ms": fr["ms"]}
        desc = "；".join(f"{label_of[str(i)]}={variants[i]}" for i in (0, 1))
        return self._ok(action,
                        f"A/B 就绪（{seg}）：{desc}。同机位已渲染；"
                        "AI 偏好已封存，选定后揭晓。ab_commit：choice ∈ 甲/乙/reroll，confidence 5–95。",
                        data={"seg": seg, "variants": vdata,
                              "choices": ["甲", "乙", "reroll"],
                              "confidence_range": [5, 95]})

    def ab_commit(self, choice: str, confidence: int, note: str = "") -> ConsoleResult:
        """落 A/B 决定：真写选中变体（或 reroll 还原），揭晓映射与 AI 理由。"""
        action = "ab_commit"
        if self._ab is None:
            return self._err(action, "NO_AB_PENDING", "", "没有待决 A/B 卡")
        if choice not in ("甲", "乙", "reroll"):
            return self._err(action, "BAD_CHOICE", choice,
                             "choice ∈ {甲, 乙, reroll}（M5-9 第三出口）")
        try:
            confidence = int(confidence)
        except (TypeError, ValueError):
            confidence = -1
        if not 5 <= confidence <= 95:
            return self._err(action, "CONFIDENCE_OUT_OF_RANGE", str(confidence),
                             "confidence 必须是 5–95 的整数（M5-10 置信度滑条）")
        ab = self._ab
        kind = ab.get("kind", "param")
        reveal = {"ai_preferred": ab["ai_preferred_label"],
                  "ai_reason": ab["ai_reason"],
                  "mapping": {lab: (ab["variants"][int(k)] if kind == "param"
                                    else ab["variants"][int(k)]["spec"])
                              for k, lab in ab["labels"].items()}}
        applied = None
        if choice == "reroll":
            if kind == "param":
                for p, val in ab["orig"].items():   # 显式还原（幂等，预览已还原过）
                    rec = self.segments[ab["seg"]]
                    self.ad.set_instance_input(rec["mod"], rec["sid"][p], val)
                self.ad.invalidate(obj=self.obj)
            # spec 级 reroll：预览结束已还原原树，无需再动（树上换零残留）
        elif kind == "spec":
            idx = int({lab: k for k, lab in ab["labels"].items()}[choice])
            chosen = ab["variants"][idx]
            r = self.recompile(ab["seg"], dict(chosen["spec"], id=ab["seg"]))
            if not r.ok:
                return r                            # recompile 结构化错误直传
            applied = dict(chosen["spec"], id=ab["seg"])
        else:
            idx = int({lab: k for k, lab in ab["labels"].items()}[choice])
            applied = ab["variants"][idx]
            for p, val in applied.items():      # 真写：vparams/dirty/WAL 全链
                self.set_param(ab["seg"], p, val)
        override_counted = False
        if choice != "reroll" and choice != ab["ai_preferred_label"]:
            self.override(note or ("A/B：人选了非 AI 偏好变体" if kind == "param"
                                   else "spec A/B：人选了非 AI 偏好结构"))     # B3 摩擦对称
            override_counted = True
        self.wal.append("ab_commit", {"seg": ab["seg"], "choice": choice,
                                      "confidence": confidence, "note": note,
                                      "ai_preferred_label": ab["ai_preferred_label"],
                                      "seed": ab["seed"],
                                      "kind": kind,
                                      "variants": (ab["variants"] if kind == "param"
                                                   else [b["spec"] for b in ab["variants"]]),
                                      "applied": applied,
                                      "override_counted": override_counted})
        if applied is not None:
            idx = int({lab: k for k, lab in ab["labels"].items()}[choice])
            if kind == "param":
                if self.pref is not None:                          # M6-6 数据流
                    self.pref.observe(ab["variants"][idx],
                                      ab["variants"][1 - idx])
            # spec 级不喂 PreferenceModel（BT 权重空间是参数值，结构变体会
            # 污染权重空间——信号类型不同，诚实分流）
            if override_counted and self.library is not None:      # M6-3 回写
                self.library.record_override(
                    {"seg": ab["seg"], "kind": f"{kind}_ab_override"},
                    note=note or "A/B：人选了非 AI 偏好变体", params=applied)
        self._ab = None
        summary = (f"已采纳 {choice}（置信度 {confidence}%）"
                   if choice != "reroll" else
                   f"已重掷（置信度 {confidence}%）——回到 commit 前状态")
        if kind == "spec" and applied is not None:
            summary += f"，结构已重编译（{applied.get('op', '?')}）"
        return self._ok(action, summary, data={"reveal": reveal,
                                               "applied": applied,
                                               "override_counted": override_counted})

    # ── M6 经验库（薄集成：库 + 偏好学习挂在 A/B 通路）────────
    def attach_experience(self, store: Any | None = None,
                          library_path: str | Path | None = None,
                          eta: float = 0.15) -> None:
        """激活经验库与偏好学习。缺省关闭（零开销）；激活后：
        * 每次 ab_commit（采纳）→ PreferenceModel.observe(被选, 落选)（M6-6）
        * 每次 override（选非 AI 偏好）→ library.record_override（M6-3 回写，
          note 已是人的语言——R15 中介在 A/B 层完成）
        * export_state 携带偏好快照与库计数（M9-4 前端可见）

        **热拔插（M8）**：store 可传任何满足 ExperienceStore 协议的实现
        （缺省 = JSONL ExperienceLibrary）——console 只依赖协议（R17 契约面），
        换实现不改上游一行；缺省通路零依赖（不激活全流程照跑）。"""
        from experience import ExperienceLibrary, PreferenceModel
        base = self._workdir or Path.cwd()
        if store is not None:
            self.library = store
        else:
            self.library = ExperienceLibrary(
                Path(library_path) if library_path
                else Path(base) / "experience_library.jsonl")
        if self.pref is None:   # 换库不重置偏好学习（热拔插不丢状态）
            self.pref = PreferenceModel(eta=eta)

    def record_experience(self, payload: dict[str, Any]) -> Any:
        """经验入库便捷通道（E2E STEP9）：dict 直传 library.record_ai。

        payload 键：trigger/attention/story/params/evidence[/verified_failure]。
        库未激活（library=None，缺省通路）→ 返回结构化 skip（不谎报成功）。
        """
        if self.library is None:
            return self._err("record_experience", "LIBRARY_NOT_BOUND", "",
                             "经验库未绑定（用 attach_experience 启用）")
        r = self.library.record_ai(
            trigger=payload.get("trigger", {}),
            attention=payload.get("attention", ""),
            story=payload.get("story", ""),
            params=payload.get("params"),
            evidence=payload.get("evidence"),
            verified_failure=bool(payload.get("verified_failure", False)))
        return self._ok("record_experience", f"经验入库 eid={r[:12]}…",
                        data={"eid": r})

    # ── W-11/W-14：垃圾桶考古 + plan 修订入库（2026-09-29）────
    def archaeology(self) -> dict[str, Any]:
        """垃圾桶考古（W-11 基础版，Orr：老技师先翻废纸篓解读坏件共性）。

        WAL 里"有痕无视图"的丢弃物收集：recompile（旧指纹被替代）/
        drop_segment / drop_part / override。共性解读 = 按 seg 分组计数
        （确定性统计，不装 AI）。重复被丢的段 = 高危区，供看图改优先复盘。
        """
        buckets: dict[str, list[dict[str, Any]]] = {}
        by_seg: dict[str, int] = {}
        for ev in self.wal.replay():
            kind = ev.get("kind")
            if kind in ("recompile", "drop_segment", "drop_part", "override"):
                seg = (ev.get("payload") or {}).get("seg", "") or \
                      (ev.get("payload") or {}).get("part", "") or "?"
                buckets.setdefault(kind, []).append(ev)
                if kind != "override":
                    by_seg[seg] = by_seg.get(seg, 0) + 1
        hot = sorted(by_seg.items(), key=lambda t: -t[1])
        return self._ok("archaeology",
                        f"垃圾桶：{sum(len(v) for v in buckets.values())} 件丢弃物，"
                        f"高危区 {hot[:3]}",
                        data={"discards": {k: len(v) for k, v in buckets.items()},
                              "by_seg": by_seg,
                              "detail": buckets})

    def note_plan_revision(self, reason: str, seg: str = "",
                           changed: bool = True) -> Any:
        """W-14（Suchman：计划是资源不是脚本）：plan 修订入库为一级事件。

        调用方（视觉环/导演/E2E）在 plan 被改写后显式调用——下次检索
        能学到"什么情况下计划容易被改、改成什么样"。库未激活 → 结构化
        skip（不谎报）。"""
        if self.library is None:
            return self._err("note_plan_revision", "LIBRARY_NOT_BOUND", seg,
                             "经验库未绑定（用 attach_experience 启用）")
        return self.record_experience({
            "trigger": {"origin": "logic_tree", "kind": "plan_revision",
                        "seg": seg or "?", "project": "plan-revision"},
            "attention": f"计划被改写：{reason[:60]}",
            "story": f"plan 修订（seg={seg or '?'}，几何变化={changed}）：{reason}",
            "params": {"changed": 1.0 if changed else 0.0},
            "evidence": [{"artifact": "console.plan",
                          "quote": reason[:120],
                          "recalc": "grep 'param\\|recompile' events.jsonl"}]})

    # ── 状态导出（M9-4a）─────────────────────────────────────
    def export_state(self) -> ConsoleResult:
        st = export_state(self.dag, self.table, self.vparams, self.commits,
                          goodpoints=[{"name": k, "thought_refs": v["thought_refs"]}
                                      for k, v in self.checkpoints.items()])
        st["thoughts"] = [
            {"id": tid, "claim": t["claim"], "kind": "assumption",
             "status": t["status"], "governs": t["governs"]}
            for tid, t in self.thoughts.items()]
        st["overrides"] = self.overrides
        st["attribution"] = {str(k): v for k, v in self.attribution.items()}
        st["kpis"] = self._compute_kpis()            # M10-4：KPI 三数源 + 曲线
        if self.pref is not None:                     # M6-6 偏好快照（前端可见）
            st["preference"] = {"w": dict(self.pref.w), "n": self.pref.n,
                                "needs_exploration": self.pref.needs_exploration(),
                                "report": self.pref.report()}
        if self.library is not None:                  # M6-2 库计数
            st["experience"] = {"entries": len(self.library.entries),
                                "path": str(self.library.path)}
        return self._ok("export_state", data=st)

    def _compute_kpis(self) -> dict[str, Any]:
        """M10-4 KPI 三数源（B3 数据在 WAL，单遍扫描）：
        override 率（唯一健康指标：长期为 0 = 人已经不看了 = 系统失效）/
        dirty 段数 / verify 失败数 + override 率曲线（每次 A/B 决策后的累计率）。
        曲线只在 ab_commit 点采样；外部 override() 调用计入分子但不新采样点。
        """
        n_ab = n_ov = verify_fails = 0
        curve: list[dict[str, Any]] = []
        for ev in self.wal.replay():
            kind = ev.get("kind")
            if kind == "override":
                n_ov += 1
            elif kind == "ab_commit":
                n_ab += 1
                curve.append({"n": n_ab, "rate": round(n_ov / n_ab, 4)})
            elif kind == "verify" and not ev["payload"].get("ok"):
                verify_fails += 1
        dirty_n = sum(1 for r in self.table.snapshot().values()
                      if r.get("dirty"))
        return {"override_rate": round(n_ov / n_ab, 4) if n_ab else None,
                "overrides": n_ov, "ab_decisions": n_ab,
                "dirty_segments": dirty_n, "verify_fails": verify_fails,
                "override_curve": curve}

    # ── override ─────────────────────────────────────────────
    def override(self, note: str = "") -> ConsoleResult:
        self.overrides += 1
        self.wal.append("override", {"n": self.overrides, "note": note})
        return self._ok("override", f"override #{self.overrides}: {note}")

    def log_pivot(self, desc: str) -> ConsoleResult:
        self.pivots.append(desc)
        self.wal.append("pivot", {"desc": desc})
        return self._ok("pivot", f"已登记 pivot: {desc}")
