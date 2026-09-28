"""logic_tree.py — M7-2 逻辑树机制 v2.0：加载/校验/换算/状态机（纯 Python 无 bpy）
================================================================================

v2.0 重构输入（虎式坦克作业审计 P1-P7 的落地）：
  * 换算单一真源：params_real 存实尺 mm，params_mm 由本模块机器换算（禁止手写）
  * deps 为执行拓扑权威（layer 仅展示分组）——topo_order 按 deps 走
  * validate_logic_tree：schema_version / tier 归属 / status 合法性 /
    deps 存在性 + 无环 / tier1 必须有 machine_spec 谓词 / instances 声明一致性
  * LogicTreeRunner：节点状态机（pending→building→passed/failed），
    门禁结果回写树文件——逻辑树从静态清单升级为作业状态机

树文件格式（schema_version 2.0）要点：
  meta.scale_factor      —— 换算因子（1:35 → 35）
  nodes[].tier           —— 1|2|3（tier_rules 落地）
  nodes[].status         —— pending|building|passed|failed|blocked
  nodes[].build.op       —— 结构化 op（域词表：armor_box/wheel_row/track_loop/...）
  nodes[].build.params_real —— 实尺 mm（单一真源）
  nodes[].build.instances   —— 批量件声明（count/per_side/layout），门禁逐实例迭代
  nodes[].gate.machine_spec —— 机验谓词 {expr, tol_mm|tol_pct|tol_deg|range, ref}
  nodes[].deps           —— 显式依赖（最少充分依赖）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["LogicTreeError", "load_tree", "mm_at_scale", "topo_order",
           "validate_logic_tree", "LogicTreeRunner", "STATUSES"]

STATUSES = ("pending", "building", "passed", "failed", "blocked")
SCHEMA_VERSION = "2.0"


class LogicTreeError(Exception):
    """逻辑树结构错误（issues 为问题清单）"""

    def __init__(self, issues: list[str]) -> None:
        self.issues = list(issues)
        super().__init__("；".join(self.issues[:5]) + ("..." if len(self.issues) > 5 else ""))


def mm_at_scale(real_mm: float, scale_factor: int = 35) -> float:
    """实尺 mm → 模型 mm（机器换算唯一入口——树文件里禁止手写换算值）"""
    return round(real_mm / scale_factor, 2)


def load_tree(path: str | Path) -> dict:
    """加载逻辑树并注入机器换算：build.params_mm = params_real / scale_factor。

    单一真源：JSON 只存 params_real（实尺），params_mm 永远由本函数生成。
    """
    tree = json.loads(Path(path).read_text(encoding="utf-8"))
    sf = int(tree.get("meta", {}).get("scale_factor", 35))
    for node in tree.get("nodes", []):
        real = node.get("build", {}).get("params_real", {})
        mm: dict[str, Any] = {}
        for k, v in real.items():
            if isinstance(v, (int, float)):
                mm[k] = mm_at_scale(v, sf)
            elif isinstance(v, (list, tuple)):
                mm[k] = [mm_at_scale(x, sf) if isinstance(x, (int, float)) else x for x in v]
            else:
                mm[k] = v
        node.setdefault("build", {})["params_mm"] = mm
    return tree


def topo_order(tree: dict) -> list[str]:
    """deps 为执行拓扑权威（layer 仅展示分组）。悬空引用/环 → LogicTreeError。"""
    byid = {n["id"]: n for n in tree.get("nodes", [])}
    order: list[str] = []
    done: set[str] = set()
    visiting: set[str] = set()

    def visit(nid: str) -> None:
        if nid in done:
            return
        if nid not in byid:
            raise LogicTreeError([f"deps 引用不存在的节点：{nid}"])
        if nid in visiting:
            raise LogicTreeError([f"依赖成环：{nid}"])
        visiting.add(nid)
        for d in byid[nid].get("deps", []):
            visit(d)
        visiting.discard(nid)
        done.add(nid)
        order.append(nid)

    for n in tree.get("nodes", []):
        visit(n["id"])
    return order


def validate_logic_tree(tree: dict) -> list[str]:
    """结构校验（v2.0 契约）。返回 issues 列表——空列表 = 合法。"""
    issues: list[str] = []
    if tree.get("schema_version") != SCHEMA_VERSION:
        issues.append(f"schema_version 应为 {SCHEMA_VERSION}，实得 {tree.get('schema_version')!r}")
    byid = {n["id"]: n for n in tree.get("nodes", [])}
    if not byid:
        issues.append("nodes 为空")
        return issues
    sf = int(tree.get("meta", {}).get("scale_factor", 0))
    if sf <= 0:
        issues.append(f"meta.scale_factor 必须为正整数，实得 {sf}")

    for n in tree.get("nodes", []):
        nid = n.get("id", "?")
        if "tier" not in n:
            issues.append(f"{nid}: 缺 tier 归属（tier_rules 落地必填）")
        elif n["tier"] not in (1, 2, 3):
            issues.append(f"{nid}: tier 非法 {n['tier']!r}（限 1|2|3）")
        if n.get("status") not in STATUSES:
            issues.append(f"{nid}: status 非法 {n.get('status')!r}（限 {STATUSES}）")
        build = n.get("build", {})
        if "op" not in build:
            issues.append(f"{nid}: build 缺结构化 op")
        if "params_real" not in build:
            issues.append(f"{nid}: build 缺 params_real（换算单一真源）")
        # tier1 必须有机验谓词
        if n.get("tier") == 1 and "machine_spec" not in n.get("gate", {}):
            issues.append(f"{nid}: tier1 节点缺 gate.machine_spec 谓词（判据不可降格）")
        # instances 一致性：声明了批量就必须有 count；门禁逐实例
        inst = build.get("instances")
        if inst is not None and not isinstance(inst.get("count"), int):
            issues.append(f"{nid}: build.instances.count 缺失或非整数")
        # gate.machine_spec.expr 非空
        ms = n.get("gate", {}).get("machine_spec", {})
        if ms and not ms.get("expr"):
            issues.append(f"{nid}: gate.machine_spec.expr 为空")

    # deps 存在性 + 无环（复用 topo 的校验路径）
    try:
        topo_order(tree)
    except LogicTreeError as e:
        issues.extend(e.issues)
    return issues


class LogicTreeRunner:
    """作业状态机：按 deps 拓扑序推进节点，门禁结果回写。

    next_ready()   —— deps 全 passed 且自身 pending 的节点（可开工集合）
    start(nid)     —— pending → building
    pass_gate(nid, evidence)  —— building → passed（evidence 留痕）
    fail_gate(nid, reason)    —— building → failed（并可 blocked 下游）
    progress()     —— {passed, failed, pending, building, total}
    """

    def __init__(self, tree: dict) -> None:
        issues = validate_logic_tree(tree)
        if issues:
            raise LogicTreeError(issues)
        self.tree = tree
        self.byid = {n["id"]: n for n in tree["nodes"]}
        self.evidence: dict[str, list[str]] = {}

    def _deps_satisfied(self, nid: str) -> bool:
        return all(self.byid[d]["status"] == "passed" for d in self.byid[nid].get("deps", []))

    def next_ready(self) -> list[str]:
        return [n["id"] for n in self.tree["nodes"]
                if n["status"] == "pending" and self._deps_satisfied(n["id"])]

    def start(self, nid: str) -> None:
        n = self.byid[nid]
        if n["status"] != "pending":
            raise ValueError(f"{nid}: 状态 {n['status']} 不可开工（需 pending）")
        if not self._deps_satisfied(nid):
            raise ValueError(f"{nid}: deps 未全部 passed")
        n["status"] = "building"

    def _depth(self, nid: str, _seen: frozenset[str] = frozenset()) -> int:
        """deps 图深度（0 = blockout 层——G1 目验门管辖区，M7-3）。"""
        if nid in _seen:
            return 0
        deps = self.byid[nid].get("deps", [])
        if not deps:
            return 0
        return 1 + max(self._depth(d, _seen | {nid}) for d in deps)

    def pass_gate(self, nid: str, evidence: str = "",
                  actor: str = "engine:evo") -> None:
        """过门。G1 铁门禁（M7-3 上游吸收）：blockout 层（depth==0）剪影/比例是
        人审美判断——机械 verifier 不替代，必须 human:* actor 审定（即使 AUTOPILOT 档）。
        G1 是**阶段维度**强制，TrustPolicy 是**风险维度**分档——两维正交叠加。"""
        n = self.byid[nid]
        if n["status"] != "building":
            raise ValueError(f"{nid}: 状态 {n['status']} 不可过门（需 building）")
        if self._depth(nid) == 0 and not str(actor).startswith("human:"):
            self.evidence.setdefault(nid, []).append(
                "G1 ⛔ blockout 层需 human: actor（阶段维度铁门禁——剪影/比例人审美，verifier 不替代）")
            raise ValueError(f"{nid}: G1 目验门——blockout 层需 human: actor 审定"
                             "（M7-3 阶段维度铁门禁；渲染图已产出供人审定）")
        n["status"] = "passed"
        self.evidence.setdefault(nid, []).append(f"{actor}: {evidence or 'gate passed'}")

    def fail_gate(self, nid: str, reason: str = "") -> None:
        n = self.byid[nid]
        if n["status"] != "building":
            raise ValueError(f"{nid}: 状态 {n['status']} 不可打回（需 building）")
        n["status"] = "failed"
        self.evidence.setdefault(nid, []).append("FAILED: " + (reason or "gate failed"))

    def retry(self, nid: str, sees: str | None = None) -> None:
        """failed → pending（修正后重新排队）。
        M7-3：修正类提案必须引用所见（sees——上一帧具体变化/changed_ratio/diff path）；
        缺失 = 警告留痕**不拦**（上游定盘：警告级）。"""
        if self.byid[nid]["status"] != "failed":
            raise ValueError(f"{nid}: 仅 failed 可 retry")
        if sees:
            self.evidence.setdefault(nid, []).append(f"sees: {sees}")
        else:
            self.evidence.setdefault(nid, []).append("△ sees 缺失（M7-3 目验引用）——留痕不拦")
        self.byid[nid]["status"] = "pending"

    def progress(self) -> dict[str, int]:
        counts: dict[str, int] = {"passed": 0, "failed": 0, "pending": 0,
                                  "building": 0, "blocked": 0, "total": len(self.byid)}
        for n in self.tree["nodes"]:
            counts[n["status"]] = counts.get(n["status"], 0) + 1
        return counts


# ══ 逻辑树 → plan-JSON 桥（v2.0：SEGMENT_OPS 白名单内 + deps 并行）══
OP_TO_SEG = {
    "armor_box":     "boolean_diff",
    "wheel_row":     "array_radial",
    "track_loop":    "sweep_circle",
    "grille":        "array_linear",
    "turret_shell":  "revolve_profile",
    "gun_barrel":    "cylinder",
    "mg_port":       "cylinder",
    "hatch_pair":    "cylinder",
    "mantlet":       "boolean_union",
    "exhaust_pipes": "cylinder",
    "detail_kit":    "array_linear",
    "camo_paint":    "set_material",
    "weathering":    "set_material",
    "display_base":  "cube",
}
GATE_ONLY_OPS = {"proportion_check", "flat_armor_check"}   # 验证门 → constraints


def to_plan(tree: dict) -> dict:
    """逻辑树 → plan-JSON（SEGMENT_OPS 白名单内 + deps 并行正确 + gate 进 constraints）。

    转换规则（M7 最高杠杆）：
      * deps 并行：sections[].depends_on = 逻辑树 deps（**非串链**——修 P1 串链缺陷）
      * build 节点 → sections（op 经 OP_TO_SEG 映射到 SEGMENT_OPS 白名单）
      * gate 节点（GATE_ONLY_OPS）→ constraints（谓词判据，不进几何 sections）
      * params_real 经 mm_at_scale 机器换算进 parameters（单一真源贯穿）
    """
    sections: list[dict] = []
    constraints: list[dict] = []
    byid = byid_of(tree)
    gate_ids = {n["id"] for n in tree.get("nodes", [])
                if n["build"]["op"] in GATE_ONLY_OPS}

    def resolve(deps: list[str]) -> list[str]:
        """deps 指向 gate 节点时穿透到 gate 的 deps（gate 是验证门不是产物）"""
        out: list[str] = []
        for d in deps:
            if d in gate_ids:
                out.extend(resolve(byid[d].get("deps", [])))
            else:
                out.append(d)
        return out

    for nid in topo_order(tree):
        n = byid[nid]
        op = n["build"]["op"]
        if op in GATE_ONLY_OPS:
            constraints.append({
                "id": nid,
                "check": n.get("gate", {}).get("machine", ""),
                "expr": n.get("gate", {}).get("machine_spec", {}).get("expr", ""),
                "tier": n.get("tier", 2)})
            continue
        seg_op = OP_TO_SEG.get(op)
        if seg_op is None:
            continue                      # 无映射的 op 跳过（不产非法 section）
        params = [{"name": k, "type": "FLOAT", "value": v}
                  for k, v in n["build"].get("params_mm", {}).items()]
        sections.append({
            "id": nid,
            "order": len(sections),
            "op": seg_op,
            "stage": "blockout" if not n.get("deps") else "structure",
            "part": n.get("layer", "").split(" ")[0],
            "consumes_input": bool(resolve(list(n.get("deps", [])))),
            "depends_on": resolve(list(n.get("deps", []))),
            "parameters": params})

    return {"version": "0.3",
            "intent": tree.get("prompt", ""),
            "sections": sections,
            "constraints": constraints}


def byid_of(tree: dict) -> dict[str, dict]:
    return {n["id"]: n for n in tree.get("nodes", [])}
