"""probe_loose.py — 定位 array→Realize 链的松散顶点来源"""
import bpy, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from console import Console
from gn_adapter import GNAdapter

K = 1.0 / 35 / 1000.0
def at35(v): return v * K

bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new("probe_root")
root = bpy.data.objects.new("probe_root", mesh)
bpy.context.collection.objects.link(root)
bpy.context.view_layer.objects.active = root

def _tf(translation, source, rotation_deg=None):
    s = {'op': 'transform', 'translation': translation}
    if rotation_deg: s['rotation_deg'] = rotation_deg
    s['source'] = source
    return s

SECS = {
    # 单轮 realize（基线：无 array）
    'P1_single': {'op': 'join_geometry', 'consumes_input': False,
                  'operand': _tf([at35(-1350), at35(-1050), at35(490)],
                                 {'op': 'cylinder', 'radius': at35(400), 'depth': at35(250)},
                                 rotation_deg=[90, 0, 0])},
    # array ×8 realize
    'P2_array8': {'op': 'join_geometry', 'consumes_input': False,
                  'operand': {'op': 'array_linear', 'count': 8, 'offset_x': at35(2700 / 7),
                              'source': _tf([at35(-1350), at35(-1050), at35(490)],
                                            {'op': 'cylinder', 'radius': at35(400), 'depth': at35(250)},
                                            rotation_deg=[90, 0, 0])}},
    # sweep 环 realize 基线
    'P3_ring': {'op': 'join_geometry', 'consumes_input': False,
                'operand': _tf([0, at35(1245), at35(490)], rotation_deg=[90, 0, 0],
                               source={'op': 'sweep_circle', 'ring_radius': at35(1400),
                                       'thickness': at35(90)})},
}

ad = GNAdapter()
roots = {}
for name, sp in SECS.items():
    m = bpy.data.meshes.new(name)
    ob = bpy.data.objects.new(name, m)
    bpy.context.collection.objects.link(ob)
    roots[name] = ob
    sp2 = dict(sp); sp2['id'] = name; sp2['stage'] = 'structure'; sp2['part'] = name
    sp2['depends_on'] = []; sp2['parameters'] = []
    console = Console(ad, ob, workdir=str(HERE / 'tiger_work'))
    r = console.compile(sp2)
    print('[probe %s] %s' % (name, 'OK' if r.ok else 'FAIL %s' % r.error))

bpy.context.view_layer.update()
deps = bpy.context.evaluated_depsgraph_get()
import bmesh
for ob in bpy.data.objects:
    if ob.type != 'MESH' or ob.name not in roots:
        continue
    oe = ob.evaluated_get(deps)
    me = oe.to_mesh()
    if me is None:
        continue
    bm = bmesh.new(); bm.from_mesh(me)
    loose = sum(1 for v in bm.verts if not v.link_edges)
    print('%-12s faces=%-5d verts=%-5d loose=%d' % (ob.name, len(bm.faces), len(bm.verts), loose))
    bm.free()
    oe.to_mesh_clear()
