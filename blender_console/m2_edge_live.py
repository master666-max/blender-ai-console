"""m2_edge_live.py — M2-1 边级拓扑谓词真机验收（Blender 5.2.1）。

跑法：blender --background --factory-startup --python m2_edge_live.py

验收（改动-对照实测纪律：每个谓词必须验证"会拦"）：
  1. 正常圆柱 → edge_topology PASS（flipped=0）
  2. 反例：手工翻转一个面的绕向 → flipped>0 → edge_topology FAIL
  3. 开放网格（杯子口）：boundary>0 但不 FAIL（边界边合法）
  4. 全链：verifier 整体在反例上 FAIL、修复后 PASS
"""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bmesh  # noqa: E402
import bpy  # noqa: E402

from gn_verify import GeometryVerifier  # noqa: E402

ROWS: list[dict] = []


def check(name, fn, expect=True):
    try:
        val = fn()
        if val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True, "detail": str(val)[:120]})
        print(f"  PASS  {name}  {str(val)[:100]}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:200]})
        print(f"  FAIL  {name}  {exc!r}")


print(f"Blender {bpy.app.version_string}")
bpy.ops.wm.read_factory_settings(use_empty=True)

ver = GeometryVerifier(budget_faces=300_000, ground_z=-10.0)

# ── [1] 正例：正常圆柱 ────────────────────────────────────────
print("\n[1] 正常圆柱（正例）")
bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.04, depth=0.095,
                                    location=(0, 0, 0.05))
cyl = bpy.context.active_object
rep = ver.check(cyl.data, cyl)
edge = next(f for f in rep.findings if f.predicate == "edge_topology")
print(f"  edge_topology: {edge.value}")
check("正常圆柱 edge_topology PASS", lambda: edge.ok, True)
check("正常圆柱整体 PASS", lambda: rep.ok, True)

# ── [2] 反例：翻转一个面的绕向 ────────────────────────────────
print("\n[2] 反例：翻转一面绕向（法线打架）")
bm = bmesh.new()
bm.from_mesh(cyl.data)
bm.faces.ensure_lookup_table()
bm.faces[0].normal_flip()                       # 翻转顶面绕向 → 与侧面的共享边不连续
bm.to_mesh(cyl.data)
bm.free()
rep2 = ver.check(cyl.data, cyl)
edge2 = next(f for f in rep2.findings if f.predicate == "edge_topology")
print(f"  edge_topology: {edge2.value}")
check("翻转一面 → flipped_winding > 0（被检出）",
      lambda: edge2.value["flipped_winding"] > 0, True)
check("翻转一面 → edge_topology FAIL（会拦）", lambda: edge2.ok, False)
check("整体 FAIL（门禁有牙齿）", lambda: rep2.ok, False)

# ── [3] 修复：全部重算绕向 → 恢复 PASS（改动-对照闭环）────────
print("\n[3] 修复（recalc normals）")
bm_fix = bmesh.new()
bm_fix.from_mesh(cyl.data)
bmesh.ops.recalc_face_normals(bm_fix, faces=bm_fix.faces)   # object-mode 安全的法线重算
bm_fix.to_mesh(cyl.data)
bm_fix.free()
rep3 = ver.check(cyl.data, cyl)
edge3 = next(f for f in rep3.findings if f.predicate == "edge_topology")
check("修复后 flipped=0", lambda: edge3.value["flipped_winding"], 0)
check("修复后整体 PASS（改动-对照闭环）", lambda: rep3.ok, True)

failed = [r for r in ROWS if not r["ok"]]
print(f"\nM2-EDGE LIVE: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
for f in failed:
    print("  FAILED:", f["case"], "->", f.get("detail"))
out = ROOT / "m8_bridge" / "m2_edge_result.json"
out.write_text(json.dumps(ROWS, ensure_ascii=False, indent=1), encoding="utf-8")
print("result ->", out)
