"""m412b_live.py — M4-12b console 段落级 rig_json 集成真机验收（R7c）
======================================================================

跑法：blender.exe -b --factory-startup -P m412b_live.py
产出：result JSON -> 2026-09-26-blender/m412b_live_result.json

验收矩阵（v2.15⑥ 登记的"console 段落级集成"闭环）：
  [1] schema 白名单：plan_schema 放行段落级 rig_json（拼错字段仍拦截）
  [2] 正例：几何段落 + rig_json 共存编译——GN 树落栈 + RIG-* 生成 +
      result.data.rig 对账面（metarig/rig/指纹/deform_patched）
  [3] rig 反例走 M4-8 结构化通道：bad parent → RIG_PARENT_UNKNOWN（无半产物落栈）
  [4] rig 变更重编译：同段落改 rig_json → 指纹变更 wipe 重建（reused=False）
  [5] 无 rig 段落回归：不带 rig_json 的 compile 行为不变（data 无 rig 键）
"""

import json
import shutil
import sys
import traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy

from plan_schema import PlanSchema
from gn_adapter import GNAdapter
from console import Console

RESULTS = ROOT.parent / "2026-09-26-blender"
ROWS: list[dict] = []


def check(name, fn, expect=True):
    try:
        val = fn()
        if val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True, "detail": str(val)[:160]})
        print(f"  PASS  {name}  {str(val)[:110]}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:260],
                     "trace": traceback.format_exc(limit=3)})
        print(f"  FAIL  {name}  {exc!r}")


RIG_JSON = {
    "name": "MugRig",
    "bones": [
        {"name": "root",  "head": [0, 0, 0],    "tail": [0, 0, 0.05]},
        {"name": "handle", "head": [0.06, 0, 0.08], "tail": [0.10, 0, 0.02],
         "parent": "root"},
    ],
}

print(f"Blender {bpy.app.version_string}")
bpy.ops.wm.read_factory_settings(use_empty=True)
shutil.rmtree(HERE / "_m412b_wal", ignore_errors=True)
WALDIR = HERE / "_m412b_wal"

ad = GNAdapter(bpy)
bpy.ops.mesh.primitive_cylinder_add()
obj = bpy.context.active_object
obj.name = "MugRigHost"
obj.data = bpy.data.meshes.new("Base_RigHost")
con = Console(ad, obj, workdir=WALDIR)

# ── [1] schema 白名单 ────────────────────────────────────────
print("\n[1] schema 白名单")
issues = PlanSchema().validate({"sections": [
    {"id": "S1", "op": "cylinder", "rig_json": RIG_JSON}]})
check("rig_json 放行（无 UNKNOWN_FIELD）",
      lambda: [str(i) for i in issues if i.code == "UNKNOWN_FIELD"], [])
issues_bad = PlanSchema().validate({"sections": [
    {"id": "S1", "op": "cylinder", "rig_josn_typo": {}}]})
check("拼错字段仍拦截",
      lambda: [i.code for i in issues_bad if i.code == "UNKNOWN_FIELD"],
      ["UNKNOWN_FIELD"])

# ── [2] 正例：几何 + rig_json 共存 ───────────────────────────
print("\n[2] 正例：几何段落 + rig_json 共存")
r = con.compile({"id": "Body", "op": "cylinder",
                 "parameters": [{"name": "radius", "value": 0.04},
                                {"name": "depth", "value": 0.09}],
                 "rig_json": RIG_JSON})
check("compile ok", lambda: r.ok, True)
check("data.rig 对账面",
      lambda: (r.data["rig"]["metarig"], r.data["rig"]["rig"],
               r.data["rig"]["deform_patched"], r.data["rig"]["reused"]),
      ("MugRig", "RIG-MugRig", True, False))
check("RIG 对象在场且为 ARMATURE",
      lambda: (bpy.data.objects.get("RIG-MugRig") is not None
               and bpy.data.objects["RIG-MugRig"].type == "ARMATURE"), True)
check("deform 骨骼已补丁",
      lambda: len([b for b in bpy.data.objects["RIG-MugRig"].data.bones
                   if b.use_deform]), 2)
check("GN 树同时落栈（AI_Body modifier）",
      lambda: any(m.name == "AI_Body" for m in obj.modifiers), True)
check("rec.rig 留档",
      lambda: con.segments["Body"]["rig"]["rig"], "RIG-MugRig")

# ── [3] rig 反例 → M4-8 结构化通道 ───────────────────────────
print("\n[3] rig 反例结构化拒绝")
bad = {**RIG_JSON, "name": "MugRigBad",
       "bones": [{**RIG_JSON["bones"][1], "parent": "ghost"}]}
r2 = con.compile({"id": "BodyBad", "op": "cube", "rig_json": bad})
check("compile ok=False", lambda: r2.ok, False)
check("错误码 RIG_PARENT_UNKNOWN", lambda: r2.error["error_code"], "RIG_PARENT_UNKNOWN")
check("无半产物落栈（AI_BodyBad 不存在）",
      lambda: any(m.name == "AI_BodyBad" for m in obj.modifiers), False)
check("坏 rig 的 RIG-* 不在场",
      lambda: bpy.data.objects.get("RIG-MugRigBad") is None, True)

# ── [4] rig 变更重编译（指纹变更 → wipe 重建；新段落触发——console 的
#      同名段落二次 compile 是既有 step 重复语义，不在本回合 scope）──
print("\n[4] rig 变更重编译")
moved = {**RIG_JSON, "bones": [
    RIG_JSON["bones"][0],
    {**RIG_JSON["bones"][1], "tail": [0.11, 0, 0.02]}]}
r3 = con.compile({"id": "BodyV2", "op": "cylinder",
                  "parameters": [{"name": "radius", "value": 0.04},
                                 {"name": "depth", "value": 0.09}],
                  "rig_json": moved})
check("重编译 ok", lambda: r3.ok, True)
check("指纹变更且 reused=False",
      lambda: (r3.data["rig"]["reused"],
               r3.data["rig"]["fingerprint"] != r.data["rig"]["fingerprint"]),
      (False, True))
check("RIG-MugRig 仍唯一在场（wipe 后重建）",
      lambda: len([o for o in bpy.data.objects if o.name.startswith("RIG-")]), 1)

# ── [5] 无 rig 段落回归 ─────────────────────────────────────
print("\n[5] 无 rig 段落回归")
r4 = con.compile({"id": "Plain", "op": "cube"})
check("无 rig_json 编译 ok", lambda: r4.ok, True)
check("data 无 rig 键", lambda: "rig" in (r4.data or {}), False)

n_ok = sum(1 for x in ROWS if x["ok"])
print(f"\nM4-12b LIVE: {n_ok}/{len(ROWS)} passed")
out = {"suite": "M4-12b console rig_json integration live",
       "passed": n_ok, "total": len(ROWS),
       "blender_version": list(bpy.app.version), "cases": ROWS}
RESULTS.mkdir(exist_ok=True)
(RESULTS / "m412b_live_result.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("result ->", RESULTS / "m412b_live_result.json")
