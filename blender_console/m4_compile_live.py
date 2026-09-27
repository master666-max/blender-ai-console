"""m4_compile_live.py — M4-3 compile_plan 真编译器真机验收（Blender 5.2.1）。

跑法：blender --background --factory-startup --python m4_compile_live.py

**全程零 _build**——四个段落全部是 AI 可直出的 op-JSON：
  S1 body   = cylinder（Radius/Depth live）
  S2 hollow = boolean_diff（operand = transform ← cylinder，掏空成杯）
  S3 handle = join_geometry（source = transform ← transform(rot) ← sweep_circle，
             Handle_Thickness 是 live knob，经别名表接进嵌套 sweep）
  S4 finish = subdivide（Subdiv_Level live）

验收项（全机械，B1 纪律）：
  1. 四段编译成功（纯 op 路径）
  2. 节点图抽查：Boolean DIFFERENCE / CurveToMesh / Subdivision 在正确的树里
  3. 几何合理：面>0、面积>0、bbox 合理（渲染 diff 抓 2 米巨环的教训变成机械断言）
  4. verifier PASS
  5. live knob：改 Radius / Handle_Thickness / Subdiv_Level → 指纹都变
  6. M4-9 归属：4 段全归属、unattributed=0
  7. R12：custom_script 被编译器拒绝（即使 escape_hatch=true）
  8. 未实现 op → OP_UNIMPLEMENTED 结构化错误
  9. 渲染 sanity：op 编译的杯子渲出来目标占比正常
"""
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

shutil.rmtree(HERE / "_m4_wal", ignore_errors=True)
con = Console(ad, obj, workdir=HERE / "_m4_wal")
con.add_thought("T1", "杯壁 4mm 适合手温咖啡", {"segment": "body", "param": "Radius"})
con.add_thought("T2", "把手 8mm 握感舒适", {"segment": "handle", "param": "Handle_Thickness"})

# ── 纯 op-JSON：四段（注意：没有任何 _build）─────────────────
SPECS = [
    {   # S1 杯体
        "id": "body", "op": "cylinder", "consumes_input": False,
        "parameters": [
            {"name": "Radius", "type": "FLOAT", "value": 0.04, "min": 0.02, "max": 0.12},
            {"name": "Depth", "type": "FLOAT", "value": 0.095, "min": 0.05, "max": 0.3},
        ],
    },
    {   # S2 掏空：入几何 − 上移的小圆柱（operand 嵌套链）
        "id": "hollow", "op": "boolean_diff", "consumes_input": True,
        "parameters": [],
        "operand": {"op": "transform", "translation": [0.0, 0.0, 0.01],
                    "source": {"op": "cylinder", "radius": 0.036, "depth": 0.085}},
    },
    {   # S3 把手：join(入几何, operand=立起来的环)
        "id": "handle", "op": "join_geometry", "consumes_input": True,
        "parameters": [
            {"name": "Handle_Thickness", "type": "FLOAT", "value": 0.008,
             "min": 0.003, "max": 0.03},
        ],
        "operand": {"op": "transform", "translation": [0.062, 0.0, 0.045],
                    "source": {"op": "transform", "rotation_deg": [90.0, 0.0, 0.0],
                               "source": {"op": "sweep_circle",
                                          "ring_radius": 0.032}}},
    },
    {   # S4 收尾
        "id": "finish", "op": "subdivide", "consumes_input": True,
        "parameters": [
            {"name": "Subdiv_Level", "type": "INT", "value": 1, "min": 0, "max": 4},
        ],
    },
]

print("\n[1] 纯 op 编译四段")
for s in SPECS:
    t0 = time.perf_counter()
    r = con.compile(s)
    ms = (time.perf_counter() - t0) * 1000
    tag = "ok" if r.ok else f"FAIL {r.error}"
    print(f"  compile {s['id']:<7} {ms:6.1f} ms  {tag}")
    check(f"编译 {s['id']}（op={s['op']}）", lambda r=r: r.ok, True)

check("段落注册 = 4", lambda: len(con.segments), 4)
check("DAG 步数 = 4", lambda: len(con.dag), 4)

# ── [2] 节点图抽查 ────────────────────────────────────────────
print("\n[2] 节点图抽查")
def _tree_ids(seg):
    return {n.bl_idname for n in con.segments[seg]["tree"].nodes}
check("S2 有 Boolean 节点",
      lambda: "GeometryNodeMeshBoolean" in _tree_ids("hollow"), True)
check("S2 boolean = DIFFERENCE",
      lambda: next(n.operation for n in con.segments["hollow"]["tree"].nodes
                   if n.bl_idname == "GeometryNodeMeshBoolean"), "DIFFERENCE")
check("S3 有 CurveToMesh（扫掠）",
      lambda: "GeometryNodeCurveToMesh" in _tree_ids("handle"), True)
check("S4 有 Subdivision",
      lambda: "GeometryNodeSubdivisionSurface" in _tree_ids("finish"), True)
check("S3 live 参数真接进嵌套 sweep（profile Radius 有线）",
      lambda: any(n.bl_idname == "GeometryNodeCurvePrimitiveCircle"
                  and n.inputs["Radius"].is_linked
                  for n in con.segments["handle"]["tree"].nodes), True)

# ── [3] 几何合理性（巨环教训 → 机械断言）─────────────────────
print("\n[3] 几何合理性")
st = con._eval_stats()
check("面数 > 0", lambda: st["faces"] > 0, True)
check("面积 > 0", lambda: st["area"] > 0, True)
check("bbox 合理（0.05–0.3m，巨环断言）",
      lambda: all(0.05 < d < 0.3 for d in st["bbox"]), True)
v = con.verify("op杯")
check("verifier PASS", lambda: v.ok, True)

# ── [4] live knob ────────────────────────────────────────────
print("\n[4] live knob（别名表接进嵌套链的参数）")
fp0 = con._output_fp(con._eval_stats())
con.set_param("body", "Radius", 0.045)
fp1 = con._output_fp(con._eval_stats())
check("改 Radius → 几何变化", lambda: fp1 != fp0, True)
con.set_param("handle", "Handle_Thickness", 0.014)
fp2 = con._output_fp(con._eval_stats())
check("改 Handle_Thickness（嵌套 sweep）→ 几何变化", lambda: fp2 != fp1, True)
con.set_param("finish", "Subdiv_Level", 2)
fp3 = con._output_fp(con._eval_stats())
check("改 Subdiv_Level → 几何变化", lambda: fp3 != fp2, True)

# ── [5] M4-9 归属 ────────────────────────────────────────────
print("\n[5] M4-9 归属（op 路径同样盖印）")
qa = con.query_attribution()
check("unattributed = 0", lambda: qa["unattributed"], 0)
check("归属映射注册 4 段", lambda: len(con.attribution), 4)
check("创建几何的段都有面（subdivide 精化不偷归属，first-creator-wins）",
      lambda: set(qa["by_segment"]), {"body", "hollow", "handle"})
check("归属总和 = 总面数", lambda: sum(qa["by_segment"].values()), qa["total"])

# ── [6] R12 + 未实现 op ─────────────────────────────────────
print("\n[6] 红线与响亮失败")
r_bad = con.compile({"id": "escape", "op": "custom_script",
                     "escape_hatch": True, "parameters": []})
check("R12：custom_script 被拒（即使有 escape_hatch）",
      lambda: not r_bad.ok and r_bad.error["error_code"] == "R12_CUSTOM_SCRIPT_DENIED",
      True)
r_un = con.compile({"id": "fil", "op": "fillet", "parameters": []})
check("未实现 op → OP_UNIMPLEMENTED",
      lambda: not r_un.ok and r_un.error["error_code"] == "OP_UNIMPLEMENTED", True)
check("错误带建议列表", lambda: len(r_un.error["suggestions"]) > 0, True)
check("失败编译不污染会话（仍 4 段）", lambda: len(con.segments), 4)
check("失败编译不污染归属", lambda: len(con.attribution), 4)

# ── [7] 渲染 sanity（op 杯子要能看）─────────────────────────
print("\n[7] 渲染 sanity")
f0 = con.render_diff("op杯")
check("渲染谓词全过", lambda: all(
    p["ok"] if isinstance(p, dict) else p
    for p in f0.data["predicates"].values() if p is not None), True)
con.set_param("body", "Radius", 0.05)
f1 = con.render_diff("杯体加粗")
check("改参数 → 渲染 diff >1%", lambda: f1.data["changed_ratio"] > 0.01, True)

# ── [8] M4-3b op 元数据契约 + 幂等双跑 ──────────────────────
print("\n[8] M4-3b op 元数据契约")
from op_compiler import OP_META, OPS, assert_meta_complete, compile_twice_fingerprint, op_meta
try:
    assert_meta_complete()
    meta_ok = True
except Exception as exc:  # noqa: BLE001
    meta_ok = False
    print("  meta error:", exc)
check("13 op 全带元数据（无实测证据不收）", lambda: meta_ok, True)
check("每条 lessons 均为 list", lambda: all(isinstance(m.get("lessons"), list)
                                            for m in OP_META.values()), True)
fp_a, fp_b = compile_twice_fingerprint(ad, {"id": "idem", "op": "cylinder",
                                            "parameters": [{"name": "Radius",
                                                            "type": "FLOAT",
                                                            "value": 0.03}]})
check("幂等双跑：同 spec 编译两次 fingerprint 一致", lambda: fp_a, fp_b)
check("op_meta 查询", lambda: op_meta("mirror")["lessons"][0].startswith("5.2"), True)

# ── 汇总 ─────────────────────────────────────────────────────
failed = [r for r in ROWS if not r["ok"]]
print(f"\nM4-COMPILE LIVE: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
for f in failed:
    print("  FAILED:", f["case"], "->", f["detail"])
(OUT / "m4_compile_live_result.json").write_text(
    json.dumps(ROWS, ensure_ascii=False, indent=1), encoding="utf-8")
print("result ->", OUT / "m4_compile_live_result.json")
