"""test_logic_tree.py — logic_tree.py v2.0 单元测试（纯 Python，秒级）。

跑法：python test_logic_tree.py
覆盖：tiger_tank.json 正例（加载/校验/换算/拓扑/状态机全流程）
      + 负例四连（缺 tier / 悬空 deps / 环 / tier1 缺谓词）+ instances 批量门。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from logic_tree import (LogicTreeError, LogicTreeRunner, load_tree,  # noqa: E402
                        mm_at_scale, topo_order, validate_logic_tree)

ROWS: list[dict] = []


def check(name, fn, expect=True):
    try:
        val = fn()
        if val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True})
        print(f"  PASS  {name}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:160]})
        print(f"  FAIL  {name}  {exc!r}")


TIGER = HERE / "logic_trees" / "tiger_tank.json"
tree = load_tree(TIGER)

# ── [1] 换算单一真源 ─────────────────────────────────────────
print("[1] 换算器（机器换算唯一入口）")
check("mm_at_scale(6320, 35) = 180.57", lambda: mm_at_scale(6320, 35), 180.57)
check("mm_at_scale(88, 35) = 2.51", lambda: mm_at_scale(88, 35), 2.51)
n11 = next(n for n in tree["nodes"] if n["id"] == "1.1")
check("车体 params_mm 机器生成",
      lambda: (n11["build"]["params_mm"]["L"], n11["build"]["params_mm"]["W"], n11["build"]["params_mm"]["H"]),
      (180.57, 105.86, 85.71))

# ── [2] 结构校验（v2.0 契约）────────────────────────────────
print("\n[2] 结构校验")
issues = validate_logic_tree(tree)
check("tiger_tank v2.0 零 issue", lambda: issues, [])
check("15 节点全部有 tier", lambda: all("tier" in n for n in tree["nodes"]), True)
check("16 节点全部有合法 status（活树：回写后可能 passed）",
      lambda: all(n.get("status") in ("pending", "building", "passed", "failed", "blocked") for n in tree["nodes"]), True)
check("15 节点全部有 deps", lambda: all("deps" in n for n in tree["nodes"]), True)
order = topo_order(tree)
check("deps 拓扑序 16 节点无环", lambda: len(order), len(tree["nodes"]))
n22 = next(n for n in tree["nodes"] if n["id"] == "2.2")
check("执行拓扑权威=deps（主炮只依赖炮塔，不串链履带）",
      lambda: n22["deps"], ["2.1"])

# ── [3] 负例：坏树必须被拦 ───────────────────────────────────
print("\n[3] 负例四连")
import copy
bad = copy.deepcopy(tree)
bad["nodes"][0].pop("tier")
check("缺 tier → 报 issue", lambda: any("tier" in i for i in validate_logic_tree(bad)), True)

def _raises_lt(tree_bad):
    try:
        topo_order(tree_bad)
        return False
    except LogicTreeError:
        return True


bad2 = copy.deepcopy(tree)
bad2["nodes"][0]["deps"] = ["不存在的节点"]
check("悬空 deps → LogicTreeError", lambda: _raises_lt(bad2), True)

bad3 = copy.deepcopy(tree)
for n in bad3["nodes"]:
    if n["id"] == "4.1":
        n["deps"] = ["4.2"]          # 4.1↔4.2 互指成环
try:
    topo_order(bad3)
    ring_caught = False
except LogicTreeError:
    ring_caught = True
check("依赖成环 → LogicTreeError", lambda: ring_caught, True)

bad4 = copy.deepcopy(tree)
for n in bad4["nodes"]:
    if n["id"] == "1.1":
        n["tier"] = 1
        n["gate"].pop("machine_spec", None)
check("tier1 缺 machine_spec → 报 issue", lambda: any("machine_spec" in i for i in validate_logic_tree(bad4)), True)


def _raises_lt(tree_bad):
    try:
        topo_order(tree_bad)
        return False
    except LogicTreeError:
        return True


# ── [4] 状态机全流程（虎式 15 节点按拓扑序推进）─────────────
print("\n[4] 状态机全流程")
_fresh = load_tree(TIGER)
for _n in _fresh["nodes"]:
    _n["status"] = "pending"      # 活树回写后 status 可能是 passed——状态机测试用重置副本
runner = LogicTreeRunner(_fresh)
check("初态全 pending", lambda: runner.progress()["pending"], len(_fresh["nodes"]))
steps = 0
while True:
    ready = runner.next_ready()
    if not ready:
        break
    for nid in ready:
        runner.start(nid)
        runner.pass_gate(nid, evidence=f"fixture {nid}")
        steps += 1
    if steps > 100:
        break
check("全流程节点逐门通过", lambda: runner.progress()["passed"], len(_fresh["nodes"]))
check("进度归零（无残留 pending）", lambda: runner.progress()["pending"], 0)
try:
    runner.start("1.1")
    check("已 passed 节点不可重复开工", lambda: False, True)
except ValueError:
    check("已 passed 节点不可重复开工", lambda: True, True)
check("evidence 留痕", lambda: len(runner.evidence.get("1.1", [])) >= 1, True)

# ── [5] instances 批量门声明 ────────────────────────────────
print("\n[5] instances 批量门")
n12 = next(n for n in tree["nodes"] if n["id"] == "1.2")
check("负重轮 instances.count=16", lambda: n12["build"]["instances"]["count"], 16)
check("负重轮 per_side=8", lambda: n12["build"]["instances"]["per_side"], 8)
check("舱门 instances.count=2", lambda: next(n for n in tree["nodes"] if n["id"] == "2.4")["build"]["instances"]["count"], 2)

failed = [r for r in ROWS if not r["ok"]]
print(f"\nLOGIC TREE UNIT: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
for f in failed:
    print("  FAILED:", f["case"], "->", f.get("detail"))
# ── [6] 逻辑树→plan 桥（M7：PlanSchema 零 issue + deps 并行）──
print("\n[6] 逻辑树→plan 桥")
from logic_tree import to_plan
from plan_schema import validate_plan
plan = to_plan(tree)
issues = validate_plan(plan, segment_names=[s['id'] for s in plan['sections']])
check("PlanSchema 零 issue", lambda: len(issues), 0)
dm = {s['id']: s['depends_on'] for s in plan['sections']}
check("主炮只依赖炮塔（并行非串链）", lambda: dm.get("2.2"), ["2.1"])
check("负重轮只依赖车体（并行）", lambda: dm.get("1.2"), ["1.1"])
check("gate 穿透（3.1/3.2 不进 sections）",
      lambda: all(s['id'] not in ('3.1', '3.2') for s in plan['sections']), True)
check("constraints 2 条（gate 节点入约束）", lambda: len(plan['constraints']), 2)

sys.exit(1 if failed else 0)
