"""tiger_tank_build.py — 虎式坦克 1:35 建模 v3 + 渲染（Blender 5.2 后台执行）
================================================================================
v3：按 1:35 模型实尺（L241 含炮/W106/H85）+ Tiger I 实车特征逐项建模。
运行：blender.exe --factory-startup --background --python tiger_tank_build.py
"""
import bpy, math, json, sys
import mathutils
from math import radians, cos, sin, pi
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "showcase" / "tiger"
OUT.mkdir(parents=True, exist_ok=True)
K = 1.0 / 35 / 1000.0


def at35(real_mm):
    return real_mm * K


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
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
print("[logic-tree] v3 build order:", " -> ".join(order))

sys.path.insert(0, str(HERE))
from logic_tree import LogicTreeRunner
from experience import ExperienceLibrary

LIB_PATH = HERE / "experience_library.json"
lib = ExperienceLibrary(LIB_PATH)
runner = LogicTreeRunner(lt)
for nid in order:
    _op = byid[nid]["build"]["op"]
    hits = lib.recall({"origin": "logic_tree", "build_op": _op}, n=2)
    print("[rag-recall] op=%-14s hits=%d" % (_op, len(hits)))


def mark(nid, extra=""):
    print("[build] [%s] %s %s" % (nid, byid[nid]["build"]["op"], extra))


def mat(name, color, rough=0.6, metal=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    return m


def camo_mat():
    """v3.3：Object 坐标（跨面一致修暗带）+ Zimmerit 竖纹 bump（防磁涂层质感）"""
    m = bpy.data.materials.new("tiger_camo")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.58
    # 迷彩斑块：Object 坐标（跨面一致）
    tc = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 6.5
    noise.inputs["Detail"].default_value = 1.4
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.38
    ramp.color_ramp.elements[0].color = (0.56, 0.48, 0.26, 1)
    ramp.color_ramp.elements[1].position = 0.60
    ramp.color_ramp.elements[1].color = (0.21, 0.25, 0.14, 1)
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    # Zimmerit 竖纹 bump：波纹沿竖向拉长（Mapping z 压缩）
    znoise = nt.nodes.new("ShaderNodeTexNoise")
    znoise.inputs["Scale"].default_value = 90.0
    znoise.inputs["Detail"].default_value = 2.0
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1.0, 1.0, 0.18)   # 竖纹拉长
    nt.links.new(tc.outputs["Object"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], znoise.inputs["Vector"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.25
    nt.links.new(znoise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


def box(name, sx, sy, sz, loc, mat=None, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.scale = (sx, sy, sz)
    if mat:
        o.data.materials.append(mat)
    return o


def cyl(name, dia, depth, loc, rot=(0, 0, 0), verts=28, mat=None):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=dia / 2,
                                        depth=depth, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    if mat:
        o.data.materials.append(mat)
    return o


M_ARMOR = camo_mat()
M_TRACK = mat("track", (0.09, 0.09, 0.09), rough=0.5, metal=0.55)
M_DARK = mat("darkdetail", (0.13, 0.12, 0.10), rough=0.5, metal=0.25)

mark("1.1", "two-tier hull + stepped front")
GND = 0.0
LOWER_Z0 = GND + at35(470)
LOWER_H = at35(1000)
LOWER_W = at35(3160)
UP_Z0 = LOWER_Z0 + LOWER_H
UP_H = at35(600)
DECK = UP_Z0 + UP_H
HULL_L = at35(6316)
UP_W = at35(2480)

box("hull_lower", HULL_L, LOWER_W, LOWER_H, (0, 0, LOWER_Z0 + LOWER_H / 2), M_ARMOR)
box("hull_super", HULL_L, UP_W, UP_H, (0, 0, UP_Z0 + UP_H / 2), M_ARMOR)
box("front_glacis", at35(320), UP_W, at35(320),
    (HULL_L / 2 - at35(160), 0, UP_Z0 + at35(160)), M_ARMOR)
box("driver_visor", at35(120), at35(400), at35(120),
    (HULL_L / 2 - at35(40), -at35(560), UP_Z0 + at35(220)), M_DARK)
cyl("hull_mg_ball", at35(160), at35(140),
    (HULL_L / 2 - at35(20), at35(500), UP_Z0 + at35(180)),
    rot=(0, radians(90), 0), verts=16, mat=M_DARK)

mark("1.2", "x16 steel-rimmed interleaved")
WR = at35(800)
TRACK_Y = at35(3705) / 2 - at35(725) / 2
WHEEL_Z = at35(520)
for side in (-1, 1):
    y_c = side * TRACK_Y
    for i in range(8):
        x = -at35(2700) / 2 + i * (at35(2700) / 7) + (at35(55) if side < 0 else -at35(55))
        y_off = y_c + side * (at35(60) if i % 2 else -at35(60))   # 内外交错
        cyl("rw_rim_%s%d" % (side, i), WR, at35(60),
            (x, y_off, WHEEL_Z), rot=(0, radians(90), 0), verts=24, mat=M_ARMOR)
        cyl("rw_hub_%s%d" % (side, i), WR * 0.58, at35(110),
            (x, y_off, WHEEL_Z), rot=(0, radians(90), 0),
            verts=16, mat=M_DARK)
for s in (-1, 1):
    cyl("drive_%d" % s, at35(580), at35(90),
        (at35(2900), s * TRACK_Y, at35(430)), rot=(0, radians(90), 0), verts=18, mat=M_DARK)
    cyl("idler_%d" % s, at35(520), at35(90),
        (-at35(2850), s * TRACK_Y, at35(500)), rot=(0, radians(90), 0), verts=18, mat=M_DARK)

mark("1.3", "44 shoes/side")
A_X, B_Z = at35(3100), at35(650)
CZ = at35(730)
N_SHOES = 44
for side in (-1, 1):
    y_c = side * TRACK_Y
    for i in range(N_SHOES):
        th = 2 * pi * i / N_SHOES
        x = A_X * cos(th)
        z = CZ + B_Z * sin(th)
        ang = math.atan2(-B_Z * cos(th), -A_X * sin(th))   # 切线贴合：底/顶水平、前后竖直
        box("shoe_%s%02d" % (side, i), at35(150), at35(725), at35(80),
            (x, y_c, z), M_TRACK, rot=(0, ang, 0))

print("[build] [1.3-fenders] fenders")  # 非树内节点（挡泥板属 1.3 附属）
for s in (-1, 1):
    box("fender_%d" % s, HULL_L * 0.96, at35(725) + at35(80), at35(60),
        (0, s * TRACK_Y, at35(1000) + LOWER_Z0), M_ARMOR)

mark("1.4", "x4")
for i in range(4):
    x = -HULL_L / 2 + at35(3800) + i * at35(360)
    box("grille_%d" % (i + 1), at35(220), at35(2200), at35(40),
        (x, 0, DECK + at35(20)), M_DARK)

mark("1.5", "exhaust x2 + shields")
for s in (-1, 1):
    cyl("exhaust_%d" % (s + 2), at35(180), at35(700),
        (-HULL_L / 2 - at35(120), s * at35(700), LOWER_Z0 + at35(650)),
        rot=(0, radians(90), 0), verts=16, mat=M_DARK)
    box("exh_shield_%d" % (s + 2), at35(500), at35(60), at35(500),
        (-HULL_L / 2 - at35(60), s * at35(700), LOWER_Z0 + at35(900)), M_ARMOR)

mark("2.1", "Henschel shaped")
TUR_Z0 = DECK
TUR_H = at35(2880) - DECK - at35(150)
TUR_D = at35(2080)
TUR_X = at35(200)
_turret = cyl("tiger_turret", TUR_D, TUR_H, (TUR_X, 0, TUR_Z0 + TUR_H / 2), verts=24, mat=M_ARMOR)
_bev = _turret.modifiers.new("bevel", 'BEVEL')
_bev.width = 0.008
_bev.segments = 5
box("turret_front", at35(250), at35(1850), TUR_H,
    (TUR_X + TUR_D / 2 - at35(60), 0, TUR_Z0 + TUR_H / 2), M_ARMOR)
box("turret_bustle", at35(600), at35(1700), TUR_H * 0.9,
    (TUR_X - TUR_D / 2 + at35(180), 0, TUR_Z0 + TUR_H * 0.45), M_ARMOR)
cyl("cupola", at35(600), at35(190),
    (TUR_X - TUR_D / 2 + at35(420), at35(420), TUR_Z0 + TUR_H + at35(95)),
    verts=16, mat=M_ARMOR)

mark("2.2", "3-segment + brake")
GUN_Z = TUR_Z0 + TUR_H * 0.50
MANT_X = TUR_X + TUR_D / 2 - at35(30)
cyl("gun_root", at35(160), at35(800),
    (MANT_X + at35(400), 0, GUN_Z), rot=(0, radians(90), 0), mat=M_DARK)
cyl("gun_mid", at35(115), at35(3050),
    (MANT_X + at35(800) + at35(3050) / 2, 0, GUN_Z), rot=(0, radians(90), 0), mat=M_DARK)
cyl("gun_brake_a", at35(190), at35(200),
    (MANT_X + at35(800) + at35(3050) + at35(100), 0, GUN_Z),
    rot=(0, radians(90), 0), mat=M_DARK)
cyl("gun_brake_b", at35(150), at35(180),
    (MANT_X + at35(800) + at35(3050) + at35(290), 0, GUN_Z),
    rot=(0, radians(90), 0), mat=M_DARK)

mark("2.3")
cyl("mg34_port", at35(130), at35(90),
    (MANT_X + at35(30), -at35(620), GUN_Z + at35(300)),
    rot=(0, radians(90), 0), mat=M_DARK)

mark("2.4", "x2")
cyl("hatch_cmd", at35(580), at35(70),
    (TUR_X - TUR_D / 2 + at35(420), -at35(380), TUR_Z0 + TUR_H + at35(150)),
    verts=18, mat=M_ARMOR)
box("hatch_loader", at35(420), at35(380), at35(70),
    (TUR_X + at35(650), at35(380), TUR_Z0 + TUR_H + at35(35)), M_ARMOR)

mark("2.5")
cyl("mantlet", at35(1000), at35(450),
    (MANT_X - at35(120), 0, GUN_Z), rot=(0, radians(90), 0), verts=20, mat=M_ARMOR)

mark("3.3", "spare track x3")
for i in range(3):
    box("spare_track_%d" % (i + 1), at35(160), at35(700), at35(95),
        (at35(1200) - i * at35(180), -at35(3160) / 2 - at35(40),
         LOWER_Z0 + LOWER_H - at35(300)), M_TRACK)

mark("3.1", "gate check")
lo_z, hi_z, lo_n, hi_n = 1e9, -1e9, "?", "?"
bpy.context.view_layer.update()
TIGER_PREFIX = ("tiger", "roadwheel", "rw_", "drive", "idler", "track_", "shoe_",
                "grille", "gun", "mg34", "hatch", "mantlet", "detail_kit",
                "hull", "front_", "driver", "exhaust", "exh_", "cupola", "fender",
                "spare", "turret")
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
print("[gate 3.1] height=%.2fmm (期望 82-86) lo=%s hi=%s" % (height_mm, lo_n, hi_n))
print("[gate 3.1] hull_length=%.2fmm (期望 180.5)" % (HULL_L * 1000))

lib.record_ai(
    trigger={"origin": "logic_tree", "project": "tiger_tank",
             "node": "3.1", "build_op": "proportion_check",
             "gate": {"height_mm": round(height_mm, 2)}},
    attention="虎式比例门：bbox 口径统计（非对象原点）",
    story="v3 建模：阶梯车头/炮塔塑造/履带板阵列/排气护罩。gate 3.1 height=%.2fmm" % height_mm,
    params={"height_mm": round(height_mm, 2)},
    evidence=["gate3.1", "bbox"])

mark("5.1")
bpy.ops.mesh.primitive_plane_add(size=2, location=(0, 0, -0.0005))
g = bpy.context.active_object
g.name = "ground"
gm = bpy.data.materials.new("ground")
gm.use_nodes = True
gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.30, 0.30, 0.31, 1)
gm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
g.data.materials.append(gm)
box("display_base", at35(300), at35(180), at35(100), (0, 0, at35(50)), M_DARK)


def sun(name, energy, rot):
    bpy.ops.object.light_add(type='SUN', location=(0, 0, 1))
    l = bpy.context.active_object
    l.name = name
    l.data.energy = energy
    l.rotation_euler = rot


sun("key", 2.4, (radians(48), 0, radians(35)))
sun("rim", 1.6, (radians(55), 0, radians(-140)))
bpy.ops.object.light_add(type='AREA', location=(-0.18, -0.28, 0.18))
f = bpy.context.active_object
f.name = "fill"
f.data.energy = 80
f.data.size = 0.35
f.rotation_euler = (radians(55), 0, radians(118))

bpy.ops.object.camera_add()
cam = bpy.context.active_object
scene.camera = cam
cam.data.lens = 55


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

for name, loc, tgt in [("front34", (0.30, -0.26, 0.15), (0, 0, 0.048)),
                       ("side", (0.0, -0.38, 0.058), (0, 0, 0.045)),
                       ("rear34", (-0.28, 0.25, 0.12), (0, 0, 0.042))]:
    aim(loc, tgt)
    scene.render.filepath = str(OUT / ("tiger-%s.png" % name))
    bpy.ops.render.render(write_still=True)
    print("[render] %s -> %s" % (name, scene.render.filepath))
print("[done]")
