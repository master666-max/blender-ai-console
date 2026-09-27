"""m2_dfm_probe.py — check_dfm 修复验证探针（BVHTree + 内偏起点）。

跑法：blender -b --factory-startup -P m2_dfm_probe.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy
import bmesh

bpy.ops.wm.read_factory_settings(use_empty=True)

from gn_verify import check_dfm


def ev_mesh(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    out = [(f.predicate, f.ok, f.value) for f in check_dfm(me, process="fdm")]
    ev.to_mesh_clear()
    return out


print("\n=== [A] 200mm 实心立方体（fdm 应 4 项全过）===")
bpy.ops.mesh.primitive_cube_add(size=0.2)
cube = bpy.context.active_object
for pred, ok, val in ev_mesh(cube):
    print(f"  {pred}: ok={ok} value={val}")

print("\n=== [B] 1mm 薄立方（min_wall 应拦；scale 不进 evaluated mesh，须真尺寸）===")
bpy.ops.mesh.primitive_cube_add(size=0.001, location=(0.5, 0, 0))
thin = bpy.context.active_object
for pred, ok, val in ev_mesh(thin):
    print(f"  {pred}: ok={ok} value={val}")

print("\n=== [C] 直立圆柱（底盖朝下 → overhang 应拦，其余应过）===")
bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.04, depth=0.095,
                                    location=(-0.5, 0, 0))
cyl = bpy.context.active_object
for pred, ok, val in ev_mesh(cyl):
    print(f"  {pred}: ok={ok} value={val}")

print("\n=== [D] 八面体（正八面体：底面法线 z=-0.577，fdm 全过候选正例）===")
bm = bmesh.new()
d = 0.06
v = [bm.verts.new(p) for p in
     ((d, 0, 0), (-d, 0, 0), (0, d, 0), (0, -d, 0), (0, 0, d), (0, 0, -d))]
for tri in ((0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
            (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)):
    bm.faces.new((v[tri[0]], v[tri[1]], v[tri[2]]))
me = bpy.data.meshes.new("Octa")
bm.to_mesh(me)
bm.free()
octa = bpy.data.objects.new("Octa", me)
bpy.context.collection.objects.link(octa)
for pred, ok, val in ev_mesh(octa):
    print(f"  {pred}: ok={ok} value={val}")

print("\nPROBE DONE")
