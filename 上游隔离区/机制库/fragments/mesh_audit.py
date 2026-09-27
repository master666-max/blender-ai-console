# -*- coding: utf-8 -*-
# 用途: 几何体检 + 三角面统计（bmesh 路径，免上下文，安全模式友好）
# 依赖: bpy / bmesh
# 实测状态: PASS（skill v1.0 验收：审计+清理对账 411 物体一致）
# 引用教训: 无（原生积木）
# 参数: obj=被审计物体；is_manifold 等属性只在 bmesh 上，MeshEdge 没有
# 来源: skill v1.0 scripts/scene_audit.py 抽象（WO-R1 P3）
import bpy
import bmesh


def geometry_report(obj):
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    r = {
        "name": obj.name,
        "tris": sum(len(p.vertices) - 2 for p in me.polygons),
        "verts": len(me.vertices),
        "non_manifold_edges": 0,
        "boundary_edges": 0,
        "wire_edges": 0,
        "flipped_winding_edges": 0,
        "zero_area_faces": 0,
    }
    for e in bm.edges:
        if e.is_boundary:
            r["boundary_edges"] += 1
        elif not e.is_manifold:
            if e.is_wire:
                r["wire_edges"] += 1
            else:
                r["non_manifold_edges"] += 1
        elif not e.is_contiguous:
            r["flipped_winding_edges"] += 1
    for f in bm.faces:
        if f.calc_area() <= 1e-12:
            r["zero_area_faces"] += 1
    bm.free()
    return r


def audited_tris_evaluated(obj):
    """含修改器的求值三角面数（用完必须 to_mesh_clear，防内存泄漏）。"""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg).to_mesh()
    tri = sum(len(p.vertices) - 2 for p in ev.polygons)
    obj.evaluated_get(dg).to_mesh_clear()
    return tri

# 用法示例（粘贴后调用）：
#   print(json.dumps(geometry_report(bpy.data.objects["TARGET"])))
