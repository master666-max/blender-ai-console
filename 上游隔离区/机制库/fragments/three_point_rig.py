# -*- coding: utf-8 -*-
# 用途: 三点布光 + 相机 rig（Area 三灯 150/40/100W 冷暖 + 50mm TRACK_TO + f/2.8 DOF）
# 依赖: bpy / mathutils
# 实测状态: PASS（skill v1.0 E2E，1280x720 EEVEE 出图回读验证）
# 引用教训: BMCP-ERR-007（视口截图非确定性—— rig 后须设 scene.camera 再渲染）
# 参数: target_loc=瞄准点(米), prefix=命名前缀, cam_pos=机位
# 来源: skill v1.0 scripts/three_point_light.py 抽象（WO-R1 P3）
import bpy
import mathutils


def rig_three_point(target_loc, prefix="RIG_", cam_pos=(7.0, -7.0, 4.0),
                    key_e=150.0, fill_e=40.0, rim_e=100.0):
    for name in (prefix + "Key", prefix + "Fill", prefix + "Rim",
                 prefix + "Cam", prefix + "Aim"):
        old = bpy.data.objects.get(name)
        if old is not None:
            bpy.data.objects.remove(old, do_unlink=True)

    def _light(name, energy, loc, size, color):
        ld = bpy.data.lights.new(name, type='AREA')
        ld.energy = energy
        ld.shape = 'SQUARE'
        ld.size = size
        ld.color = color
        lo = bpy.data.objects.new(name, ld)
        bpy.context.scene.collection.objects.link(lo)
        lo.location = loc
        return lo

    _light(prefix + "Key", key_e,
           (target_loc[0] + 4, target_loc[1] - 4, target_loc[2] + 4), 2.0, (1.0, 0.95, 0.88))
    _light(prefix + "Fill", fill_e,
           (target_loc[0] - 4, target_loc[1] - 3, target_loc[2] + 2), 3.0, (0.85, 0.9, 1.0))
    _light(prefix + "Rim", rim_e,
           (target_loc[0], target_loc[1] + 5, target_loc[2] + 3), 1.0, (1.0, 1.0, 1.0))

    aim = bpy.data.objects.new(prefix + "Aim", None)
    bpy.context.scene.collection.objects.link(aim)
    aim.location = target_loc

    cam_data = bpy.data.cameras.new(prefix + "Cam")
    cam_data.lens = 50.0
    cam_data.dof.use_dof = True
    cam_data.dof.focus_object = aim
    cam_data.dof.aperture_fstop = 2.8
    cam = bpy.data.objects.new(prefix + "Cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = cam_pos
    ctc = cam.constraints.new('TRACK_TO')
    ctc.target = aim
    ctc.track_axis = 'TRACK_NEGATIVE_Z'
    ctc.up_axis = 'UP_Y'
    bpy.context.scene.camera = cam      # 不设这个渲染报 No camera found
    return {"key": prefix + "Key", "fill": prefix + "Fill", "rim": prefix + "Rim",
            "camera": prefix + "Cam"}


def aim_of_object(obj):
    """取物体包围盒中心（世界空间）作为瞄准点。"""
    bb = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    return (sum(v.x for v in bb) / 8.0,
            sum(v.y for v in bb) / 8.0,
            sum(v.z for v in bb) / 8.0)

# 用法示例（粘贴后调用）：
#   rig = rig_three_point(aim_of_object(bpy.data.objects["TARGET"]), prefix="RIG_")
#   print(json.dumps(rig))
