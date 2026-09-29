"""build_via_mcp.py — 通过 BlenderMCP 桥在持久会话中构建雨夜便利店
================================================================================
流程：读 konbini_build.py 源码 → execute_code 注入（建模+光照+scene.json 导出）
→ 逐机位渲染 → save_blend。此后该 .blend 可随时打开继续。
"""
import json
from pathlib import Path
from mcp_bridge import bl_call, bl_exec

HERE = Path(__file__).resolve().parent
SRC = HERE / "konbini_build.py"
build_src = (SRC).read_text(encoding="utf-8")

# 会话内执行：全量建模 + 光照 + scene.json 导出（konbini_web/）
prelude = ("import sys\nsys.path.insert(0, r'%s')\n__file__ = r'%s'\n"
           % (str(HERE), str(SRC)))
r = bl_exec(prelude + build_src, timeout=240)
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
    print("[shot]", name)
print("SHOTS_DONE")
""".replace("%OUT%", str(HERE / "konbini_shots")).replace(
    "%SHOTS%", json.dumps(SHOTS).replace("[", "(").replace("]", ")"))

r = bl_exec(shot_code, timeout=600)
print("[mcp] shots:", json.dumps(r, ensure_ascii=False)[:200])

r = bl_call({"type": "save_blend",
             "params": {"path": str(HERE / "konbini_session.blend")}})
print("[mcp] save:", json.dumps(r, ensure_ascii=False)[:120])
