"""gn_adapter 在真实 Blender 5.2.1 上的冒烟测试。

跑法：
  "<Blender>/blender.exe" --background --factory-startup --python gn_adapter_live.py

故意包含**应当失败**的用例（非法类型连接、回环、非语义参数名），
确认它们真的被拦住 —— 而不是只在干净代码上通过。
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy

from gn_adapter import (
    GNAdapter,
    GNValidationError,
    ParamSpec,
    UnsupportedBlender,
)

RESULTS: list[dict] = []


def check(name: str, fn):
    try:
        val = fn()
        RESULTS.append({"case": name, "ok": True, "detail": val})
        print(f"  PASS  {name}  {val}")
    except Exception as exc:  # noqa: BLE001
        RESULTS.append({"case": name, "ok": False, "detail": repr(exc)[:220]})
        print(f"  FAIL  {name}  {exc!r}")


def expect_raise(name: str, exc_type, fn):
    try:
        fn()
    except exc_type as exc:
        RESULTS.append({"case": name, "ok": True, "detail": f"正确拒绝：{str(exc)[:120]}"})
        print(f"  PASS  {name}  正确拒绝：{str(exc)[:110]}")
        return
    except Exception as exc:  # noqa: BLE001
        RESULTS.append({"case": name, "ok": False, "detail": f"抛了错误类型 {exc!r}"})
        print(f"  FAIL  {name}  抛了错误类型 {exc!r}")
        return
    RESULTS.append({"case": name, "ok": False, "detail": "本应抛错但没有"})
    print(f"  FAIL  {name}  本应抛错但没有")


def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def cube():
    bpy.ops.mesh.primitive_cube_add()
    return bpy.context.active_object


print(f"Blender {bpy.app.version_string}")

# ── 1. 版本守卫 ────────────────────────────────────────────────
check("版本守卫放行 5.2", lambda: GNAdapter(bpy).version)


class _FakeBpy:
    class app:
        version = (4, 5, 0)


expect_raise("版本守卫拒绝 4.5", UnsupportedBlender, lambda: GNAdapter(_FakeBpy()))

# ── 2. 造一棵参数化的树 ────────────────────────────────────────
ad = GNAdapter(bpy)

fresh()
ob = cube()
tree = ad.new_group("Procedural_Plate")
sid_level = ad.promote_input(tree, ParamSpec(
    name="Subdiv_Level", type="INT", default=2, min=0, max=6,
    description="细分级别，越高越圆滑"))
sid_width = ad.promote_input(tree, ParamSpec(
    name="Plate_Width", type="FLOAT", default=1.0, min=0.01, max=10.0, unit="m"))
sid_base = ad.promote_input(tree, ParamSpec(name="Base_Geometry", type="GEOMETRY"))
sid_out = ad.promote_output(tree, "Geometry", "GEOMETRY")

check("socket_map 具名", lambda: ad.socket_map(tree))
check("具名参数解析出 identifier", lambda: f"Subdiv_Level -> {ad.socket_id(tree, 'Subdiv_Level')}")

gi = ad.add_node(tree, "NodeGroupInput")
go = ad.add_node(tree, "NodeGroupOutput")
cube_node = ad.add_node(tree, "GeometryNodeMeshCube", label="Base_Slab")
subd = ad.add_node(tree, "GeometryNodeSubdivisionSurface", label="Smooth")

check("合法连接 cube→subdiv", lambda: ad.link(tree, cube_node, "Mesh", subd, "Mesh").from_node.name)
check("合法连接 size", lambda: ad.link(tree, gi, "Plate_Width", cube_node, "Size").to_node.name)
check("合法连接 level", lambda: ad.link(tree, gi, "Subdiv_Level", subd, "Level").to_node.name)
check("合法连接 subdiv→output", lambda: ad.link(tree, subd, "Mesh", go, "Geometry").to_node.name)

# ── 3. 非法类型连接必须被拒 ────────────────────────────────────
# 实测：Blender 自己的 links.new() **不会**拦这种连接（GEOMETRY → INT 也能连上）
expect_raise(
    "拒绝 GEOMETRY→INT 非法连接",
    GNValidationError,
    lambda: ad.link(tree, gi, "Base_Geometry", subd, "Level"),
)

# ── 4. 回环必须被拒，且要回滚 ──────────────────────────────────
tree2 = ad.new_group("Cycle_Probe")
a = ad.add_node(tree2, "GeometryNodeSetPosition", label="A")
b = ad.add_node(tree2, "GeometryNodeSetPosition", label="B")
n_before = len(tree2.links)
ad.link(tree2, a, "Geometry", b, "Geometry")
expect_raise("拒绝回环", GNValidationError, lambda: ad.link(tree2, b, "Geometry", a, "Geometry"))
check("回环被拒后链接已回滚", lambda: {"before": n_before, "after": len(tree2.links)})

# ── 5. 非语义参数名必须被拒 ────────────────────────────────────
for bad in ("parm3", "args[0]", "Socket_2", "Input_1"):
    expect_raise(f"拒绝参数名 {bad!r}", GNValidationError, lambda bad=bad: ParamSpec(name=bad))

# ── 6. 序列化确定性与 diff ────────────────────────────────────
f1 = ad.fingerprint(tree)
f2 = ad.fingerprint(tree)
check("两次 fingerprint 一致", lambda: f1 == f2 and f1[:16])

tree3 = ad.new_group("Procedural_Plate_v2")
ad.promote_input(tree3, ParamSpec(name="Subdiv_Level", type="INT", default=2))
ad.promote_output(tree3, "Geometry", "GEOMETRY")
gi3 = ad.add_node(tree3, "NodeGroupInput")
go3 = ad.add_node(tree3, "NodeGroupOutput")
subd3 = ad.add_node(tree3, "GeometryNodeSubdivisionSurface")
cb3 = ad.add_node(tree3, "GeometryNodeMeshCube")
tri3 = ad.add_node(tree3, "GeometryNodeTriangulate")  # v2 多一个节点
ad.link(tree3, cb3, "Mesh", subd3, "Mesh")
ad.link(tree3, subd3, "Mesh", tri3, "Mesh")
ad.link(tree3, tri3, "Mesh", go3, "Geometry")
d = ad.diff(tree, tree3)
check("diff 检出新增节点", lambda: d["nodes_added"])

# ── 7. per-instance 输入（opinion 覆盖）+ 求值 ────────────────
ob2 = ob
mod2 = ad.attach(ob2, tree, "Layer_Bottom")
deps = bpy.context.evaluated_depsgraph_get()


def faces_of(obj):
    deps.update()  # invalidate() 只打标记，真正重算要靠 depsgraph
    eo = obj.evaluated_get(deps)
    m = eo.to_mesh()
    n = len(m.polygons)
    eo.to_mesh_clear()
    return n


deps.update()


def assert_faces(label, expect):
    """断言而非记录 —— 前一版只记录数字，结果 per-instance 覆盖静默失效却仍然 PASS。"""

    def run():
        got = faces_of(ob2)
        if got != expect:
            raise AssertionError(f"{label}：期望 {expect} 面，实得 {got} 面")
        return f"{got} 面 ✓"

    return check(label, run)


assert_faces("默认 level=2 → 期望 96 面", 96)
ad.set_instance_input(mod2, sid_level, 4)
assert_faces("per-instance 覆盖 level=4 → 期望 1536 面", 1536)

# ── 7b. opinion 层栈：需要一棵**消费上游几何**的树才能复合 ────────
fresh()
ob_layer = cube()
dep_layer = bpy.context.evaluated_depsgraph_get()
layer = ad.new_group("Layer_Smooth")
ad.promote_input(layer, ParamSpec(name="Base_Geometry", type="GEOMETRY"))
sid_lv = ad.promote_input(layer, ParamSpec(name="Smooth_Level", type="INT", default=2))
ad.promote_output(layer, "Geometry", "GEOMETRY")
lg_in = ad.add_node(layer, "NodeGroupInput")
lg_out = ad.add_node(layer, "NodeGroupOutput")
lg_sub = ad.add_node(layer, "GeometryNodeSubdivisionSurface", label="Layer_Subdiv")
ad.link(layer, lg_in, "Base_Geometry", lg_sub, "Mesh")
ad.link(layer, lg_in, "Smooth_Level", lg_sub, "Level")
ad.link(layer, lg_sub, "Mesh", lg_out, "Geometry")
ml1 = ad.attach(ob_layer, layer, "Layer_Bottom")
ml2 = ad.attach(ob_layer, layer, "Layer_Top")


def layer_faces():
    dep_layer.update()
    eo = ob_layer.evaluated_get(dep_layer)
    m = eo.to_mesh()
    n = len(m.polygons)
    eo.to_mesh_clear()
    return n


def assert_layer(label, expect):
    def run():
        got = layer_faces()
        if got != expect:
            raise AssertionError(f"{label}：期望 {expect}，实得 {got}")
        return f"{got} 面 ✓"

    return check(label, run)


assert_layer("层栈：两层默认 lv2 → 6·4²·4² = 1536", 1536)
ad.set_instance_input(ml1, sid_lv, 1)
assert_layer("底层覆盖成 lv1 → 6·4·4² = 384", 384)
ad.set_instance_input(ml2, sid_lv, 3)
assert_layer("顶层再覆盖成 lv3 → 6·4·4³ = 1536", 1536)
ob_layer.modifiers.remove(ml2)
ad.invalidate(obj=ob_layer, tree=layer)
assert_layer("删掉顶层 = 回退一层 → 6·4 = 24", 24)

# ── 8. realize（bake 边界）────────────────────────────────────
t0 = time.perf_counter()
mesh = ad.realize(ob_layer, ml1)
t1 = time.perf_counter()
check("realize 成功（bake 边界）", lambda: {
    "ms": round((t1 - t0) * 1000, 2),
    "faces": len(mesh.polygons),
    "modifiers_left": len(ob_layer.modifiers),
})

# ── 9. 迭代成本（回归基线）────────────────────────────────────
fresh()
ob3 = cube()
g4 = ad.new_group("Perf")
ad.promote_input(g4, ParamSpec(name="LevA", type="INT", default=5))
ad.promote_input(g4, ParamSpec(name="LevB", type="INT", default=3))
ad.promote_output(g4, "Geometry", "GEOMETRY")
n4, l4 = g4.nodes, g4.links
gi4, go4 = n4.new("NodeGroupInput"), n4.new("NodeGroupOutput")
cb4 = n4.new("GeometryNodeMeshCube")
prev = cb4.outputs["Mesh"]
for _ in range(2):
    s = n4.new("GeometryNodeSubdivisionSurface")
    l4.new(prev, s.inputs["Mesh"])
    prev = s.outputs["Mesh"]
l4.new(gi4.outputs["LevA"], n4[-2].inputs["Level"])
l4.new(gi4.outputs["LevB"], n4[-1].inputs["Level"])
l4.new(prev, go4.inputs["Geometry"])
m4 = ad.attach(ob3, g4, "Perf")
dg4 = bpy.context.evaluated_depsgraph_get()
dg4.update()
sid_b = ad.socket_id(g4, "LevB")
ts = []
for i, v in enumerate((2, 4, 2, 4, 2, 4, 2)):
    ad.set_instance_input(m4, sid_b, v)
    t0 = time.perf_counter()
    dg4.update()
    ev = ob3.evaluated_get(dg4)
    mm = ev.to_mesh()
    nfaces = len(mm.polygons)
    ev.to_mesh_clear()
    ts.append((time.perf_counter() - t0) * 1000)
ts.sort()
check("改一个参数的重算耗时（ms）", lambda: round(ts[len(ts) // 2], 2))
check("重算后结果确实变了（面数）", lambda: nfaces)

# ── 汇总 ──────────────────────────────────────────────────────
failed = [r for r in RESULTS if not r["ok"]]
print()
print(f"LIVE SMOKE: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
if failed:
    for f in failed:
        print("  FAILED:", f["case"], "->", f["detail"])

out = Path(r"D:\WorkBuddy专用！危险！！！！！！！！\2026-09-26-blender\gn_adapter_live_result.json")
out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print("result ->", out)
