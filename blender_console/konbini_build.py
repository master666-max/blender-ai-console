"""konbini_build.py — 雨夜便利店街角微缩场景（三渲二/二次元/可交互 GLTF）
================================================================================
构图：2.4×2.4m 方形底座；便利店居后部中央，门朝南（-Y）；
      L 形人行道 + 前部车道 + 斑马线；左暗巷；右 vending 机群。
命名约定（three.js 动效匹配）：
  MAT_SignGlow / MAT_Lightbox / MAT_VendA / MAT_VendB  → 霓虹闪烁
  OBJ_DoorL / OBJ_DoorR                                 → 自动门滑动
  MAT_Glass                                             → 雨水滑落目标
  MAT_Wet*                                              → 湿反光
运行：blender --background --python konbini_build.py  → export GLTF
"""
import bpy, math, random
import json as _json
from pathlib import Path

random.seed(42)
# ── 清场 ────────────────────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
S = bpy.context.scene

# ── helpers ─────────────────────────────────────────────────
def mat(name, color, rough=0.6, metal=0.0, emit=None, emit_str=1.0, alpha=1.0):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1.0)
        b.inputs["Emission Strength"].default_value = emit_str
    if alpha < 1.0:
        b.inputs["Alpha"].default_value = alpha
        m.blend_method = 'BLEND'
    return m

def box(name, size, loc, m, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.scale = (size[0] / 2, size[1] / 2, size[2] / 2)
    o.data.materials.append(m)
    return o

def cyl(name, r, depth, loc, m, rot=(0, 0, 0), verts=16):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, location=loc,
                                        rotation=rot, vertices=verts)
    o = bpy.context.active_object
    o.name = name
    o.data.materials.append(m)
    return o

def plane(name, sx, sy, loc, m, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_plane_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.scale = (sx / 2, sy / 2, 1)
    o.data.materials.append(m)
    return o

# ── 材质表 ──────────────────────────────────────────────────
M_BASE   = mat("MAT_Base", (0.23, 0.24, 0.27), 0.45)
M_ROAD   = mat("MAT_Road", (0.14, 0.15, 0.18), 0.30, 0.30)
M_WET    = mat("MAT_Wet1", (0.04, 0.06, 0.09), 0.08, 0.55)
M_SIDE   = mat("MAT_Sidewalk", (0.48, 0.50, 0.54), 0.85)
M_WALL   = mat("MAT_Wall", (0.88, 0.86, 0.80), 0.7)
M_WALL2  = mat("MAT_Wall2", (0.75, 0.76, 0.78), 0.7)
M_GLASS  = mat("MAT_Glass", (0.55, 0.75, 0.85), 0.05, 0.0, alpha=0.35)
M_FRAME  = mat("MAT_Frame", (0.15, 0.17, 0.20), 0.5, 0.3)
M_FLOOR  = mat("MAT_FloorIn", (0.92, 0.90, 0.85), 0.6)
M_SHelf  = mat("MAT_Shelf", (0.90, 0.91, 0.93), 0.4, 0.1)
M_WARM   = mat("MAT_WarmGlow", (1, 1, 1), 0.4, emit=(1.0, 0.75, 0.42), emit_str=3.0)
M_SIGN   = mat("MAT_SignGlow", (1, 1, 1), 0.4, emit=(1.0, 0.45, 0.12), emit_str=4.0)   # 招牌橙
M_SIGNB  = mat("MAT_SignGlowB", (1, 1, 1), 0.4, emit=(0.25, 0.85, 1.0), emit_str=3.5)  # 青
M_LIGHTB = mat("MAT_Lightbox", (1, 1, 1), 0.4, emit=(1.0, 0.9, 0.75), emit_str=3.0)
M_VENDA  = mat("MAT_VendA", (1, 1, 1), 0.35, emit=(1.0, 0.25, 0.30), emit_str=2.6)     # 红贩卖机
M_VENDB  = mat("MAT_VendB", (1, 1, 1), 0.35, emit=(0.20, 0.45, 1.0), emit_str=2.6)     # 蓝
M_DARK   = mat("MAT_Dark", (0.10, 0.10, 0.12), 0.7)
M_POLE   = mat("MAT_Pole", (0.35, 0.38, 0.42), 0.5, 0.4)
M_METAL  = mat("MAT_Metal", (0.55, 0.58, 0.62), 0.35, 0.6)
M_RUBBER = mat("MAT_Rubber", (0.06, 0.06, 0.07), 0.9)
M_UMB    = mat("MAT_Umbrella", (0.85, 0.30, 0.35), 0.5)
M_ZEBRA  = mat("MAT_Zebra", (0.80, 0.82, 0.85), 0.3, 0.2)
M_GREEN  = mat("MAT_Green", (0.20, 0.45, 0.25), 0.8)
M_DOOR   = mat("MAT_DoorAuto", (0.60, 0.78, 0.85), 0.05, alpha=0.45)
M_POSTER = [mat(f"MAT_Poster{i}", c, 0.5, emit=c, emit_str=0.6)
            for i, c in enumerate([(0.9, 0.5, 0.3), (0.4, 0.7, 0.9),
                                   (0.9, 0.8, 0.4), (0.7, 0.5, 0.9)])]
M_PROD   = [mat(f"MAT_Prod{i}", c, 0.5) for i, c in enumerate(
    [(0.9, 0.35, 0.3), (0.3, 0.6, 0.9), (0.95, 0.8, 0.35), (0.4, 0.8, 0.5),
     (0.8, 0.4, 0.8), (0.95, 0.55, 0.2), (0.5, 0.85, 0.9), (0.9, 0.9, 0.6)])]
M_TL_R   = mat("MAT_TL_Red", (1, 1, 1), 0.3, emit=(1.0, 0.15, 0.15), emit_str=2.5)
M_TL_G   = mat("MAT_TL_Green", (1, 1, 1), 0.3, emit=(0.15, 1.0, 0.35), emit_str=2.5)
M_TL_OFF = mat("MAT_TL_Off", (0.12, 0.12, 0.14), 0.5)

# ── 底座 ────────────────────────────────────────────────────
box("Base", (2.4, 2.4, 0.12), (0, 0, -0.06), M_BASE)

# ── 道路系统 ────────────────────────────────────────────────
# 车道（前部横贯）
plane("Road", 2.4, 0.92, (0, -0.74, 0.001), M_ROAD)
# 人行道（L 形：店前 + 右侧转角）
plane("SidewalkF", 2.4, 0.44, (0, -0.06, 0.015), M_SIDE)
plane("SidewalkR", 0.42, 0.44, (0.99, -0.28, 0.015), M_SIDE)
# 路缘
box("CurbF", (2.4, 0.03, 0.035), (0, -0.285, 0.017), M_SIDE)
# 排水沟（人行道内缘缝）
box("Drain", (2.3, 0.05, 0.01), (0, -0.26, 0.0175), M_DARK)
# 斑马线（车道上，反光白条）
for i in range(6):
    plane(f"Zebra{i}", 0.09, 0.55, (-0.62 + i * 0.22, -0.74, 0.003), M_ZEBRA)
# 车道中线
plane("CenterLine", 2.3, 0.03, (0, -0.74, 0.003), M_ZEBRA)
# 停车位线（右段车道）
for i in range(2):
    plane(f"ParkLine{i}", 0.02, 0.4, (0.72 + i * 0.45, -0.85, 0.003), M_ZEBRA)
# 积水路面（车道反光斑）
plane("Wet1", 0.7, 0.35, (-0.55, -0.85, 0.004), M_WET)
plane("Wet2", 0.5, 0.3, (0.35, -0.60, 0.004), M_WET)
plane("Wet3", 0.4, 0.25, (0.75, -0.95, 0.004), M_WET)

# ── 便利店主体 ──────────────────────────────────────────────
BX, BY = -0.05, 0.62           # 建筑中心
BW, BD, BH = 1.7, 1.05, 2.05   # 宽/深/高
box("Body", (BW, BD, BH), (BX, BY, BH / 2), M_WALL)
box("RoofBand", (BW + 0.06, BD + 0.06, 0.08), (BX, BY, BH + 0.04), M_WALL2)
box("RoofTop", (BW, BD, 0.02), (BX, BY, BH + 0.09), M_DARK)
# 店内地板
plane("FloorIn", BW - 0.1, BD - 0.12, (BX, BY + 0.02, 0.012), M_FLOOR)
# 橱窗大玻璃（正面 + 右侧）
box("GlassFront", (1.25, 0.02, 1.15), (BX - 0.12, BY - BD / 2 - 0.005, 1.12), M_GLASS)
box("GlassSide", (0.02, 0.62, 1.15), (BX + BW / 2 + 0.005, BY - 0.18, 1.12), M_GLASS)
# 橱窗框
box("FrameF1", (1.3, 0.03, 0.05), (BX - 0.12, BY - BD / 2, 1.72), M_FRAME)
box("FrameF2", (1.3, 0.03, 0.05), (BX - 0.12, BY - BD / 2, 0.52), M_FRAME)
box("FrameV", (0.04, 0.035, 1.22), (BX - 0.73, BY - BD / 2, 1.12), M_FRAME)
# 自动门（双滑，正面中央）——命名给 three.js 动效
box("OBJ_DoorL", (0.36, 0.025, 1.16), (-0.15, BY - BD / 2 - 0.01, 1.11), M_DOOR)
box("OBJ_DoorR", (0.36, 0.025, 1.16), (0.22, BY - BD / 2 - 0.01, 1.11), M_DOOR)
box("DoorFrame", (0.82, 0.04, 0.06), (0.035, BY - BD / 2, 1.73), M_FRAME)
# 屋檐雨棚（正面 + 右侧挑出）
box("AwningF", (BW + 0.35, 0.34, 0.05), (BX, BY - BD / 2 - 0.15, 1.80), M_WALL2)
box("AwningR", (0.30, BD - 0.3, 0.05), (BX + BW / 2 + 0.13, BY + 0.05, 1.80), M_WALL2)
# 招牌（屋顶发光灯箱，橙）+ 副招牌（青）
box("MAT_SignGlow", (1.5, 0.14, 0.30), (BX, BY + 0.02, 2.28), M_SIGN)
box("SignSub", (0.6, 0.06, 0.12), (BX - 0.95, BY - 0.35, 2.05), M_SIGNB)
# 门口立式招牌
cyl("SignPole", 0.015, 1.1, (0.62, -0.28, 0.58), M_POLE)
box("SignStand", (0.34, 0.06, 0.42), (0.62, -0.28, 1.28), M_SIGN)
# 门口地垫
box("DoorMat", (0.75, 0.35, 0.012), (0.035, BY - BD / 2 - 0.22, 0.032), M_DARK)

# ── 店内陈设（暖光内藏）────────────────────────────────────
# 天花灯箱 ×2
box("MAT_Lightbox", (0.55, 0.4, 0.03), (BX - 0.45, BY + 0.1, 1.92), M_LIGHTB)
box("MAT_Lightbox", (0.55, 0.4, 0.03), (BX + 0.4, BY + 0.1, 1.92), M_LIGHTB)
# 货架 ×3（白架 + 商品阵列）
for r, gy in enumerate([0.38, 0.62, 0.86]):
    gx = BX - 0.42
    box(f"Shelf{r}", (0.85, 0.24, 0.06), (gx, gy, 0.35), M_SHelf)
    box(f"ShelfBk{r}", (0.85, 0.02, 0.75), (gx, gy + 0.11, 0.68), M_SHelf)
    for lv, z in enumerate([0.42, 0.62, 0.82, 1.02]):
        for i in range(9):
            m = random.choice(M_PROD)
            box(f"Prod{r}_{lv}_{i}", (0.055, 0.10, 0.14),
                (gx - 0.38 + i * 0.092, gy - 0.04, z), m)
# 饮料柜（后墙发光横柜 + 彩瓶）
box("DrinkCase", (0.95, 0.18, 1.5), (BX - 0.35, BY + 0.42, 0.78), M_SHelf)
box("MAT_Lightbox", (0.85, 0.02, 1.1), (BX - 0.35, BY + 0.325, 0.80), M_LIGHTB)
for i in range(12):
    m = random.choice(M_PROD)
    cyl(f"Drink{i}", 0.018, 0.10, (BX - 0.70 + i * 0.062, BY + 0.33, 0.55 + (i % 3) * 0.30), m,
        rot=(math.pi / 2, 0, 0), verts=10)
# 便当/饭团冷柜（左墙横排）
box("BentoCase", (0.18, 0.55, 0.9), (BX - 0.78, BY - 0.05, 0.48), M_SHelf)
for i in range(8):
    box(f"Bento{i}", (0.10, 0.11, 0.05), (BX - 0.78, BY - 0.27 + i * 0.062,
        0.30 + (i % 4) * 0.17), random.choice(M_PROD))
# 收银台（右前）+ 咖啡机 + 收银屏
box("Counter", (0.55, 0.30, 0.42), (BX + 0.55, BY - 0.30, 0.24), M_WALL2)
box("CounterTop", (0.60, 0.34, 0.03), (BX + 0.55, BY - 0.30, 0.465), M_DARK)
box("Coffee", (0.10, 0.12, 0.24), (BX + 0.44, BY - 0.30, 0.60), M_DARK)
box("CashScreen", (0.10, 0.04, 0.12), (BX + 0.66, BY - 0.26, 0.58), M_DARK)
box("MAT_Lightbox", (0.06, 0.05, 0.03), (BX + 0.62, BY - 0.30, 0.53), M_LIGHTB)
# 关东煮柜台（收银台左）
cyl("Oden", 0.07, 0.14, (BX + 0.22, BY - 0.30, 0.54), M_METAL, verts=12)
for i in range(5):
    box(f"Oden{i}", (0.035, 0.035, 0.05), (BX + 0.19 + (i % 3) * 0.03,
        BY - 0.32 + (i // 3) * 0.04, 0.63), M_PROD[i])
# 杂志架（左前墙边）
box("MagRack", (0.06, 0.5, 0.6), (BX - 0.80, BY - 0.42, 0.35), M_SHelf)
for i in range(6):
    box(f"Mag{i}", (0.015, 0.09, 0.13), (BX - 0.765, BY - 0.62 + i * 0.085,
        0.28 + (i % 3) * 0.17), random.choice(M_PROD))
# 店内海报（橱窗内侧贴）
for i, (px, pz) in enumerate([(-0.55, 1.35), (-0.30, 1.35), (0.55, 1.40)]):
    box(f"Poster{i}", (0.16, 0.008, 0.22), (px, BY - BD / 2 + 0.015, pz),
        random.choice(M_POSTER))
# 后场门（右后墙白门）
box("BackDoor", (0.02, 0.34, 1.0), (BX + BW / 2 - 0.01, BY + 0.28, 0.55), M_FLOOR)
# 店内暖光（three.js 也可加；Blender 侧给 GLTF emissive 就够——不放灯避免导出复杂）

# ── 街角元素 ────────────────────────────────────────────────
# 自动贩卖机 ×2（右侧墙外，红/蓝发光正面）
for i, (vx, vm) in enumerate([(0.97, M_VENDA), (1.13, M_VENDB)]):
    box(f"MAT_Vend{'AB'[i]}", (0.13, 0.42, 0.95), (vx, 0.10, 0.51),
        mat(f"MAT_VendBody{'AB'[i]}", (0.12, 0.12, 0.14), 0.5))
    box(f"VendFace{'AB'[i]}", (0.012, 0.34, 0.72), (vx - 0.071, 0.10, 0.56), vm)
    box(f"VendTop{'AB'[i]}", (0.05, 0.40, 0.06), (vx, 0.10, 1.01), M_DARK)
# 自行车 ×2（人行道右段）
for i, bx in enumerate([(0.62, -0.20), (0.80, -0.16)]):
    ox, oy = bx
    for dx in (-0.14, 0.14):
        cyl(f"BikeWheel{i}_{dx}", 0.085, 0.015, (ox + dx, oy, 0.085), M_RUBBER,
            rot=(0, math.pi / 2, 0), verts=12)
    box(f"BikeFrame{i}", (0.26, 0.015, 0.02), (ox, oy, 0.13), M_METAL, rot=(0, 0, 0.12))
    box(f"BikeBar{i}", (0.02, 0.22, 0.02), (ox + 0.16, oy, 0.20), M_METAL)
    box(f"BikeSeat{i}", (0.06, 0.02, 0.02), (ox - 0.08, oy, 0.19), M_DARK)
# 雨伞架（自动门旁，桶+伞）
cyl("UmbStand", 0.035, 0.24, (-0.42, -0.24, 0.13), M_METAL, verts=10)
for i in range(4):
    cyl(f"Umb{i}", 0.008, 0.42, (-0.425 + i * 0.012, -0.235 + i * 0.01, 0.30),
        [M_UMB, M_METAL, M_PROD[2], M_PROD[4]][i], rot=(0.06, 0.05, 0), verts=8)
# 垃圾桶（贩卖机旁）
cyl("Trash", 0.075, 0.42, (1.06, -0.20, 0.22), M_GREEN, verts=12)
cyl("TrashLid", 0.082, 0.02, (1.06, -0.20, 0.44), M_DARK, verts=12)
# 路灯 ×2（对面车道边 + 右角）
for i, (lx, ly) in enumerate([(-1.06, -1.05), (1.10, -1.05)]):
    cyl(f"LampPole{i}", 0.022, 1.55, (lx, ly, 0.78), M_POLE, verts=10)
    box(f"LampArm{i}", (0.22 * (1 if i else -1), 0.02, 0.02), (lx + 0.10 * (1 if i else -1), ly, 1.54), M_POLE)
    box(f"LampHead{i}", (0.10, 0.05, 0.03), (lx + 0.20 * (1 if i else -1), ly, 1.52), M_WARM)
# 电线杆 ×2 + 电线（对面）
for i, px in enumerate([-1.10, 1.06]):
    cyl(f"Pole{i}", 0.028, 1.7, (px, -1.06, 0.85), M_WALL2, verts=10)
    box(f"PoleCross{i}", (0.30, 0.02, 0.02), (px, -1.06, 1.62), M_WALL2)
# 电线（悬链线近似：多段小盒）
for seg_i in range(8):
    t0, t1 = seg_i / 8, (seg_i + 1) / 8
    x0, x1 = -0.95 + (0.55 - (-0.95)) * t0, -0.95 + (0.55 - (-0.95)) * t1
    xm = (x0 + x1) / 2
    sag = 0.06 * math.sin(math.pi * (t0 + t1) / 2)
    box(f"Wire{seg_i}", (math.dist((x0, 0), (x1, 0)), 0.006, 0.006),
        (xm, -1.06, 1.60 - sag), M_DARK, rot=(0, 0, 0))
# 路牌（对面杆上）
box("RoadSign", (0.18, 0.01, 0.10), (0.55, -1.03, 1.38), M_ZEBRA)
box("RoadSignBar", (0.02, 0.01, 0.08), (0.55, -1.06, 1.32), M_POLE)
# 交通信号灯（对面车道，红灯微变——three.js 动效）
box("TLBox", (0.07, 0.06, 0.20), (0.62, -1.12, 1.30), M_DARK)
box("OBJ_TL_Red", (0.045, 0.012, 0.045), (0.62, -1.088, 1.355), M_TL_R)
box("OBJ_TL_Green", (0.045, 0.012, 0.045), (0.62, -1.088, 1.245), M_TL_OFF)
# 街角护栏（右缘）
for i in range(5):
    cyl(f"RailP{i}", 0.008, 0.30, (1.18, -0.05 - i * 0.13, 0.17), M_METAL, verts=8)
box("RailBar1", (0.012, 0.60, 0.015), (1.18, -0.31, 0.30), M_METAL)
box("RailBar2", (0.012, 0.60, 0.015), (1.18, -0.31, 0.17), M_METAL)
# 公告栏（小巷墙上）
box("Board", (0.015, 0.42, 0.34), (BX - BW / 2 - 0.008, BY - 0.55, 1.25), M_WALL2)
for i in range(3):
    box(f"BoardP{i}", (0.006, 0.11, 0.13), (BX - BW / 2 - 0.016, BY - 0.66 + i * 0.115,
        1.25), M_POSTER[i])
# 空调外机（右墙高位）
box("ACU", (0.14, 0.24, 0.30), (BX + BW / 2 + 0.08, BY + 0.42, 1.55), M_WALL2)
box("ACU2", (0.16, 0.02, 0.02), (BX + BW / 2 + 0.08, BY + 0.29, 1.42), M_METAL)
# 小巷地面（暗）
plane("Alley", (0.34), (0.34), (-1.02, 0.62, 0.006), M_DARK)

# ── 灯光（Blender 侧仅用于预览渲染；GLTF 导出 emissive 材质即可）──
S.world = bpy.data.worlds.new("Night")
S.world.use_nodes = True
S.world.node_tree.nodes["Background"].inputs[0].default_value = (0.015, 0.02, 0.045, 1)
S.world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

def light(name, tp, loc, energy, color, size=0.5):
    d = bpy.data.lights.new(name, tp)
    d.energy = energy
    d.color = color
    if tp == 'AREA':
        d.size = size
    o = bpy.data.objects.new(name, d)
    o.location = loc
    bpy.context.collection.objects.link(o)
    return o

light("InWarm1", 'AREA', (-0.5, 0.6, 1.85), 60, (1.0, 0.78, 0.5), 0.7)
light("InWarm2", 'AREA', (0.45, 0.6, 1.85), 60, (1.0, 0.78, 0.5), 0.7)
light("SignNeon", 'POINT', (BX, BY - 0.4, 2.25), 25, (1.0, 0.5, 0.15))
light("LampGlow", 'POINT', (0.92, -1.02, 1.50), 18, (1.0, 0.72, 0.40))
light("CoolMoon", 'SUN', (0.3, -0.2, 2.5), 0.35, (0.55, 0.65, 0.95))

# ── 相机 + 渲染预设（确认造型用）────────────────────────────
cam_d = bpy.data.cameras.new("Cam")
cam = bpy.data.objects.new("Cam", cam_d)
bpy.context.collection.objects.link(cam)
cam.location = (1.35, -3.05, 1.95)
cam_d.lens = 40
tgt = bpy.data.objects.new("CamTarget", None)
tgt.location = (-0.05, 0.15, 0.85)
bpy.context.collection.objects.link(tgt)
con = cam.constraints.new('TRACK_TO')
con.target = tgt
con.track_axis = 'TRACK_NEGATIVE_Z'
con.up_axis = 'UP_Y'
S.camera = cam
S.render.engine = 'BLENDER_EEVEE'
S.render.resolution_x = 1280
S.render.resolution_y = 960
S.eevee.use_shadows = True

# ── 导出 GLTF ───────────────────────────────────────────────
outdir = Path(__file__).parent / "konbini_web"
outdir.mkdir(exist=True) if False else outdir.mkdir(exist_ok=True)
# ── 场景 JSON 导出（绕开 GLTF 生态：blender 5.2 导出与 three loader 兼容连环雷）
out_objs = []
for o in bpy.data.objects:
    if o.type != 'MESH':
        continue
    d = o.dimensions
    nv = len(o.data.vertices)
    g = 'box' if nv == 8 else ('cyl' if nv > 12 else 'plane')
    mrec = {'c': [0.8, 0.8, 0.8], 'e': None, 'es': 0.0, 'a': 1.0, 'mt': 0.0, 'ro': 0.6}
    if o.data.materials:
        mm = o.data.materials[0]
        if mm and mm.use_nodes:
            b = next((nd for nd in mm.node_tree.nodes
                      if nd.type == 'BSDF_PRINCIPLED'), None)
            if b:
                mrec['c'] = [round(c, 3) for c in b.inputs['Base Color'].default_value[:3]]
                mrec['a'] = round(b.inputs['Alpha'].default_value, 3)
                mrec['mt'] = round(b.inputs['Metallic'].default_value, 3)
                mrec['ro'] = round(b.inputs['Roughness'].default_value, 3)
                es = b.inputs['Emission Strength'].default_value
                if es and es > 0:
                    mrec['e'] = [round(c, 3) for c in b.inputs['Emission Color'].default_value[:3]]
                    mrec['es'] = round(es, 2)
    out_objs.append({
        'n': o.name, 'g': g,
        's': [round(d.x, 4), round(d.y, 4), round(d.z, 4)],
        'p': [round(o.location.x, 4), round(o.location.y, 4), round(o.location.z, 4)],
        'r': [round(o.rotation_euler.x, 4), round(o.rotation_euler.y, 4),
              round(o.rotation_euler.z, 4)],
        'm': mrec})
(WEB := Path(__file__).parent / "konbini_web").mkdir(exist_ok=True)
(WEB / "scene.json").write_text(_json.dumps(out_objs, ensure_ascii=False), encoding='utf-8')
print("[konbini] scene.json objects:", len(out_objs))
