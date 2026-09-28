"""probe_setparam.py — 定位 set_param 打空杯身的最小复现"""
import bpy, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new("p_root")
root = bpy.data.objects.new("p_root", mesh)
bpy.context.collection.objects.link(root)
bpy.context.view_layer.objects.active = root

from console import Console
from gn_adapter import GNAdapter
import json

console = Console(GNAdapter(), root, workdir=HERE / "probe_work")
SPEC = {"id": "1.1", "op": "revolve_profile", "stage": "structure", "part": "mug",
        "consumes_input": False, "depends_on": [],
        "parameters": [
            {"name": "Radius_Top", "type": "FLOAT", "value": 0.040},
            {"name": "Radius_Bottom", "type": "FLOAT", "value": 0.034},
            {"name": "Depth", "type": "FLOAT", "value": 0.095}]}
r = console.compile(SPEC)
print("[p] compile:", r.ok)

def faces():
    deps = bpy.context.evaluated_depsgraph_get()
    ev = root.evaluated_get(deps)
    m = ev.to_mesh()
    n = len(m.polygons)
    zs = [v.co.z for v in m.vertices] or [0]
    ev.to_mesh_clear()
    return n, round(max(zs) * 1000, 1)

def snap_inputs(mod):
    try:
        ins = mod.properties.inputs
        out = {}
        for k in ins.keys():
            try:
                g = ins[k]
                out[k] = dict(g) if hasattr(g, "keys") else str(g)
            except Exception as e:
                out[k] = f"<{e!r}>"
        return out
    except Exception as e:
        return {"err": repr(e)}

rec = console.segments["1.1"]
mod = rec["mod"]
print("[p] sid:", rec["sid"])
print("[p] before:", faces(), "| inputs:", json.dumps(snap_inputs(mod), default=str)[:400])

r1 = console.set_param("1.1", "Depth", 0.080)
print("[p] set 0.080:", r1.ok, r1.summary[:60], "→", faces())

r2 = console.set_param("1.1", "Depth", 0.095)
print("[p] set 0.095:", r2.ok, r2.summary[:60], "→", faces())
print("[p] after inputs:", json.dumps(snap_inputs(mod), default=str)[:400])
