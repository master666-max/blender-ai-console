# -*- coding: utf-8 -*-
# 用途: 高模→低模 selected-to-active 烘焙要点（法线/AO/漫透色，含落盘回读）
# 依赖: bpy / mathutils 无需；安全模式友好（无 open/numpy）
# 实测状态: PASS（v2.2.0 入库验证：无头 factory-startup 幂等双跑，NORMAL 128px 两轮产物一致）
# 引用教训: BMCP-ERR-014（active=低模=落图目标；目标节点不复用——换 image 旧图零用户被回收）
# 参数: bake_s2a(high_obj, low_obj, out_dir, tag, size=1024, samples=16,
#              cage_extrusion=0.004, max_ray_distance=0.02) → report dict
# 来源: DSH 实测 denia/scripts/stage6_bake.py 提炼（爱弥丝烘焙实战）
import bpy
import json
import os


def _new_target_node(mat, img):
    """每个烘焙目标新建 TEX_IMAGE 节点——禁止复用旧节点换图（BMCP-ERR-014）。"""
    node = mat.node_tree.nodes.new('ShaderNodeTexImage')
    node.name = "BAKE_TARGET"
    node.location = (-1400, 400)
    node.image = img
    for n in mat.node_tree.nodes:
        n.select = False
    node.select = True
    mat.node_tree.nodes.active = node
    return node


def _mk_img(name, size, non_color):
    old = bpy.data.images.get(name)
    if old:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(name, size, size, alpha=False, float_buffer=False)
    if non_color:
        img.colorspace_settings.name = 'Non-Color'
    return img


def bake_s2a(high_obj, low_obj, out_dir, tag, size=1024, samples=16,
             cage_extrusion=0.004, max_ray_distance=0.02):
    """selected-to-active 烘焙：high 投射到 low。

    ERR-014 心智模型：**取色看源（选中=high），落图看目标（active=low）**——
    active 必须是低模，方向反了不报错、只出平图。
    """
    res = {}
    scene = bpy.context.scene
    old_engine = scene.render.engine
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.render.bake.margin = 8

    os.makedirs(out_dir, exist_ok=True)
    jobs = [
        ("normal", size, True, {'normal_space': 'TANGENT'}),
        ("ao", max(256, size // 4), True, {}),
        ("basecolor", size, False, {'pass_filter': {'COLOR'}}),
        ("roughness", max(256, size // 2), True, {}),
    ]
    saved = []
    for kind, sz, non_color, kw in jobs:
        img = _mk_img(tag + "_" + kind, sz, non_color)
        for m in low_obj.data.materials:
            if m:
                _new_target_node(m, img)
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        high_obj.select_set(True)
        low_obj.select_set(True)
        bpy.context.view_layer.objects.active = low_obj  # 低模=落图目标
        try:
            if kind == "normal":
                bpy.ops.object.bake(type='NORMAL', use_selected_to_active=True,
                                    cage_extrusion=cage_extrusion,
                                    max_ray_distance=max_ray_distance, **kw)
            else:
                bpy.ops.object.bake(type={'ao': 'AO', 'basecolor': 'DIFFUSE',
                                          'roughness': 'ROUGHNESS'}[kind],
                                    use_selected_to_active=True, **kw)
            res[kind] = "ok"
        except Exception as e:
            res[kind] = str(e)[:120]
            continue
        img.filepath_raw = os.path.join(out_dir, tag + "_" + kind + ".png")
        img.file_format = 'PNG'
        try:
            img.save()
            saved.append([tag + "_" + kind + ".png", list(img.size)])
        except Exception as e:
            saved.append([tag + "_" + kind + ".png", str(e)[:60]])
    scene.render.engine = old_engine
    res["saved"] = saved
    res["low_faces"] = len(low_obj.data.polygons)
    return res


if __name__ == "__main__":
    print("BAKE_REPORT " + json.dumps(res))
