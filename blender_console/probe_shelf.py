# probe_shelf.py — 通过 MCP 查证货架陈设存在性
from mcp_bridge import bl_call

code = """
import bpy, json
names = sorted(o.name for o in bpy.data.objects
               if ('Shelf' in o.name or 'DCase' in o.name
                   or 'Bento' in o.name or 'Band' in o.name))
locs = {o.name: [round(c, 2) for c in o.location]
        for o in bpy.data.objects if o.name.startswith('Shelf')}
res = {'n': len(names), 'sample': names[:10], 'locs': locs}
open(r'D:/WorkBuddy专用！危险！！！！！！！！/2026-09-26-21-02-58/blender_console/probe_out.json',
     'w').write(json.dumps(res))
"""
r = bl_call({"type": "execute_code", "params": {"code": code}})
print("status:", r.get("status"))
print(open(r"D:/WorkBuddy专用！危险！！！！！！！！/2026-09-26-21-02-58/blender_console/probe_out.json").read())
