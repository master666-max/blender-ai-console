"""m45_probe3.py — SDF 管线语义探针：operation 枚举 + Threshold 等值面 + 端到端差集。"""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）
import bpy

OUT = ROOT.parent / "2026-09-26-blender"
rep = {}
ng = bpy.data.node_groups.new("_probe3", "GeometryNodeTree")

# 1) SDFGridBoolean 的节点属性（operation 枚举?）
nb = ng.nodes.new("GeometryNodeSDFGridBoolean")
rep["boolean_props"] = [p.identifier for p in nb.bl_rna.properties
                        if not p.identifier.startswith(("rna", "name", "label",
                                                        "location", "color", "width",
                                                        "height", "select", "inputs",
                                                        "outputs", "internal_links",
                                                        "parent", "show", "mute",
                                                        "bl_idname", "use_custom"))]
try:
    nb.operation = "DIFFERENCE"
    rep["operation_set"] = "DIFFERENCE ok"
except Exception as exc:  # noqa: BLE001
    rep["operation_set"] = f"FAIL: {exc!r}"

# 2) 端到端：cube(sdf) difference sphere(sdf) → mesh，数顶点
def _mesh_vox(nid, name):
    n = ng.nodes.new(nid)
    n.name = name
    return n

n_cube = ng.nodes.new("GeometryNodeMeshCube")
n_sph = ng.nodes.new("GeometryNodeMeshUVSphere")
n_sph.inputs["Radius"].default_value = 0.06
m2s1 = _mesh_vox("GeometryNodeMeshToSDFGrid", "m2s_cube")
m2s1.inputs["Voxel Size"].default_value = 0.01
m2s2 = _mesh_vox("GeometryNodeMeshToSDFGrid", "m2s_sph")
m2s2.inputs["Voxel Size"].default_value = 0.01
ng.links.new(n_cube.outputs["Mesh"], m2s1.inputs["Mesh"])
ng.links.new(n_sph.outputs["Mesh"], m2s2.inputs["Mesh"])
ng.links.new(m2s1.outputs["SDF Grid"], nb.inputs["Grid 1"])
ng.links.new(m2s2.outputs["SDF Grid"], nb.inputs["Grid 2"])
g2m = _mesh_vox("GeometryNodeGridToMesh", "g2m")
ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
ng.links.new(g2m.outputs["Mesh"],
             (ng.nodes.new("NodeGroupOutput")).inputs["Geometry"])
obj = bpy.data.objects.get("P") or bpy.data.objects.new("P", bpy.data.meshes.new("P"))
if not obj.users_collection:
    bpy.context.collection.objects.link(obj)
mod = obj.modifiers.get("M") or obj.modifiers.new("M", "NODES")
mod.node_group = ng
for th in (0.0, 0.1):
    g2m.inputs["Threshold"].default_value = th
    ng.links.new(nb.outputs["Grid"], g2m.inputs["Grid"])
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    rep[f"pipeline_th{th}"] = {"verts": len(me.vertices), "polys": len(me.polygons)}
    ev.to_mesh_clear()

(OUT / "m45_probe3.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
print(json.dumps(rep, ensure_ascii=False, indent=1))
print("result ->", OUT / "m45_probe3.json")
