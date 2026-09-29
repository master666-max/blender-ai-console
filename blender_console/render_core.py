"""render_core.py — 核心渲染管道（与场景内容完全解耦）
================================================================================
设计目标（2026-09-29，用户指令"独立出核心渲染管道，剔除一切方向性干扰"）：
  场景内容（便利店/虎式/任何课题）与渲染管线分离。管线自身用最小测试体块
  （Cornell 式：主盒+球+圆柱+地面）独立验证，质量可评判后再承载真实场景。

组成：
  clear_scene()          清场
  LighRig.apply(style)   灯光装备：三焦点+环境底光（styles: studio/night/neutral）
  CameraRig.setup(...)   Track-To 相机（位置/目标/焦距一次给定）
  RenderCore.still(...)  静帧渲染（分辨率/采样/AOI/Raytracing）
  test_subject()         Cornell 式最小测试体块（验证管道专用，非场景内容）
"""
import bpy, math
from pathlib import Path


# ── 清场 ────────────────────────────────────────────────────
def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


# ── 材质（管道内置基础材质）─────────────────────────────────
def mat(name, color, rough=0.6, metal=0.0, emit=None, es=0.0, alpha=1.0):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = next((nd for nd in m.node_tree.nodes if nd.type == "BSDF_PRINCIPLED"), None)
    if b is None:
        b = m.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1.0)
        b.inputs["Emission Strength"].default_value = es
    if alpha < 1.0:
        b.inputs["Alpha"].default_value = alpha
        m.blend_method = 'BLEND'
    return m


def _bev(o, w=0.012, seg=2):
    md = o.modifiers.new("bev", 'BEVEL')
    md.width = w
    md.segments = seg
    return o


def box(name, size, loc, m, rot=(0, 0, 0), bevel=0.012):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.scale = (size[0]/2, size[1]/2, size[2]/2)
    o.data.materials.append(m)
    if bevel:
        _bev(o, bevel)
    return o


def cyl(name, r, depth, loc, m, rot=(0, 0, 0), verts=24):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, location=loc,
                                        rotation=rot, vertices=verts)
    o = bpy.context.active_object
    o.name = name
    o.data.materials.append(m)
    _bev(o, 0.006)
    return o


def sphere(name, r, loc, m, segs=32):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=loc,
                                         segments=segs, ring_count=segs//2)
    o = bpy.context.active_object
    o.name = name
    o.data.materials.append(m)
    _bev(o, 0.004, 1)
    return o


def plane(name, sx, sy, loc, m, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_plane_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.scale = (sx/2, sy/2, 1)
    o.data.materials.append(m)
    return o


# ── 灯光装备（LightRig）─────────────────────────────────────
# 教训固话（2026-09-29 视觉核验复盘）：
#   * 微缩模型摄影 = 高环境底光（暗部有信息）+ 焦点光——不是"环境压死"
#   * 三焦点：Key（主）+ Fill（补，弱 3:1~4:1）+ Rim（轮廓）
#   * 所有灯 use_contact_shadow（放置感）
class LightRig:
    STYLES = {
        # 夜霓虹：冷环境底 + 暖 Key + 品红 Rim（便利店用）
        "night":  dict(ambient=(0.020, 0.026, 0.048), amb_e=5.0,
                       key=(1.0, 0.72, 0.42), key_e=900, rim=(1.0, 0.30, 0.55), rim_e=300,
                       fill=(0.45, 0.55, 0.85), fill_e=0.55),
        # 影棚：中性高环境（管道验证用——最诚实的形体检视光）
        "studio": dict(ambient=(0.30, 0.32, 0.36), amb_e=2.2,
                       key=(1.0, 0.98, 0.94), key_e=700, rim=(0.85, 0.90, 1.0), rim_e=220,
                       fill=(0.70, 0.74, 0.80), fill_e=0.5),
        # 中性黄昏：暖环境
        "golden": dict(ambient=(0.14, 0.10, 0.07), amb_e=4.0,
                       key=(1.0, 0.80, 0.55), key_e=800, rim=(0.55, 0.65, 1.0), rim_e=280,
                       fill=(0.55, 0.45, 0.40), fill_e=0.5),
    }

    def __init__(self, style="studio", world_strength=None):
        cfg = dict(self.STYLES[style])
        if world_strength is not None:
            cfg["amb_e"] = world_strength
        w = bpy.data.worlds.get("RC_World") or bpy.data.worlds.new("RC_World")
        bpy.context.scene.world = w
        w.use_nodes = True
        bg = w.node_tree.nodes["Background"]
        bg.inputs[0].default_value = (*cfg["ambient"], 1)
        bg.inputs[1].default_value = cfg["amb_e"]
        self.cfg = cfg

    def three_point(self, target=(0, 0, 0.5), radius=2.2, height=1.9,
                    key_angle=35, rim_angle=-125):
        """三焦点环绕 target：Key 右前上 / Rim 左后上 / Fill 正前（低弱）。"""
        c = self.cfg
        tx, ty, tz = target
        a = math.radians(key_angle)
        kx, ky = tx + radius*math.cos(a), ty - radius*math.sin(a)
        key = bpy.data.lights.new("Key", 'AREA')
        key.energy = c["key_e"]; key.color = c["key"]; key.size = 0.9
        ko = bpy.data.objects.new("Key", key)
        ko.location = (kx, ky, height)
        ko.rotation_euler = (math.radians(48), 0, math.radians(key_angle))
        r = math.radians(rim_angle)
        rx, ry = tx + radius*math.cos(r), ty - radius*math.sin(r)
        rim = bpy.data.lights.new("Rim", 'AREA')
        rim.energy = c["rim_e"]; rim.color = c["rim"]; rim.size = 0.7
        ro = bpy.data.objects.new("Rim", rim)
        ro.location = (rx, ry, height + 0.4)
        ro.rotation_euler = (math.radians(55), 0, math.radians(rim_angle + 180))
        fill = bpy.data.lights.new("Fill", 'AREA')
        fill.energy = c["fill_e"] * 60
        fill.color = c["fill"]; fill.size = 2.4
        fo = bpy.data.objects.new("Fill", fill)
        fo.location = (tx, ty - radius - 1.0, height + 0.5)
        fo.rotation_euler = (math.radians(35), 0, 0)
        for o in (ko, ro, fo):
            bpy.context.collection.objects.link(o)
            if hasattr(o.data, "use_contact_shadow"):
                o.data.use_contact_shadow = True
        return [ko, ro, fo]


# ── 相机装备 ────────────────────────────────────────────────
class CameraRig:
    def __init__(self, loc, target, lens=38, name="RC_Cam"):
        cam_d = bpy.data.cameras.new(name)
        cam_d.lens = lens
        cam = bpy.data.objects.new(name, cam_d)
        bpy.context.collection.objects.link(cam)
        cam.location = loc
        tgt = bpy.data.objects.new(name + "_T", None)
        tgt.location = target
        bpy.context.collection.objects.link(tgt)
        con = cam.constraints.new('TRACK_TO')
        con.target = tgt
        con.track_axis = 'TRACK_NEGATIVE_Z'
        con.up_axis = 'UP_Y'
        bpy.context.scene.camera = cam
        self.cam = cam
        return


# ── 渲染核心 ────────────────────────────────────────────────
class RenderCore:
    def __init__(self, res=(1440, 1080), samples=64):
        sc = bpy.context.scene
        sc.render.engine = 'BLENDER_EEVEE'
        sc.eevee.taa_render_samples = samples
        sc.render.resolution_x, sc.render.resolution_y = res
        try:
            sc.eevee.use_raytracing = True            # 5.2 EEVEE Next GI
        except AttributeError:
            pass

    @staticmethod
    def still(filepath):
        sc = bpy.context.scene
        sc.render.image_settings.file_format = 'PNG'
        sc.render.filepath = str(filepath)
        bpy.ops.render.render(write_still=True)
        return filepath


# ── Cornell 式最小测试体块（验证管道专用）───────────────────
def test_subject():
    """主盒 + 球 + 圆柱 + 地面：覆盖平/曲/竖直面，足以评判
    环境底光/暗部信息/接触阴影/轮廓——与任何场景内容无关。"""
    cyl_m = mat("RC_Metal", (0.55, 0.58, 0.62), 0.25, 0.8)
    M = dict(
        ground=mat("RC_Ground", (0.30, 0.31, 0.36), 0.6),
        body=mat("RC_Body", (0.62, 0.64, 0.70), 0.55),
        ball=mat("RC_Ball", (0.75, 0.30, 0.26), 0.35),
        metal=cyl_m,
        dark=mat("RC_Dark", (0.08, 0.08, 0.10), 0.6),
    )
    plane("RC_Floor", 3.2, 3.2, (0, 0, 0), M["ground"])
    box("RC_Box", (0.7, 0.7, 1.1), (0.35, 0.15, 0.55), M["body"])
    sphere("RC_Ball", 0.30, (-0.42, -0.25, 0.30), M["ball"])
    cyl("RC_Cyl", 0.17, 0.62, (-0.15, 0.42, 0.31), M["metal"])
    box("RC_Back", (2.6, 0.06, 1.5), (0, 0.85, 0.75), M["dark"])
    return M
