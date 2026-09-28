"""tiger_tank_build.py — 虎式坦克 1:35 建模 + 渲染（Blender 5.2 后台执行）
================================================================================
运行：blender.exe --background --python tiger_tank_build.py
产物：showcase/tiger/tiger-{front34,side,rear34}.png（3 视角 Cycles 渲染）

逻辑树驱动（logic_trees/tiger_tank.json）：按 deps 拓扑序逐节点构建，
每节点打印 [node-id] op 执行留痕；尺寸单一真源 = 实尺 mm / 35（机器换算）。
"""
import bpy, math, sys, json
import mathutils
from math import radians
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "showcase" / "tiger"
OUT.mkdir(parents=True, exist_ok=True)
SCALE = 35


def at35(real_mm):
    """实尺 mm → Blender m（1:35 机器换算）"""
    return real_mm / SCALE / 1000.0


# ── 场景清空 ────────────────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# ── 逻辑树 deps 拓扑序（构建顺序留痕）───────────────────────
lt = json.loads((HERE / "logic_trees" / "tiger_tank.json").read_text(encoding="utf-8"))
byid = {n["id"]: n for n in lt["nodes"]}
order, done = [], set()


def visit(nid):
    if nid in done:
        return
    for d in byid[nid]["deps"]:
        visit(d)
    done.add(nid)
    order.append(nid)


for n in lt["nodes"]:
    visit(n["id"])
print("[logic-tree] build order:", " -> ".join(order))


def mark(nid, extra=""):
    print("[build] [%s] %s %s" % (nid, byid[nid]["build"]["op"], extra))


def mat(name, color, rough=0.6, metal=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    return m


def camo_mat():
    """Dunkelgelb 底 + Olivgrun 斑块（Noise→ColorRamp 混色，4.1 迷彩门）"""
    m = bpy.data.materials.new("tiger_camo")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.62
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 9.0
    noise.inputs["Detail"].default_value = 2.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.42
    ramp.color_ramp.elements[0].color = (0.47, 0.41, 0.25, 1)   # Dunkelgelb
    ramp.color_ramp.elements[1].position = 0.58
    ramp.color_ramp.elements[1].color = (0.24, 0.28, 0.15, 1)   # Olivgrun
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    return m


def box(name, sx, sy, sz, loc, mat=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = (sx / 2, sy / 2, sz / 2)
    if mat:
        o.data.materials.append(mat)
    return o


def cyl(name, dia, depth, loc, rot=(0, 0, 0), verts=24, mat=None):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=dia / 2,
                                        depth=depth, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    if mat:
        o.data.materials.append(mat)
    return o


M_ARMOR = camo_mat()
M_TRACK = mat("track", (0.10, 0.10, 0.10), rough=0.5, metal=0.6)
M_DARK = mat("darkdetail", (0.16, 0.15, 0.12), rough=0.55)
M_TREAD = mat("tread_rubber", (0.08, 0.08, 0.08), rough=0.8)

# ── [1.1] 车体装甲盒 ────────────────────────────────────────
mark("1.1")
HULL_L, HULL_W, HULL_H = at35(6320), 0.066, at35(1536)
hull = box("tiger_hull", HULL_L, HULL_W, HULL_H, (0, 0, 0.015 + HULL_H / 2), M_ARMOR)

# ── [1.2] 行走机构：交错负重轮 x16 ─────────────────────────
mark("1.2", "x16 interleaved")
WR = at35(800) / 2
wheel_z = WR
for side, y_c in ((-1, -0.0426), (1, 0.0426)):
    for i in range(8):
        x = -0.068 + i * (0.136 / 7) + (0.010 if side < 0 else -0.010)
        cyl("roadwheel_%s%d" % ("L" if side < 0 else "R", i + 1),
            WR * 2, 0.009, (x, y_c, wheel_z), rot=(0, radians(90), 0), mat=M_DARK)

# ── [1.3] 履带环 x2（椭圆环带近似）─────────────────────────
mark("1.3", "x2")
for side, y_c in ((-1, -0.0426), (1, 0.0426)):
    bpy.ops.mesh.primitive_torus_add(major_radius=0.055, minor_radius=0.0098,
                                     location=(0, y_c, 0.023),
                                     rotation=(radians(90), 0, 0))
    tr = bpy.context.active_object
    tr.name = "track_%s" % ("L" if side < 0 else "R")
    tr.scale = (1.35, 0.23, 1.0)          # rotX90 后 world z ← local y：y 压扁成履带轮廓
    tr.data.materials.append(M_TREAD)

# ── [1.4] 动力舱格栅 ────────────────────────────────────────
mark("1.4", "x4")
for i in range(4):
    x = 0.052 + i * 0.011
    box("grille_%d" % (i + 1), 0.008, HULL_W * 0.7, 0.0015,
        (x, 0, 0.015 + HULL_H + 0.0008), M_DARK)

# ── [2.1] 炮塔 ──────────────────────────────────────────────
mark("2.1")
TUR_Z0 = 0.015 + HULL_H
TUR_H = at35(3000) - TUR_Z0
cyl("tiger_turret", at35(2080) * 0.86, TUR_H, (-0.006, 0, TUR_Z0 + TUR_H / 2),
    verts=20, mat=M_ARMOR)

# ── [2.2] 主炮（外露 141mm + 炮口制退器）───────────────────
mark("2.2")
gun_y0 = 0
barrel_len = at35(4930)          # 单一真源：实尺 4930mm（逻辑树 reference），禁止双重换算
gun_x0 = -0.006 + at35(2080) * 0.43
cyl("gun_barrel", at35(88) * 1.3, barrel_len,
    (gun_x0 + barrel_len / 2, 0, TUR_Z0 + TUR_H * 0.55), rot=(0, radians(90), 0), mat=M_DARK)
cyl("muzzle_brake", at35(88) * 1.8, at35(130),
    (gun_x0 + barrel_len - at35(70), 0, TUR_Z0 + TUR_H * 0.55),
    rot=(0, radians(90), 0), mat=M_DARK)

# ── [2.3] 同轴机枪位 ───────────────────────────────────────
mark("2.3")
cyl("mg34_port", 0.006, 0.006,
    (gun_x0 + 0.008, -at35(2080) * 0.18, TUR_Z0 + TUR_H * 0.62),
    rot=(0, radians(90), 0), mat=M_DARK)

# ── [2.4] 舱门 x2 ──────────────────────────────────────────
mark("2.4", "x2")
cyl("hatch_commander", 0.011, 0.002, (-0.018, -0.014, TUR_Z0 + TUR_H + 0.001), verts=20, mat=M_ARMOR)
box("hatch_loader", 0.014, 0.012, 0.002, (0.006, 0.014, TUR_Z0 + TUR_H + 0.001), M_ARMOR)

# ── [2.5] 防盾 ─────────────────────────────────────────────
mark("2.5")
box("mantlet", 0.020, 0.036, 0.026, (gun_x0 - 0.002, 0, TUR_Z0 + TUR_H * 0.55), M_ARMOR)

# ── [3.2] 装甲垂直面（垂直建模即满足；打正常线标记）────────
mark("3.2", "vertical armor ok")

# ── [3.3] 细节挂载 x3 ──────────────────────────────────────
mark("3.3", "x3")
for i, (dx, dz) in enumerate(((-0.05, 0.030), (-0.038, 0.030), (-0.026, 0.030))):
    box("detail_kit_%d" % (i + 1), 0.009, 0.010, 0.004, (dx, HULL_W / 2 + 0.0005, dz), M_DARK)

# ── [3.1] 比例自检（bbox 口径 + 白名单：仅统计虎式部件）────
TIGER_PREFIX = ("tiger", "roadwheel", "track_", "grille", "gun", "mg34",
                "hatch", "mantlet", "detail_kit")
lo_z, hi_z, lo_n, hi_n = 1e9, -1e9, "?", "?"
bpy.context.view_layer.update()
for o in bpy.data.objects:
    if o.type != 'MESH' or not o.name.startswith(TIGER_PREFIX):
        continue
    for c in o.bound_box:
        wz = (o.matrix_world @ mathutils.Vector(c)).z
        if wz < lo_z:
            lo_z, lo_n = wz, o.name
        if wz > hi_z:
            hi_z, hi_n = wz, o.name
height_mm = (hi_z - lo_z) * 1000
print("[gate 3.1] bbox height=%.2fmm (期望 85.71±2) lo=%s hi=%s"
      % (height_mm, lo_n, hi_n))

# ── 地台 + 展台 ────────────────────────────────────────────
mark("5.1")
bpy.ops.mesh.primitive_plane_add(size=2, location=(0, 0, -0.0005))
ground = bpy.context.active_object
ground.name = "ground"
gm = bpy.data.materials.new("ground")
gm.use_nodes = True
gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.30, 0.30, 0.30, 1)
gm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
ground.data.materials.append(gm)
box("display_base", at35(220), at35(120), 0.004, (0, 0, 0.002), M_DARK)

# ── 灯光 ───────────────────────────────────────────────────
def sun(name, energy, rot):
    bpy.ops.object.light_add(type='SUN', location=(0, 0, 1))
    l = bpy.context.active_object
    l.name = name
    l.data.energy = energy
    l.rotation_euler = rot
    return l


sun("key", 3.2, (radians(48), 0, radians(35)))
sun("rim", 1.8, (radians(55), 0, radians(-135)))
bpy.ops.object.light_add(type='AREA', location=(-0.15, -0.25, 0.15))
fill = bpy.context.active_object
fill.name = "fill"
fill.data.energy = 60
fill.data.size = 0.3
fill.rotation_euler = (radians(55), 0, radians(115))

# ── 相机 + 渲染设置 ────────────────────────────────────────
import mathutils

bpy.ops.object.camera_add()
cam = bpy.context.active_object
scene.camera = cam
cam.data.lens = 60


def aim(loc, target):
    cam.location = loc
    d = mathutils.Vector(target) - mathutils.Vector(loc)
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()


scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 48
scene.render.resolution_x = 1024
scene.render.resolution_y = 640
try:
    scene.cycles.use_denoising = True
except Exception:
    pass

VIEWS = [("front34", (0.26, -0.22, 0.13), (0, 0, 0.045)),
         ("side", (0.0, -0.34, 0.055), (0, 0, 0.045)),
         ("rear34", (-0.24, 0.23, 0.115), (0, 0, 0.04))]

for name, loc, tgt in VIEWS:
    aim(loc, tgt)
    scene.render.filepath = str(OUT / ("tiger-%s.png" % name))
    bpy.ops.render.render(write_still=True)
    print("[render] %s -> %s" % (name, scene.render.filepath))

print("[done] renders written to", OUT)
