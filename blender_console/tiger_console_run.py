"""tiger_console_run.py — 虎式坦克 · 走 console.py 正链真机验证（不重复造轮子）
================================================================================
废弃 tiger_tank_build.py 手搓 bpy 路径（归档为实验），改走系统管线：
  IntakeSession（虎式，坦克域）→ to_plan_skeleton → 填 op 细节（逻辑树 deps 并行）
  → PlanSchema.validate → Console.compile 逐段（GN 编译，op_compiler 真机）
  → verify → render_diff 三件套 → state 导出（m9_web 控制台消费）
运行：blender.exe --factory-startup --background --python tiger_console_run.py
产物：showcase/tiger/chain-*.png + tiger_console_state.json + 逐段 [chain] 留痕
"""
import bpy, sys, json, math
import mathutils
from math import radians
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "showcase" / "tiger"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(HERE))
K = 1.0 / 35 / 1000.0


def at35(real_mm):
    return real_mm * K


# ── 场景清空 + 真源对象 ─────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new("tiger_root")
root = bpy.data.objects.new("tiger_root", mesh)
bpy.context.collection.objects.link(root)
bpy.context.view_layer.objects.active = root

# ── ① intake（虎式，坦克域）──
from intake import IntakeSession
s = IntakeSession(brief='1:35 二战德军虎式坦克后期型（1944 Henschel 炮塔）静态展示',
                  mode='full',
                  parts=['车体', '炮塔', '炮管', '履带', '负重轮', '舱门'],
                  scene_facts={'scale': '1:35', 'period': '1944后期型'})
s.ask_round()
s.submit({'length_real': 6320, 'front_armor': 102,
          'roadwheel_per_side': 8, 'gun_caliber': 88})
s.freeze()
sk = s.to_plan_skeleton()
print('[chain ①] intake → 骨架 %d sections（坦克域问题卡 ✅）' % len(sk['sections']))

# ── ② 逻辑树 deps 并行桥：骨架串链 → 逻辑树 deps（修 P1）──
from logic_tree import load_tree, to_plan
lt = load_tree(HERE / 'logic_trees' / 'tiger_tank.json')
lt_plan = to_plan(lt)
lt_deps = {s2['id']: s2['depends_on'] for s2 in lt_plan['sections']}
OP_MAP = {'armor_box': 'boolean_diff', 'wheel_row': 'array_radial',
          'track_loop': 'sweep_circle', 'grille': 'array_linear',
          'turret_shell': 'revolve_profile', 'gun_barrel': 'cylinder',
          'mg_port': 'cylinder', 'hatch_pair': 'cylinder', 'mantlet': 'boolean_union',
          'detail_kit': 'array_linear', 'camo_paint': 'set_material',
          'weathering': 'set_material', 'display_base': 'cube',
          'exhaust_pipes': 'cylinder'}
GATE = {'proportion_check', 'flat_armor_check'}
byid = {n['id']: n for n in lt['nodes']}

def resolve(deps):
    out = []
    for d in deps:
        if byid[d]['build']['op'] in GATE:
            out.extend(resolve(byid[d].get('deps', [])))
        else:
            out.append(d)
    return out

sec_map = {s2['id']: s2 for s2 in sk['sections']}
for nid in byid:
    n = byid[nid]
    if n['build']['op'] in GATE:
        continue
    if nid not in sec_map:                     # 骨架只有 parts×stages；按树补 op 细节段
        sec_map[nid] = {'id': nid, 'op': OP_MAP.get(n['build']['op'], 'cube'),
                        'stage': 'structure', 'part': nid,
                        'consumes_input': True, 'depends_on': [], 'parameters': []}
    sec = sec_map[nid]
    sec['op'] = OP_MAP.get(n['build']['op'], sec['op'])
    sec['depends_on'] = resolve(list(n.get('deps', [])))
    _pm = n['build'].get('params_mm', {})
    _np = [{'name': k, 'type': 'FLOAT', 'value': v} for k, v in _pm.items()]
    if _np:
        sec['parameters'] = _np
    if n['build']['op'] == 'armor_box':        # boolean_diff 需 operand 嵌套（M4-8 结构化错误 suggestions 的修复动作）
        sec['operand'] = {'op': 'cube',
                          'parameters': [{'name': 'Size_X', 'type': 'FLOAT', 'value': at35(5800)},
                                         {'name': 'Size_Y', 'type': 'FLOAT', 'value': at35(2900)},
                                         {'name': 'Size_Z', 'type': 'FLOAT', 'value': at35(2400)}]}
# M4-8 契约：boolean_diff 需要 operand（嵌套 op spec——op_compiler L211-219）
for _s in sec_map.values():
    if _s['op'] == 'boolean_diff' and 'operand' not in _s:
        _pr = byid[_s['id']]['build'].get('params_real', {})
        _L, _W, _H = _pr.get('L', 6320), _pr.get('W', 3160), _pr.get('H', 1000)
        _wall = at35(100)                        # 壁厚 100mm 装甲 → 内腔各向 -200mm
        _s['operand'] = {'op': 'cube',
                         'size': [at35(_L - 200), at35(_W - 200), at35(_H + 400)],
                         'location': [0, 0, at35(200)]}   # 内腔上穿（敞口车体）
plan = {'version': '0.3', 'intent': sk['intent'], 'sections': list(sec_map.values()),
        'constraints': sk.get('constraints', [])}

# ── ③ PlanSchema 校验 ──
from plan_schema import validate_plan
issues = validate_plan(plan, segment_names=[s2['id'] for s2 in plan['sections']])
errs = [i for i in issues if i.level == 'error']
print('[chain ②] PlanSchema: %d sections, %d issues (%d error)'
      % (len(plan['sections']), len(issues), len(errs)))
for i in errs[:6]:
    print('   ', str(i)[:110])
if errs:
    print('[chain] schema error —— 修正后再跑（本轮如实报告）')

# ── ④ Console.compile 逐段（GN 真机编译）──
from console import Console
from gn_adapter import GNAdapter
ad = GNAdapter()
console = Console(ad, root, workdir=str(HERE / 'tiger_work'))
compiled, failed = 0, []
from logic_tree import topo_order as lt_topo
_topo = lt_topo(lt)
_sec_by_id = {s2['id']: s2 for s2 in plan['sections']}
_compile_order = [(_sec_by_id[nid] if nid in _sec_by_id else None) for nid in _topo]
_compile_order = [s2 for s2 in _compile_order if s2]
for sec in _compile_order:
    r = console.compile(sec)
    if r.ok:
        compiled += 1
        print('[chain ③] compile %s ✅ %s' % (sec['id'], (r.summary or '')[:60]))
    else:
        failed.append((sec['id'], r.error))
        print('[chain ③] compile %s ⛔ %s' % (sec['id'], json.dumps(r.error, ensure_ascii=False)[:140]))
print('[chain ③] compile: %d ok / %d fail' % (compiled, len(failed)))

# ── ⑤ verify + 渲染（三件套真机）──
r = console.verify(label='tiger-v3-chain')
print('[chain ④] verify ok=%s :: %s' % (r.ok, (r.summary or '')[:80]))
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 48
scene.render.resolution_x = 1024
scene.render.resolution_y = 640
try:
    scene.cycles.use_denoising = True
except Exception:
    pass
bpy.ops.object.light_add(type='SUN', location=(0.2, -0.2, 0.4))
bpy.context.active_object.data.energy = 3.0
bpy.context.active_object.rotation_euler = (math.radians(48), 0, math.radians(35))
bpy.ops.object.light_add(type='SUN', location=(-0.2, 0.2, 0.3))
bpy.context.active_object.data.energy = 1.6
bpy.context.active_object.rotation_euler = (math.radians(55), 0, math.radians(-140))
bpy.ops.object.camera_add()
cam = bpy.context.active_object
scene.camera = cam
cam.data.lens = 55
cam.location = (0.30, -0.26, 0.15)
d = mathutils.Vector((0, 0, 0.048)) - mathutils.Vector(cam.location)
cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
scene.render.filepath = str(OUT / 'tiger-chain-front34.png')
bpy.ops.render.render(write_still=True)
print('[render] tiger-chain-front34.png ✅')

# ── ⑥ export_state（Web 控制台消费）──
from m1_core import export_state
st = export_state(console.dag, console.table, console.vparams,
                  console.commits, [], {'override_rate': 0.0})
(HERE.parent / 'm9_web' / 'state.json').write_text(
    json.dumps(st, ensure_ascii=False, indent=1), encoding='utf-8')
print('[chain ⑤] export_state → m9_web/state.json（Web 控制台刷新即虎式流程轴）')
print('[chain DONE] compiled=%d failed=%d' % (compiled, len(failed)))
