"""render_diff_live.py — M9-3 渲染 diff 管线真机验收（Blender 5.2.1 headless）。

跑法：blender --background --factory-startup --python render_diff_live.py

验收项（全部机械断言，B1 纪律）：
  1. 基线帧：谓词全过 / diff 为空 / 目标占比合理 / dHash 是 64bit
  2. 确定性：无变化重渲 → changed_px=0、hamming=0（probe_render 已证 0 像素差）
  3. 稳态性能：<500ms/帧（首帧 GL 冷启动单列）
  4. 敏感性：改把手粗细 → 像素变化 >1%、diff 图非空且是 PNG
  5. 哈希转移谓词：几何已变 → ok（hamming 记录供 EXP-4）
  6. dHash 分离度（EXP-4 证据）：大改（半径 0.04→0.075）→ hamming ≥4
  7. B1 机械反驳信号：同值重写 → 零变化 → refutable_assumption 触发
"""
import base64
import json
import shutil
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy

from gn_adapter import GNAdapter
from console import Console
from render_diff import RenderDiffer

OUT = ROOT / "results"
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

shutil.rmtree(HERE / "_render_wal", ignore_errors=True)
con = Console(ad, obj, workdir=HERE / "_render_wal")
con.add_thought("T1", "把手粗 8mm 握感舒适",
                {"segment": "handle", "param": "Handle_Thickness"})

# ── 编译两段（与 console_live 同构）──────────────────────────
spec_body = {"id": "body", "op": "revolve_profile", "consumes_input": False,
             "parameters": [{"name": "Body_Radius", "type": "FLOAT", "value": 0.04},
                            {"name": "Body_Depth", "type": "FLOAT", "value": 0.095}]}
def _build_body(ad, tree, sid):
    gi = ad.add_node(tree, "NodeGroupInput"); go = ad.add_node(tree, "NodeGroupOutput")
    cyl = ad.add_node(tree, "GeometryNodeMeshCylinder")
    sm = ad.add_node(tree, "GeometryNodeSetShadeSmooth")
    ad.link(tree, gi, "Body_Radius", cyl, "Radius")
    ad.link(tree, gi, "Body_Depth", cyl, "Depth")
    ad.link(tree, cyl, "Mesh", sm, "Mesh"); ad.link(tree, sm, "Mesh", go, "Geometry")
spec_body["_build"] = _build_body

spec_handle = {"id": "handle", "op": "sweep_rounded_rect", "consumes_input": True,
               "parameters": [{"name": "Handle_Thickness", "type": "FLOAT", "value": 0.008}]}
def _build_handle(ad, tree, sid):
    gi = ad.add_node(tree, "NodeGroupInput"); go = ad.add_node(tree, "NodeGroupOutput")
    ring = ad.add_node(tree, "GeometryNodeCurvePrimitiveCircle")
    ring.inputs["Radius"].default_value = 0.032   # 不接=默认 1.0m → 2 米巨环（M9-3 首战抓到的荒谬几何）
    prof = ad.add_node(tree, "GeometryNodeCurvePrimitiveCircle")
    sweep = ad.add_node(tree, "GeometryNodeCurveToMesh")
    xf = ad.add_node(tree, "GeometryNodeTransform")
    xf.inputs["Translation"].default_value = (0.062, 0.0, 0.045)
    join = ad.add_node(tree, "GeometryNodeJoinGeometry")
    ad.link(tree, gi, "Handle_Thickness", prof, "Radius")
    ad.link(tree, ring, "Curve", sweep, "Curve")
    ad.link(tree, prof, "Curve", sweep, "Profile Curve")
    ad.link(tree, sweep, "Mesh", xf, "Geometry")
    ad.link(tree, xf, "Geometry", join, "Geometry")
    ad.link(tree, gi, "Incoming_Geometry", join, "Geometry")
    ad.link(tree, join, "Geometry", go, "Geometry")
spec_handle["_build"] = _build_handle

r1 = con.compile(spec_body)
r2 = con.compile(spec_handle)
check("编译两段", lambda: r1.ok and r2.ok, True)

# ── [1] 基线帧 ───────────────────────────────────────────────
print("\n[1] 基线帧")
f0 = con.render_diff("初始")
print("  baseline preds:", f0.data["predicates"])
check("基线帧：谓词全过", lambda: RenderDiffer.ok(f0.data["predicates"]), True)
check("基线帧：diff 为空（基线语义）", lambda: f0.render_diff_b64, "")
check("基线帧：目标占比 >2%", lambda: f0.data["opaque_ratio"] > 0.02, True)
check("基线帧：dHash 64bit", lambda: 0 <= f0.data["dhash"] < 2 ** 64, True)
check("基线帧：ok=True", lambda: f0.ok, True)
print(f"  cold start = {con.differ.cold_start_ms} ms（GL 初始化，一次性）")

# ── [2] 确定性 ───────────────────────────────────────────────
print("\n[2] 确定性（无变化重渲）")
f1 = con.render_diff("无变化")
check("无变化：changed_px == 0", lambda: f1.data["changed_px"], 0)
check("无变化：hamming == 0", lambda: f1.data["hamming"], 0)
check("无变化：diff 图显著小于变化帧（灰底零高亮）",
      lambda: len(f1.render_diff_b64) < 20000, True)
check("稳态耗时 <500ms", lambda: f1.data["ms"] < 500, True)

# ── [3] 敏感性 ───────────────────────────────────────────────
print("\n[3] 敏感性（把手 0.008→0.014）")
con.set_param("handle", "Handle_Thickness", 0.014)
f2 = con.render_diff("把手加粗")
check("敏感性：像素变化 >1%", lambda: f2.data["changed_ratio"] > 0.01, True)
check("敏感性：diff 图 >2KB", lambda: len(f2.render_diff_b64) > 2000, True)
check("diff 图是 PNG", lambda: base64.b64decode(f2.render_diff_b64)[:4], b"\x89PNG")
check("变化时机械假设为空（无异常信号）", lambda: f2.refutable_assumption, "")
check("summary 携带变化率", lambda: "像素变化" in f2.summary, True)

# ── [4] 哈希转移谓词 ─────────────────────────────────────────
print("\n[4] 哈希转移谓词（几何已变路径）")
check("几何已变 → 转移谓词 ok",
      lambda: f2.data["predicates"]["hash_transition"]["ok"], True)
print(f"  hamming(把手加粗) = {f2.data['hamming']}（EXP-4 样本）")

# ── [5] dHash 分离度（EXP-4 证据）───────────────────────────
print("\n[5] 大改的 dHash 分离度（半径 0.04→0.075）")
con.set_param("body", "Body_Radius", 0.075)
f3 = con.render_diff("杯体大改")
check("大改：hamming ≥4（结构级分离）", lambda: f3.data["hamming"] >= 4, True)
print(f"  hamming(杯体大改) = {f3.data['hamming']}，changed_ratio = {f3.data['changed_ratio']}")

# ── [6] B1 机械反驳信号 ─────────────────────────────────────
print("\n[6] 同值重写 → 机械反驳假设")
con.set_param("body", "Body_Radius", 0.075)   # 同值
f4 = con.render_diff("同值重写")
check("同值重写：像素零变化", lambda: f4.data["changed_px"], 0)
check("同值重写：refutable_assumption 触发",
      lambda: "零变化" in f4.refutable_assumption, True)

# ── 汇总 ─────────────────────────────────────────────────────
failed = [r for r in ROWS if not r["ok"]]
print(f"\nRENDER-DIFF LIVE: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
for f in failed:
    print("  FAILED:", f["case"], "->", f["detail"])
(OUT / "render_diff_live_result.json").write_text(
    json.dumps(ROWS, ensure_ascii=False, indent=1), encoding="utf-8")
print("result ->", OUT / "render_diff_live_result.json")
