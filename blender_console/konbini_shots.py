"""konbini_shots.py — 多角度动态渲染（5 个电影机位，EEVEE 离线）
================================================================================
机位语言（每张一个叙事）：
  S1 establishing  东南 3/4 俯视——主视觉，街角全貌
  S2 窥视店内      正南低机位贴橱窗——暖光与陈列的特写
  S3 暗巷视角      从左巷黑暗中望向店角——孤独感构图
  S4 展台俯瞰      高空正俯——微缩模型全景（底座为展台）
  S5 招牌仰角      低角度仰拍——霓虹招牌压住雨夜天空
运行：blender --background --python konbini_shots.py
"""
import bpy, math, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SRC = HERE / "konbini_build.py"

# 复用 v3 建模（读源码执行——场景重建）
exec(compile(SRC.read_text(encoding="utf-8"), str(SRC), "exec"))

OUT = HERE / "konbini_shots"
OUT.mkdir(exist_ok=True)
sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE'
sc.eevee.taa_render_samples = 64
sc.render.resolution_x = 1440
sc.render.resolution_y = 1080

# ── 视觉核验清单 #2 修复：环境底光重建（微缩模型摄影 = 高环境 + 焦点）──
w = sc.world.node_tree.nodes["Background"]
w.inputs[1].default_value = 5.0          # 世界底光 ×5：暗部有信息（不再是纯黑虚空）
sun = bpy.data.lights.new("SkyFill", 'SUN')
sun.energy = 0.8; sun.color = (0.45, 0.55, 0.85)
so = bpy.data.objects.new("SkyFill", sun)
so.rotation_euler = (math.radians(50), 0, math.radians(-30))
bpy.context.collection.objects.link(so)
# EEVEE Next 光线追踪 GI + 接触阴影（暗部 bounce/贴地阴影）
try:
    sc.eevee.use_raytracing = True
except Exception:
    pass
for lo in bpy.data.objects:
    if lo.type == 'LIGHT' and hasattr(lo.data, 'use_contact_shadow'):
        lo.data.use_contact_shadow = True

cam = bpy.data.objects["C"]
tgt = bpy.data.objects["T"]

SHOTS = [
    ("S1_establishing", (2.75, -2.75, 2.50), (-0.15, 0.25, 0.65), 35),
    ("S2_peek",         (0.05, -1.75, 1.18), (-0.30, 0.55, 0.75), 42),
    ("S3_alley",        (-1.12, 0.85, 1.35), (0.45, 0.05, 0.85), 30),
    ("S4_diorama",      (1.95, -2.05, 3.35), (0.0, 0.05, 0.10), 33),
    ("S5_sign",         (0.75, -1.95, 0.45), (-0.10, 0.55, 1.95), 38),
]
SHOTS[2] = ("S3_alley", (-1.65, -1.35, 1.45), (0.35, 0.30, 0.80), 32)   # 巷口斜视

for name, loc, tgt_loc, lens in SHOTS:
    cam.location = loc
    tgt.location = tgt_loc
    cam.data.lens = lens
    sc.render.filepath = str(OUT / f"{name}.png")
    bpy.ops.render.render(write_still=True)
    print("[shot]", name)
print("[konbini] 5 shots done →", OUT)
