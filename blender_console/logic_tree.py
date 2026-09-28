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

    def pass_gate(self, nid: str, evidence: str = "") -> None:
        n = self.byid[nid]
        if n["status"] != "building":
            raise ValueError(f"{nid}: 状态 {n['status']} 不可过门（需 building）")
        n["status"] = "passed"
        self.evidence.setdefault(nid, []).append(evidence or "gate passed")

    def fail_gate(self, nid: str, reason: str = "") -> None:
        n = self.byid[nid]
        if n["status"] != "building":
            raise ValueError(f"{nid}: 状态 {n['status']} 不可打回（需 building）")
        n["status"] = "failed"
        self.evidence.setdefault(nid, []).append("FAILED: " + (reason or "gate failed"))

    def retry(self, nid: str) -> None:
        """failed → pending（修正后重新排队）"""
        if self.byid[nid]["status"] != "failed":
            raise ValueError(f"{nid}: 仅 failed 可 retry")
        self.byid[nid]["status"] = "pending"

    def progress(self) -> dict[str, int]:
        counts: dict[str, int] = {"passed": 0, "failed": 0, "pending": 0,
                                  "building": 0, "blocked": 0, "total": len(self.byid)}
        for n in self.tree["nodes"]:
            counts[n["status"]] = counts.get(n["status"], 0) + 1
        return counts
