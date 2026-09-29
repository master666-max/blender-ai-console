"""render_core_test.py — 核心渲染管道独立验证（Cornell 体块 × 2 rig × 2 机位）
================================================================================
质量判定（管道维度，与场景内容无关）：
  1 暗部信息（纯黑=失败）
  2 高光层次（焦点面有过渡）
  3 接触阴影（物体贴地有暗环——放置感）
  4 轮廓/形体（倒角软边可见）
运行：blender --background --python render_core_test.py
"""
import bpy, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from render_core import clear_scene, LightRig, CameraRig, RenderCore, test_subject

OUT = HERE / "render_core_shots"
OUT.mkdir(exist_ok=True)

JOBS = [
    ("studio_key", "studio", (2.4, -2.4, 1.9), (0.0, 0.0, 0.55), 40, 900),
    ("night_key",  "night",  (2.4, -2.4, 1.9), (0.0, 0.0, 0.55), 40, 900),
    ("studio_top", "studio", (1.4, -1.4, 3.1), (0.0, 0.0, 0.30), 36, 1100),
    ("night_low",  "night",  (0.9, -2.9, 0.65), (0.0, 0.1, 0.85), 42, 700),
]

for name, style, loc, tgt, lens, key_e in JOBS:
    clear_scene()
    rig = LightRig(style, world_strength=None if style == "studio" else 5.0)
    rig.cfg["key_e"] = key_e
    rig.three_point(target=(0, 0, 0.5))
    CameraRig(loc, tgt, lens)
    RenderCore(res=(1280, 960), samples=48)
    test_subject()
    out = RenderCore.still(OUT / f"{name}.png")
    print("[rc]", name, "→", out)
print("[render_core] test done →", OUT)
