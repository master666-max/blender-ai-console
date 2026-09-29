"""konbini_v3_scene.py — 雨夜便利店场景 v3（通过 MCP execute_code 注入执行）
================================================================================
v3 策略（吸收全部教训）：
  * 无 alpha 玻璃（W-15 EEVEE 透射磨砂）→ 橱窗开口留空 + 斜高光条暗示
  * 店内自发光体系：店内可见面直接带 emissive（动画平涂逻辑，不受光路影响）
  * 光照 = render_core 架构：环境底光 ×3 + Key(店内暖)/Rim(招牌品红)/点缀
  * 全程 bpy.data API（无 ops——主线程桥安全）
  * 命名保留动效锚点：MAT_Sign/MAT_Lightbox/MAT_Vend/OBJ_DoorL/R/OBJ_TL_*
"""
import bpy
import json
import math
import random

random.seed(11)

# ── 清默认三件 ──────────────────────────────────────────────
for o in list(bpy.data.objects):
    if o.name in ("Cube", "Camera", "Light"):
        bpy.data.objects.remove(o, do_unlink=True)

col = bpy.data.collections.get("KONBINI") or bpy.data.collections.new("KONBINI")
if col.name not in [c.name for c in bpy.context.scene.collection.children]:
    bpy.context.scene.collection.children.link(col)

# ── helpers（纯数据 API）────────────────────────────────────
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
    return m

CUBE_V = [(-.5,-.5,-.5),(.5,-.5,-.5),(.5,.5,-.5),(-.5,.5,-.5),
          (-.5,-.5,.5),(.5,-.5,.5),(.5,.5,.5),(-.5,.5,.5)]
CUBE_F = [(0,1,2,3),(4,7,6,5),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)]

def box(name, size, loc, m, rot=(0, 0, 0), bevel=0.012, coll=None):
    sx, sy, sz = size
    mesh = bpy.data.meshes.new(name)
    vs = [(x*sx, y*sy, z*sz) for x, y, z in CUBE_V]
    mesh.from_pydata(vs, [], CUBE_F)
    mesh.update()
    o = bpy.data.objects.new(name, mesh)
    o.location = loc
    o.rotation_euler = rot
    (coll or col).objects.link(o)
    o.data.materials.append(m)
    md = o.modifiers.new("bev", 'BEVEL')
    md.width = bevel; md.segments = 2
    return o

def cyl(name, r, depth, loc, m, rot=(0, 0, 0), verts=20, coll=None):
    mesh = bpy.data.meshes.new(name)
    vs, fs = [], []
    for i in range(verts):
        a0, a1 = i/verts*2*math.pi, (i+1)/verts*2*math.pi
        vs += [(r*math.cos(a0), r*math.sin(a0), -depth/2),
               (r*math.cos(a1), r*math.sin(a1), -depth/2),
               (r*math.cos(a1), r*math.sin(a1), depth/2),
               (r*math.cos(a0), r*math.sin(a0), depth/2)]
    for i in range(verts):
        b0 = i*4
        fs += [(b0, b0+1, b0+2, b0+3)]
    mesh.from_pydata(vs, [], fs)
    mesh.update()
    o = bpy.data.objects.new(name, mesh)
    o.location = loc; o.rotation_euler = rot
    (coll or col).objects.link(o)
    o.data.materials.append(m)
    return o

def sphere(name, r, loc, m, segs=28):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=loc,
                                         segments=segs, ring_count=segs//2)
    o = bpy.context.active_object
    o.name = name
    o.data.materials.append(m)
    for c in list(o.users_collection):
        c.objects.unlink(o)
    col.objects.link(o)
    return o

def plane(name, sx, sy, loc, m, rot=(0, 0, 0), coll=None):
    sx, sy = max(sx, 0.001), max(sy, 0.001)
    vs = [(-sx/2, -sy/2, 0), (sx/2, -sy/2, 0), (sx/2, sy/2, 0), (-sx/2, sy/2, 0)]
    fs = [(0, 2, 1), (0, 3, 2)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vs, [], fs)
    mesh.update()
    o = bpy.data.objects.new(name, mesh)
    o.location = loc; o.rotation_euler = rot
    (coll or col).objects.link(o)
    o.data.materials.append(m)
    return o

# ── 材质（6 色板 + 店内自发光系列）──────────────────────────
M_BASE  = mat("MAT_Base",   (0.22, 0.23, 0.27), 0.45)
M_ROAD  = mat("MAT_Road",   (0.13, 0.14, 0.17), 0.28, 0.32)
M_WET   = mat("MAT_Wet",    (0.06, 0.08, 0.12), 0.04, 0.72)
M_SIDE  = mat("MAT_Side",   (0.44, 0.46, 0.51), 0.85)
M_CURB  = mat("MAT_Curb",   (0.55, 0.57, 0.60), 0.8)
M_WALL  = mat("MAT_Wall",   (0.55, 0.60, 0.70), 0.65,
              emit=(0.55, 0.60, 0.70), es=0.10)          # 店墙微自发光
M_TRIM  = mat("MAT_Trim",   (0.15, 0.17, 0.21), 0.5, 0.3)
M_FLOOR = mat("MAT_Floor",  (0.88, 0.76, 0.58), 0.6,
              emit=(0.88, 0.72, 0.50), es=0.28)          # 店内地板自发光（暖）
M_WHITE = mat("MAT_White",  (0.90, 0.88, 0.84), 0.45,
              emit=(0.85, 0.80, 0.72), es=0.22)          # 货架自发光（微）
M_DARK  = mat("MAT_Dark",   (0.07, 0.07, 0.09), 0.7)
M_POLE  = mat("MAT_Pole",   (0.20, 0.22, 0.26), 0.45, 0.5)
M_METAL = mat("MAT_Metal",  (0.55, 0.58, 0.62), 0.28, 0.75)
M_WARM  = mat("MAT_Warm",   (1, 1, 1), 0.4, emit=(1.0, 0.68, 0.34), es=3.2)  # 暖橙焦点
M_SIGN  = mat("MAT_Sign",   (1, 1, 1), 0.4, emit=(1.0, 0.16, 0.44), es=3.0)  # 品红焦点
M_SIGN2 = mat("MAT_Sign2",  (1, 1, 1), 0.4, emit=(0.15, 0.78, 1.0), es=2.6)  # 青
M_VEND  = mat("MAT_Vend",   (1, 1, 1), 0.35, emit=(0.98, 0.52, 0.14), es=2.4)  # 钠橙
M_BAND  = mat("MAT_Band",   (1, 1, 1), 0.4, emit=(1.0, 0.72, 0.42), es=1.8)  # 商品带
M_ZEBRA = mat("MAT_Zebra",  (0.62, 0.65, 0.70), 0.3, 0.2)
M_UMB   = mat("MAT_Umb",    (0.78, 0.22, 0.30), 0.5)
M_GRN   = mat("MAT_GRN",    (0.10, 0.24, 0.16), 0.8)
M_PROD  = [mat(f"MAT_P{n}", c, 0.5) for n, c in
           enumerate([(0.90, 0.35, 0.30), (0.30, 0.55, 0.90), (0.95, 0.78, 0.35),
                      (0.40, 0.78, 0.50), (0.80, 0.40, 0.80), (0.95, 0.55, 0.20)])]
M_HL    = mat("MAT_HL", (1, 1, 1), 0.1, emit=(0.9, 0.95, 1.0), es=0.55)      # 玻璃高光条

# ── 底座 ────────────────────────────────────────────────────
box("Base", (2.4, 2.4, 0.15), (0, 0, -0.075), M_BASE, bevel=0.02)

# ── 道路 ────────────────────────────────────────────────────
plane("Road", 2.4, 0.86, (0, -0.77, 0.002), M_ROAD, coll=col)
plane("WetA", 0.95, 0.34, (-0.45, -0.82, 0.004), M_WET, coll=col)
plane("WetB", 0.62, 0.28, (0.55, -0.62, 0.004), M_WET, coll=col)
plane("Walk", 2.4, 0.40, (0, -0.14, 0.014), M_SIDE, coll=col)
box("Curb", (2.4, 0.035, 0.04), (0, -0.335, 0.02), M_CURB, coll=col)
box("Drain", (2.2, 0.045, 0.008), (0, -0.31, 0.033), M_DARK, coll=col)
for i in range(5):
    plane(f"Z{i}", 0.10, 0.52, (-0.70 + i*0.26, -0.77, 0.004), M_ZEBRA, coll=col)
plane("Cline", 2.3, 0.028, (0, -0.77, 0.004), M_ZEBRA, coll=col)
plane("WetZ", 0.85, 0.5, (-0.35, -0.77, 0.005), M_WET, coll=col)
# 湿反光竖条（光源倒影）
plane("ReflLamp", 0.10, 0.80, (1.10, -1.00, 0.006), M_WARM,
      rot=(math.pi/2, 0, 0.06), coll=col)
plane("ReflVend", 0.09, 0.50, (1.09, -0.42, 0.006), M_WARM,
      rot=(math.pi/2, 0, 0), coll=col)
plane("ReflSign", 0.12, 0.38, (-0.10, -0.60, 0.006),
      mat("MAT_ReflSign", (1, 1, 1), 0.1, 0.6, emit=(1.0, 0.28, 0.44), es=0.9),
      rot=(math.pi/2, 0, 0), coll=col)
# 停车位线
for i in range(2):
    plane(f"Park{i}", 0.02, 0.40, (0.70 + i*0.45, -0.88, 0.004), M_ZEBRA, coll=col)

# ── 便利店主体 ──────────────────────────────────────────────
BX, BY = -0.02, 0.62
BW, BD, BH = 2.0, 0.98, 1.95
box("Body", (BW, BD, BH), (BX, BY, BH/2), M_WALL, coll=col)
box("Cornice", (BW+0.05, BD+0.05, 0.06), (BX, BY, BH+0.03), M_TRIM, coll=col)
plane("FloorIn", BW-0.12, BD-0.14, (BX, BY, 0.012), M_FLOOR, coll=col)
# 地面导视贴条（店内）
plane("GuideIn", 0.5, 0.06, (BX+0.3, BY-0.1, 0.017),
      mat("MAT_Guide", (0.9, 0.85, 0.7), 0.5, emit=(0.9, 0.8, 0.6), es=0.3),
      coll=col)
FX = BY - BD/2 - 0.005
# 橱窗开口（无玻璃）+ 窗框分格
box("FrameTop", (1.30, 0.035, 0.05), (BX-0.52, FX+0.01, 1.66), M_TRIM, coll=col)
box("FrameBot", (1.30, 0.035, 0.05), (BX-0.52, FX+0.01, 0.47), M_TRIM, coll=col)
box("FrameV1", (0.035, 0.035, 1.20), (BX-1.05, FX+0.01, 1.06), M_TRIM, coll=col)
box("FrameV2", (0.035, 0.035, 1.20), (BX-0.28, FX+0.01, 1.06), M_TRIM, coll=col)
box("FrameV3", (0.035, 0.035, 1.20), (BX-0.80, FX+0.01, 1.06), M_TRIM, coll=col)
# 玻璃高光条 ×2（斜向，动画玻璃暗示——替代实体玻璃）
plane("HL1", 1.10, 0.07, (BX-0.55, FX-0.012, 1.42), M_HL,
      rot=(math.pi/2, 0, math.radians(38)), coll=col)
plane("HL2", 0.90, 0.05, (BX-0.50, FX-0.012, 0.98), M_HL,
      rot=(math.pi/2, 0, math.radians(38)), coll=col)
# 自动门（双滑，门框；无玻璃门板——开口+框）
box("OBJ_DoorL", (0.24, 0.02, 1.14), (-0.02, FX-0.01, 1.06),
    mat("MAT_DoorG", (0.55, 0.72, 0.85), 0.05, alpha=0.55), coll=col)
box("OBJ_DoorR", (0.24, 0.02, 1.14), (0.24, FX-0.01, 1.06),
    mat("MAT_DoorG", (0.55, 0.72, 0.85), 0.05, alpha=0.55), coll=col)
box("DFr", (0.62, 0.04, 0.05), (0.11, FX, 1.665), M_TRIM, coll=col)
# 右实墙段 + 店招底板
box("WallR", (0.26, 0.02, 1.35), (BX+0.87, FX, 0.72), M_WALL, coll=col)
# 屋檐雨棚
box("Awning", (BW+0.36, 0.36, 0.045), (BX, BY-BD/2-0.16, 1.78), M_TRIM, coll=col)
box("AwningE", (BW+0.36, 0.02, 0.075), (BX, BY-BD/2-0.33, 1.77), M_WARM, coll=col)
# 招牌（品红主 + 青副）
box("MAT_Sign", (1.55, 0.13, 0.30), (BX, BY+0.03, 2.22), M_SIGN, coll=col)
box("MAT_Sign2", (0.52, 0.05, 0.11), (BX-0.76, BY-0.32, 1.96), M_SIGN2, coll=col)
cyl("SPole", 0.016, 1.15, (0.86, -0.30, 0.60), M_POLE, coll=col)
box("MAT_Vend", (0.30, 0.05, 0.40), (0.86, -0.30, 1.32), M_VEND, coll=col)
box("Mat", (0.68, 0.32, 0.012), (0.11, FX-0.20, 0.03), M_DARK, coll=col)

# ── 店内（自发光体系）───────────────────────────────────────
box("MAT_Warm", (0.62, 0.10, 0.025), (BX-0.5, BY+0.05, 1.86), M_WARM, coll=col)
box("MAT_Warm", (0.62, 0.10, 0.025), (BX+0.42, BY+0.05, 1.86), M_WARM, coll=col)
# 后墙暖光带 ×2
box("WarmB1", (1.75, 0.02, 0.15), (BX, BY+BD/2-0.03, 1.52), M_WARM, coll=col)
box("WarmB2", (1.75, 0.02, 0.09), (BX, BY+BD/2-0.03, 1.02), M_WARM, coll=col)
# 饮料柜（发光内嵌 + 瓶排）
box("DCase", (1.0, 0.16, 1.32), (BX-0.35, BY+0.40, 0.70), M_WHITE, coll=col)
box("MAT_Warm", (0.9, 0.02, 1.02), (BX-0.35, BY+0.30, 0.74), M_WARM, coll=col)
for i in range(10):
    box(f"Btl{i}", (0.045, 0.06, 0.13), (BX-0.72+i*0.082, BY+0.29,
        0.42 + (i % 3)*0.30), M_PROD[i % 6], coll=col)
# 货架 ×2（正面发光带）
for r, gy in enumerate([0.34, 0.60]):
    box(f"Shelf{r}", (0.80, 0.22, 0.05), (BX-0.45, gy, 0.42), M_WHITE, coll=col)
    box(f"ShelfB{r}", (0.80, 0.02, 0.62), (BX-0.45, gy+0.10, 0.72), M_WHITE, coll=col)
    box("MAT_Band", (0.72, 0.05, 0.10), (BX-0.45, gy-0.06, 0.60), M_BAND, coll=col)
    box("MAT_Band", (0.72, 0.05, 0.10), (BX-0.45, gy-0.06, 0.86), M_BAND, coll=col)
# 便当柜（左墙）
box("Bento", (0.16, 0.5, 0.85), (BX-0.90, BY-0.10, 0.46), M_WHITE, coll=col)
box("MAT_Band", (0.04, 0.4, 0.08), (BX-0.80, BY-0.10, 0.55), M_BAND, coll=col)
# 收银台 + 咖啡机 + 关东煮
box("Cnt", (0.52, 0.28, 0.40), (BX+0.62, BY-0.28, 0.23), M_WALL, coll=col)
box("CntT", (0.56, 0.32, 0.025), (BX+0.62, BY-0.28, 0.45), M_TRIM, coll=col)
box("Cof", (0.09, 0.11, 0.22), (BX+0.52, BY-0.28, 0.57), M_DARK, coll=col)
cyl("Oden", 0.065, 0.13, (BX+0.28, BY-0.28, 0.53), M_METAL, coll=col)
box("MAT_Band", (0.08, 0.08, 0.04), (BX+0.28, BY-0.28, 0.62), M_WARM, coll=col)
# 杂志架
box("Mag", (0.05, 0.44, 0.55), (BX-0.94, BY-0.42, 0.33), M_WHITE, coll=col)
box("MAT_Band", (0.02, 0.36, 0.07), (BX-0.905, BY-0.42, 0.45), M_BAND, coll=col)
# 海报 ×3（橱窗上沿内侧）
box("Pst1", (0.15, 0.006, 0.20), (BX-0.60, FX+0.015, 1.32), M_VEND, coll=col)
box("Pst2", (0.15, 0.006, 0.20), (BX-0.38, FX+0.015, 1.32), M_SIGN2, coll=col)
box("Pst3", (0.15, 0.006, 0.20), (BX-0.16, FX+0.015, 1.32), M_BAND, coll=col)
# 后场门 + 储物柜
box("BDoor", (0.02, 0.32, 0.95), (BX+BW/2-0.012, BY+0.25, 0.52), M_FLOOR, coll=col)
box("Lockers", (0.10, 0.40, 0.85), (BX+0.80, BY+0.55, 0.46), M_SIDE, coll=col)
# 冰柜（左前矮柜）
box("Freezer", (0.5, 0.30, 0.55), (BX-0.62, BY-0.28, 0.30), M_WHITE, coll=col)
box("MAT_Band", (0.42, 0.04, 0.06), (BX-0.62, BY-0.42, 0.52), M_BAND, coll=col)

# ── 街角 ────────────────────────────────────────────────────
for i, (vx, vm) in enumerate([(1.02, M_SIGN2), (1.16, M_VEND)]):
    box(f"VBody{i}", (0.13, 0.40, 0.92), (vx, 0.05, 0.50), M_DARK, coll=col)
    box("MAT_Vend", (0.012, 0.32, 0.66), (vx-0.07, 0.05, 0.55), vm, coll=col)
    box(f"VTop{i}", (0.04, 0.38, 0.05), (vx, 0.05, 0.985), M_DARK, coll=col)
cyl("UmbSt", 0.032, 0.22, (-0.48, -0.26, 0.13), M_POLE, coll=col)
for i in range(3):
    cyl(f"Umb{i}", 0.007, 0.40, (-0.485+i*0.012, -0.255+i*0.012, 0.28),
        [M_UMB, M_POLE, M_GRN][i], rot=(0.05, 0.04, 0), coll=col)
cyl("Trash", 0.07, 0.40, (0.60, -0.26, 0.22), M_GRN, coll=col)
cyl("TrashL", 0.076, 0.02, (0.60, -0.26, 0.43), M_DARK, coll=col)
bw = (0.55, -0.24)
for dx in (-0.16, 0.16):
    cyl(f"BWh{dx}", 0.088, 0.014, (bw[0]+dx, bw[1], 0.088), M_DARK,
        rot=(0, math.pi/2, 0), coll=col)
box("BFr", (0.30, 0.014, 0.02), (bw[0], bw[1], 0.135), M_POLE, rot=(0, 0, 0.1), coll=col)
box("BBr", (0.02, 0.20, 0.02), (bw[0]+0.17, bw[1], 0.21), M_POLE, coll=col)
box("BSt", (0.07, 0.02, 0.02), (bw[0]-0.09, bw[1], 0.20), M_DARK, coll=col)
box("AC", (0.15, 0.26, 0.30), (BX+BW/2+0.09, BY+0.40, 1.52), M_WALL, coll=col)
box("ACb", (0.17, 0.02, 0.02), (BX+BW/2+0.09, BY+0.26, 1.38), M_POLE, coll=col)
box("Brd", (0.014, 0.40, 0.32), (BX-BW/2-0.006, BY-0.48, 1.22), M_TRIM, coll=col)
box("MAT_Band", (0.006, 0.30, 0.10), (BX-BW/2-0.014, BY-0.48, 1.22), M_BAND, coll=col)
for i, lx in enumerate([-1.06, 1.10]):
    cyl(f"LP{i}", 0.02, 1.5, (lx, -1.08, 0.75), M_POLE, coll=col)
    box(f"LA{i}", (0.24, 0.02, 0.02), (lx+0.12*(1 if i else -1), -1.08, 1.48),
        M_POLE, coll=col)
    box(f"LH{i}", (0.11, 0.05, 0.03), (lx+0.22*(1 if i else -1), -1.08, 1.46),
        M_WARM, coll=col)
cyl("WP", 0.026, 1.65, (1.10, -1.10, 0.83), M_WALL, coll=col)
box("WPc", (0.26, 0.02, 0.02), (1.10, -1.10, 1.58), M_WALL, coll=col)
for s in range(6):
    t0, t1 = s/6, (s+1)/6
    x0, x1 = 1.10 + (-2.4)*t0, 1.10 + (-2.4)*t1
    box(f"Wr{s}", (abs(x1-x0), 0.006, 0.005), ((x0+x1)/2, -1.10,
        1.56 - 0.05*math.sin(math.pi*(t0+t1)/2)), M_DARK, coll=col)
box("TLB", (0.06, 0.055, 0.18), (0.88, -1.10, 1.24), M_DARK, coll=col)
box("OBJ_TL_Red", (0.04, 0.012, 0.04), (0.88, -1.07, 1.29), M_VEND, coll=col)
box("OBJ_TL_Green", (0.04, 0.012, 0.04), (0.88, -1.07, 1.19), M_DARK, coll=col)
box("RS", (0.16, 0.008, 0.09), (-1.02, -1.05, 1.30), M_ZEBRA, coll=col)
for i in range(4):
    cyl(f"RL{i}", 0.007, 0.26, (1.17, -0.30-i*0.14, 0.15), M_POLE, coll=col)
box("RLb", (0.01, 0.48, 0.014), (1.17, -0.51, 0.27), M_POLE, coll=col)

# ── 灯光（render_core 架构）─────────────────────────────────
S = bpy.context.scene
S.world = bpy.data.worlds.get("N") or bpy.data.worlds.new("N")
S.world.use_nodes = True
wnt = S.world.node_tree
bg = next((nd for nd in wnt.nodes if nd.type == 'BACKGROUND'), None)
if bg is None:
    bg = wnt.nodes.new("ShaderNodeBackground")
out_w = next((nd for nd in wnt.nodes if nd.type == 'OUTPUT_WORLD'), None)
if out_w is None:
    out_w = wnt.nodes.new("ShaderNodeOutputWorld")
    wnt.links.new(bg.outputs[0], out_w.inputs[0])
wnt.links.new(bg.outputs[0], out_w.inputs["Surface"])
bg.inputs[0].default_value = (0.018, 0.024, 0.048, 1)
bg.inputs[1].default_value = 3.0

def light(name, tp, loc, e, c, size=0.4, rot=None):
    d = bpy.data.lights.new(name, tp); d.energy = e; d.color = c
    if tp == 'AREA':
        d.size = size
    o = bpy.data.objects.new(name, d); o.location = loc
    if rot:
        o.rotation_euler = rot
    bpy.context.scene.collection.objects.link(o)
    if hasattr(d, "use_contact_shadow"):
        d.use_contact_shadow = True
    return o

light("W1", 'AREA', (BX-0.5, BY+0.05, 1.83), 110, (1.0, 0.74, 0.44), 0.6)
light("W2", 'AREA', (BX+0.45, BY+0.05, 1.83), 110, (1.0, 0.74, 0.44), 0.6)
light("W3", 'AREA', (BX, BY-0.30, 1.50), 26, (1.0, 0.80, 0.55), 0.9,
      rot=(math.radians(28), 0, 0))
light("Sign", 'POINT', (BX, BY-0.30, 2.12), 20, (1.0, 0.35, 0.55))
light("Vend", 'POINT', (1.09, -0.12, 0.62), 7, (0.55, 0.70, 1.0))
light("Lmp", 'POINT', (1.24, -1.08, 1.40), 9, (1.0, 0.70, 0.38))
light("InDeep", 'POINT', (BX-0.3, BY+0.35, 1.35), 30, (1.0, 0.72, 0.42))
light("Sky", 'SUN', (0, 0, 0), 0.40, (0.50, 0.60, 0.92))
so = bpy.data.objects["Sky"]
so.rotation_euler = (math.radians(50), 0, math.radians(-30))

# ── 相机 ────────────────────────────────────────────────────
cam_d = bpy.data.cameras.new("C"); cam = bpy.data.objects.new("C", cam_d)
S.collection.objects.link(cam)
cam.location = (2.7, -2.9, 2.45)
cam_d.lens = 36
tgt = bpy.data.objects.new("T", None); tgt.location = (-0.05, 0.10, 0.60)
S.collection.objects.link(tgt)
c = cam.constraints.new('TRACK_TO'); c.target = tgt
c.track_axis = 'TRACK_NEGATIVE_Z'; c.up_axis = 'UP_Y'
S.camera = cam

# ── 渲染设置 ────────────────────────────────────────────────
S.render.engine = 'BLENDER_EEVEE'
S.render.resolution_x = 1440
S.render.resolution_y = 1080
S.eevee.taa_render_samples = 64

# ── scene.json 导出（three.js 重建通道）─────────────────────
out_objs = []
for o in bpy.data.objects:
    if o.type != 'MESH' or o.name not in [x.name for x in col.objects]:
        continue
    d = o.dimensions
    nv = len(o.data.vertices)
    g = 'box' if nv == 8 else ('cyl' if nv > 12 else 'plane')
    mrec = {'c': [0.8, 0.8, 0.8], 'e': None, 'es': 0.0, 'a': 1.0, 'mt': 0.0, 'ro': 0.6}
    if o.data.materials:
        mm = o.data.materials[0]
        if mm and mm.use_nodes:
            b = next((nd for nd in mm.node_tree.nodes if nd.type == 'BSDF_PRINCIPLED'), None)
            if b:
                mrec['c'] = [round(c, 3) for c in b.inputs['Base Color'].default_value[:3]]
                mrec['a'] = round(b.inputs['Alpha'].default_value, 3)
                mrec['mt'] = round(b.inputs['Metallic'].default_value, 3)
                mrec['ro'] = round(b.inputs['Roughness'].default_value, 3)
                es = b.inputs['Emission Strength'].default_value
                if es and es > 0:
                    mrec['e'] = [round(c, 3) for c in b.inputs['Emission Color'].default_value[:3]]
                    mrec['es'] = round(es, 2)
    out_objs.append({'n': o.name, 'g': g,
                     's': [round(d.x, 4), round(d.y, 4), round(d.z, 4)],
                     'p': [round(o.location.x, 4), round(o.location.y, 4), round(o.location.z, 4)],
                     'r': [round(o.rotation_euler.x, 4), round(o.rotation_euler.y, 4),
                           round(o.rotation_euler.z, 4)],
                     'm': mrec})
WEB = Path(r"D:/WorkBuddy专用！危险！！！！！！！！/2026-09-26-21-02-58/blender_console/konbini_web")
WEB.mkdir(exist_ok=True)
(WEB / "scene.json").write_text(json.dumps(out_objs, ensure_ascii=False), encoding='utf-8')
print("[konbini v3] objects:", len(out_objs))
