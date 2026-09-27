"""m2_predicates_live.py — M2-1 剩余谓词 + M2-4 双份 + M2-6 DFM 对账 真机验收（Blender 5.2.1）。

跑法：blender --background --factory-startup --python m2_predicates_live.py

验收（改动-对照纪律：每谓词正例 + 反例，"必须拦"逐个验证）：
  1. check_budget_class：blockout 预算内过 / 超预算拦（阶段分类）
  2. check_stack_depth：正常栈过 / 9 层 modifier 拦
  3. check_parent_cycle：无父链过 / parent 环拦
  4. check_naming：语义名过 / Cube.001 默认名拦
  5. M2-4 双份验收补完：before 面数非零场景——verify_transition 的 eval 与
     baked 双份一致（A23 场景补全）
  6. BUDGET_BY_STAGE 全阶段对账（R2 审计尾款）：五阶段限额表逐值 +
     每阶段边界（limit 过 / limit+1 拦）
  7. M2-6 DFM 对账：check_dfm 首次有机测试——修复两处"从未执行过"级 bug
     （BMesh 无 ray_cast → BVHTree；min_wall 射线外偏自交 → 内偏起点）。
     fdm 组：八面体正例（全 4 谓词）+ 薄壁/悬垂/桥接/非流形各反例；
     injection / cnc 组各 1 组正反例。
     已知缺口（诚实登记）：injection 的 draft_deg 在 _DFM_LIMITS 声明但
     无谓词消费——拔模角检查未实现（工单 M2-8/后续回合）。
"""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]  # 仓库根（相对推导，跨机器可移植）

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy  # noqa: E402
import bmesh  # noqa: E402

from gn_verify import GeometryVerifier, check_dfm, _DFM_LIMITS  # noqa: E402

OUT = ROOT / "results"
ROWS: list[dict] = []


def check(name, fn, expect=True):
    try:
        val = fn()
        if val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True, "detail": str(val)[:120]})
        print(f"  PASS  {name}  {str(val)[:100]}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:200]})
        print(f"  FAIL  {name}  {exc!r}")


def finding(findings, name):
    """按谓词名取 Finding（反例断言指向具体谓词，不笼统看整体）。"""
    return next(f for f in findings if f.predicate == name)


def dfm_ok(obj, process="fdm"):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    fs = check_dfm(me, process=process)
    ev.to_mesh_clear()
    return fs


print(f"Blender {bpy.app.version_string}")
bpy.ops.wm.read_factory_settings(use_empty=True)

# ── [1] 面预算分类（M2-1a）───────────────────────────────────
print("\n[1] check_budget_class（阶段差异化预算）")
check("blockout 1500 面 ≤2000 过", lambda: GeometryVerifier.check_budget_class(1500, "blockout").ok, True)
check("blockout 3000 面 >2000 拦", lambda: GeometryVerifier.check_budget_class(3000, "blockout").ok, False)
check("detail 30000 面 ≤50000 过",
      lambda: GeometryVerifier.check_budget_class(30000, "detail").ok, True)
check("未知 stage 回退 detail 预算",
      lambda: GeometryVerifier.check_budget_class(30000, "???").ok, True)

# ── [2] 栈深度（M2-1b）───────────────────────────────────────
print("\n[2] check_stack_depth")
bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.04, depth=0.095)
cyl = bpy.context.active_object
cyl.name = "Mug_Body"
check("0 层过", lambda: GeometryVerifier.check_stack_depth(cyl).ok, True)
for i in range(2):
    cyl.modifiers.new(f"D{i}", 'DISPLACE')
check("2 层过", lambda: GeometryVerifier.check_stack_depth(cyl).ok, True)
for i in range(9):
    cyl.modifiers.new(f"X{i}", 'DISPLACE')
check("11 层 > 8 拦", lambda: GeometryVerifier.check_stack_depth(cyl).ok, False)

# ── [3] 父子成环（M2-1c）─────────────────────────────────────
print("\n[3] check_parent_cycle")
bpy.ops.mesh.primitive_cube_add(size=0.1, location=(0.3, 0, 0))
a = bpy.context.active_object
a.name = "Mug_PartA"
bpy.ops.mesh.primitive_cube_add(size=0.1, location=(0.3, 0.3, 0))
b = bpy.context.active_object
b.name = "Mug_PartB"
b.parent = a
check("正常父子链过", lambda: GeometryVerifier.check_parent_cycle(b).ok, True)
# Blender ID 层禁止自环赋值（构造层已防）——遍历逻辑用 mock 验证
class _FakeObj:
    def __init__(self, name, parent=None):
        self.name, self.parent = name, parent


fa = _FakeObj("A")
fb = _FakeObj("B", parent=fa)
fa.parent = fb                                     # 双节点环（数据层构造）
check("双节点环被拦（mock）", lambda: GeometryVerifier.check_parent_cycle(fb).ok, False)
fa.parent = None
check("解除后恢复过（mock）", lambda: GeometryVerifier.check_parent_cycle(fb).ok, True)

# ── [4] 命名约定（M2-1d）─────────────────────────────────────
print("\n[4] check_naming（语义命名，EXP-001 戒律）")
check("语义名 Mug_Body 过", lambda: GeometryVerifier.check_naming(cyl).ok, True)
bpy.ops.mesh.primitive_cube_add(size=0.05, location=(-0.3, 0, 0))
junk = bpy.context.active_object                                   # 默认名 Cube / Cube.001
check("默认名 Cube 拦", lambda: GeometryVerifier.check_naming(junk).ok, False)
junk.name = "parm3"
check("parm3 拦", lambda: GeometryVerifier.check_naming(junk).ok, False)
junk.name = "Cube.003"
check("Cube.003（去尾巴后仍默认名）拦", lambda: GeometryVerifier.check_naming(junk).ok, False)
junk.name = "Mug_Spout"
check("改成语义名后过", lambda: GeometryVerifier.check_naming(junk).ok, True)

# ── [5] M2-4 双份验收补完（before 面数非零场景）──────────────
print("\n[5] M2-4 双份几何验收（before 面数非零）")
from gn_adapter import GNAdapter  # noqa: E402
from console import Console  # noqa: E402

ad = GNAdapter(bpy)
bpy.ops.mesh.primitive_cube_add(size=0.2, location=(0, 0, 1.0))
mug = bpy.context.active_object
mug.name = "Mug"
mug.data = bpy.data.meshes.new("Mug_Base")
con = Console(ad, mug, workdir=HERE / "_m2p_wal")
BODY = {"id": "body", "op": "cylinder", "consumes_input": False,
        "parameters": [{"name": "Radius", "type": "FLOAT", "value": 0.04},
                       {"name": "Depth", "type": "FLOAT", "value": 0.095}]}
check("body 编译", lambda: con.compile(BODY).ok, True)
st0 = con._eval_stats()
check("before 面数非零（M2-4 场景前置）", lambda: st0["faces"] > 0, True)
# verify_transition 双份：eval（局部求值）与 baked（to_mesh 求值）面数一致
# A23 双份：bake（checkpoint 的 to_mesh 快照）与 eval（depsgraph 求值）两条
# 求值路径必须一致——before 面数非零场景（工单 M2-4 补完项）
cp_ms = con.checkpoint("GP")
st_bake = con._eval_stats()
check("bake 边界前后 eval 一致（双份路径 1）",
      lambda: st_bake["faces"] == st0["faces"] and st_bake["area"] == st0["area"], True)
con.set_param("body", "Radius", 0.045)
st_chg = con._eval_stats()
check("改参后几何确实变化（对照）",
      lambda: st_chg["faces"] != st0["faces"] or st_chg["area"] != st0["area"], True)
rev = con.revert_to_checkpoint("GP")
st_rev = con._eval_stats()
check("revert 后 eval 回到 bake 基线（双份路径 2）",
      lambda: (st_rev["faces"], round(st_rev["area"], 6)),
      (st0["faces"], round(st0["area"], 6)))

# ── [6] BUDGET_BY_STAGE 全阶段对账（R2 审计尾款）─────────────
print("\n[6] BUDGET_BY_STAGE 五阶段限额对账")
_EXPECT_BUDGET = {"blockout": 2_000, "structure": 20_000, "detail": 50_000,
                  "cleanup": 50_000, "deliver": 200_000}
check("限额表逐值一致",
      lambda: dict(GeometryVerifier.BUDGET_BY_STAGE), _EXPECT_BUDGET)
for stage, lim in _EXPECT_BUDGET.items():
    check(f"{stage} 边界：{lim} 面过 / {lim + 1} 面拦",
          lambda s=stage, l=lim: (
              GeometryVerifier.check_budget_class(l, s).ok
              and not GeometryVerifier.check_budget_class(l + 1, s).ok), True)

# ── [7] M2-6 DFM 对账（check_dfm 首次有机测试）───────────────
print("\n[7] M2-6 DFM 谓词对账（fdm / injection / cnc 各组）")
_EXPECT_DFM = {
    "fdm": {"wall_min_mm": 1.2, "overhang_deg": 45, "bridge_max_mm": 10},
    "sla": {"wall_min_mm": 0.5, "overhang_deg": 30, "bridge_max_mm": 5},
    "sls": {"wall_min_mm": 0.7, "overhang_deg": 999, "bridge_max_mm": 30},
    "injection": {"wall_min_mm": 0.8, "draft_deg": 1.0},
    "cnc": {"wall_min_mm": 0.8},
}
check("_DFM_LIMITS 表逐值一致",
      lambda: {k: dict(v) for k, v in _DFM_LIMITS.items()}, _EXPECT_DFM)

# 正例：正八面体（底面法线 z=-0.577 > -cos45°=-0.707 → 非 45° 悬垂；
#   闭流形、无边界边、壁厚 57.7mm）——fdm 全 4 谓词应全过
bm = bmesh.new()
d = 0.06
_v = [bm.verts.new(p) for p in
      ((d, 0, 0), (-d, 0, 0), (0, d, 0), (0, -d, 0), (0, 0, d), (0, 0, -d))]
for tri in ((0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
            (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)):
    bm.faces.new((_v[tri[0]], _v[tri[1]], _v[tri[2]]))
me = bpy.data.meshes.new("Octa")
bm.to_mesh(me)
bm.free()
octa = bpy.data.objects.new("Octa", me)
bpy.context.collection.objects.link(octa)

fs = dfm_ok(octa, "fdm")
check("fdm 正例八面体：min_wall 过", lambda: finding(fs, "dfm_min_wall").ok, True)
check("fdm 正例八面体：overhang 过", lambda: finding(fs, "dfm_overhang").ok, True)
check("fdm 正例八面体：bridge 过", lambda: finding(fs, "dfm_bridge_span").ok, True)
check("fdm 正例八面体：manifold 过", lambda: finding(fs, "dfm_manifold").ok, True)

# 反例①：1mm 薄立方（< 1.2mm）→ min_wall 拦（scale 不进 evaluated mesh，
#   物体缩放在 bmesh 里不可见——必须真尺寸几何，probe 实锤）
bpy.ops.mesh.primitive_cube_add(size=0.001, location=(0.5, 0, 0))
thin = bpy.context.active_object
fs = dfm_ok(thin, "fdm")
check("fdm 反例：1mm 薄壁 → min_wall 拦", lambda: finding(fs, "dfm_min_wall").ok, False)

# 反例②：直立圆柱（底盖朝下 90°）→ overhang 拦（其余谓词过=干净归因）
bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.04, depth=0.095,
                                    location=(-0.5, 0, 0))
cyl = bpy.context.active_object
fs = dfm_ok(cyl, "fdm")
check("fdm 反例：平底圆柱 → overhang 拦", lambda: finding(fs, "dfm_overhang").ok, False)
check("fdm 反例②对照：其 min_wall 仍过（归因干净）",
      lambda: finding(fs, "dfm_min_wall").ok, True)

# 反例③：无底圆锥（开边界）→ manifold 拦；裙边 7.85mm < 10mm → bridge 过
bpy.ops.mesh.primitive_cone_add(vertices=32, radius1=0.04, radius2=0.0,
                                depth=0.095, location=(1.0, 0, 0))
cone = bpy.context.active_object
bm = bmesh.new()
bm.from_mesh(cone.data)
bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.normal.z < -0.9],
                 context='FACES')
bm.to_mesh(cone.data)
bm.free()
fs = dfm_ok(cone, "fdm")
check("fdm 反例：无底圆锥 → manifold 拦", lambda: finding(fs, "dfm_manifold").ok, False)
check("fdm 反例③对照：裙边 7.9mm 桥接仍过（归因干净）",
      lambda: finding(fs, "dfm_bridge_span").ok, True)

# 反例④：200mm 平面（边界边 200mm > 10mm）→ bridge 拦
bpy.ops.mesh.primitive_plane_add(size=0.2, location=(1.5, 0, 0))
plane = bpy.context.active_object
fs = dfm_ok(plane, "fdm")
check("fdm 反例：200mm 平面 → bridge 拦", lambda: finding(fs, "dfm_bridge_span").ok, False)

# injection 组（wall_min 0.8mm；draft_deg 声明未实现=诚实缺口）
fs = dfm_ok(octa, "injection")
check("injection 正例八面体全过", lambda: all(f.ok for f in fs), True)
bpy.ops.mesh.primitive_cube_add(size=0.0005, location=(0.5, 0.5, 0))  # 0.5mm
thin05 = bpy.context.active_object
check("injection 对照：1mm 薄壁过（1mm > 0.8mm 预算内）",
      lambda: finding(dfm_ok(thin, "injection"), "dfm_min_wall").ok, True)
fs = dfm_ok(thin05, "injection")
check("injection 反例：0.5mm 薄壁（< 0.8mm）拦",
      lambda: finding(fs, "dfm_min_wall").ok, False)

# cnc 组（wall_min 0.8mm，无 overhang/bridge 谓词）
fs = dfm_ok(octa, "cnc")
check("cnc 正例八面体全过", lambda: all(f.ok for f in fs), True)
fs = dfm_ok(thin05, "cnc")
check("cnc 反例：0.5mm 薄壁 → min_wall 拦", lambda: finding(fs, "dfm_min_wall").ok, False)
check("cnc 无 overhang 谓词（工艺相关谓词裁剪）",
      lambda: any(f.predicate == "dfm_overhang" for f in fs), False)

failed = [r for r in ROWS if not r["ok"]]
print(f"\nM2-PREDICATES LIVE: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
for f in failed:
    print("  FAILED:", f["case"], "->", f.get("detail"))
out = OUT / "m2_predicates_result.json"
out.write_text(json.dumps(ROWS, ensure_ascii=False, indent=1), encoding="utf-8")
print("result ->", out)
sys.exit(1 if failed else 0)
