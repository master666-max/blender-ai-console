"""m411_live.py — M4-11 材质编译真机验收（Blender 5.2.1）。

跑法：blender --background --factory-startup --python m411_live.py

核心约束（EXP-006）：材质编译进节点树（GeometryNodeSetMaterial 引用
mat_compiler 产物），禁走 bpy 材质槽——重编译随段落重建引用，结构性
免疫槽位静默丢失。

验收项（全机械，B1 纪律，改动-对照闭环）：
  1. 正例：三段马克杯（body → hollow → glaze[set_material]），材质节点树
     在场 + Principled 参数与 plan 对账（surface 覆盖生效）
  2. 物理约束反例：IOR/Metallic 越界、未知 preset、未知 surface 字段、
     缺 material_plan ——全部编译期响亮失败（M4-8 结构化错误）
  3. 幂等：同 plan 编译两次 → 同名材质（无 .001）+ 指纹一致
  4. EXP-006 免疫验证（破坏-重建对照）：删材质 datablock →
     compile_material 重建同指纹材质 → 新段 Set_Material 引用恢复
  5. verifier + 渲染 sanity
"""
import base64
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy

from gn_adapter import GNAdapter
from console import Console
from op_compiler import spec_field_whitelist
from mat_compiler import compile_material, material_fingerprint

OUT = Path(r"D:\WorkBuddy专用！危险！！！！！！！！\2026-09-26-blender")
ROWS: list[dict] = []


def check(name, fn, expect=None):
    try:
        val = fn()
        if expect is not None and val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True, "detail": str(val)[:140]})
        print(f"  PASS  {name}  {val}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:200]})
        print(f"  FAIL  {name}  {exc!r}")


print(f"Blender {bpy.app.version_string}")
ad = GNAdapter(bpy)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.active_object
obj.name = "Mug"
obj.data = bpy.data.meshes.new("Base")

shutil.rmtree(HERE / "_m411_wal", ignore_errors=True)
con = Console(ad, obj, workdir=HERE / "_m411_wal")

CERAMIC = {"preset": "ceramic", "surface": {"roughness": 0.2}}

SPECS = [
    {"id": "body", "op": "cylinder", "consumes_input": False,
     "parameters": [
         {"name": "Radius", "type": "FLOAT", "value": 0.04, "min": 0.02, "max": 0.12},
         {"name": "Depth", "type": "FLOAT", "value": 0.095, "min": 0.05, "max": 0.3},
     ]},
    {"id": "hollow", "op": "boolean_diff", "consumes_input": True,
     "parameters": [],
     "operand": {"op": "transform", "translation": [0.0, 0.0, 0.01],
                 "source": {"op": "cylinder", "radius": 0.036, "depth": 0.085}}},
    {"id": "glaze", "op": "set_material", "consumes_input": True,
     "parameters": [],
     "material_plan": CERAMIC},
]

print("\n[1] 正例：三段编译 + 材质节点树在场")
for s in SPECS:
    t0 = time.perf_counter()
    r = con.compile(s)
    ms = (time.perf_counter() - t0) * 1000
    print(f"  compile {s['id']:<7} {ms:6.1f} ms  {'ok' if r.ok else f'FAIL {r.error}'}")
    check(f"编译 {s['id']}（op={s['op']}）", lambda r=r: r.ok, True)

glaze_tree = con.segments["glaze"]["tree"]
set_mat = next((n for n in glaze_tree.nodes
                if n.bl_idname == "GeometryNodeSetMaterial"), None)
check("glaze 树有 Set_Material 节点", lambda: set_mat is not None, True)
mat_ref = set_mat.inputs["Material"].default_value if set_mat else None
check("Set_Material 引用 MAT_ceramic 材质",
      lambda: mat_ref is not None and mat_ref.name.startswith("MAT_ceramic"), True)
mat = bpy.data.materials.get(mat_ref.name)
bsdf = next((n for n in mat.node_tree.nodes
             if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)
check("材质节点树有 Principled BSDF", lambda: bsdf is not None, True)
check("材质节点树有 Output Material",
      lambda: any(n.bl_idname == "ShaderNodeOutputMaterial"
                  for n in mat.node_tree.nodes), True)
check("Roughness 对账（surface 覆盖 0.2 生效）",
      lambda: round(float(bsdf.inputs["Roughness"].default_value), 3), 0.2)
check("Metallic 对账（ceramic=0）",
      lambda: float(bsdf.inputs["Metallic"].default_value), 0.0)
check("IOR 对账（ceramic=1.5）",
      lambda: round(float(bsdf.inputs["IOR"].default_value), 2), 1.5)
coat_sock = next((bsdf.inputs[nm] for nm in ("Coat Weight", "Clearcoat")
                  if nm in bsdf.inputs), None)
check("Coat 层在场（ceramic coat=0.6）",
      lambda: coat_sock is not None and round(float(coat_sock.default_value), 2), 0.6)

print("\n[2] 物理约束反例（编译期响亮失败，M4-8 结构化）")
BAD = [
    ("IOR 越界 3.5", {"id": "bad_ior", "op": "set_material", "consumes_input": True,
                      "parameters": [], "material_plan": {"preset": "ceramic",
                      "surface": {"ior": 3.5}}}, "IOR_RANGE"),
    ("Metallic 越界 1.5", {"id": "bad_metal", "op": "set_material",
                           "consumes_input": True, "parameters": [],
                           "material_plan": {"preset": "ceramic",
                           "surface": {"metallic": 1.5}}}, "METALLIC_RANGE"),
    ("未知 preset", {"id": "bad_preset", "op": "set_material",
                     "consumes_input": True, "parameters": [],
                     "material_plan": {"preset": "unobtanium"}},
     "MATERIAL_PRESET_UNKNOWN"),
    ("未知 surface 字段", {"id": "bad_field", "op": "set_material",
                           "consumes_input": True, "parameters": [],
                           "material_plan": {"preset": "ceramic",
                           "surface": {"sparkle": 1.0}}}, "MATERIAL_SURFACE_FIELD"),
    ("缺 material_plan", {"id": "no_plan", "op": "set_material",
                          "consumes_input": True, "parameters": []},
     "MISSING_MATERIAL_PLAN"),
]
for tag, spec, want_code in BAD:
    def _reject(spec=spec, want_code=want_code):
        # M4-8 契约：编译期拒绝走结构化结果（r.error.error_code），不抛裸异常
        r = con.compile(spec)
        if r.ok:
            return f"未被拒绝（{want_code}）"
        code = (r.error or {}).get("error_code", "")
        return code if code == want_code else f"错误码不符 {code}"
    check(f"反例拒绝：{tag}", _reject, want_code)
check("反例全部零残迹（无新段落注册）", lambda: len(con.segments), 3)

print("\n[3] 幂等：同 plan 两次编译 → 同名材质 + 指纹一致")
m1 = compile_material(bpy, CERAMIC)
fp1 = material_fingerprint(m1)
m2 = compile_material(bpy, CERAMIC)
check("无 .001 去重（同名复用）", lambda: m1.name == m2.name, True)
check("指纹一致（参数重放）", lambda: material_fingerprint(m2), fp1)

print("\n[4] EXP-006 免疫验证（破坏-重建对照）")
victim_name = m1.name
bpy.data.materials.remove(bpy.data.materials[victim_name])
check("破坏：材质 datablock 已删",
      lambda: bpy.data.materials.get(victim_name) is None, None)
m3 = compile_material(bpy, CERAMIC)
check("重建：编译器路径重建同名材质",
      lambda: m3.name == victim_name, True)
check("重建指纹 = 破坏前指纹（确定性产物）",
      lambda: material_fingerprint(m3), fp1)
glaze2 = {"id": "glaze2", "op": "set_material", "consumes_input": True,
          "parameters": [], "material_plan": CERAMIC}
r = con.compile(glaze2)
check("新段编译（删材质后）", lambda: r.ok, True)
sm2 = next((n for n in con.segments["glaze2"]["tree"].nodes
            if n.bl_idname == "GeometryNodeSetMaterial"), None)
check("新段 Set_Material 引用已恢复（重建材质）",
      lambda: sm2 is not None
      and sm2.inputs["Material"].default_value.name == victim_name, True)

print("\n[5] verifier + 渲染 sanity（基线/改动两帧对照）")
v = con.verify("m411")
check("verifier PASS", lambda: v.ok, True)
rd0 = con.render_diff("m411_base")
check("首帧=基线：无 diff 图（基线语义）", lambda: rd0.render_diff_b64, "")
r = con.set_param("body", "Radius", 0.045)
check("set_param body.Radius=0.045", lambda: r.ok, True)
rd1 = con.render_diff("m411_changed")
check("改动帧 diff 出图 >2KB", lambda: len(rd1.render_diff_b64) > 2000, True)
check("diff 图是 PNG", lambda: base64.b64decode(rd1.render_diff_b64)[:4],
      b"\x89PNG")

print("\n[6] plan_schema 白名单联动（单一事实源）")
check("set_material 白名单含 material_plan",
      lambda: "material_plan" in spec_field_whitelist("set_material"), True)
check("set_material 白名单含 source（通用链）",
      lambda: "source" in spec_field_whitelist("set_material"), True)

failed = [r for r in ROWS if not r["ok"]]
print(f"\nM4-11 LIVE: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
out = OUT / "m411_result.json"
out.write_text(json.dumps(ROWS, ensure_ascii=False, indent=1), encoding="utf-8")
print("result ->", out)
sys.exit(1 if failed else 0)
