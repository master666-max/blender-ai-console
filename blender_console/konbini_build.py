"""konbini_build.py v2 — 雨夜便利店街角微缩（推倒重做）
================================================================================
v1 教训（用户裁决："全他妈是混乱的方块"）：
  * 258 个无倒角 primitives 平铺 = 方块堆，不是微缩模型
  * 五颜六色的商品盒 = 噪声，不是氛围
  * 元素撒满底座 = 没有构图
v2 三原则：
  1. 减件聚焦：~110 件，每件有存在理由；商品只做"发光色带暗示"不逐个建模
  2. 全量倒角：BEVEL 0.012×2 段——圆润感 = 微缩模型感的第一来源
  3. 色彩克制：夜蓝基调 + 三个光焦点（店内暖橙/招牌品红/街灯钠黄）
运行：blender --background --python konbini_build.py [--python-expr 渲染]
"""
import bpy, math, random, sys
from pathlib import Path

random.seed(7)
bpy.ops.wm.read_factory_settings(use_empty=True)
S = bpy.context.scene

# ── helpers ─────────────────────────────────────────────────
def mat(name, color, rough=0.6, metal=0.0, emit=None, es=0.0, alpha=1.0):
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
        b.inputs["Emission Strength"].default_value = es
    if alpha < 1.0:
        b.inputs["Alpha"].default_value = alpha
        m.blend_method = 'BLEND'
    return m

def bev(o, w=0.012, seg=2):
    md = o.modifiers.new("bev", 'BEVEL')
    md.width = w; md.segments = seg
    return o

def box(name, size, loc, m, rot=(0, 0, 0), bevel=0.012):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.scale = (size[0]/2, size[1]/2, size[2]/2)
    o.data.materials.append(m)
    if bevel:
        bev(o, bevel)
    return o

def cyl(name, r, depth, loc, m, rot=(0, 0, 0), verts=20, bevel=0.006):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, location=loc,
                                        rotation=rot, vertices=verts)
    o = bpy.context.active_object
    o.name = name
    o.data.materials.append(m)
    if bevel:
        bev(o, bevel)
    return o

def plane(name, sx, sy, loc, m, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_plane_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.scale = (sx/2, sy/2, 1)
    o.data.materials.append(m)
    return o

# ── 材质（#1 色板纪律：夜蓝紫底 / 暖橙光 / 品红招 / 青 vending / 沥青黑 / 玻璃青）
M_BASE  = mat("MAT_Base",   (0.13, 0.14, 0.19), 0.5)                    # 夜蓝紫底座
M_ROAD  = mat("MAT_Road",   (0.08, 0.09, 0.13), 0.25, 0.35)             # 沥青黑
M_WET   = mat("MAT_Wet",    (0.05, 0.07, 0.11), 0.04, 0.75)             # 镜面积水
M_SIDE  = mat("MAT_Side",   (0.28, 0.30, 0.38), 0.85)                   # 冷灰人行道
M_CURB  = mat("MAT_Curb",   (0.36, 0.39, 0.46), 0.8)
M_WALL  = mat("MAT_Wall",   (0.30, 0.34, 0.44), 0.65)                   # 店墙夜蓝灰
M_TRIM  = mat("MAT_Trim",   (0.13, 0.15, 0.19), 0.5, 0.3)
M_GLASS = mat("MAT_Glass",  (0.45, 0.68, 0.85), 0.04, alpha=0.28)       # 玻璃青
M_DOOR  = mat("MAT_Door",   (0.48, 0.72, 0.86), 0.04, alpha=0.38)
M_FLOOR = mat("MAT_Floor",  (0.85, 0.72, 0.55), 0.6)                    # 店内暖米
M_WHITE = mat("MAT_White",  (0.80, 0.78, 0.74), 0.45)
M_DARK  = mat("MAT_Dark",   (0.05, 0.05, 0.07), 0.7)
M_POLE  = mat("MAT_Pole",   (0.18, 0.20, 0.24), 0.45, 0.5)
M_METAL = mat("MAT_Metal",  (0.40, 0.44, 0.50), 0.3, 0.7)
M_WARM  = mat("MAT_Warm",   (1, 1, 1), 0.4, emit=(1.0, 0.62, 0.25), es=2.6)   # 暖橙焦点
M_SIGN  = mat("MAT_Sign",   (1, 1, 1), 0.4, emit=(1.0, 0.18, 0.42), es=2.8)   # 品红焦点
M_SIGN2 = mat("MAT_Sign2",  (1, 1, 1), 0.4, emit=(0.15, 0.75, 1.0), es=2.2)   # 青焦点
M_VEND  = mat("MAT_Vend",   (1, 1, 1), 0.35, emit=(0.95, 0.50, 0.12), es=2.0)  # 钠橙
M_BAND  = mat("MAT_Band",   (1, 1, 1), 0.4, emit=(1.0, 0.70, 0.40), es=1.5)   # 商品带（暖）
M_ZEBRA = mat("MAT_Zebra",  (0.55, 0.58, 0.64), 0.3, 0.2)
M_UMB   = mat("MAT_Umb",    (0.75, 0.20, 0.28), 0.5)                    # 品红系伞
M_GRN   = mat("MAT_GRN",    (0.10, 0.22, 0.16), 0.8)

# ── 底座 ────────────────────────────────────────────────────
box("Base", (2.4, 2.4, 0.15), (0, 0, -0.075), M_BASE, bevel=0.02)

# ── 道路系统 ────────────────────────────────────────────────
plane("Road", 2.4, 0.86, (0, -0.77, 0.002), M_ROAD)
plane("WetA", 0.95, 0.34, (-0.45, -0.82, 0.004), M_WET)
plane("WetB", 0.62, 0.28, (0.55, -0.62, 0.004), M_WET)
plane("Walk", 2.4, 0.40, (0, -0.14, 0.014), M_SIDE)
box("Curb", (2.4, 0.035, 0.04), (0, -0.335, 0.02), M_CURB)
box("Drain", (2.2, 0.045, 0.008), (0, -0.31, 0.033), M_DARK)
for i in range(5):
    plane(f"Z{i}", 0.10, 0.52, (-0.70 + i*0.26, -0.77, 0.004), M_ZEBRA)
plane("Cline", 2.3, 0.028, (0, -0.77, 0.004), M_ZEBRA)
plane("WetZ", 0.85, 0.5, (-0.35, -0.77, 0.005), M_WET)

# ── #3 湿反光竖条（动画夜雨标志性笔触：每个光源倒影一根拉长亮条）──
plane("ReflLamp", 0.10, 0.85, (1.10, -1.02, 0.006), M_WARM, rot=(math.pi/2, 0, 0.06))
plane("ReflVend", 0.09, 0.55, (1.09, -0.45, 0.006), M_WARM, rot=(math.pi/2, 0, 0))
plane("ReflSign", 0.12, 0.40, (-0.10, -0.62, 0.006),
      mat("MAT_ReflSign", (1,1,1), 0.1, 0.6, emit=(1.0, 0.30, 0.45), es=0.9),
      rot=(math.pi/2, 0, 0))
# ── #6 前景遮挡：一把撑开的伞（近景，微微入画）──
cyl("FgUmbPole", 0.012, 0.85, (-1.35, -1.35, 0.85), M_DARK, rot=(0.16, -0.10, 0))
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.42, location=(-1.30, -1.32, 1.22),
                                     segments=24, ring_count=12)
fu = bpy.context.active_object; fu.name = "FgUmbrella"
fu.scale = (1.0, 1.0, 0.55)
fu.data.materials.append(M_UMB)
bev(fu, 0.01)
cyl("FgUmbTip", 0.008, 0.10, (-1.30, -1.32, 1.48), M_DARK)

# ── 便利店主体 ──────────────────────────────────────────────
BX, BY = -0.02, 0.62
BW, BD, BH = 2.0, 0.98, 1.95
box("Body", (BW, BD, BH), (BX, BY, BH/2), M_WALL)
box("Cornice", (BW+0.05, BD+0.05, 0.06), (BX, BY, BH+0.03), M_TRIM)
plane("FloorIn", BW-0.12, BD-0.14, (BX, BY, 0.012), M_FLOOR)
FX = BY - BD/2 - 0.005
box("GlassL", (1.06, 0.02, 1.12), (BX-0.52, FX, 1.06), M_GLASS)
box("GlassR", (0.02, 0.55, 1.12), (BX+0.94, FX-0.02, 1.06), M_GLASS)
box("FrT", (1.16, 0.035, 0.05), (BX-0.52, FX+0.01, 1.66), M_TRIM)
box("FrB", (1.16, 0.035, 0.05), (BX-0.52, FX+0.01, 0.47), M_TRIM)
box("WallR", (0.30, 0.02, 1.35), (BX+0.85, FX, 0.72), M_WALL)
box("OBJ_DoorL", (0.26, 0.022, 1.14), (-0.14, FX-0.01, 1.06), M_DOOR)
box("OBJ_DoorR", (0.26, 0.022, 1.14), (0.13, FX-0.01, 1.06), M_DOOR)
box("DFr", (0.60, 0.04, 0.05), (0.0, FX, 1.665), M_TRIM)
box("Awning", (BW+0.36, 0.36, 0.045), (BX, BY-BD/2-0.16, 1.78), M_TRIM)
box("AwningE", (BW+0.36, 0.02, 0.075), (BX, BY-BD/2-0.33, 1.77), M_WARM)
box("MAT_Sign", (1.55, 0.13, 0.30), (BX, BY+0.03, 2.22), M_SIGN)
box("MAT_Sign2", (0.52, 0.05, 0.11), (BX-0.72, BY-0.32, 1.96), M_SIGN2)
cyl("SPole", 0.016, 1.15, (0.86, -0.30, 0.60), M_POLE)
box("MAT_Vend", (0.30, 0.05, 0.40), (0.86, -0.30, 1.32), M_VEND)
box("Mat", (0.68, 0.32, 0.012), (0.0, FX-0.20, 0.03), M_DARK)

# ── 店内 ────────────────────────────────────────────────────
box("MAT_Warm", (0.62, 0.10, 0.025), (BX-0.5, BY+0.05, 1.86), M_WARM)
box("MAT_Warm", (0.62, 0.10, 0.025), (BX+0.42, BY+0.05, 1.86), M_WARM)
box("DCase", (1.0, 0.16, 1.35), (BX-0.35, BY+0.40, 0.72), M_WHITE)
box("MAT_Warm", (0.9, 0.02, 1.05), (BX-0.35, BY+0.31, 0.74), M_WARM)
for i in range(10):
    box(f"Btl{i}", (0.045, 0.06, 0.13), (BX-0.72+i*0.082, BY+0.30,
        0.42 + (i % 3)*0.30), [M_VEND, M_SIGN2, M_ZEBRA, M_UMB][i % 4])
for r, gy in enumerate([0.34, 0.60]):
    box(f"Shelf{r}", (0.80, 0.22, 0.05), (BX-0.45, gy, 0.42), M_WHITE)
    box(f"ShelfB{r}", (0.80, 0.02, 0.62), (BX-0.45, gy+0.10, 0.72), M_WHITE)
    box("MAT_Band", (0.72, 0.05, 0.10), (BX-0.45, gy-0.06, 0.60), M_BAND)
    box("MAT_Band", (0.72, 0.05, 0.10), (BX-0.45, gy-0.06, 0.86), M_BAND)
box("Bento", (0.16, 0.5, 0.85), (BX-0.90, BY-0.10, 0.46), M_WHITE)
box("MAT_Band", (0.04, 0.4, 0.08), (BX-0.80, BY-0.10, 0.55), M_BAND)
box("Cnt", (0.52, 0.28, 0.40), (BX+0.62, BY-0.28, 0.23), M_WALL)
box("CntT", (0.56, 0.32, 0.025), (BX+0.62, BY-0.28, 0.45), M_TRIM)
box("Cof", (0.09, 0.11, 0.22), (BX+0.52, BY-0.28, 0.57), M_DARK)
cyl("Oden", 0.065, 0.13, (BX+0.30, BY-0.28, 0.53), M_METAL, verts=14)
box("MAT_Band", (0.08, 0.08, 0.04), (BX+0.30, BY-0.28, 0.62), M_WARM)
box("Mag", (0.05, 0.44, 0.55), (BX-0.94, BY-0.42, 0.33), M_WHITE)
box("MAT_Band", (0.02, 0.36, 0.07), (BX-0.905, BY-0.42, 0.45), M_BAND)
box("Pst1", (0.15, 0.006, 0.20), (BX-0.62, FX+0.015, 1.32), M_VEND)
box("Pst2", (0.15, 0.006, 0.20), (BX-0.40, FX+0.015, 1.32), M_SIGN2)
box("BDoor", (0.02, 0.32, 0.95), (BX+BW/2-0.012, BY+0.25, 0.52), M_FLOOR)

# ── 街角 ────────────────────────────────────────────────────
for i, (vx, vm) in enumerate([(1.02, M_SIGN2), (1.16, M_VEND)]):
    box(f"VBody{i}", (0.13, 0.40, 0.92), (vx, 0.05, 0.50), M_DARK)
    box("MAT_Vend", (0.012, 0.32, 0.66), (vx-0.07, 0.05, 0.55), vm)
    box(f"VTop{i}", (0.04, 0.38, 0.05), (vx, 0.05, 0.985), M_DARK)
cyl("UmbSt", 0.032, 0.22, (-0.48, -0.26, 0.13), M_POLE, verts=12)
for i in range(3):
    cyl(f"Umb{i}", 0.007, 0.40, (-0.485+i*0.012, -0.255+i*0.012, 0.28),
        [M_UMB, M_POLE, M_GRN][i], rot=(0.05, 0.04, 0), verts=8)
cyl("Trash", 0.07, 0.40, (0.60, -0.26, 0.22), M_GRN, verts=14)
cyl("TrashL", 0.076, 0.02, (0.60, -0.26, 0.43), M_DARK, verts=14)
bw = (0.55, -0.24)
for dx in (-0.16, 0.16):
    cyl(f"BWh{dx}", 0.088, 0.014, (bw[0]+dx, bw[1], 0.088), M_DARK,
        rot=(0, math.pi/2, 0), verts=14)
box("BFr", (0.30, 0.014, 0.02), (bw[0], bw[1], 0.135), M_POLE, rot=(0, 0, 0.1))
box("BBr", (0.02, 0.20, 0.02), (bw[0]+0.17, bw[1], 0.21), M_POLE)
box("BSt", (0.07, 0.02, 0.02), (bw[0]-0.09, bw[1], 0.20), M_DARK)
box("AC", (0.15, 0.26, 0.30), (BX+BW/2+0.09, BY+0.40, 1.52), M_WALL)
box("ACb", (0.17, 0.02, 0.02), (BX+BW/2+0.09, BY+0.26, 1.38), M_POLE)
box("Brd", (0.014, 0.40, 0.32), (BX-BW/2-0.006, BY-0.48, 1.22), M_TRIM)
box("MAT_Band", (0.006, 0.30, 0.10), (BX-BW/2-0.014, BY-0.48, 1.22), M_BAND)
for i, lx in enumerate([-1.06, 1.10]):
    cyl(f"LP{i}", 0.02, 1.5, (lx, -1.08, 0.75), M_POLE, verts=12)
    box(f"LA{i}", (0.24, 0.02, 0.02), (lx+0.12*(1 if i else -1), -1.08, 1.48), M_POLE)
    box(f"LH{i}", (0.11, 0.05, 0.03), (lx+0.22*(1 if i else -1), -1.08, 1.46), M_WARM)
cyl("WP", 0.026, 1.65, (1.10, -1.10, 0.83), M_WALL, verts=12)
box("WPc", (0.26, 0.02, 0.02), (1.10, -1.10, 1.58), M_WALL)
for s in range(6):
    t0, t1 = s/6, (s+1)/6
    x0 = 1.10 + (-2.4)*t0
    x1 = 1.10 + (-2.4)*(t1)
    box(f"Wr{s}", (abs(x1-x0), 0.006, 0.005), ((x0+x1)/2, -1.10,
        1.56 - 0.05*math.sin(math.pi*(t0+t1)/2)), M_DARK)
box("TLB", (0.06, 0.055, 0.18), (0.88, -1.10, 1.24), M_DARK)
box("OBJ_TL_Red", (0.04, 0.012, 0.04), (0.88, -1.07, 1.29), M_VEND)
box("OBJ_TL_Green", (0.04, 0.012, 0.04), (0.88, -1.07, 1.19), M_DARK)
box("RS", (0.16, 0.008, 0.09), (-1.02, -1.05, 1.30), M_ZEBRA)
for i in range(4):
    cyl(f"RL{i}", 0.007, 0.26, (1.17, -0.30-i*0.14, 0.15), M_POLE, verts=8)
box("RLb", (0.01, 0.48, 0.014), (1.17, -0.51, 0.27), M_POLE)

# ── 灯光 ────────────────────────────────────────────────────
S.world = bpy.data.worlds.new("N")
S.world.use_nodes = True
bg = S.world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.006, 0.008, 0.018, 1)
bg.inputs[1].default_value = 1.0

def light(name, tp, loc, e, c, size=0.4):
    d = bpy.data.lights.new(name, tp); d.energy = e; d.color = c
    if tp == 'AREA':
        d.size = size
    o = bpy.data.objects.new(name, d); o.location = loc
    bpy.context.collection.objects.link(o)

light("W1", 'AREA', (BX-0.5, BY+0.05, 1.83), 85, (1.0, 0.76, 0.46), 0.6)
light("W2", 'AREA', (BX+0.45, BY+0.05, 1.83), 85, (1.0, 0.76, 0.46), 0.6)
light("W3", 'AREA', (BX, BY-0.25, 1.55), 18, (1.0, 0.80, 0.55), 0.8)
light("Sign", 'POINT', (BX, BY-0.25, 2.15), 18, (1.0, 0.45, 0.55))
light("Vend", 'POINT', (1.09, -0.15, 0.65), 8, (0.7, 0.75, 1.0))
light("Lmp", 'POINT', (1.28, -1.08, 1.42), 12, (1.0, 0.72, 0.40))
light("Fill", 'AREA', (0.30, -2.60, 1.75), 14, (0.55, 0.62, 0.85), 2.2)
md = bpy.data.lights.new("Moon", 'SUN'); md.energy = 0.25
md.color = (0.55, 0.66, 0.95)
mo = bpy.data.objects.new("Moon", md)
mo.rotation_euler = (math.radians(55), 0, math.radians(-25))
bpy.context.collection.objects.link(mo)

# ── 相机 ────────────────────────────────────────────────────
cam_d = bpy.data.cameras.new("C"); cam = bpy.data.objects.new("C", cam_d)
bpy.context.collection.objects.link(cam)
cam.location = (2.75, -2.75, 2.55)
cam_d.lens = 38
tgt = bpy.data.objects.new("T", None); tgt.location = (-0.15, 0.25, 0.65)
bpy.context.collection.objects.link(tgt)
c = cam.constraints.new('TRACK_TO'); c.target = tgt
c.track_axis = 'TRACK_NEGATIVE_Z'; c.up_axis = 'UP_Y'
S.camera = cam

# ── 渲染设置（EEVEE + Freestyle）────────────────────────────
S.render.engine = 'BLENDER_EEVEE'
S.render.resolution_x = 1440
S.render.resolution_y = 1080
S.eevee.taa_render_samples = 64
vl = S.view_layers[0]
S.render.use_freestyle = True    # W-路径：三渲二线条
_lstyle = bpy.data.linestyles.get("LS2") or bpy.data.linestyles.new("LS2")
_lstyle.thickness = 1.6
_lstyle.color = (0.07, 0.08, 0.13)
_ls = vl.freestyle_settings.linesets[0]
_ls.linestyle = _lstyle

# ── 场景 JSON 导出 ──────────────────────────────────────────
import json as _json
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
WEB = Path(__file__).parent / "konbini_web"
WEB.mkdir(exist_ok=True)
(WEB / "scene.json").write_text(_json.dumps(out_objs, ensure_ascii=False), encoding='utf-8')
print("[konbini] v2 objects:", len(out_objs))


# ── turntable 视频输出（EEVEE 全渲染能力：GI/辉光/柔影）──────
import os as _os
if _os.environ.get("KONBINI_TURNTABLE"):
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_EEVEE'
    sc.eevee.taa_render_samples = 48
    sc.render.resolution_x = 1280
    sc.render.resolution_y = 720
    sc.render.fps = 24
    sc.frame_start = 1
    sc.frame_end = 144                     # 6 秒 @24fps
    sc.render.image_settings.file_format = 'PNG'
    fr = Path(__file__).parent / "konbini_frames"
    fr.mkdir(exist_ok=True)
    sc.render.filepath = str(fr / "fr_")
    # compositor 辉光（5.2 API 兼容尝试——失败不阻塞帧渲染）
    try:
        sc.use_nodes = True
        nt = sc.node_tree
        nt.nodes.clear()
        rl = nt.nodes.new("CompositorNodeRLayers")
        gl = nt.nodes.new("CompositorNodeGlare")
        gl.glare_type = 'BLOOM'
        gl.threshold = 0.9
        gl.size = 8
        gl.mix = -0.6
        comp = nt.nodes.new("CompositorNodeComposite")
        nt.links.new(rl.outputs["Image"], gl.inputs["Image"])
        nt.links.new(gl.outputs["Image"], comp.inputs["Image"])
        print("[konbini] compositor bloom OK")
    except Exception as _ce:
        print("[konbini] compositor skip:", repr(_ce)[:120])
    # 相机绕 target 环绕（摇摆 210°）
    tgt_loc = (-0.05, 0.10, 0.55)
    import math as _m
    def drive():
        f = sc.frame_current
        ang = _m.radians(-105 + 210 * (f - 1) / 143)     # -105° → +105°
        rad = 3.35
        cam.location = (tgt_loc[0] + rad * _m.sin(ang),
                        tgt_loc[1] - rad * _m.cos(ang),
                        1.55 + 0.35 * _m.sin(_m.radians(f / 143 * 180)))
        d = cam.location - __import__("mathutils").Vector(tgt_loc)
        cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    bpy.app.handlers.frame_change_pre.append(lambda s, _: drive())
    sc.frame_set(1); drive()
    bpy.ops.render.render(animation=True)
    print("[konbini] turntable done:", sc.render.filepath)
