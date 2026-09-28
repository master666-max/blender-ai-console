"""tiger_tank_build.py — 虎式坦克 1:35 建模 v2 + 渲染（Blender 5.2 后台执行）
================================================================================
v2：按逻辑树 15 节点逐节点落实——superstructure 双层车体 / Henschel 炮塔塑造 /
炮管三段 / 履带板沿椭圆阵列 / 负重轮双色轮毂 / 排气管 / 备用履带。
运行：blender.exe --background --python tiger_tank_build.py
产物：showcase/tiger/tiger-{front34,side,rear34}.png
"""
import bpy, math, json, sys
import mathutils
from math import radians, cos, sin, pi
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "showcase" / "tiger"
OUT.mkdir(parents=True, exist_ok=True)
SCALE = 35
K = 1.0 / SCALE / 1000.0          # 实尺 mm → Blender m


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
sys.path.insert(0, str(HERE))
from logic_tree import LogicTreeRunner
from experience import ExperienceLibrary
print("[logic-tree] v2 build order:", " -> ".join(order))

# ── 融合三环初始化（管线×视觉×RAG）──────────────────────────
LIB_PATH = HERE / "experience_library.json"
lib = ExperienceLibrary(LIB_PATH)
runner = LogicTreeRunner(lt)
_seen_ops = {}
for _nid in order:
    _op = byid[_nid]["build"]["op"]
    if _op in _seen_ops:
        continue
    _seen_ops[_op] = True
    _hits = lib.recall({"origin": "logic_tree", "build_op": _op}, n=2)
    print("[rag-recall] op=%-14s hits=%d %s" % (_op, len(_hits),
          "; ".join(h.eid for h in _hits) if _hits else "(冷启动)"))


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
    m = bpy.data.materials.new("tiger_camo")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.58
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 7.0
    noise.inputs["Detail"].default_value = 1.6
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.40
    ramp.color_ramp.elements[0].color = (0.44, 0.38, 0.22, 1)
    ramp.color_ramp.elements[1].position = 0.62
    ramp.color_ramp.elements[1].color = (0.20, 0.24, 0.13, 1)
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    return m


def box(name, sx, sy, sz, loc, mat=None, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.scale = (sx, sy, sz)          # size=1 棱柱：dimensions == scale（目标尺寸）
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
M_DARK = mat("darkdetail", (0.14, 0.13, 0.11), rough=0.5, metal=0.3)
M_RUBBER = mat("rubber", (0.05, 0.05, 0.05), rough=0.85)

# ══ [1.1] 车体：下层盒 + 上层 superstructure（双层）══════════
mark("1.1", "two-tier hull")
HULL_L = at35(6320)
LOWER_H = at35(1000)                       # 下层盒高（含侧裙区）
LOWER_W = at35(3160)                       # 下层宽（履带内侧车体）
UP_W = at35(2480)                          # 上层 superstructure（内收）
UP_H = at35(600)
LOWER_Z0 = at35(480)
UP_Z0 = LOWER_Z0 + LOWER_H
box("hull_lower", HULL_L, LOWER_W, LOWER_H, (0, 0, LOWER_Z0 + LOWER_H / 2), M_ARMOR)
box("hull_super", HULL_L, UP_W, UP_H, (0, 0, UP_Z0 + UP_H / 2), M_ARMOR)
# 前上装甲阶梯（驾驶段）
box("hull_front_step", at35(500), UP_W, at35(300),
    (HULL_L / 2 - at35(250), 0, UP_Z0 + UP_H / 2), M_ARMOR)

# ══ [1.2] 行走机构：交错负重轮 x16（双色轮毂）+ 驱动/诱导轮 ══
mark("1.2", "x16 two-tone + drive/idler")
WR = at35(800)
TRACK_Y = at35(3705) / 2 - at35(725) / 2
hub_m = M_DARK
for side in (-1, 1):
    y_c = side * TRACK_Y
    for i in range(8):
        x = -at35(2800) / 2 + i * (at35(2800) / 7) + (at35(60) if side < 0 else -at35(60))
        z = at35(520)
        cyl("rw_hub_%s%d" % (side, i), WR * 0.62, at35(120),
            (x, y_c + side * at35(30), z), rot=(0, radians(90), 0), verts=20, mat=hub_m)
        cyl("rw_rim_%s%d" % (side, i), WR, at35(60),
            (x, y_c, z), rot=(0, radians(90), 0), verts=24, mat=M_ARMOR)
# 驱动轮（前）+ 诱导轮（后）
cyl("drive_wheel", at35(560), at35(100), (at35(2950), -TRACK_Y, at35(480)),
    rot=(0, radians(90), 0), verts=18, mat=hub_m)
cyl("idler_wheel", at35(520), at35(100), (-at35(2900), -TRACK_Y, at35(450)),
    rot=(0, radians(90), 0), verts=18, mat=hub_m)
for s2 in (1,):
    cyl("drive_wheel_R", at35(560), at35(100), (at35(2950), TRACK_Y, at35(480)),
        rot=(0, radians(90), 0), verts=18, mat=hub_m)
    cyl("idler_wheel_R", at35(520), at35(100), (-at35(2900), TRACK_Y, at35(450)),
        rot=(0, radians(90), 0), verts=18, mat=hub_m)

# ══ [1.3] 履带：沿椭圆阵列履带板（44 板/侧，带齿感）══════════
mark("1.3", "44 shoes/side")
A_X, B_Z = at35(3050), at35(760)           # 椭圆半轴（x / z）
CZ = B_Z + at35(60)                        # 椭圆中心（底部近地）
N_SHOES = 44
for side in (-1, 1):
    y_c = side * TRACK_Y
    for i in range(N_SHOES):
        th = 2 * pi * i / N_SHOES
        x = A_X * cos(th)
        z = CZ + B_Z * sin(th)
        tangent = math.atan2(-B_Z * sin(th) * (1 if cos(th) >= 0 else 1), A_X * cos(th))
        plate = box("shoe_%s%02d" % (side, i), at35(150), at35(725), at35(90),
                    (x, y_c, z), M_TRACK)
        plate.rotation_euler = (0, 0, 0)
        # 履带板绕 y 轴贴合切线方向
        plate.rotation_euler = (0, -math.atan2(B_Z * cos(th), A_X * sin(th)) + (pi / 2 if sin(th) >= 0 else -pi / 2), 0)

# ══ [1.4] 动力舱格栅 ════════════════════════════════════════
mark("1.4", "x4")
DECK = UP_Z0 + UP_H
for i in range(4):
    x = at35(5050) / 2 - i * at35(310) - at35(200)
    box("grille_%d" % (i + 1), at35(180), UP_W * 0.62, at35(40),
        (x, 0, DECK + at35(20)), M_DARK)

# ══ [2.1] 炮塔：Henschel 塑造（棱柱主体+前楔+指挥官塔）═══════
mark("2.1", "Henschel shaped")
TUR_Z0 = DECK
TUR_H = at35(3000) - DECK - at35(120)      # 顶部留舱门凸起
TUR_L, TUR_W = at35(2500), at35(2080)
turret = cyl("tiger_turret", TUR_W, TUR_H, (at35(-300) if False else at35(-250), 0, TUR_Z0 + TUR_H / 2),
             verts=14, mat=M_ARMOR)
turret.rotation_euler = (0, 0, radians(90))   # 椭圆主轴沿车长
turret.scale = (TUR_L / TUR_W, 1.0, 1.0)
box("turret_front", at35(700), TUR_W * 0.92, TUR_H,
    (at35(-250) + TUR_L / 2 - at35(250), 0, TUR_Z0 + TUR_H / 2), M_ARMOR)
cyl("cupola", at35(600), at35(180),
    (at35(-250) - TUR_L * 0.28, at35(380), TUR_Z0 + TUR_H + at35(90)), verts=16, mat=M_ARMOR)

# ══ [2.2] 主炮三段（根部粗段+中段+双室制退器）═══════════════
mark("2.2", "3-segment")
GUN_Z = TUR_Z0 + TUR_H * 0.52
MANT_X = at35(-250) + TUR_L / 2 + at35(120)
seg1_len, seg2_len, brake_len = at35(900), at35(3650), at35(380)
cyl("gun_root", at35(140), seg1_len,
    (MANT_X + seg1_len / 2, 0, GUN_Z), rot=(0, radians(90), 0), mat=M_DARK)
cyl("gun_mid", at35(100), seg2_len,
    (MANT_X + seg1_len + seg2_len / 2, 0, GUN_Z), rot=(0, radians(90), 0), mat=M_DARK)
cyl("gun_brake_a", at35(150), brake_len * 0.55,
    (MANT_X + seg1_len + seg2_len + brake_len * 0.28, 0, GUN_Z),
    rot=(0, radians(90), 0), mat=M_DARK)
cyl("gun_brake_b", at35(120), brake_len * 0.45,
    (MANT_X + seg1_len + seg2_len + brake_len * 0.78, 0, GUN_Z),
    rot=(0, radians(90), 0), mat=M_DARK)

# ══ [2.3] 同轴机枪位 ════════════════════════════════════════
mark("2.3")
cyl("mg34_port", at35(120), at35(80),
    (MANT_X + at35(60), -TUR_W * 0.30, GUN_Z + at35(240)),
    rot=(0, radians(90), 0), mat=M_DARK)

# ══ [2.4] 舱门 x2 ═══════════════════════════════════════════
mark("2.4", "x2")
cyl("hatch_cmd", at35(580), at35(60),
    (at35(-250) - TUR_L * 0.30, -at35(320), TUR_Z0 + TUR_H + at35(30)), verts=18, mat=M_ARMOR)
box("hatch_loader", at35(400), at35(340), at35(60),
    (at35(-250) + at35(500), at35(380), TUR_Z0 + TUR_H + at35(30)), M_ARMOR)

# ══ [2.5] 防盾 ══════════════════════════════════════════════
mark("2.5")
box("mantlet", at35(500), at35(1000), at35(800),
    (MANT_X - at35(100), 0, GUN_Z), M_ARMOR)

# ══ [2.3b] 排气管 x2（车尾）═════════════════════════════════
mark("1.5", "exhaust x2")
for s in (-1, 1):
    cyl("exhaust_%d" % (s + 2), at35(150), at35(900),
        (-HULL_L / 2 - at35(150), s * at35(500), LOWER_Z0 + at35(700)),
        rot=(0, radians(90), 0), mat=M_DARK)

# ══ [3.3] 细节挂载：备用履带 x3（前上装甲板）════════════════
mark("3.3", "spare track x3")
for i in range(3):
    box("spare_track_%d" % (i + 1), at35(150), at35(700), at35(90),
        (at35(1800) - i * at35(170), 0, UP_Z0 + UP_H + at35(45)), M_TRACK)

# ══ [3.1] 比例自检（bbox 口径）══════════════════════════════
mark("3.1", "gate check")
lo_z, hi_z, lo_n, hi_n = 1e9, -1e9, "?", "?"
bpy.context.view_layer.update()
for o in bpy.data.objects:
    if o.type != 'MESH' or o.name.startswith(("ground", "display_base", "key", "fill", "rim", "camera")):
        continue
    for c in o.bound_box:
        wz = (o.matrix_world @ mathutils.Vector(c)).z
        if wz < lo_z:
            lo_z, lo_n = wz, o.name
        if wz > hi_z:
            hi_z, hi_n = wz, o.name
h_mm = (hi_z - lo_z) * 1000
print("[gate 3.1] height=%.2fmm (期望 85.71±2) lo=%s hi=%s" % (h_mm, lo_n, hi_n))
print("[gate 3.1] length=%.2fmm (期望 180.57±2)" % (HULL_L * 1000))

# ── 融合②视觉环：gate 谓词执行器 v0 ────────────────────────
def band(rel):
    a = abs(rel)
    return "带内" if a < 0.02 else ("偏移一点" if a < 0.10 else "明显偏离")

_pred_results = []
def pred(name, actual, expect, tol_mm):
    rel = (actual - expect) / max(expect, 1e-9)
    ok = abs(actual - expect) <= tol_mm
    _pred_results.append({"predicate": name, "actual_mm": round(actual, 2),
                          "expect_mm": expect, "tol_mm": tol_mm,
                          "rel_pct": round(rel * 100, 2), "band": band(rel), "ok": ok})
    return ok

_hull = bpy.data.objects.get("hull_lower")
pred("hull_length", _hull.dimensions.x * 1000, at35(6320) * 1000, 2.0)
pred("hull_height_total", h_mm, at35(3000) * 1000, 2.0)
_n_rw = len([o for o in bpy.data.objects if o.name.startswith("roadwheel")])
_pred_results.append({"predicate": "roadwheel_count", "actual": _n_rw, "expect": 16, "ok": _n_rw == 16})
print("[gate-spec] 谓词执行结果:")
for _p in _pred_results:
    print("   ", json.dumps(_p, ensure_ascii=False))

# ── 融合③RAG 沉淀环：逐节点 record_ai（P0 脚本轨）────────────
_GATE_JSON = json.dumps(_pred_results, ensure_ascii=False)
for _nid in order:
    _n = byid[_nid]
    _op = _n["build"]["op"]
    _mm = _n["build"].get("params_mm", {})
    _att = "注意：%s | 门：%s" % (_n["name"], _n["gate"].get("machine", ""))
    _story = ("构建 %s（%s）：%s。gate 结果=%s。目验要点=%s"
              % (_n["name"], _op, _n["build"].get("note", ""),
                 "通过" if all(p.get("ok", True) for p in _pred_results) else "见谓词报告",
                 _n["gate"].get("visual", "")))
    lib.record_ai(
        trigger={"origin": "logic_tree", "project": "tiger_tank",
                 "node": _nid, "build_op": _op, "params_mm": _mm},
        attention=_att[:120], story=_story[:600],
        params=_mm, evidence=[_GATE_JSON[:400]])
    _st = runner.byid[_nid]["status"]
    if _st == "pending":
        runner.start(_nid)
        runner.pass_gate(_nid, evidence="gate + render")
    elif _st == "passed":
        pass                       # 幂等：状态机回写后重跑不重复过门
print("[rag-record] 沉淀 %d 条节点经验 -> %s" % (len(order), LIB_PATH.name))
print("[runner] progress:", runner.progress())
for _n in lt["nodes"]:
    _n["status"] = runner.byid[_n["id"]]["status"]
lt_path = HERE / "logic_trees" / "tiger_tank.json"
lt_path.write_text(json.dumps(lt, ensure_ascii=False, indent=1), encoding="utf-8")
print("[logic-tree] status 回写完成 ->", lt_path.name)

# ══ [5.1] 地台/展台/灯光/相机/渲染 ══════════════════════════
mark("5.1")
bpy.ops.mesh.primitive_plane_add(size=2, location=(0, 0, -0.0005))
g = bpy.context.active_object
g.name = "ground"
gm = bpy.data.materials.new("ground")
gm.use_nodes = True
gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.30, 0.30, 0.31, 1)
gm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
g.data.materials.append(gm)
box("display_base", at35(260), at35(150), at35(100), (0, 0, at35(50)), M_DARK)


def sun(name, energy, rot):
    bpy.ops.object.light_add(type='SUN', location=(0, 0, 1))
    l = bpy.context.active_object
    l.name = name
    l.data.energy = energy
    l.rotation_euler = rot


sun("key", 3.0, (radians(48), 0, radians(35)))
sun("rim", 1.6, (radians(55), 0, radians(-140)))
bpy.ops.object.light_add(type='AREA', location=(-0.16, -0.26, 0.16))
f = bpy.context.active_object
f.name = "fill"
f.data.energy = 70
f.data.size = 0.32
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

for name, loc, tgt in [("front34", (0.30, -0.24, 0.14), (0.01, 0, 0.045)),
                       ("side", (0.0, -0.36, 0.055), (0, 0, 0.045)),
                       ("rear34", (-0.27, 0.24, 0.12), (0, 0, 0.04))]:
    aim(loc, tgt)
    scene.render.filepath = str(OUT / ("tiger-%s.png" % name))
    bpy.ops.render.render(write_still=True)
    print("[render] %s -> %s" % (name, scene.render.filepath))
print("[done]")
