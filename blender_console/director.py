"""director.py — M7 · 导演模式：把既有零件组装成"人导演、AI 执行"的工作流
================================================================================

组装清单（全部已落地，本模块只做编排与纪律，不含任何新几何逻辑）：
  编译      console.compile（op-JSON → GN，M4-3）
  机械门禁  console.verify / render_diff（M2/M9-3）
  三件套    render_diff_b64 + summary + refutable_assumption（B1/M9-1）
  介入      console.ab_prepare/commit（B2/M5）· console.override（B3）
  回退      console.pop_layer / checkpoint / revert（M3）
  经验      console.library（M6-2/3，override 回写 + D9 差异化建议）
  账本      console.wal（B6 人/AI 通路分离）

导演模式与审计模式的区别（六问·第六问定盘）：
  门不在每一步拦，只在**高影响面**（Tier 3）拦；人的注意力花在"好不好看"，
  不花在"合不合规"。可观测性不是审批的工具，是放手的底气。

TrustPolicy 是策略对象（开闭原则）：AUTOPILOT / NORMAL / STRICT 只是换实例，
不是改代码路径。分档按**影响面**（修正 3）：结构 op / 吃上游几何 → 高档；
op_path 只做初始粗分。
"""

from __future__ import annotations

import time
from typing import Any

from console import Console

__all__ = ["DirectorSession", "AutoPilotPolicy", "NormalPolicy", "StrictPolicy"]

T1 = "T1_AUTOPILOT"     # 门禁照跑，人不拦（事后可审计）
T2 = "T2_NOTIFY"        # 出三件套，自动通过，人可回看/打回
T3 = "T3_DIRECTOR"      # 人必须 accept / override，才能进入下一段

# M7-2 · 工艺阶段（吸收 13 分册七阶段骨架；op 路线按语义重写内容）
STAGES = ("blockout", "structure", "detail", "cleanup", "deliver")
_STAGE_ORDER = {"blockout": 0, "structure": 1, "detail": 2, "cleanup": 3, "deliver": 4}
# 偏序门管辖的"后期段"：其依赖闭包内的大形段（blockout/structure）必须实时 verify PASS
_LATE_STAGES = ("detail", "cleanup", "deliver")

_STRUCTURED_OPS = {"boolean_diff", "boolean_union", "boolean_intersect",
                   "subdivide", "mirror", "merge_by_distance", "join_geometry"}


class TrustPolicy:
    """策略对象：classify(spec) → Tier。影响面分档（修正 3），op_path 只做粗分。"""

    name = "base"

    def classify(self, spec: dict[str, Any]) -> str:
        raise NotImplementedError

    @staticmethod
    def impact(spec: dict[str, Any]) -> dict[str, Any]:
        """影响面：吃不吃上游、参数量、是否结构 op（改拓扑的）。"""
        op = spec.get("op", "")
        return {"op": op,
                "consumes_input": bool(spec.get("consumes_input")),
                "n_params": len(spec.get("parameters", [])),
                "structural": op in _STRUCTURED_OPS}


class AutoPilotPolicy(TrustPolicy):
    """全自动驾驶：门禁照跑（verifier 仍会拦坏几何），人不拦。"""
    name = "AUTOPILOT"

    def classify(self, spec: dict[str, Any]) -> str:
        return T1


class StrictPolicy(TrustPolicy):
    """全导演：每段都等人。"""
    name = "STRICT"

    def classify(self, spec: dict[str, Any]) -> str:
        return T3


class NormalPolicy(TrustPolicy):
    """默认：结构 op 或吃上游几何 → 导演拍板；纯自产图元 → 通知即可。"""
    name = "NORMAL"

    def classify(self, spec: dict[str, Any]) -> str:
        imp = self.impact(spec)
        if imp["structural"]:
            return T3
        if imp["consumes_input"]:
            return T3 if imp["n_params"] >= 3 else T2
        return T1


class DirectorSession:
    """一个导演会话 = 一台 Console + 一份 TrustPolicy + 段级状态机。

    状态机：IDLE → propose → PRESENTED（T3 阻塞 / T1/T2 自动通过）→ accept/override → IDLE
    纪律：提案必须带一条可反驳的假设（B1/B5）；override 必须带 note（R15 语言化）；
         打回 = 删层 + override 计数 + 经验库回写 + 差异化建议（M6-3/D9）。
    """

    def __init__(self, console: Console, policy: TrustPolicy | None = None) -> None:
        self.con = console
        self.policy = policy or NormalPolicy()
        self.brief = ""
        self.state = "IDLE"
        self.stage_of: dict[str, str] = {}    # M7-2：段名 → 工艺阶段
        self.pending: dict[str, Any] | None = None
        self.history: list[dict[str, Any]] = []
        self._started = time.perf_counter()

    # ── 会话 ─────────────────────────────────────────────────
    def begin(self, brief: str = "") -> dict[str, Any]:
        self.brief = brief
        self.state = "IDLE"
        self.con.wal.append("director_begin", {"brief": brief,
                                               "policy": self.policy.name})
        return {"state": self.state, "policy": self.policy.name, "brief": brief}

    def set_policy(self, policy: TrustPolicy, reason: str = "") -> dict[str, Any]:
        """运行时**换装**治理策略（M8 热拔插原则：换装 = 登记动作，不静默替换）。

        TrustPolicy 是策略对象（开闭原则）——AUTOPILOT/NORMAL/STRICT 或任何
        自定义实现（如按项目定档）都从这里注入。T3 待决时拒绝换装（先清场）。
        """
        if self.state == "PRESENTED":
            raise RuntimeError("有 T3 待决提案——先 accept/override 再换策略")
        old = self.policy.name
        self.policy = policy
        self.con.wal.append("director_set_policy", {"from": old,
                                                    "to": policy.name,
                                                    "reason": reason})
        return {"state": self.state, "from": old, "to": policy.name}

    def _require_idle(self, action: str) -> None:
        if self.state != "IDLE":
            raise RuntimeError(f"{action} 需要会话处于 IDLE，当前 {self.state}"
                               f"（先 accept/override 待决提案）")

    # ── AI 提案 ──────────────────────────────────────────────
    def propose(self, spec: dict[str, Any], assumption: str = "",
                ai_reason: str = "", deviation: str = "",
                sees: str = "") -> dict[str, Any]:
        """AI 提案：编译 → 机械门禁 → 渲染三件套 → 按档决定是否等人。

        assumption 必填（B1/B5：没有可反驳假设的提案不配占用导演注意力）。
        M7-2：spec 可带 stage（工艺阶段，偏序律门禁）与 part（部件路径，子母目录）；
              deviation = 声明式偏离（Tier 2 自评即过，只留痕不拦——上游 13 分册 §6）。
        M7-3：stage=blockout 强制 T3 目验（阶段维度铁门禁，与 TrustPolicy 风险维度正交，
              AUTOPILOT 也不豁免——剪影比例是审美判断，机械 verifier 不替代）；
              sees = 修正类提案引用的"上一帧所见"（留痕不拦——MVP 分寸）。
        """
        if self.state == "PRESENTED":
            raise RuntimeError("上一提案还在待决（T3 阻塞）——先 accept/override")
        if not assumption or not assumption.strip():
            raise ValueError("提案必须带一条可反驳的假设（B1 三件套）；"
                             "没有假设就没有可质疑的对象，导演模式无从谈起")
        stage = spec.get("stage") or ""
        part = spec.get("part") or ""
        if stage and stage not in STAGES:
            raise ValueError(f"未知 stage {stage!r}；合法：{list(STAGES)}")
        if sees:
            self.con.wal.append("director_sees", {"sees": sees})

        # M7-2 阶段偏序门（G1 铁门禁的 DAG 化）：detail/cleanup/deliver 提案的
        # 依赖闭包内，大形段（blockout/structure）必须**实时** verify PASS——
        # 按部件传播（依赖闭包），非全局锁：无关部件的并行工作不受影响。
        if stage in _LATE_STAGES:
            deps = list(spec.get("depends_on") or [])
            if not deps and self.con.order:
                deps = [self.con.order[-1]]      # 隐式线性前驱（compile 缺省链）
            blocked = []
            seen, stack = set(), list(deps)
            while stack:
                nm = stack.pop()
                if nm in seen or nm not in self.stage_of:
                    continue
                seen.add(nm)
                st = self.stage_of[nm]
                if st in ("blockout", "structure"):
                    gate = self.con.verify(f"stage_gate:{nm}")
                    if not gate.ok:   # ConsoleResult.ok 反映 verify 结果（M2 门禁修复）
                        blocked.append((nm, gate.data.get("failures", [])[:2]))
                step = next((s for s in self.con.dag.all_steps() if s.seg == nm), None)
                if step:
                    stack.extend(d.removeprefix("step:") for d in step.deps)
            if blocked:
                detail_msg = "；".join(f"大形段 {n} 未过验证：{fs}" for n, fs in blocked)
                self.con.wal.append("director_g1_blocked",
                                    {"stage": stage, "detail": detail_msg})
                return {"accepted": False, "tier": T3, "g1_blocked": True,
                        "error": {"error_code": "G1_BLOCKED",
                                  "failed_node": spec.get("id", "?"),
                                  "reason": f"G1 铁门禁：{detail_msg}——禁细节（大形先行）",
                                  "suggestions": [{"action": "fix_or_drop",
                                                   "target": n} for n, _ in blocked]}}

        tier = self.policy.classify(spec)
        if stage == "blockout":
            tier = T3            # M7-3 目验铁门禁：大形剪影必须人看（AUTOPILOT 不豁免）
        r = self.con.compile(spec)
        if not r.ok:
            return {"accepted": False, "compile_error": r.error,
                    "tier": tier,
                    "error": r.error}
        seg = spec["id"]
        gate = self.con.verify(f"director:{seg}")
        try:
            rd = self.con.render_diff(f"propose_{seg}")
            degraded = False
        except Exception as exc:                 # M7-3 渲染降级 △：异常路径显式声明
            rd = {"summary": f"渲染降级 △：{exc}", "render_diff_b64": "",
                  "data": {"png_path": None}}
            degraded = True
        # 首帧是基线（无 diff 图）——导演必须能**看见**第一段，补全帧
        img_b64 = rd.render_diff_b64
        if not img_b64 and rd.data.get("png_path"):
            import base64 as _b64
            from pathlib import Path as _Path
            img_b64 = _b64.b64encode(_Path(rd.data["png_path"]).read_bytes()).decode()
        impact = TrustPolicy.impact(spec)
        accepted = tier != T3
        if accepted:
            self.state = "IDLE"
        else:
            self.state = "PRESENTED"
            self.pending = {"seg": seg, "spec": spec, "assumption": assumption,
                            "tier": tier}
        self.stage_of[seg] = stage or "structure"   # M7-2：缺省按中性结构段记录
        rec = {"seg": seg, "tier": tier, "gate_ok": gate.ok,
               "assumption": assumption, "ai_reason": ai_reason,
               "auto_accepted": accepted, "impact": impact,
               "summary": rd.summary, "render_diff_b64": img_b64,
               "png_path": rd.data.get("png_path"),
               "stage": stage, "part": part,
               "deviation": deviation, "degraded": degraded, "sees": sees}
        if deviation:
            self.con.wal.append("director_deviation",
                                {"seg": seg, "deviation": deviation})
        if degraded:
            self.con.wal.append("director_render_degraded",
                                {"seg": seg, "reason": rd.summary})
        self.history.append(rec)
        self.con.wal.append("director_propose", {"seg": seg, "tier": tier,
                                                 "gate_ok": gate.ok,
                                                 "assumption": assumption,
                                                 "auto_accepted": accepted,
                                                 "ai_reason": ai_reason,
                                                 "stage": stage, "part": part,
                                                 "deviation": deviation,
                                                 "degraded": degraded})
        return rec

    # ── 人：通过 / 打回 ──────────────────────────────────────
    def drop_part(self, part: str) -> dict[str, Any]:
        """M7-2 子树回退：按 part 打回整个部件（逆拓扑序逐段 drop_segment）。

        新中间粒度：比单段粗、比全局细——"这个部件推倒重来"（逻辑分支树的回退语义）。
        """
        r = self.con.drop_part(part)
        if not r.ok:
            return {"accepted": False, "error": r.error}
        return {"state": self.state, "dropped": r.data.get("removed", [])}

    def accept(self, note: str = "") -> dict[str, Any]:
        """导演通过待决提案（T3）。通过即落账——回退有 M3 三层兜底，不必怕。"""
        if self.state != "PRESENTED":
            raise RuntimeError("没有待决提案")
        seg = self.pending["seg"]
        self.con.wal.append("director_accept", {"seg": seg, "note": note})
        self.state = "IDLE"
        self.pending = None
        return {"state": self.state, "accepted": seg, "note": note}

    def override(self, note: str) -> dict[str, Any]:
        """导演打回：删层（L1 回退）+ override 计数 + 经验库回写 + D9 差异化建议。

        note 必填（R15：人的语言化中介——打回不带理由，经验库不收）。
        pivot 之后（已导出/落盘）拒绝打回——只许 forward recovery（A29）。
        """
        if self.state != "PRESENTED":
            raise RuntimeError("没有待决提案")
        if not note or not note.strip():
            raise ValueError("override 必须带 note（R15：没有语言化的打回不进经验库）")
        seg = self.pending["seg"]
        pop = self.con.drop_segment(seg)           # 删 modifier + 清 DAG 叶步 + 清簿记
        if not pop.ok:
            # A29：pivot 之后拒绝打回——只许 forward recovery，原样上报
            return {"accepted": False, "error": pop.error, "state": self.state}
        ms = pop.data.get("ms")
        self.con.segments.pop(seg, None)           # 段落簿记同步清除
        self.con._specs.pop(seg, None)
        self.con.override(note)                    # B3：唯一健康指标 +1
        suggestions: list[dict[str, Any]] = []
        if self.con.library is not None:           # M6-3 回写 + D9 建议
            eid = self.con.library.record_override(
                {"seg": seg, "kind": "director_override"}, note=note)
            suggestions = [{"eid": e.eid, "attention": e.attention,
                            "params": e.params}
                           for e in self.con.library.recall({"seg": seg}, n=3)]
        self.con.wal.append("director_override", {"seg": seg, "note": note,
                                                  "popped": seg, "ms": ms,
                                                  "suggestions": len(suggestions)})
        self.state = "IDLE"
        self.pending = None
        return {"state": self.state, "overridden": seg, "popped": seg,
                "ms": ms, "suggestions": suggestions}

    # ── 汇报 ─────────────────────────────────────────────────
    def status(self) -> dict[str, Any]:
        n = len(self.history)
        overrides = self.con.overrides
        return {"state": self.state, "policy": self.policy.name,
                "proposals": n, "overrides": overrides,
                "override_rate": round(overrides / n, 3) if n else 0.0,
                "pending": self.pending["seg"] if self.pending else None,
                "brief": self.brief}

    def finish(self) -> dict[str, Any]:
        """收工：export_state（M9-4）+ 导演会话统计。"""
        st = self.con.export_state().data
        out = {"export": st, "session": self.status(),
               "elapsed_s": round(time.perf_counter() - self._started, 1)}
        self.con.wal.append("director_finish", self.status())
        return out
