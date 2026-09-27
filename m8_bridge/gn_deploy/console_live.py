"""console.py 真机验收——M4-3 compile + M3 回退 + M9-1 tool return + M4-8 struct error"""
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]  # 仓库根（相对推导，跨机器可移植）
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bpy
from gn_adapter import GNAdapter, ParamSpec
from console import Console, ConsoleResult

ROWS = []
def check(name, fn, expect=None):
    try:
        val = fn()
        if expect is not None and val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True, "detail": str(val)[:120]})
        print(f"  PASS  {name}  {val}")
    except Exception as e:
        ROWS.append({"case": name, "ok": False, "detail": repr(e)[:160]})
        print(f"  FAIL  {name}  {e!r}")

def expect_raise(name, et, fn):
    try: fn()
    except et as e:
        ROWS.append({"case": name, "ok": True, "detail": str(e)[:100]})
        print(f"  PASS  {name}  正确拒绝")
        return
    except Exception as e:
        ROWS.append({"case": name, "ok": False, "detail": f"错误类型 {e!r}"})
        print(f"  FAIL  {name}  错误类型")
        return
    ROWS.append({"case": name, "ok": False, "detail": "未抛错"})
    print(f"  FAIL  {name}  未抛错")

print(f"Blender {bpy.app.version_string}")
ad = GNAdapter(bpy)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.active_object; obj.name = "Mug"
obj.data = bpy.data.meshes.new("Base")
con = Console(ad, obj)

# thoughts
con.add_thought("T1", "把手粗 7mm 握感舒适", {"segment": "handle", "param": "Handle_Thickness"})

# compile 3 segments
spec_body = {"id": "body", "op": "revolve_profile", "consumes_input": False,
             "parameters": [{"name": "Body_Radius", "type": "FLOAT", "value": 0.04},
                            {"name": "Body_Depth", "type": "FLOAT", "value": 0.095}]}
def _build_body(ad, tree, sid):
    gi = ad.add_node(tree, "NodeGroupInput"); go = ad.add_node(tree, "NodeGroupOutput")
    cyl = ad.add_node(tree, "GeometryNodeMeshCylinder"); sm = ad.add_node(tree, "GeometryNodeSetShadeSmooth")
    ad.link(tree, gi, "Body_Radius", cyl, "Radius")
    ad.link(tree, gi, "Body_Depth", cyl, "Depth")
    ad.link(tree, cyl, "Mesh", sm, "Mesh"); ad.link(tree, sm, "Mesh", go, "Geometry")
spec_body["_build"] = _build_body

spec_handle = {"id": "handle", "op": "sweep_rounded_rect", "consumes_input": True,
               "parameters": [{"name": "Handle_Thickness", "type": "FLOAT", "value": 0.008}]}
def _build_handle(ad, tree, sid):
    gi = ad.add_node(tree, "NodeGroupInput"); go = ad.add_node(tree, "NodeGroupOutput")
    ring = ad.add_node(tree, "GeometryNodeCurvePrimitiveCircle")
    ring.inputs["Radius"].default_value = 0.032   # 不接=默认 1.0m → 2 米巨环（M9-3 渲染 diff 抓出）
    prof = ad.add_node(tree, "GeometryNodeCurvePrimitiveCircle")
    sweep = ad.add_node(tree, "GeometryNodeCurveToMesh")
    join = ad.add_node(tree, "GeometryNodeJoinGeometry")
    xf = ad.add_node(tree, "GeometryNodeTransform")
    ad.link(tree, gi, "Handle_Thickness", prof, "Radius")
    ad.link(tree, ring, "Curve", sweep, "Curve")
    ad.link(tree, prof, "Curve", sweep, "Profile Curve")
    ad.link(tree, sweep, "Mesh", xf, "Geometry")
    ad.link(tree, xf, "Geometry", join, "Geometry")
    ad.link(tree, gi, "Incoming_Geometry", join, "Geometry")
    ad.link(tree, join, "Geometry", go, "Geometry")
spec_handle["_build"] = _build_handle

r1 = con.compile(spec_body)
if not r1.ok:
    print("  compile body error:", r1.error)   # 结构化错误直接可见（M4-8）
check("compile body", lambda: r1.ok and r1.data.get("nodes", 0) > 0, True)
r2 = con.compile(spec_handle)
if not r2.ok:
    print("  compile handle error:", r2.error)
check("compile handle", lambda: r2.ok, True)

# M9-1 tool return format
tr = r1.to_tool_return()
check("tool return has action+ok", lambda: tr["action"] == "compile" and tr["ok"] is True, True)

# M4-9 归属（编译时盖印，与 gn_session 同一机制）
qa = con.query_attribution()
check("M4-9 归属：unattributed=0", lambda: qa["unattributed"], 0)
check("M4-9 归属：两段都有面", lambda: len(qa["by_segment"]), 2)

# set_param with backdating
r3 = con.set_param("body", "Body_Radius", 0.045)
check("set_param body 0.045", lambda: r3.ok and "几何变化" in r3.summary, True)

# verify
r4 = con.verify("post_param")
check("verify PASS", lambda: r4.ok and "PASS" in r4.summary, True)

# checkpoint
r5 = con.checkpoint("GP1", ("T1",))
check("checkpoint GP1", lambda: r5.ok and "GP1" in r5.summary, True)

# structured error
r6 = con.set_param("nonexistent", "foo", 1)
check("structured error: SEG_NOT_FOUND",
      lambda: not r6.ok and r6.error["error_code"] == "SEG_NOT_FOUND", True)

# schema 拦截（M4-7）：未知 op 必须在编译前被拒
r8 = con.compile({"id": "bad", "op": "not_a_real_op", "parameters": []})
check("schema 拦截 UNKNOWN_OP",
      lambda: not r8.ok and r8.error["error_code"] == "SCHEMA_FAIL", True)

# export
r7 = con.export_state()
check("export_state", lambda: r7.ok and "steps" in r7.data, True)
check("export 含 attribution", lambda: len(r7.data.get("attribution", {})), 2)

print(f"\nCONSOLE: {sum(1 for r in ROWS if r['ok'])}/{len(ROWS)} passed")
out = ROOT.parent / "2026-09-26-blender" / "console_result.json"
out.write_text(json.dumps(ROWS, ensure_ascii=False, indent=1), encoding="utf-8")
