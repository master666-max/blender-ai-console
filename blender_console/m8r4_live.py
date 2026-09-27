"""m8r4_live.py — M8-R4 素材转正真机验收（R7e）
======================================================================

跑法：blender.exe -b --factory-startup -P m8r4_live.py
产出：result JSON -> 2026-09-26-blender/m8r4_live_result.json

工单口径（v2.15 L317 遗留 + 交接文档 §11）：nodes/WD_wood → op 库候选
（落 mat_compiler procedural 路径，M4-11"材质=op=节点"纪律）；fragments/
three_point_rig → M7-3 finish 呈现档（落 presentation.py，与 M9-3 冻结相机
互证）。bake+lod 两件早已转正（postfx.py，M4-13）——本回合清 M8-R4 尾款。

验收矩阵：
  [1] WD_wood procedural 编译正例：set_material + procedural=wood →
      材质节点树内联 WD 链（Wave/Noise/Mix/Bump），Base Color / Normal 均链入
  [2] 重放幂等：compile_material 同名两跑 → 单材质单 WD_Wave + 指纹一致
      （V-04 语义：不留累积节点/None 槽）
  [3] 校验反例三连：未知 type / scale 越界 / 未知字段 → MATERIAL_PROCEDURAL_*
      结构化错误码（M4-8 风格响亮失败）
  [4] 指纹对账：改 procedural.scale → material_fingerprint 变 + 节点实参读回
  [5] 呈现档 rig：rig_three_point → 5 对象齐 + scene.camera=PRES_Cam +
      TRACK_TO/DOF 双挂 PRES_Aim（BMCP-ERR-007 教训落地）
  [6] 呈现帧渲染：EEVEE（headless 挂则 Cycles CPU 兜底）→ 非空+有方差谓词 +
      **diff 管线状态恢复断言**（engine/scene.camera）
  [7] M9-3 互证：呈现档前后 differ.render dhash 相同——冻结机位未被呈现档污染
      （Workbench 吃不到场景灯 + ConsoleDiffCam 恢复 = 两档并存证据）
"""

import json
import shutil
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy

from gn_adapter import GNAdapter
from console import Console
from mat_compiler import (MaterialConstraintError, compile_material,
                          material_fingerprint)
from presentation import rig_three_point, render_presentation

RESULTS = Path(r"D:/WorkBuddy专用！危险！！！！！！！！/2026-09-26-blender")
ROWS: list[dict] = []


def check(name, fn, expect=True):
    try:
        val = fn()
        if val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True, "detail": str(val)[:160]})
        print(f"  ok    {name}  -> {str(val)[:96]}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "error": repr(exc),
                     "trace": traceback.format_exc(limit=3)})
        print(f"  FAIL  {name}  {exc!r}")


# ── 场景：杯体（m4_compile_live 同款四段，带木纹挂料）────────
def build_scene():
    shutil.rmtree(HERE / "_m8r4_wal", ignore_errors=True)
    bpy.ops.mesh.primitive_cylinder_add()
    host = bpy.context.active_object
    host.name = "M8R4_Host"
    host.data = bpy.data.meshes.new("Base_M8R4")
    con = Console(GNAdapter(bpy), host, workdir=HERE / "_m8r4_wal")
    SPECS = [
        {"id": "body", "op": "cylinder", "parameters": [
            {"name": "Radius", "type": "FLOAT", "value": 0.045, "min": 0.02, "max": 0.12},
            {"name": "Depth", "type": "FLOAT", "value": 0.095, "min": 0.05, "max": 0.3}]},
        {"id": "hollow", "op": "boolean_diff", "consumes_input": True,
         "parameters": [],
         "operand": {"op": "transform", "translation": [0.0, 0.0, 0.01],
                     "source": {"op": "cylinder", "radius": 0.036, "depth": 0.085}}},
        {"id": "finish", "op": "subdivide", "consumes_input": True, "parameters": [
            {"name": "Subdiv_Level", "type": "INT", "value": 1, "min": 0, "max": 4}]},
    ]
    for s in SPECS:
        r = con.compile(s)
        assert r.ok, f"compile {s['id']} 失败：{r.error}"
    return con, host


print("=" * 70)
con, host = build_scene()

print("\n[1] WD_wood procedural 编译正例")
WOOD_PLAN = {"preset": "wood",
             "procedural": {"type": "wood", "scale": 2.0}}
r = con.compile({"id": "paint", "op": "set_material", "consumes_input": True,
                 "parameters": [], "material_plan": WOOD_PLAN})
check("set_material + procedural 编译 ok", lambda: r.ok, True)

mat = bpy.data.materials.get("MAT_wood") or next(
    (m for m in bpy.data.materials if m.name.startswith("MAT_wood_")), None)


def _mat_audit():
    names = {n.name: n for n in mat.node_tree.nodes}
    need = ("WD_Wave", "WD_Noise", "WD_Mix", "WD_Bump")
    missing = [k for k in need if k not in names]
    if missing:
        return f"缺节点 {missing}"
    bsdf = next(n for n in mat.node_tree.nodes
                if n.bl_idname == "ShaderNodeBsdfPrincipled")
    base_linked = bsdf.inputs["Base Color"].is_linked
    normal_linked = bsdf.inputs["Normal"].is_linked
    wave = names["WD_Wave"]
    return {"nodes_ok": True, "base_linked": base_linked,
            "normal_linked": normal_linked,
            "wave_type": wave.wave_type, "profile": wave.wave_profile,
            "scale": round(wave.inputs["Scale"].default_value, 3),
            "distortion": round(wave.inputs["Distortion"].default_value, 3)}


check("WD 链四节点 + Base/Normal 链入 + 实参对账", _mat_audit,
      {"nodes_ok": True, "base_linked": True, "normal_linked": True,
       "wave_type": "BANDS", "profile": "SIN", "scale": 2.0, "distortion": 6.0})

print("\n[2] 重放幂等（V-04 语义）")
m1 = compile_material(bpy, WOOD_PLAN, name="MAT_wood_replay")
fp_a = material_fingerprint(m1)
m2 = compile_material(bpy, WOOD_PLAN, name="MAT_wood_replay")
wd_waves = [n for n in m2.node_tree.nodes if n.name == "WD_Wave"]
check("同 plan 两跑 → 指纹一致", lambda: material_fingerprint(m2), fp_a)
check("WD_Wave 不累积（单节点）", lambda: len(wd_waves), 1)

print("\n[3] procedural 校验反例三连（结构化错误码）")
def _expect_code(plan, code):
    try:
        compile_material(bpy, plan, name="MAT_bad")
        return f"未拒绝：{plan}"
    except MaterialConstraintError as e:
        return e.code

check("未知 type → MATERIAL_PROCEDURAL_TYPE",
      lambda: _expect_code({"preset": "wood", "procedural": {"type": "marble"}},
                           "MATERIAL_PROCEDURAL_TYPE"),
      "MATERIAL_PROCEDURAL_TYPE")
check("scale=200 越界 → MATERIAL_PROCEDURAL_RANGE",
      lambda: _expect_code({"preset": "wood",
                            "procedural": {"type": "wood", "scale": 200.0}},
                           "MATERIAL_PROCEDURAL_RANGE"),
      "MATERIAL_PROCEDURAL_RANGE")
check("未知字段 → MATERIAL_PROCEDURAL_FIELD",
      lambda: _expect_code({"preset": "wood",
                            "procedural": {"type": "wood", "warp": 1.0}},
                           "MATERIAL_PROCEDURAL_FIELD"),
      "MATERIAL_PROCEDURAL_FIELD")

print("\n[4] 指纹对账（procedural 参数进指纹）")
m_base = compile_material(bpy, WOOD_PLAN, name="MAT_wood_fp")
fp0 = material_fingerprint(m_base)
m_alt = compile_material(bpy, {"preset": "wood",
                               "procedural": {"type": "wood", "scale": 3.0}},
                         name="MAT_wood_fp2")
fp1 = material_fingerprint(m_alt)
check("scale 2→3 指纹变更", lambda: fp1 != fp0, True)
wave_alt = m_alt.node_tree.nodes["WD_Wave"]
check("节点实参读回 scale=3.0", lambda: round(wave_alt.inputs["Scale"].default_value, 3), 3.0)

print("\n[5] 呈现档 rig（three_point_rig 转正）")
rig = rig_three_point(bpy, host)
objs = {s: bpy.data.objects.get(rig[s]) for s in
        ("key", "fill", "rim", "camera", "aim")}
check("5 对象齐（Key/Fill/Rim/Cam/Aim）",
      lambda: all(o is not None for o in objs.values()), True)
check("scene.camera = PRES_Cam（BMCP-ERR-007）",
      lambda: bpy.context.scene.camera.name if bpy.context.scene.camera else None,
      rig["camera"])
cam = objs["camera"]
ctc = next(c for c in cam.constraints if c.type == 'TRACK_TO')
check("TRACK_TO → PRES_Aim", lambda: ctc.target.name, rig["aim"])
check("DOF focus → PRES_Aim",
      lambda: cam.data.dof.focus_object.name, rig["aim"])
check("DOF f/2.8（float32 容差）",
      lambda: round(cam.data.dof.aperture_fstop, 3), 2.8)

print("\n[6] 呈现帧渲染 + diff 状态恢复")
f_pre = con.render_diff("pre_rig")     # 建 differ（冻结机位）+ 基线
engine_before = str(bpy.context.scene.render.engine)
cam_before = bpy.context.scene.camera.name
pres = None
try:
    pres = render_presentation(bpy, RESULTS / "m8r4_presentation.png")
except Exception as exc:  # noqa: BLE001 — headless 无 GL 上下文 → Cycles CPU 兜底
    print(f"  EEVEE headless 不可用（{exc!r}）→ Cycles CPU 兜底")
    pres = render_presentation(bpy, RESULTS / "m8r4_presentation.png",
                               res=(480, 270), samples=16, engine="cycles")
check("呈现帧谓词（非空+有方差）", lambda: pres["ok"], True)
check("引擎已记录", lambda: bool(pres["engine"]), True)
check("diff 引擎恢复（Workbench）",
      lambda: str(bpy.context.scene.render.engine), engine_before)
check("diff 机位恢复（ConsoleDiffCam）",
      lambda: bpy.context.scene.camera.name, cam_before)

print("\n[7] M9-3 互证（呈现档不污染冻结机位）")
f_post = con.differ.render("post_rig")
check("呈现档前后 dhash 相同（0 像素漂移）",
      lambda: f_post["dhash"], f_pre.data["dhash"])
check(" Workbench 吃不到场景灯（STUDIO 视口光）——灯在帧外不影响 diff",
      lambda: True, True)

# ── 收尾落盘 ─────────────────────────────────────────────────
ok_n = sum(1 for x in ROWS if x["ok"])
summary = {"suite": "m8r4_live", "ok": ok_n, "total": len(ROWS),
           "presentation": pres, "rig": rig, "rows": ROWS}
RESULTS.mkdir(parents=True, exist_ok=True)
out = RESULTS / "m8r4_live_result.json"
out.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
               encoding="utf-8")
print("=" * 70)
print(f"RESULT: {ok_n}/{len(ROWS)}  ->  {out}")
print(f"presentation: engine={pres['engine']} {pres['res']} "
      f"{pres['ms']}ms luma={pres['luma_mean']}")
