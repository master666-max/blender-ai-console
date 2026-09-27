import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bpy
from gn_adapter import GNAdapter
from console import Console
from intake import IntakeSession

ad = GNAdapter(bpy)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.active_object
obj.data = bpy.data.meshes.new("B")
con = Console(ad, obj, workdir=HERE / "_probe_wal")

s = IntakeSession(brief="马克杯", mode="direct")
sk = s.to_plan_skeleton()
for sec in sk["sections"]:
    r = con.compile(dict(sec))
    print(sec["id"], sec["op"], sec.get("stage"), "ok" if r.ok else f"ERR {r.error}")
