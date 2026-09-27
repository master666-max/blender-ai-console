"""
gn_session.py — M1 集成层：m1_core 数据层 × GNAdapter × 机械 verifier
=====================================================================

把数据层（FlowDAG / WALLog / RevisionTable / VersionedParams / SegmentCommits）
接到执行层（GNAdapter）与验证层（GeometryVerifier）上，形成可用的会话门面。

M1 集成要点（工单）：
* A1  依赖显式化：段= DAG 一步，`set_deps()` 可声明跨段依赖；环在 dag.add() 即拒绝
* A16 Step 双携带：`command`（trace：编译/参数事件的 WAL 序列）+ `gn_delta`（节点树 diff，A33）
* A28 backdating：参数写 → touch 置脏 → 执行 → report_output 回报 → 输出未变则级联截断
* A29 pivot：LogOnly（导出/落盘）之后拒绝回退
* 旧线性 FlowAxis 退役（core_types.FlowAxis 保留仅作历史参照）

跑法：blender --background --factory-startup --python gn_session_live.py（见配套 live 测试）
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import bpy

from gn_adapter import GNAdapter, GNValidationError, ParamSpec
from gn_verify import GeometryVerifier
from m1_core import (CycleError, FlowDAG, LogOnly, ParamUpdate, PivotBlocked,
                     RevisionTable, SagaTag, SegmentCommits, StepRecord,
                     VersionedParams, WALLog, export_state)

__all__ = ["SegmentSpec", "GNSession", "StructuredError",
           "stamp_attribution", "read_face_attribution", "ATTR_NAME"]

ATTR_NAME = "console_seg"   # M4-9：段落归属命名属性（INT / POINT 域）


# ══════════════════════════════════════════════════════════════
# M4-9 · 段落归属（编译时 named attribute · POINT 域 + 0 哨兵）
# ══════════════════════════════════════════════════════════════
def stamp_attribution(tree: Any, attr_name: str, idx: int) -> None:
    """在段落树尾串归属写入链（probe_m49c 实测 v2 方案，2026-09-27）。

    为什么不是 Exists?keep:write（首版）：Input Named Attribute 的 **Exists
    是网格级而非逐面级**——上游段一旦写过属性，本段新增几何也 Exists=True
    → 新面永远拿不到归属（live 31/44 的根因之一）。
    v2 语义（全部实测）：
      * **POINT 域**：CC 细分保留原始顶点（每个子面恰含 ≥1 原始顶点）；
        FACE 域会被细分稀释（实测每父面 4 子面仅 1 保值 → 65536 误零）。
      * **0 = 无归属哨兵**：FunctionNodeCompare(INT, EQUAL, 0) → Switch：
        值为 0 → 写本段索引；非零 → 保留（first-creator-wins）。
      * 5.2 节点名：比较节点是 **FunctionNodeCompare**（GeometryNodeCompare /
        ShaderNodeCompare 均 undefined——又一个 API 漂移点）。
    R6/D8 合规：属性由树在每次求值时再生，不引用任何拓扑索引。
    """
    go = next(n for n in tree.nodes if n.bl_idname == "NodeGroupOutput")
    out_sock = go.inputs["Geometry"]
    src = out_sock.links[0].from_socket if out_sock.is_linked else None

    rd = tree.nodes.new("GeometryNodeInputNamedAttribute")
    rd.data_type = 'INT'
    rd.inputs["Name"].default_value = attr_name
    cmp = tree.nodes.new("FunctionNodeCompare")
    cmp.data_type = 'INT'
    cmp.operation = 'EQUAL'
    cmp.inputs["B"].default_value = 0              # 哨兵：0 = 无归属
    sw = tree.nodes.new("GeometryNodeSwitch")
    sw.input_type = 'INT'
    sw.inputs["True"].default_value = idx          # 零 → 写本段
    st = tree.nodes.new("GeometryNodeStoreNamedAttribute")
    st.data_type = 'INT'
    st.domain = 'POINT'
    st.inputs["Name"].default_value = attr_name

    tree.links.new(rd.outputs["Attribute"], cmp.inputs["A"])
    tree.links.new(cmp.outputs["Result"], sw.inputs["Switch"])
    tree.links.new(rd.outputs["Attribute"], sw.inputs["False"])   # 非零 → 保留
    if src is not None:
        tree.links.new(src, st.inputs["Geometry"])
    tree.links.new(sw.outputs["Output"], st.inputs["Value"])
    tree.links.new(st.outputs["Geometry"], out_sock)


def read_face_attribution(mesh: Any, attr_name: str,
                          attribution: dict[int, str]) -> dict[str, Any]:
    """面归属查询（机械反查）：面 = 各顶点属性中**最小非零值**所属段。

    min 语义 = first-creator-wins（段索引按创建顺序递增）。
    细分新顶点被插值成邻域值（实测非 0），min 仍解析到正确段。
    POINT 域 data 与顶点按下标对齐（元素没有 .index 属性——踩过）。
    """
    from collections import Counter
    vals = [0] * len(mesh.vertices)
    if attr_name in mesh.attributes:
        a = mesh.attributes[attr_name]
        if a.domain == 'POINT':
            for i, d in enumerate(a.data):
                vals[i] = d.value
    out: dict[str, Any] = {"total": len(mesh.polygons),
                           "by_segment": {}, "unattributed": 0}
    cnt: Counter = Counter()
    for p in mesh.polygons:
        seg_idx = 0
        for vi in p.vertices:
            v = vals[vi]
            if v > 0 and (seg_idx == 0 or v < seg_idx):
                seg_idx = v
        cnt[seg_idx] += 1
    for v, n in sorted(cnt.items()):
        name = attribution.get(v)
        if name:
            out["by_segment"][name] = n
        else:
            out["unattributed"] += n
    return out


# ══════════════════════════════════════════════════════════════
# M4-8 · 结构化错误（d2-agent：裸文本→结构化 = 恢复率 +36.7-40pp）
# ══════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class StructuredError:
    """编译/求值/verifier 的统一错误格式——LLM 可机器解析并自主修复。

    d2-agent 调研：裸文本报错的恢复率≈0；结构化错误+建议 → +36.7-40pp。
    每个字段都有明确用途：LLM 读 error_code 选分支，读 suggestions 逐条尝试。
    """
    error_code: str                    # 机器可读（如 "UNKNOWN_OP", "CYCLE", "DFM_FAIL"）
    failed_node: str                   # 出错位置（段落名/节点名/socket 路径）
    reason: str                        # 人类可读原因
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    #   每条: {"action": "replace_param"|"remove_dep"|..., "target": str, "value": Any}
    severity: str = "error"            # "error" | "warning"

    def to_dict(self) -> dict[str, Any]:
        return {"error_code": self.error_code, "failed_node": self.failed_node,
                "reason": self.reason, "suggestions": self.suggestions,
                "severity": self.severity}


@dataclass
class SegmentSpec:
    """声明式段落：AI 产出的就是它（EXP-1 的 spec 路线）。"""
    name: str
    params: list[ParamSpec]
    build: Callable[[GNAdapter, Any, dict[str, str]], None]
    consumes_input: bool = False          # False = 自产几何（首段）
    thought_refs: tuple[str, ...] = ()
    obj: str = "Mug"                      # A2 区域反查键


@dataclass
class SegmentRec:
    name: str
    spec: SegmentSpec
    tree: Any
    sid: dict[str, str]                   # 参数名 → socket identifier
    mod: Any
    dump: dict[str, Any]                  # A16 gn_delta 的"现状"侧
    step_id: str
    fingerprint: str
    gn_delta: dict[str, Any] = field(default_factory=dict)   # A16：节点树 diff


class GNSession:
    """一个会话 = 一棵 FlowDAG + 一条 WAL + 一张 RevisionTable + 一组 opinion 层。"""

    ATTR_NAME = ATTR_NAME   # M4-9 归属属性名（模块级常量，console 共用）

    def __init__(self, ad: GNAdapter, obj: Any, workdir: Path | None = None) -> None:
        self.ad = ad
        self.obj = obj
        self.deps = ad.bpy.context.evaluated_depsgraph_get()
        self.dag = FlowDAG()
        self.wal = WALLog(Path(workdir) / "events.jsonl" if workdir else None)
        self.table = RevisionTable(self.dag)
        self.vparams = VersionedParams()
        self.commits = SegmentCommits()
        self.verifier = GeometryVerifier(budget_faces=300_000, ground_z=-1.0)
        self.segments: dict[str, SegmentRec] = {}
        self.order: list[str] = []
        self.checkpoints: dict[str, dict[str, Any]] = {}
        self.thoughts: dict[str, dict[str, Any]] = {}
        self.overrides = 0                 # B3：唯一健康指标
        self.pivots: list[str] = []        # A29：pivot 之后只许 forward
        self._deps_hint: dict[str, tuple[str, ...]] = {}
        self._param_steps: dict[str, float] = {}
        self._snapshots: dict[str, Any] = {}
        # M4-9：归属索引 → 段名（1 起；0 = 无归属）。反查时用它解码。
        self.attribution: dict[int, str] = {}
        self._seg_index: dict[str, int] = {}

    # ── 思维图（极简：claim + 掌管哪段哪参）─────────────────
    def add_thought(self, tid: str, claim: str,
                    governs: dict[str, str] | None = None) -> None:
        self.thoughts[tid] = {"claim": claim, "governs": governs or {},
                              "status": "ACTIVE"}

    # ── 依赖声明（A1：显式，可非线性）────────────────────────
    def set_deps(self, seg: str, deps: Iterable[str]) -> None:
        self._deps_hint[seg] = tuple(deps)

    # ── M4-9：编译时段落归属（d4-semantic 独有优势）──────────
    def _append_attribution(self, tree: Any, seg_name: str) -> int:
        """登记段索引并调用 v2 归属链（POINT 域 + 0 哨兵，见模块级 docstring）。"""
        idx = self._seg_index.setdefault(seg_name, len(self._seg_index) + 1)
        self.attribution[idx] = seg_name
        stamp_attribution(tree, self.ATTR_NAME, idx)
        return idx

    def query_attribution(self) -> dict[str, Any]:
        """读最终网格的段落归属分布（机械反查：这块面是谁的决策）。

        返回 {"total", "by_segment": {段名: 面数}, "unattributed"}。
        配合 M9-6 标注反查 / M2-7 语义一致性，是 TNP 问题的编译时解法。
        """
        self.deps.update()
        ev = self.obj.evaluated_get(self.deps)
        m = ev.to_mesh()
        out = read_face_attribution(m, self.ATTR_NAME, self.attribution)
        ev.to_mesh_clear()
        return out

    # ── 编译：spec → GN 节点组 → opinion 层 → DAG 步 ─────────
    def compile_segment(self, spec: SegmentSpec) -> SegmentRec:
        # A1：依赖在**任何 Blender 状态改变之前**验证——缺失 = 响亮失败且零残迹
        #（否则 DAG add 抛错时树/modifier/归属已泄漏，会话被污染，live 实测 31/44）
        deps = self._deps_hint.get(spec.name)
        if deps is None:
            # 默认 = 线性链（上一段的步）；跨段依赖用 set_deps 显式声明（A1）
            deps = (self.segments[self.order[-1]].step_id,) if self.order else ()
        known = set(self.segments) | {r.step_id for r in self.segments.values()}
        unknown = [d for d in deps if d not in known]
        if unknown:
            raise ValueError(
                f"段落 {spec.name!r} 声明了不存在的依赖 {unknown}；"
                f"已知段：{sorted(self.segments) or '（无——首段不能声明依赖）'}")

        tree = self.ad.new_group(spec.name)
        sid: dict[str, str] = {}
        if spec.consumes_input:
            sid["Incoming_Geometry"] = self.ad.promote_input(
                tree, ParamSpec("Incoming_Geometry", "GEOMETRY"))
        for p in spec.params:
            sid[p.name] = self.ad.promote_input(tree, p)
        self.ad.promote_output(tree, "Geometry", "GEOMETRY")
        spec.build(self.ad, tree, sid)
        self._append_attribution(tree, spec.name)      # M4-9：树尾归属
        mod = self.ad.attach(self.obj, tree, spec.name)

        step_id = f"step:{spec.name}"
        dump = self.ad.dump(tree)
        prev = self.segments.get(spec.name)
        gn_delta = ({"initial": True, "fingerprint": self.ad.fingerprint(tree)[:16]}
                    if prev is None else self.ad.diff(prev.tree, tree))
        step = StepRecord(
            step_id=step_id, seg=spec.name, obj=spec.obj,
            params=tuple((p.name, p.default) for p in spec.params),
            deps=deps, thought_refs=tuple(spec.thought_refs),
            seed=0, selection=(),
            revision=self.table.global_revision,
            gn_delta=tuple(sorted(gn_delta.items())),
        )
        self.dag.add(step)                 # A1：环在这里即拒

        rec = SegmentRec(name=spec.name, spec=spec, tree=tree, sid=sid,
                         mod=mod, dump=dump, step_id=step_id,
                         fingerprint=self.ad.fingerprint(tree)[:16],
                         gn_delta=gn_delta)
        self.segments[spec.name] = rec
        if spec.name not in self.order:
            self.order.append(spec.name)

        # 参数域以 spec 默认值初始化（只补缺口，不覆盖已写值）——
        # 否则 checkpoint 只存"写过的参数"，未写过参数的改动回退不回去
        #（live 31/44：Subdiv_Level 改 3 后 revert 面数回不去，实测根因）
        cur = self.vparams.get()
        fresh = {f"{spec.name}.{p.name}": p.default for p in spec.params
                 if f"{spec.name}.{p.name}" not in cur}
        if fresh:
            self.vparams.set_many(fresh)

        self.wal.append("compile", {"seg": spec.name, "step": step_id,
                                    "fingerprint": rec.fingerprint,
                                    "gn_delta": gn_delta})
        return rec

    def recompile_segment(self, name: str, new_spec: SegmentSpec) -> dict[str, Any]:
        """重编译一段 → A16/A33：gn_delta = 新旧节点树 diff（adapter.dump 之上）。

        旧树不销毁（内容寻址精神）：diff 留档后旧组作为历史版本仍在 .blend 里。
        B3 修复：新 modifier 会追加到栈尾——attach 后**必须移回旧位**，
        否则段落顺序 ≠ modifier 顺序，opinion 语义被静默重排。
        """
        old = self.segments[name]
        old_idx = list(self.obj.modifiers).index(old.mod)   # B3：先记旧位
        self.obj.modifiers.remove(old.mod)
        tree = self.ad.new_group(name)            # Blender 自动去重（name.001）
        sid: dict[str, str] = {}
        if new_spec.consumes_input:
            sid["Incoming_Geometry"] = self.ad.promote_input(
                tree, ParamSpec("Incoming_Geometry", "GEOMETRY"))
        for p in new_spec.params:
            sid[p.name] = self.ad.promote_input(tree, p)
        self.ad.promote_output(tree, "Geometry", "GEOMETRY")
        new_spec.build(self.ad, tree, sid)
        self._append_attribution(tree, name)      # M4-9：沿用原归属索引
        mod = self.ad.attach(self.obj, tree, name)
        # B3：把新 modifier 从栈尾移回旧位（move(当前尾索引 → 旧索引)）
        new_idx = len(self.obj.modifiers) - 1
        if new_idx != old_idx:
            self.obj.modifiers.move(new_idx, old_idx)
        gn_delta = self.ad.diff(old.tree, tree)   # A33：跨版本 DAG 可 diff
        rec = SegmentRec(name=name, spec=new_spec, tree=tree, sid=sid, mod=mod,
                         dump=self.ad.dump(tree), step_id=old.step_id,
                         fingerprint=self.ad.fingerprint(tree)[:16],
                         gn_delta=gn_delta)
        self.segments[name] = rec
        # 重编译后必须**重放当前参数值**到新 modifier 的 per-instance 输入——
        # 否则新树静默回到接口默认值，会话账本与真实几何分裂
        #（live 45/46 抓到：重编译把手后用户调的 0.007 被重置成 0.011，实测）
        cur = self.vparams.get()
        reapplied = {}
        for p in new_spec.params:
            key = f"{name}.{p.name}"
            if key in cur and p.name in sid:
                self.ad.set_instance_input(mod, sid[p.name], cur[key])
                reapplied[key] = cur[key]
        # 新增参数以默认值入参数域（只补缺口——已写参数不许被重编译重置）
        fresh = {f"{name}.{p.name}": p.default for p in new_spec.params
                 if f"{name}.{p.name}" not in cur}
        if fresh:
            self.vparams.set_many(fresh)
        self.wal.append("gn_delta", {"seg": name, "delta": gn_delta,
                                     "mod_index": old_idx,
                                     "reapplied": reapplied})
        return gn_delta

    # ── 参数写入（A28/A29：量化 → 置脏 → 机械逆可查）────────
    def set_param(self, seg: str, param: str, value: Any,
                  step: float | None = None) -> dict[str, Any]:
        rec = self.segments[seg]
        key = f"{seg}.{param}"
        old = self.vparams.get().get(key)
        pu = ParamUpdate(seg, param, old, value)
        cur = self.vparams.get()
        cur[key] = pu.new
        self.vparams.set_many({key: pu.new})          # 内部走 quantize（A28）

        fp_src = {k: v for k, v in cur.items() if k.startswith(seg + ".")}
        fp = json.dumps(fp_src, sort_keys=True, ensure_ascii=False, default=str)
        dirty = self.table.touch(seg, fp)             # A28 置脏 + 传播

        self.ad.set_instance_input(rec.mod, rec.sid[param], pu.new)  # 内含 invalidate
        self.wal.append("param", {"seg": seg, "param": param,
                                  "old": old, "new": pu.new,
                                  "dirty": dirty})
        return {"inverse": pu.inverse(), "dirty": dirty}

    # ── 求值与度量（几何量，A19：禁用面数做变更判定）─────────
    def evaluate(self) -> dict[str, float]:
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

    @staticmethod
    def output_fingerprint(st: dict[str, float]) -> str:
        """输出指纹 = 几何量（A19），非面数。"""
        blob = json.dumps({"a": st["area"], "b": st["bbox"]}, sort_keys=True)
        import hashlib
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def report_output(self, seg: str, output_fp: str) -> bool:
        """A28 backdating：执行后回报输出指纹。False = 输出未变，级联截断。"""
        changed = self.table.report_output(seg, output_fp)
        self.wal.append("output", {"seg": seg, "changed": changed,
                                   "fingerprint": output_fp})
        return changed

    # ── 验证 ─────────────────────────────────────────────────
    @contextmanager
    def _stack_upto(self, upto_seg: str | None):
        """B2 修复：临时禁用 upto_seg 之后的 modifier——局部性在**段输出**上求值。

        为什么需要：S3 细分（下游）会把全部顶点重新平滑，全栈求值下任何
        上游改动都表现为 moved≥40%——局部性谓词在复合网格上失真（B2）。
        段级求值后，moved 反映的才是这一段的真实手术范围。
        用完必须恢复可见性并 invalidate，不留副作用。
        """
        if upto_seg is None:
            yield
            return
        rec = self.segments.get(upto_seg)
        mods = list(self.obj.modifiers)
        try:
            cut = mods.index(rec.mod) if rec is not None else -1
        except ValueError:  # noqa: PERF203  modifier 已不在栈中
            cut = -1
        if cut < 0:
            yield
            return
        hidden = [(m, m.show_viewport) for m in mods[cut + 1:]]
        for m, _ in hidden:
            m.show_viewport = False
        try:
            yield
        finally:
            for m, prev in hidden:
                m.show_viewport = prev
            self.ad.invalidate(obj=self.obj)

    def snapshot_coords(self, upto_seg: str | None = None) -> tuple[set, int]:
        """段落执行前的顶点坐标签名 + 物体数（A25/A24 的 before 侧）。

        upto_seg：只求值到该段为止（B2 段级求值）。
        ⚠️ verify_transition 必须用**同一个** upto_seg，前后才可比。
        """
        with self._stack_upto(upto_seg):
            self.deps.update()
            ev = self.obj.evaluated_get(self.deps)
            m = ev.to_mesh()
            keys = {(round(v.co.x, 5), round(v.co.y, 5), round(v.co.z, 5))
                    for v in m.vertices}
            nobj = len(self.ad.bpy.data.objects)
            ev.to_mesh_clear()
        return keys, nobj

    def verify_transition(self, label: str, before: tuple[set, int],
                          before_faces: int,
                          upto_seg: str | None = None) -> dict[str, Any]:
        """段落级转换门禁（M2-2）：局部性 + 物体数一致性 + 改/加比。

        before = snapshot_coords(upto_seg) 的返回值；必须在段落执行**前**采集，
        且 upto_seg 与本次调用一致（B2：段级求值，避免下游平滑稀释局部性）。
        """
        keys, nobj_expected = before
        with self._stack_upto(upto_seg):
            self.deps.update()
            ev = self.obj.evaluated_get(self.deps)
            m = ev.to_mesh()
            nf = len(m.polygons)
            loc = GeometryVerifier.check_locality(keys, m)
            ev.to_mesh_clear()
        nobj_actual = len(self.ad.bpy.data.objects)
        cnt = GeometryVerifier.check_object_count(nobj_expected, nobj_actual)
        ratio = GeometryVerifier.edit_vs_add_ratio(before_faces, nf)
        gate = loc.ok and cnt.ok
        self.wal.append("transition", {"label": label, "moved": loc.value,
                                       "objects_ok": cnt.ok,
                                       "upto_seg": upto_seg,
                                       "edit_add_ratio": ratio, "gate": gate})
        return {"gate": gate, "moved": loc.value, "objects_ok": cnt.ok,
                "edit_add_ratio": ratio, "faces": nf,
                "failures": [str(loc), str(cnt)]}

    # ── M2-7 · 语义一致性门禁（M4-9 归属驱动的区域局部性）────
    def snapshot_region(self, upto_seg: str | None = None) -> dict[int, tuple]:
        """面级区域快照：{面号: (质心, 归属段名)}——"改 A 只动 A"的 before 侧。

        upto_seg 语义同 snapshot_coords（B2 段级求值）。
        ⚠️ 前提：参数微调不改变拓扑，面号在两次快照间稳定（拓扑变了门禁会拦）。
        """
        with self._stack_upto(upto_seg):
            self.deps.update()
            ev = self.obj.evaluated_get(self.deps)
            m = ev.to_mesh()
            vals = [0] * len(m.vertices)
            if self.ATTR_NAME in m.attributes:
                a = m.attributes[self.ATTR_NAME]
                for i, d in enumerate(a.data):
                    vals[i] = d.value
            snap: dict[int, tuple] = {}
            for i, p in enumerate(m.polygons):
                c = p.center
                seg_idx = 0
                for vi in p.vertices:
                    v = vals[vi]
                    if v > 0 and (seg_idx == 0 or v < seg_idx):
                        seg_idx = v
                snap[i] = ((round(c.x, 5), round(c.y, 5), round(c.z, 5)),
                           self.attribution.get(seg_idx, ""))
            ev.to_mesh_clear()
        return snap

    def verify_region_locality(self, label: str, before: dict[int, tuple],
                               changed_seg: str,
                               upto_seg: str | None = None) -> dict[str, Any]:
        """"改 A 只动 A"的机械判定（M2-7）：非 changed_seg 的面必须纹丝不动。

        这是 A25 局部性的**语义正确形态**：坐标集局部性在"改动段占网格
        大头"时永远过不了（改把手=动全部把手顶点，占 82% → moved≥40% 必炸，
        live 31/44 实测）；真断言是"不属于改动段的面没动"——
        由编译时段落归属（M4-9）保证可判定。
        """
        after = self.snapshot_region(upto_seg)
        topo_ok = len(after) == len(before)
        moved_out = outside = 0
        if topo_ok:
            for i, (c_after, s_after) in after.items():
                c_before, s_before = before[i]
                if s_before != changed_seg:
                    outside += 1
                    if c_after != c_before:
                        moved_out += 1
        gate = topo_ok and moved_out == 0
        self.wal.append("region", {"label": label, "changed": changed_seg,
                                   "outside": outside, "moved_out": moved_out,
                                   "upto_seg": upto_seg, "gate": gate})
        return {"gate": gate, "topo_ok": topo_ok, "outside": outside,
                "moved_out": moved_out,
                "failures": ([] if gate else
                             (["拓扑变了，面号不可比"] if not topo_ok else
                              [f"{moved_out}/{outside} 个非 {changed_seg} 面被移动"]))}

    def verify(self, label: str = "") -> dict[str, Any]:
        self.deps.update()
        ev = self.obj.evaluated_get(self.deps)
        m = ev.to_mesh()
        rep = self.verifier.check(m, self.obj)
        nf = len(m.polygons)
        ev.to_mesh_clear()
        self.wal.append("verify", {"label": label, "ok": rep.ok, "faces": nf})
        return {"ok": rep.ok, "faces": nf, "failures": [str(f) for f in rep.failures]}

    # ── 三层回退 ─────────────────────────────────────────────
    def _assert_no_pivot(self) -> None:
        """A29：跨过 pivot（导出/落盘）之后，回退被拒绝——只许 forward recovery。"""
        if self.pivots:
            raise PivotBlocked(f"已有 pivot（{self.pivots}）——只许 forward recovery")

    def checkpoint(self, name: str, thought_refs: tuple[str, ...] = ()) -> float:
        """GoodPoint = 快照 = bake 边界（A14）。

        快照存两样：bake 网格（对照/预览用）+ **参数表快照**（回退的真正机制——
        把"存数据"退化为"存参数"，几十字节；A29 的机械逆序列）。
        """
        t0 = time.perf_counter()
        self.deps.update()
        snap = self.ad.bpy.data.meshes.new_from_object(
            self.obj.evaluated_get(self.deps))
        dt = (time.perf_counter() - t0) * 1000
        self.checkpoints[name] = {"mesh": snap, "params": dict(self.vparams.get()),
                                  "thought_refs": list(thought_refs)}
        self.wal.append("checkpoint", {"name": name,
                                       "faces": len(snap.polygons),
                                       "thought_refs": list(thought_refs)})
        return round(dt, 3)

    def revert_to_checkpoint(self, name: str) -> float:
        """L2 语义层回退：**参数回滚**——逐参数写回 checkpoint 值（机械逆序列）。

        不把快照网格直接盖回去：modifier 还在，盖数据会被再求值一次（双重加工）。
        参数回滚后求值自然回到锚点几何——这才是参数域的"逆"。
        """
        self._assert_no_pivot()
        t0 = time.perf_counter()
        for key, val in self.checkpoints[name]["params"].items():
            seg, _, param = key.partition(".")
            rec = self.segments.get(seg)
            if rec and param in rec.sid:
                self.set_param(seg, param, val)
        self.ad.invalidate(obj=self.obj)
        self.deps.update()
        return round((time.perf_counter() - t0) * 1000, 3)

    def pop_layer(self) -> tuple[str, float]:
        """L1 状态层回退：删一层 opinion（语义 = 少一层加工，非回到过去——A21）。"""
        self._assert_no_pivot()
        t0 = time.perf_counter()
        name = self.order[-1]
        self.obj.modifiers.remove(self.segments[name].mod)
        self.order.pop()
        self.ad.invalidate(obj=self.obj)
        self.deps.update()
        return name, round((time.perf_counter() - t0) * 1000, 3)

    def override(self, note: str = "") -> None:
        """B3：人的每次打回都 +1 并落 WAL——override 率是唯一健康指标。"""
        self.overrides += 1
        self.wal.append("override", {"n": self.overrides, "note": note})

    def log_pivot(self, desc: str) -> LogOnly:
        """A29：pivot（导出/落盘）登记——此后只许 forward recovery。"""
        lo = LogOnly(desc)
        self.pivots.append(desc)
        self.wal.append("pivot", {"desc": desc})
        return lo

    # ── 影响预览（A29：推翻前必须先算因果闭包）───────────────
    def impact_preview(self, seg: str) -> dict[str, Any]:
        step = next(s for s in self.dag.all_steps() if s.seg == seg)
        desc = self.dag.descendants(step.step_id)
        downstream = sorted({self.dag.get(d).seg for d in desc} | {seg})
        may_fail = [s for s in downstream
                    if self.segments[s].spec.consumes_input]
        return {"seg": seg, "will_replay": downstream, "n": len(downstream),
                "may_fail": may_fail, "m": len(may_fail)}

    # ── 状态导出（M9-4a Web 契约）────────────────────────────
    def export_state(self) -> dict[str, Any]:
        st = export_state(self.dag, self.table, self.vparams, self.commits,
                          goodpoints=[{"name": k, "thought_refs": v["thought_refs"]}
                                      for k, v in self.checkpoints.items()])
        st["thoughts"] = [
            {"id": tid, "claim": t["claim"], "kind": "assumption",
             "status": t["status"], "governs": t["governs"]}
            for tid, t in self.thoughts.items()]
        st["overrides"] = self.overrides
        # M4-9：归属映射（前端反查"这块面是谁的决策"时解码 console_seg 用）
        st["attribution"] = {str(k): v for k, v in self.attribution.items()}
        return st
