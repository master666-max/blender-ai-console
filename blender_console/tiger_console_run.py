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

# ── v3.4 几何对齐：声明式 op 链（零 bpy 手搓，全部 plan spec 表达）────
# 对齐基准 = tiger_tank_build.py v3.4（WebSearch 实尺：车体 6320×3160、
# 轮 R400×8 轴距 2700、履带宽 725、炮塔 R1030、88mm L/56 炮管 4930）。
# 机制依据：join_geometry(consumes_input) 吃上游累积 + operand 新部件；
# source 嵌套让 primitive 可被 transform/array/boolean 组合（compile_op L546）。
# 近似如实标注：交错轮合并宽 250、履带环椭圆化 scale-z 0.32、车头一级台阶。

def _tf(translation, source=None, rotation_deg=None, scale=None):
    s = {'op': 'transform', 'translation': translation}
    if rotation_deg is not None:
        s['rotation_deg'] = rotation_deg
    if scale is not None:
        s['scale'] = scale
    if source is not None:
        s['source'] = source
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
    """段级累积：吃上游（compile 传 chain_src）+ operand 新部件。
    嵌套用法（1.1 source）显式传 source=另一路几何。"""
    s = {'op': 'join_geometry', 'consumes_input': True, 'operand': operand}
    if source is not None:
        s['source'] = source
    return s

SPEC_CHAINS = {
    # 1.1 船体（6320×2400×1000 @z250）⊕上层结构（4600×2400×300 @z1390，重叠 10mm）。
    #     阶梯车头=上层不延伸到前部（自然形成），零布尔——MeshBoolean 吃非焊接
    #     join 输入必产接缝非流形（真机实测 manifold 3→9 的教训）
    '1.1': _join(_cube(4600, 2400, 300, [at35(0), 0, at35(1390)]),
                 source=_cube(6320, 2400, 1000, [at35(0), 0, at35(750)])),
    # 1.2 负重轮 ×8×2 侧（真交错）：外列 y-1175 起点 x-1350，内列 y+1175 错半步。
    #     三路 join：Incoming(车体) + 轮A + 轮B——compile_op 的 source 语义=替换上游，
    #     内层 join2(source=arrayA, operand=arrayB) 并出双列，外层 join 再并 Incoming
    '1.2': {'op': 'join_geometry', 'consumes_input': True,
            'operand': {'op': 'join_geometry',
                        'source': {'op': 'array_linear', 'count': 8,
                                   'offset_x': at35(2700 / 7),
                                   'source': _cyl(400, 250, rot=([90, 0, 0],
                                                                 [at35(-1350), at35(-1225), at35(490)]))},
                        'operand': {'op': 'array_linear', 'count': 8,
                                    'offset_x': at35(2700 / 7),
                                    'source': _cyl(400, 250, rot=([90, 0, 0],
                                                                  [at35(-1157), at35(1225), at35(490)]))}}},
    # 1.3 履带环 ×2 显式双链：R1750 z×0.26 椭圆化 y±1245，rotX90 立起。
    #     同 1.2：内层 join2 并双环，外层 join 再并 Incoming
    '1.3': {'op': 'join_geometry', 'consumes_input': True,
            'operand': {'op': 'join_geometry',
                        'source': _tf([0, at35(1245), at35(490)], rotation_deg=[90, 0, 0],
                                      scale=[1.0, 0.26, 1.0],
                                      source={'op': 'sweep_circle', 'ring_radius': at35(1750),
                                              'thickness': at35(90)}),
                        'operand': _tf([0, at35(-1245), at35(490)], rotation_deg=[90, 0, 0],
                                       scale=[1.0, 0.26, 1.0],
                                       source={'op': 'sweep_circle', 'ring_radius': at35(1750),
                                               'thickness': at35(90)})}},
    # 1.4 发动机格栅 ×4：顶甲面 z1560 凸出（此前 z1290 藏在车体内）
    '1.4': _join({'op': 'array_linear', 'count': 4, 'offset_x': at35(220),
                  'source': _cube(700, 900, 30, [at35(-2100), 0, at35(1565)])}),
    # 1.5 排气管 ×2：凸出车尾装甲面 x-3160 → 管 x-3100 竖管
    '1.5': _join({'op': 'boolean_union',
                  'source': _cyl(75, 900, rot=([0, 0, 0], [at35(-3220), at35(250), at35(1050)])),
                  'operand': _cyl(75, 900, rot=([0, 0, 0], [at35(-3220), at35(-250), at35(1050)]))}),
    # 2.1 Henschel 炮塔：R1030 高 780，座圈 z1550，中心 x350
    '2.1': _join(_tf([at35(350), 0, at35(1940)],
                     source={'op': 'revolve_profile', 'radius_top': at35(980),
                             'radius_bottom': at35(1030), 'depth': at35(780)})),
    # 2.2 88mm L/56 炮管 + 双室制退器：沿 X，炮轴 z1850，炮尖 x5290（全长 8.45m）
    '2.2': _join({'op': 'boolean_union',
                  'source': _cyl(50, 3590, rot=([0, 90, 0], [at35(3495), 0, at35(1850)])),
                  'operand': _cyl(95, 320, rot=([0, 90, 0], [at35(5130), 0, at35(1850)]))}),
    # 2.3 MG34 车体机枪球座：凸出前装甲面 x3160 → x3170
    '2.3': _join(_cyl(90, 150, rot=([0, 90, 0], [at35(3170), at35(-620), at35(1050)]))),
    # 2.4 指挥塔 R290 + 装填手舱盖 R210
    '2.4': _join({'op': 'boolean_union',
                  'source': _cyl(290, 150, rot=([0, 0, 0], [at35(900), 0, at35(2405)])),
                  'operand': _cyl(210, 80, rot=([0, 0, 0], [at35(-150), at35(350), at35(2370)]))}),
    # 2.5 防盾（mantlet）：R225 长 400，炮塔前缘 x1380
    '2.5': _join(_cyl(225, 400, rot=([0, 90, 0], [at35(1580), 0, at35(1850)]))),
    # 3.3 备用履带 ×3：车尾侧挂 y1700（凸出车侧装甲面 8.6mm），步 180
    '3.3': _join({'op': 'array_linear', 'count': 3, 'offset_x': at35(180),
                  'source': _cube(160, 700, 95, [at35(1200), at35(1700), at35(1150)])}),
    # 4.1/4.2 材质两段：吃上游 pass-through
    '4.1': {'op': 'set_material', 'consumes_input': True,
            'material_plan': {'preset': 'metal',
                              'surface': {'roughness': 0.62}}},
    '4.2': {'op': 'set_material', 'consumes_input': True,
            'material_plan': {'preset': 'metal',
                              'surface': {'roughness': 0.78}}},
    # 5.1 展示底座（300×180×100，托履带底）
    '5.1': _join(_cube(300, 180, 100, [at35(0), 0, at35(-50)])),
}

sec_map = {}
for nid in byid:
    n = byid[nid]
    if n['build']['op'] in GATE:
        continue                                  # gate 段只验证不产几何
    sec = dict(SPEC_CHAINS[nid])                  # v3.4 对齐 spec（深拷贝外层）
    sec['id'] = nid
    sec['stage'] = 'structure'
    sec['part'] = nid
    sec['depends_on'] = resolve(list(n.get('deps', [])))
    sec['parameters'] = []
    sec_map[nid] = sec

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
world = bpy.data.worlds.get('World') or bpy.data.worlds.new('World')
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get('Background')
if bg:
    bg.inputs[0].default_value = (0.85, 0.86, 0.88, 1.0)
    bg.inputs[1].default_value = 1.1
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
bpy.context.active_object.rotation_euler = (math.radians(42), 0, math.radians(-25))
bpy.ops.object.light_add(type='SUN', location=(-0.2, 0.2, 0.3))
bpy.context.active_object.data.energy = 1.6
bpy.context.active_object.rotation_euler = (math.radians(55), 0, math.radians(150))
bpy.ops.object.camera_add()
cam = bpy.context.active_object
scene.camera = cam
cam.data.lens = 60
cam.location = (0.42, -0.35, 0.19)
# 瞄准全车中心（车体 x∈[-3.16,5.29] 实尺 → 场景中心 x≈at35(1060)，高中心 z≈at35(1000)）
d = mathutils.Vector((at35(1060), 0, at35(1000))) - mathutils.Vector(cam.location)
cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

# 地面承接阴影（v3.4 同款观感；渲染环境不属于建模正链）
bpy.ops.mesh.primitive_plane_add(size=2, location=(0, 0, -0.001))
ground = bpy.context.active_object
ground.name = 'ground'
gm = bpy.data.materials.new('ground')
gm.use_nodes = True
gm.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.30, 0.30, 0.31, 1)
gm.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.9
ground.data.materials.append(gm)

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
