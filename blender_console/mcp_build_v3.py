"""mcp_build_v3.py — 通过 MCP 桥注入 konbini v3 场景 + 5 机位渲染 + 保存"""
import json
from pathlib import Path
from mcp_bridge import bl_exec, bl_call

HERE = Path(__file__).resolve().parent
scene_src = (HERE / "konbini_v3_scene.py").read_text(encoding="utf-8")

prelude = ("import sys\nsys.path.insert(0, r'%s')\n__file__ = r'%s'\n"
           % (str(HERE), str(HERE / "konbini_v3_scene.py")))

r = bl_exec(prelude + scene_src, timeout=240)
print("[mcp] build:", json.dumps(r, ensure_ascii=False)[:200])

SHOTS = [
    ("S1_establishing", (2.75, -2.75, 2.50), (-0.15, 0.25, 0.65), 35),
    ("S2_peek",         (0.05, -1.75, 1.18), (-0.30, 0.55, 0.75), 42),
    ("S3_alley",        (-1.65, -1.35, 1.45), (0.35, 0.30, 0.80), 32),
    ("S4_diorama",      (1.95, -2.05, 3.35), (0.0, 0.05, 0.10), 33),
    ("S5_sign",         (0.75, -1.95, 0.45), (-0.10, 0.55, 1.95), 38),
]
shot_code = """
import bpy, math
cam = bpy.data.objects["C"]
tgt = bpy.data.objects["T"]
sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE'
sc.eevee.taa_render_samples = 64
sc.render.resolution_x = 1440
sc.render.resolution_y = 1080
out = Path(r"%OUT%")
out.mkdir(exist_ok=True)
for name, loc, tloc, lens in %SHOTS%:
    cam.location = loc
    tgt.location = tloc
    cam.data.lens = lens
    sc.render.filepath = str(out / (name + ".png"))
    bpy.ops.render.render(write_still=True)
print("SHOTS_DONE")
""".replace("%OUT%", str(HERE / "konbini_shots")).replace(
    "%SHOTS%", json.dumps(SHOTS).replace("[", "(").replace("]", ")"))

r = bl_exec(shot_code, timeout=600)
print("[mcp] shots:", json.dumps(r, ensure_ascii=False)[:200])

r = bl_call({"type": "save_blend",
             "params": {"path": str(HERE / "konbini_v3.blend")}})
print("[mcp] save:", json.dumps(r, ensure_ascii=False)[:120])
