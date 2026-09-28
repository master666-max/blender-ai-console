"""mug_showcase_live.py — 门面展示图 · 呈现档真机产物（用户验收：旧图棱面杯不过关）

跑法：blender.exe -b --factory-startup -P mug_showcase_live.py
产出：showcase/mug.png（1024² EEVEE，挂了降级 Cycles CPU）
      results/mug_showcase_result.json

旧图问题（用户实测打脸）：M6 AB 帧是 32 边 Workbench 工程帧——棱面刺眼、
把手硬怼、当门面就是砸门面。本脚本用项目自己的呈现管线（M7-3 presentation
rig_three_point + render_presentation）重做：
  * 杯身 128 边 + 真凹腔（boolean EXACT，R7g 教训：刀具体顶面必须穿出外壁）
  * 把手 torus 嵌入外壁 0.04（壁厚 0.08 的一半——穿到内腔会穿帮，贴面不融合会零凹边）
  * bevel 30° 限角倒角（杯口 + 接缝）+ shade smooth
  * 陶瓷白 Principled（Roughness 0.2 + Coat 0.5）+ 地面 + 世界补光
  * 三点布光 key 150 / fill 40 / rim 100 + 50mm f/2.8 浅景深
诚实口径：建模-材质-灯光-渲染全部由本仓库管线在场完成，非外部素材。
"""
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import bpy  # type: ignore[attr-defined]

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from presentation import rig_three_point, render_presentation  # noqa: E402

OUT = ROOT / "showcase" / "mug.png"
RES = (1024, 1024)

# ── 首动作清场（exp3 实锤：此前不持有任何 DG 引用）─────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


def primitive(op, name, **kw):
    op(**kw)
    ob = bpy.context.active_object
    ob.name = name
    return ob


def apply_modifier(ob, name):
    """-b 模式 modifier_apply 的 poll 需要 active object——primitive ops 会抢 active，每次显式设回。"""
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier=name)


# ── [1] 杯身：128 边外壁 + EXACT 凹腔（刀顶穿出外壁顶才掏得空）────────
body = primitive(bpy.ops.mesh.primitive_cylinder_add, "MugBody",
                 vertices=128, radius=0.5, depth=1.1, location=(0, 0, 0))
cutter = primitive(bpy.ops.mesh.primitive_cylinder_add, "MugCavity",
                   vertices=128, radius=0.42, depth=1.0, location=(0, 0, 0.15))
cav = body.modifiers.new("cav", 'BOOLEAN')
cav.operation = 'DIFFERENCE'
cav.solver = 'EXACT'
cav.object = cutter
apply_modifier(body, "cav")
bpy.data.objects.remove(cutter, do_unlink=True)

# ── [2] 把手：torus 立起、嵌入外壁 0.04（壁厚一半；到内腔穿帮，贴面零融合）──
handle = primitive(bpy.ops.mesh.primitive_torus_add, "MugHandle",
                   major_radius=0.30, minor_radius=0.055,
                   major_segments=96, minor_segments=32,
                   location=(0.76, 0, 0.02), rotation=(1.5708, 0, 0))
un = body.modifiers.new("un", 'BOOLEAN')
un.operation = 'UNION'
un.solver = 'EXACT'
un.object = handle
apply_modifier(body, "un")
bpy.data.objects.remove(handle, do_unlink=True)

# ── [3] 30° 限角 bevel（杯口 + 接缝 + 底沿）+ smooth ─────────────────
bev = body.modifiers.new("bev", 'BEVEL')
bev.width = 0.012
bev.segments = 3
bev.limit_method = 'ANGLE'
bev.angle_limit = 0.5236
apply_modifier(body, "bev")
try:
    bpy.ops.object.shade_auto_smooth(angle=0.5236)
except (AttributeError, TypeError):
    bpy.ops.object.shade_smooth()

# ── [4] 材质：陶瓷白 + 地面灰 + 世界补光 ─────────────────────────────
mat = bpy.data.materials.new("Ceramic")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.93, 0.92, 0.90, 1.0)
bsdf.inputs["Roughness"].default_value = 0.32
for coat in ("Coat Weight", "Coating"):
    if coat in bsdf.inputs:
        bsdf.inputs[coat].default_value = 0.8
        break
body.data.materials.append(mat)

bpy.ops.mesh.primitive_plane_add(size=12, location=(0, 0, -0.551))
floor = bpy.context.active_object
fmat = bpy.data.materials.new("Floor")
fmat.use_nodes = True
fb = fmat.node_tree.nodes["Principled BSDF"]
fb.inputs["Base Color"].default_value = (0.13, 0.13, 0.14, 1.0)
fb.inputs["Roughness"].default_value = 0.6
floor.data.materials.append(fmat)

w = bpy.data.worlds.new("ShowWorld")
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.03, 0.03, 0.035, 1.0)
w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
scene.world = w

# AgX 把白瓷压灰——换 Filmic + 中高对比，白瓷的 correct 选择
try:
    scene.view_settings.view_transform = 'Filmic'
    scene.view_settings.look = 'Medium High Contrast'
except TypeError:
    pass

# ── [5] 三点布光 + 50mm f/2.8 + 渲染（EEVEE 挂了退 Cycles CPU）────────
rig = rig_three_point(bpy, body, key_e=300.0, fill_e=25.0, rim_e=500.0,
                      lens=50.0, dof_fstop=2.8)
bpy.context.view_layer.update()
t0 = time.perf_counter()
engine_used = "eevee"
try:
    rep = render_presentation(bpy, OUT, res=RES, samples=64, engine="eevee")
except Exception as e:  # noqa: BLE001
    print(f"EEVEE failed ({type(e).__name__}: {str(e)[:100]}) -> Cycles CPU fallback")
    engine_used = "cycles"
    rep = render_presentation(bpy, OUT, res=RES, samples=64, engine="cycles")
ms = round((time.perf_counter() - t0) * 1000, 1)

n_verts = len(body.data.vertices)
print(f"mug showcase: {engine_used} {RES[0]}x{RES[1]} in {ms}ms · verts={n_verts} · "
      f"preds(not_black={rep.get('not_black')}, has_variance={rep.get('has_variance')})")

out = {"suite": "mug showcase (presentation rig, M7-3)",
       "engine": engine_used, "res": list(RES), "render_ms": ms,
       "verts": n_verts, "rig": rig, "predicates": {k: rep.get(k) for k in ("not_black", "has_variance")},
       "png": str(OUT.relative_to(ROOT))}
(ROOT / "results" / "mug_showcase_result.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("result ->", ROOT / "results" / "mug_showcase_result.json")
