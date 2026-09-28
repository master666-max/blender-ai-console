"""tiger_diag.py — 逐段几何诊断（bbox/面数/实例数），配合 run 主链排障。"""
import bpy, sys, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# 复用 run 脚本的前置（intake/spec 链），只编译不渲染
import importlib.util
spec = importlib.util.spec_from_file_location("tcr", HERE / "tiger_console_run.py")
# 直接执行到 compile 完成为止太重——改为独立最小复现：手动编译 4 个关键段
from console import Console
from gn_adapter import GNAdapter
import math

K = 1.0 / 35 / 1000.0
def at35(v): return v * K

bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new("diag_root")
root = bpy.data.objects.new("diag_root", mesh)
bpy.context.collection.objects.link(root)
bpy.context.view_layer.objects.active = root

def _tf(translation, source=None, rotation_deg=None, scale=None):
    s = {'op': 'transform', 'translation': translation}
    if rotation_deg is not None: s['rotation_deg'] = rotation_deg
    if scale is not None: s['scale'] = scale
    if source is not None: s['source'] = source
    return s

def _cyl(r, depth, rot=None):
    s = {'op': 'cylinder', 'radius': at35(r), 'depth': at35(depth)}
    if rot is not None:
        return _tf(rot[1], source=s, rotation_deg=rot[0])
    return s

def _cube(sx, sy, sz, translation=None):
    s = {'op': 'cube', 'size': [at35(sx), at35(sy), at35(sz)]}
    return _tf(translation, source=s) if translation else s

def _join(operand, source=None):
    s = {'op': 'join_geometry', 'consumes_input': True, 'operand': operand}
    if source is not None: s['source'] = source
    return s

SECS = {
    # 单轮（无 array）：验证 source→transform→cylinder 链
    'T1_single_wheel': _join(_cyl(400, 250, rot=([90, 0, 0], [at35(-1350), 0, at35(490)]))),
    # 阵列轮 ×8
    'T2_array_wheel': {'op': 'array_linear', 'consumes_input': True, 'count': 8,
                       'offset_x': at35(2700 / 7),
                       'source': _cyl(400, 250, rot=([90, 0, 0], [at35(-1350), 0, at35(490)]))},
    # 裸 transform 旋转 cube（验证 rotation_deg 是否生效）
    'T3_rot_cube': _tf([0, 0, at35(500)], rotation_deg=[45, 0, 0],
                       source=_cube(1000, 200, 100)),
    # sweep 环（验证 ring 生成与位置）
    'T4_ring': _tf([0, 0, at35(490)], rotation_deg=[90, 0, 0],
                   source={'op': 'sweep_circle', 'ring_radius': at35(1400),
                           'thickness': at35(90)}),
    # 裸 cylinder（无 transform 基线）
    'T5_bare_cyl': _cyl(400, 250),
}

ad = GNAdapter()
console = Console(ad, root, workdir=str(HERE / 'tiger_work'))
for name, sp in SECS.items():
    sp2 = dict(sp); sp2['id'] = name; sp2['stage'] = 'structure'; sp2['part'] = name
    sp2['depends_on'] = []; sp2['parameters'] = []
    r = console.compile(sp2)
    ok = 'OK ' if r.ok else 'FAIL'
    print('[diag %s] %s %s' % (name, ok, json.dumps(r.error, ensure_ascii=False)[:100] if not r.ok else ''))

bpy.context.view_layer.update()
deps = bpy.context.evaluated_depsgraph_get()
print('\n=== evaluated objects ===')
for ob in bpy.data.objects:
    if ob.type != 'MESH':
        continue
    oe = ob.evaluated_get(deps)
    me = oe.to_mesh()
    if me is None:
        print('%-20s mesh=None' % ob.name); continue
    n_faces = len(me.polygons)
    xs = [v.co.x for v in me.vertices] or [0]
    ys = [v.co.y for v in me.vertices] or [0]
    zs = [v.co.z for v in me.vertices] or [0]
    print('%-20s faces=%-5d verts=%-5d bbox x[%.4f,%.4f] y[%.4f,%.4f] z[%.4f,%.4f]'
          % (ob.name, n_faces, len(me.vertices), min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)))
    oe.to_mesh_clear()
# 实例统计
print('\n=== instances in depsgraph ===')
cnt = sum(1 for i, ob in zip(range(len(deps.object_instances)), deps.object_instances)
          if ob.is_instance)
print('instance count:', cnt)
