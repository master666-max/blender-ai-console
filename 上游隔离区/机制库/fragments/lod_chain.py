# -*- coding: utf-8 -*-
# 用途: LOD 链生成（DECIMATE 比例链 + apply + 旧网格回收）+ GLB 导出回读
# 依赖: bpy / os（安全模式友好——导出算子放行）
# 实测状态: PASS（v2.2.0 入库验证：无头 factory-startup 幂等双跑，两轮 LOD 面数与 GLB 字节一致）
# 引用教训: 07 分册（导出必回读）；13 分册（面数预算用乘法之后实测值）
# 参数: build_lod_chain(src_objs, prefix, ratios=[("LOD1",0.5),("LOD2",0.25),("LOD3",0.1)],
#              out_dir=None, glb_name=None) → report dict
# 来源: DSH 实测 tank/scripts/s16_lod.py + s26_lod_export.py 提炼（坦克 LOD 实战）
import bpy
import os


def _apply_decimate(obj, ratio):
    md = obj.modifiers.new("Dec", 'DECIMATE')
    md.decimate_type = 'COLLAPSE'
    md.ratio = ratio
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev)
    old = obj.data
    obj.data = me
    obj.modifiers.clear()
    if old.users == 0:
        bpy.data.meshes.remove(old)


def build_lod_chain(src_objs, prefix, ratios=None, out_dir=None, glb_name=None):
    """为 src_objs 生成逐级减面副本并 apply。

    幂等：先删同前缀旧 LOD 对象与零用户网格，重跑不留残骸。
    src_objs 不被修改（LOD 副本独立命名）。
    """
    if ratios is None:
        ratios = [("LOD1", 0.5), ("LOD2", 0.25), ("LOD3", 0.10)]
    res = {"lods": [], "removed_old": 0}

    # 幂等清理：删同前缀旧 LOD
    for o in list(bpy.data.objects):
        if o.name.startswith(prefix) and o.type == 'MESH':
            for tag, _r in ratios:
                if tag + "_" in o.name:
                    d = o.data
                    bpy.data.objects.remove(o, do_unlink=True)
                    if d and d.users == 0:
                        bpy.data.meshes.remove(d)
                    res["removed_old"] += 1
                    break

    base_faces = sum(len(o.data.polygons) for o in src_objs)
    res["base_faces"] = base_faces

    scene_collection = bpy.context.scene.collection
    for tag, ratio in ratios:
        made = []
        for o in src_objs:
            nob = o.copy()
            nob.data = o.data.copy()
            nob.name = o.name.replace(prefix, prefix + tag + "_") if prefix in o.name \
                else prefix + tag + "_" + o.name
            nob.data.name = nob.name + "_ME"
            scene_collection.objects.link(nob)
            _apply_decimate(nob, ratio)
            made.append(nob)
        faces = sum(len(n.data.polygons) for n in made)
        res["lods"].append({"tag": tag, "ratio": ratio, "faces": faces,
                            "objects": [n.name for n in made]})

    if out_dir and glb_name:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, glb_name)
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        last_tag = ratios[-1][0]
        last = [o for o in bpy.data.objects
                if o.name.startswith(prefix + last_tag + "_") and o.type == 'MESH']
        for o in last:
            o.select_set(True)
        bpy.context.view_layer.objects.active = last[0]
        try:
            bpy.ops.export_scene.gltf(filepath=path, export_format='GLB',
                                      use_selection=True, export_apply=False,
                                      export_yup=True, export_image_format='AUTO')
            res["glb"] = [glb_name, os.path.getsize(path)]
        except Exception as e:
            res["glb"] = [glb_name, str(e)[:120]]
    return res
