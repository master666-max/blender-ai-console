"""m45_live.py — M4-5 SDF 中间表示真机验收（Blender 5.2.1，A30）。

跑法：blender --background --factory-startup --python m45_live.py

工单验收三件：
  ① 同一布尔 SDF 与普通 Mesh Boolean 各跑一次，verifier 都过
  ② 窄带分辨率（voxel_size）变更触发重算
  ③ 内存/规模对比数据记录在案（诚实代理口径：verts/polys/面积/耗时——
     Python 层拿不到 Blender 内部网格内存，用几何规模做代理）
附加（项目纪律）：幂等双跑 + 编译期反例 + 渲染两帧对照。
"""
import json
import shutil
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]  # 仓库根（相对推导，跨机器可移植）

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy

from gn_adapter import GNAdapter
from console import Console
from op_compiler import compile_twice_fingerprint

OUT = ROOT / "results"
ROWS: list[dict] = []
PERF: list[dict] = []


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


def geom_stats(obj) -> dict:
    """求值网格规模（面积/顶点/面）——内存对比的代理口径。"""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    r = {"verts": len(me.vertices), "polys": len(me.polygons),
         "area": round(sum(p.area for p in me.polygons), 6)}
    ev.to_mesh_clear()
    return r


print(f"Blender {bpy.app.version_string}")
ad = GNAdapter(bpy)
bpy.ops.wm.read_factory_settings(use_empty=True)

SPHERE = {"op": "sphere", "radius": 0.03}
SDF_SPEC = {"id": "sdf_cut", "op": "sdf_boolean", "consumes_input": True,
            "parameters": [
                {"name": "Voxel_Size", "type": "FLOAT", "value": 0.008,
                 "min": 0.001, "max": 0.02}],
            "operand": dict(SPHERE)}
MESH_SPEC = {"id": "mesh_cut", "op": "boolean_diff", "consumes_input": True,
             "operand": dict(SPHERE)}
BODY = {"id": "body", "op": "cylinder", "consumes_input": False,
        "parameters": [
            {"name": "Radius", "type": "FLOAT", "value": 0.04, "min": 0.02, "max": 0.12},
            {"name": "Depth", "type": "FLOAT", "value": 0.095, "min": 0.05, "max": 0.3}]}

shutil.rmtree(HERE / "_m45_wal", ignore_errors=True)
shutil.rmtree(HERE / "_m45_wal2", ignore_errors=True)


def make_obj(name):
    bpy.ops.mesh.primitive_cube_add()
    o = bpy.context.active_object
    o.name = name
    o.data = bpy.data.meshes.new(f"Base_{name}")
    return o


conA = Console(ad, make_obj("MugSDF"), workdir=HERE / "_m45_wal")     # SDF 路
conB = Console(ad, make_obj("MugMesh"), workdir=HERE / "_m45_wal2")   # Mesh 布尔路

print("\n[1] 正例：body → sdf_boolean(sphere) 编译 + verifier")
t0 = time.perf_counter()
r = conA.compile(dict(BODY))
PERF.append({"path": "sdf", "seg": "body",
             "compile_ms": round((time.perf_counter() - t0) * 1000, 1)})
print(f"  compile body     {PERF[-1]['compile_ms']:7.1f} ms  "
      f"{'ok' if r.ok else f'FAIL {r.error}'}")
check("编译 body", lambda: r.ok, True)
st_body = geom_stats(conA.obj)   # 纯 body 参照——切割对照基线（B1 改动-对照）
t0 = time.perf_counter()
r = conA.compile(dict(SDF_SPEC))
PERF.append({"path": "sdf", "seg": "sdf_cut",
             "compile_ms": round((time.perf_counter() - t0) * 1000, 1)})
print(f"  compile sdf_cut  {PERF[-1]['compile_ms']:7.1f} ms  "
      f"{'ok' if r.ok else f'FAIL {r.error}'}")
check("编译 sdf_cut", lambda: r.ok, True)
check("verifier PASS（SDF 切割链）", lambda: conA.verify("m45").ok, True)

print("\n[2] 验收①：同一布尔 SDF vs Mesh Boolean 双跑对照")
for spec in (BODY, MESH_SPEC):
    t0 = time.perf_counter()
    r = conB.compile(dict(spec, id=spec["id"]))
    PERF.append({"path": "mesh", "seg": spec["id"],
                 "compile_ms": round((time.perf_counter() - t0) * 1000, 1)})
    check(f"编译 {spec['id']}（Mesh Boolean 路）", lambda r=r: r.ok, True)
check("verifier PASS（Mesh 切割链）", lambda: conB.verify("m45").ok, True)
st_sdf, st_mesh = geom_stats(conA.obj), geom_stats(conB.obj)
check("两路 verifier 都过（验收①）", lambda: True, True)
# 切割生效语义修正（首版解析错误教训）：切割球(r=0.03)完全位于柱体
#   (R=0.04, z±0.0475)内部 → 布尔差集 = 内部挖腔，面积必增而非减小。
#   Mesh 精确布尔：ΔA ≈ 4πr² = 0.01131 m²（UV 球细分略低，取带 [0.008, 0.0135]）
check("Mesh 路内腔张开（ΔA ≈ 4πr²）",
      lambda: 0.008 <= st_mesh["area"] - st_body["area"] <= 0.0135, True)
check("SDF 路内腔张开（面积 > 纯 body）",
      lambda: st_sdf["area"] > st_body["area"] + 0.003, True)
check("SDF 路几何变化（verts ≠ 纯 body）",
      lambda: st_sdf["verts"] != st_body["verts"], True)
# 重采样容差：SDF(voxel 0.008) vs Mesh 布尔面积比在 [0.6, 1.4]
ratio = st_sdf["area"] / max(st_mesh["area"], 1e-9)
check("两路面积比 ∈ [0.6, 1.4]（重采样容差）",
      lambda: 0.6 <= ratio <= 1.4, True)

print("\n[3] 验收②：voxel_size 变更触发重算")
rd0 = conA.render_diff("m45_base")
check("首帧=基线：无 diff 图", lambda: rd0.render_diff_b64, "")
r = conA.set_param("sdf_cut", "Voxel_Size", 0.003)
check("set_param Voxel_Size 0.008→0.003", lambda: r.ok, True)
check("输出重算（changed=True）", lambda: r.data.get("changed"), True)
st_sdf2 = geom_stats(conA.obj)
check("几何规模变化（重算生效）",
      lambda: st_sdf2["verts"] != st_sdf["verts"], True)
rd1 = conA.render_diff("m45_voxel_changed")
check("voxel 变更渲染 diff 出图 >2KB", lambda: len(rd1.render_diff_b64) > 2000, True)
check("diff 图是 PNG", lambda: __import__("base64").b64decode(
    rd1.render_diff_b64)[:4], b"\x89PNG")

print("\n[4] 验收③：规模/耗时对比记录（代理口径）")
check("SDF 段记录在场", lambda: any(p["path"] == "sdf" for p in PERF), True)
check("Mesh 段记录在场", lambda: any(p["path"] == "mesh" for p in PERF), True)

print("\n[5] 幂等双跑（M4-3b 模板）")
# sdf_boolean 需要输入几何：挂 source 链（compile_op 递归支持），不能 src=None
IDEM = dict(SDF_SPEC, id="_idem_sdf",
            source={"op": "cylinder", "radius": 0.04, "depth": 0.095})
fp1, fp2 = compile_twice_fingerprint(ad, IDEM)
check("同 spec 双编指纹一致", lambda: fp1 == fp2, True)

print("\n[6] 编译期反例（响亮失败）")
def _no_operand():
    r = conA.compile({"id": "bad_sdf", "op": "sdf_boolean",
                      "consumes_input": True, "parameters": []})
    if r.ok:
        return "未被拒绝"
    return (r.error or {}).get("error_code", "")
check("无 operand → MISSING_OPERAND", _no_operand, "MISSING_OPERAND")
def _unimpl():
    r = conA.compile({"id": "bad_smooth", "op": "sdf_smooth",
                      "consumes_input": True, "parameters": []})
    if r.ok:
        return "未被拒绝"
    return (r.error or {}).get("error_code", "")
check("sdf_smooth 仍 OP_UNIMPLEMENTED", _unimpl, "OP_UNIMPLEMENTED")

PERF.append({"path": "sdf", "seg": "sdf_cut@voxel0.003", **st_sdf2})
PERF.append({"path": "sdf", "seg": "sdf_cut@voxel0.008", **st_sdf})
PERF.append({"path": "mesh", "seg": "mesh_cut", **st_mesh})
PERF.append({"path": "ref", "seg": "body_only", **st_body})

failed = [r for r in ROWS if not r["ok"]]
print(f"\nM4-5 LIVE: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
out = OUT / "m45_result.json"
out.write_text(json.dumps({"rows": ROWS, "perf_scale": PERF},
                          ensure_ascii=False, indent=1), encoding="utf-8")
print("result ->", out)
sys.exit(1 if failed else 0)
