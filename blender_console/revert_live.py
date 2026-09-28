"""revert_live.py — 回退功能完整真机实验（Blender 5.2）

实验矩阵（13 步）：
  1  编译三段（cube Size 参数化 / +cylinder Radius 参数化 / +sphere，join 累积）
  2  checkpoint cp1 → SnapshotStore 落盘 + WAL restore_point
  3  set_param seg_b.Radius 0.01→0.03（几何生效，bbox 变大）
  4  revert_to_checkpoint cp1 → 参数回滚，bbox 回原值
  5  pop_layer → 删最后一段（面数下降）
  6  drop_segment seg_b → 打回段落 + DAG/WAL 清理
  7  verify PASS
  8  checkpoint cp2
  9  log_pivot → 语义设防
  10 revert after pivot → PIVOT_BLOCKED（负例）
  11 pop_layer after pivot → PIVOT_BLOCKED（负例）
  12 override("人工打回") → WAL override + KPI 计数
  13 WAL 全量 + 快照盘存 + 汇总
运行：blender.exe --factory-startup --background --python revert_live.py
"""
import bpy, sys, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
WORK = HERE / "revert_work"
WORK.mkdir(exist_ok=True)

ROWS = []
def check(n, desc, cond):
    ROWS.append(cond)
    print("[rv %2d] %s %s" % (n, "PASS" if cond else "FAIL", desc))

def bbox_of(obj, deps):
    ev = obj.evaluated_get(deps)
    m = ev.to_mesh()
    xs = [v.co.x for v in m.vertices] or [0]
    ys = [v.co.y for v in m.vertices] or [0]
    zs = [v.co.z for v in m.vertices] or [0]
    ev.to_mesh_clear()
    return (round(max(xs) - min(xs), 4), round(max(ys) - min(ys), 4),
            round(max(zs) - min(zs), 4))

bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new("rv_root")
root = bpy.data.objects.new("rv_root", mesh)
bpy.context.collection.objects.link(root)
bpy.context.view_layer.objects.active = root

from console import Console
from gn_adapter import GNAdapter
import os
os.environ.setdefault("BLENDER_CONSOLE_WORKDIR", str(WORK))
ad = GNAdapter()
console = Console(ad, root, workdir=str(WORK))

# ── 1 三段编译（join 累积链）──────────────────────────────
SECS = [
    {"id": "seg_a", "op": "cube", "stage": "structure", "part": "a",
     "consumes_input": False, "depends_on": [],
     "parameters": [{"name": "Size", "type": "FLOAT", "value": 0.05}]},
    {"id": "seg_b", "op": "join_geometry", "stage": "structure", "part": "b",
     "consumes_input": True, "depends_on": [],
     "parameters": [{"name": "Radius", "type": "FLOAT", "value": 0.012}],
     "operand": {"op": "cylinder", "radius": 0.012, "depth": 0.04,
                 "parameters": []}},
    {"id": "seg_c", "op": "join_geometry", "stage": "structure", "part": "c",
     "consumes_input": True, "depends_on": [],
     "operand": {"op": "sphere", "radius": 0.018, "parameters": []}},
]
# 实验注记（2026-09-29 真机）：可调参数必须在**顶层 spec** 声明——_build_tree
# 只提升顶层 parameters 为段级 GN socket；operand 嵌套里的 parameters 不提升，
# set_param 会 PARAM_NOT_FOUND。operand 内的 op 通过段级 sid 别名绑定（_A）。

oks = []
for sp in SECS:
    r = console.compile(sp)
    oks.append(r.ok)
    print("   compile %s: %s %s" % (sp["id"], "ok" if r.ok else r.error, ""))
check(1, "三段编译全过（%s）" % oks, all(oks))

deps = bpy.context.evaluated_depsgraph_get()
f0 = len(root.evaluated_get(deps).to_mesh().polygons) if True else 0
ev = root.evaluated_get(deps); m0 = ev.to_mesh(); f0 = len(m0.polygons); ev.to_mesh_clear()
print("   初始面数:", f0)

# ── 2 checkpoint cp1 ─────────────────────────────────────
r = console.checkpoint("cp1")
check(2, "checkpoint cp1: %s" % r.summary, r.ok)
snap_files = sorted(p.name for p in WORK.rglob("*.json*")) if WORK.exists() else []
print("   快照/WAL 盘存:", snap_files[:8])

# ── 3 set_param 几何生效 ─────────────────────────────────
bbox_before = bbox_of(root, deps)
r = console.set_param("seg_b", "Radius", 0.03)
deps = bpy.context.evaluated_depsgraph_get()
bbox_after = bbox_of(root, deps)
grew = bbox_after[0] > bbox_before[0] or bbox_after[1] > bbox_before[1]
check(3, "set_param seg_b.Radius 0.012→0.03 几何生效 bbox%s→%s" % (bbox_before, bbox_after), r.ok and grew)

# ── 4 revert 回滚 ────────────────────────────────────────
r = console.revert_to_checkpoint("cp1")
deps = bpy.context.evaluated_depsgraph_get()
bbox_reverted = bbox_of(root, deps)
check(4, "revert_to_checkpoint cp1 bbox 回滚 %s→%s" % (bbox_after, bbox_reverted),
      r.ok and bbox_reverted == bbox_before)

# ── 5 pop_layer ──────────────────────────────────────────
deps = bpy.context.evaluated_depsgraph_get()
ev = root.evaluated_get(deps); m = ev.to_mesh(); f_pre = len(m.polygons); ev.to_mesh_clear()
r = console.pop_layer()
deps = bpy.context.evaluated_depsgraph_get()
ev = root.evaluated_get(deps); m = ev.to_mesh(); f_post = len(m.polygons); ev.to_mesh_clear()
check(5, "pop_layer 删 seg_c：面数 %d→%d" % (f_pre, f_post), r.ok and f_post < f_pre)

# ── 6 drop_segment seg_b（此时 order[-1]==seg_b）────────
r = console.drop_segment("seg_b")
check(6, "drop_segment seg_b（DAG+WAL 清理）: %s" % r.summary, r.ok)

# ── 7 verify ─────────────────────────────────────────────
r = console.verify("rv-mid")
check(7, "verify: %s" % r.summary, r.ok)

# ── 8 checkpoint cp2 ─────────────────────────────────────
r = console.checkpoint("cp2")
check(8, "checkpoint cp2: %s" % r.summary, r.ok)

# ── 9 log_pivot ──────────────────────────────────────────
r = console.log_pivot("实验：大改方向已定，历史封存")
check(9, "log_pivot: %s" % r.summary, r.ok)

# ── 10 pivot 后 revert → 负例 PIVOT_BLOCKED ──────────────
r = console.revert_to_checkpoint("cp1")
blocked = (not r.ok) and r.error.get("error_code") == "PIVOT_BLOCKED"
check(10, "pivot 后 revert 被拒（PIVOT_BLOCKED）", blocked)

# ── 11 pivot 后 pop_layer → 负例 PIVOT_BLOCKED ───────────
r = console.pop_layer()
blocked = (not r.ok) and r.error.get("error_code") == "PIVOT_BLOCKED"
check(11, "pivot 后 pop_layer 被拒（PIVOT_BLOCKED）", blocked)

# ── 12 override ──────────────────────────────────────────
r = console.override("实验打回：轮距不对")
kpi = console.kpi() if hasattr(console, "kpi") else None
ok12 = r.ok and (kpi is None or kpi.get("overrides", 0) >= 1)
check(12, "override 入账: %s（overrides=%s）" % (r.summary, kpi and kpi.get("overrides")), ok12)

# ── 13 WAL 全量 + 汇总 ──────────────────────────────────
kinds = [ev.get("kind") for ev in console.wal.replay()]
need = {"restore_point", "param", "drop_segment", "verify", "pivot", "override"}
have = need & set(kinds)
check(13, "WAL 六类事件齐（%s）" % sorted(have), have == need)
print("\n   WAL 事件流:", kinds)
snap_refs = sorted(p.name for p in WORK.rglob("*snap*")) if WORK.exists() else []
print("   SnapshotStore 盘存:", snap_refs[:6] or "(目录结构见 WORK)")

failed = sum(1 for x in ROWS if not x)
print("\nREVERT LIVE: %d/%d passed" % (len(ROWS) - failed, len(ROWS)))
sys.exit(1 if failed else 0)
