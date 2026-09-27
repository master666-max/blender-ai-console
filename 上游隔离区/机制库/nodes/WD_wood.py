# -*- coding: utf-8 -*-
# 用途: 木纹基础节点组 WD_wood_base（代码重建=唯一事实来源；安全模式禁 append）
# 依赖: bpy
# 实测状态: PASS（v1.4：单次+幂等复跑均验证——v1.3 时 apply_wood 重复调用会累积 None 槽，V-04 修复）
# 引用教训: BMCP-ERR-006 无关；接口用 4.0+ interface.new_socket（旧 API 已删）
# 参数: name=组名, scale=木纹密度默认值
# 来源: 02 分册 §6 配方实体化（WO-R2 F-19）
import bpy


def make_wood_group(name="WD_wood_base", scale_default=2.0):
    # 幂等：先删同名旧组
    old = bpy.data.node_groups.get(name)
    if old is not None:
        bpy.data.node_groups.remove(old)

    grp = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    # 4.0+ 唯一接口 API（grp.inputs.new()/outputs.new() 已删除）
    so_scale = grp.interface.new_socket(
        name="Scale", in_out='INPUT', socket_type='NodeSocketFloat')
    so_scale.default_value = scale_default
    so_scale.min_value = 0.0
    so_scale.max_value = 100.0
    so_light = grp.interface.new_socket(
        name="Color Light", in_out='INPUT', socket_type='NodeSocketColor')
    so_light.default_value = (0.72, 0.55, 0.35, 1.0)
    so_dark = grp.interface.new_socket(
        name="Color Dark", in_out='INPUT', socket_type='NodeSocketColor')
    so_dark.default_value = (0.35, 0.18, 0.06, 1.0)
    grp.interface.new_socket(
        name="Shader", in_out='OUTPUT', socket_type='NodeSocketShader')

    gin = grp.nodes.new('NodeGroupInput');  gin.location = (-600, 0)
    gout = grp.nodes.new('NodeGroupOutput'); gout.location = (600, 0)
    wave = grp.nodes.new('ShaderNodeTexWave'); wave.location = (-350, 100)
    wave.wave_type = 'BANDS'
    wave.bands_direction = 'X'
    wave.wave_profile = 'SIN'
    wave.inputs['Scale'].default_value = scale_default
    wave.inputs['Distortion'].default_value = 6.0    # 扭曲是木纹的灵魂
    wave.inputs['Detail'].default_value = 3.0
    noise = grp.nodes.new('ShaderNodeTexNoise'); noise.location = (-350, -150)
    noise.inputs['Scale'].default_value = 2.0
    noise.inputs['Detail'].default_value = 3.0
    mix = grp.nodes.new('ShaderNodeMix'); mix.location = (-50, 0)
    mix.data_type = 'RGBA'
    mix.blend_type = 'MIX'                            # RGBA 色口 = inputs[6]/[7]，输出口 = outputs[2]
    bump = grp.nodes.new('ShaderNodeBump'); bump.location = (200, -200)
    bump.inputs['Strength'].default_value = 0.15
    bsdf = grp.nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location = (400, 0)
    bsdf.inputs['Roughness'].default_value = 0.45

    grp.links.new(gin.outputs['Scale'], wave.inputs['Scale'])
    grp.links.new(noise.outputs['Fac'], wave.inputs['Vector'])   # 噪声扰动波纹=木纹
    grp.links.new(wave.outputs['Fac'], mix.inputs[0])            # Factor
    grp.links.new(gin.outputs['Color Dark'], mix.inputs[6])      # A_Color
    grp.links.new(gin.outputs['Color Light'], mix.inputs[7])     # B_Color
    grp.links.new(mix.outputs[2], bsdf.inputs['Base Color'])     # Result_Color
    grp.links.new(mix.outputs[2], bump.inputs['Height'])
    grp.links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])
    grp.links.new(bsdf.outputs['BSDF'], gout.inputs[0])
    return grp


def apply_wood(obj, name="WD_wood_base"):
    """把节点组实例化进新材质并挂到物体（V-04 幂等版：复跑不留 None 槽、active 恒有效）。"""
    mat_name = "MAT_" + name
    for i in range(len(obj.data.materials) - 1, -1, -1):
        slot = obj.data.materials[i]
        if slot is not None and slot.name == mat_name:
            obj.data.materials.pop(index=i)   # 先摘旧槽，防 remove 数据块后留 None 空洞
    old = bpy.data.materials.get(mat_name)
    if old is not None and old.users == 0:
        bpy.data.materials.remove(old)
    mat = bpy.data.materials.new(mat_name)
    gnode = mat.node_tree.nodes.new('ShaderNodeGroup')   # 组实例的 bl_idname（'NodeGroup' 不存在！）
    gnode.node_tree = bpy.data.node_groups[name]
    out = None
    for n in mat.node_tree.nodes:
        if n.type == 'OUTPUT_MATERIAL':
            out = n
    if out is None:
        out = mat.node_tree.nodes.new('ShaderNodeOutputMaterial')
    links = mat.node_tree.links
    links.new(gnode.outputs['Shader'], out.inputs['Surface'])
    obj.data.materials.append(mat)
    obj.active_material = mat   # V-04：防 active 指向被摘除的旧槽
    return mat

# 用法示例（粘贴后调用）：
#   make_wood_group()
#   mat = apply_wood(bpy.data.objects["TARGET"])
#   print(json.dumps({"group": "WD_wood_base", "mat": mat.name}))
