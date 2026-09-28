"""mug_rollback_live.py — 门面演示：AI 侧动作可回退（WAL 事件链 + 确定性重放 + 指纹对账）

跑法：blender.exe -b --factory-startup -P mug_rollback_live.py
剧本：A 建杯身 → checkpoint → B 加把手 → checkpoint → C 破坏性误操作（刀削穿杯壁）
      → 按 WAL 重放（跳过 C）重建 → D 指纹对账 D==B → 哈希链 verify()
产出：showcase/rollback/{A,B,C,D}.png · showcase/rollback-strip.png（帧条，系统 Python 合成）
      results/mug_rollback_result.json
账本：动作同步追加 showcase/mug-ledger.jsonl（与建模演示同一个账本，人侧单一入口）

回退的机制语义（对 README 门面）：
  * AI 的每个动作先落 WAL（哈希链，防篡改可验证）；
  * 回退 = 按 WAL replay 重执行白名单事件（build.*），跳过破坏事件（modify.oops）；
  * 对账 = 网格指纹（verts/faces/体积）逐项相等 + 哈希链 verify() == True。
  证据在图（C 明显残、D 与 B 一致），判据在册（指纹三元组），结论可追溯。
"""
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import bmesh  # type: ignore[attr-defined]
import bpy  # type: ignore[attr-defined]
from mathutils import Matrix  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender_console"))

from m1_core import WALLog  # noqa: E402
from presentation import render_presentation  # noqa: E402

LEDGER = ROOT / "showcase" / "mug-ledger.jsonl"
WAL_PATH = ROOT / "showcase" / "mug-rollback-wal.jsonl"
FRAME_DIR = ROOT / "showcase" / "rollback"
RESULT = ROOT / "results" / "mug_rollback_result.json"

fps: list[dict] = []


def ledger(act: str, detail: str, gate: str = "", ok: bool = True) -> None:
    rec = {"ts": round(time.time(), 3), "actor": "AI", "act": act,
           "detail": detail, "gate": gate, "ok": bool(ok)}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def apply_mod(ob, name: str) -> None:
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier=name)


# ═══════════════════ 几何构建（与建模演示同参数，确定性）═══════════════════
def build_body():
    """A/树 3.1+1.1+1.3：杯身锥台 + 内腔（origin 归零，本地=世界）。"""
    bpy.ops.mesh.primitive_cone_add(vertices=192, radius1=0.038, radius2=0.040,
                                    depth=0.095, location=(0, 0, 0.0475))
    body = bpy.context.active_object
    body.name = "Mug"
    body.data.transform(Matrix.Translation((0, 0, 0.0475)))
    body.location = (0, 0, 0)
    bpy.ops.mesh.primitive_cone_add(vertices=192, radius1=0.0338, radius2=0.0356,
                                    depth=0.089, location=(0, 0, 0.0525))
    cutter = bpy.context.active_object
    mod = body.modifiers.new("Cavity", 'BOOLEAN')
    mod.operation = 'DIFFERENCE'
    mod.solver = 'EXACT'
    mod.object = cutter
    apply_mod(body, "Cavity")
    bpy.data.objects.remove(cutter, do_unlink=True)
    return body


def add_handle(body):
    """B/树 2.1-2.4：椭圆弧弯管把手 EXACT 融合。"""
    cu = bpy.data.curves.new("HandlePath", 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_depth = 0.007
    cu.bevel_resolution = 12
    sp = cu.splines.new('POLY')
    N = 48
    sp.points.add(N)
    for i in range(N + 1):
        phi = -math.pi / 2 + math.pi * i / N
        sp.points[i].co = (0.036 + 0.042 * math.cos(phi), 0.0,
                           0.0475 + 0.019 * math.sin(phi), 1.0)
    hob = bpy.data.objects.new("HandlePath", cu)
    scene.collection.objects.link(hob)
    bpy.ops.object.select_all(action='DESELECT')
    hob.select_set(True)
    bpy.context.view_layer.objects.active = hob
    bpy.ops.object.convert(target='MESH')
    hmesh = bpy.context.active_object
    mod = body.modifiers.new("HandleUnion", 'BOOLEAN')
    mod.operation = 'UNION'
    mod.solver = 'EXACT'
    mod.object = hmesh
    apply_mod(body, "HandleUnion")
    bpy.data.objects.remove(hmesh, do_unlink=True)
    try:
        bpy.ops.object.select_all(action='DESELECT')
        body.select_set(True)
        bpy.context.view_layer.objects.active = body
        bpy.ops.object.shade_auto_smooth(angle=math.radians(30.0))
    except Exception:
        bpy.ops.object.shade_smooth()


def gouge(body):
    """C：破坏性误操作——EXACT 刀把杯身前壁削穿（视觉明显残废）。"""
    bpy.ops.mesh.primitive_cube_add(size=0.07, location=(0, -0.045, 0.06))
    killer = bpy.context.active_object
    killer.rotation_euler = (0.35, 0, 0.15)
    mod = body.modifiers.new("Oops", 'BOOLEAN')
    mod.operation = 'DIFFERENCE'
    mod.solver = 'EXACT'
    mod.object = killer
    apply_mod(body, "Oops")
    bpy.data.objects.remove(killer, do_unlink=True)


def fingerprint(ob) -> dict:
    """网格指纹：verts/faces/体积三元组（对账用）。"""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    vol = bm.calc_volume()
    fp = {"verts": len(bm.verts), "faces": len(bm.faces),
          "volume_ml": round(vol * 1e6, 3)}
    bm.free()
    ev.to_mesh_clear()
    return fp


def mesh_sha(ob) -> str:
    """全量坐标哈希（更强对账：逐顶点一致）。"""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    coords = sorted(tuple(round(c, 7) for c in v.co) for v in me.vertices)
    ev.to_mesh_clear()
    blob = json.dumps(coords, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


# ═══════════════════ 场景（复用建模演示的呈现档配置）══════════════════
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
if WAL_PATH.exists():
    WAL_PATH.unlink()          # 每次演示从零开链
wal = WALLog(WAL_PATH)
ledger("rollback:session", "回退演示开始——剧本 A 杯身 → B 把手 → C 误操作 → WAL 重放回退 → 指纹对账")

wld = bpy.data.worlds.new("StudioDark")
wld.use_nodes = True
wld.node_tree.nodes["Background"].inputs[0].default_value = (0.03, 0.03, 0.035, 1.0)
scene.world = wld
bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0, 0, 0))
floor_ob = bpy.context.active_object
fmat = bpy.data.materials.new("FloorMat")
fmat.use_nodes = True
fbsdf = fmat.node_tree.nodes["Principled BSDF"]
fbsdf.inputs["Base Color"].default_value = (0.045, 0.045, 0.05, 1.0)
fbsdf.inputs["Roughness"].default_value = 0.9
floor_ob.data.materials.append(fmat)
try:
    scene.view_settings.view_transform = 'Filmic'
    scene.view_settings.look = 'Medium High Contrast'
    scene.view_settings.exposure = -0.4
except Exception:
    pass


def _area_light(name, energy, loc, size, color=(1.0, 1.0, 1.0)):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy = energy
    ld.size = size
    ld.color = color
    lo = bpy.data.objects.new(name, ld)
    scene.collection.objects.link(lo)
    lo.location = loc


_area_light("PRES_Key", 85.0, (0.42, -0.52, 0.52), 0.25, (1.0, 0.96, 0.90))
_area_light("PRES_Fill", 22.0, (-0.50, -0.30, 0.22), 0.6, (0.85, 0.90, 1.0))
_area_light("PRES_Rim", 260.0, (-0.05, 0.55, 0.42), 0.2, (1.0, 1.0, 1.0))
aim = bpy.data.objects.new("PRES_Aim", None)
scene.collection.objects.link(aim)
aim.location = (0, 0, 0.048)
cam_d = bpy.data.cameras.new("PRES_Cam")
cam_d.lens = 50.0
cam_d.dof.use_dof = True
cam_d.dof.focus_distance = 0.51
cam_d.dof.aperture_fstop = 2.8
pres_cam = bpy.data.objects.new("PRES_Cam", cam_d)
scene.collection.objects.link(pres_cam)
pres_cam.location = (0.30, -0.40, 0.16)
ctc = pres_cam.constraints.new('TRACK_TO')
ctc.target = aim
ctc.track_axis = 'TRACK_NEGATIVE_Z'
ctc.up_axis = 'UP_Y'
scene.camera = pres_cam


def make_mat():
    mat = bpy.data.materials.new("Porcelain")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.93, 0.92, 0.90, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.32
    coat = bsdf.inputs.get("Coat Weight")
    if coat is not None:
        coat.default_value = 0.8
    return mat


PORC = make_mat()
FRAME_DIR.mkdir(parents=True, exist_ok=True)


def snap(ob, name: str) -> str:
    """512² 呈现帧（演示帧，res/samples 减半求速度）。"""
    if ob.data.materials:
        ob.data.materials[0] = PORC
    else:
        ob.data.materials.append(PORC)
    out = FRAME_DIR / f"{name}.png"
    rep = render_presentation(bpy, out, res=(512, 512), samples=32, engine="eevee")
    assert rep["ok"], f"帧 {name} 渲染谓词失败: {rep}"
    return str(out.relative_to(ROOT))


# ═══════════════════ 剧本执行（每步 WAL + 账本）══════════════════
# A 杯身
wal.append("checkpoint", {"stage": "A", "desc": "杯身就绪（树 3.1+1.1+1.3）"})
body = build_body()
wal.append("build.body", {"op": "cone+cavity", "vertices": 192})
fp_a = fingerprint(body)
sha_a = mesh_sha(body)
snap(body, "A")
ledger("rollback:A", f"杯身建好 checkpoint｜指纹 {fp_a}", gate="ROLLBACK")

# B 把手
wal.append("checkpoint", {"stage": "B", "desc": "把手融合（树 2.1-2.4）"})
add_handle(body)
wal.append("build.handle", {"op": "curve_bevel+union", "tube_r_mm": 7})
fp_b = fingerprint(body)
sha_b = mesh_sha(body)
snap(body, "B")
ledger("rollback:B", f"把手融合 checkpoint｜指纹 {fp_b}", gate="ROLLBACK")

# C 破坏性误操作
wal.append("modify.oops", {"op": "cube_gouge", "note": "AI 手滑：刀削穿杯壁"})
gouge(body)
fp_c = fingerprint(body)
sha_c = mesh_sha(body)
snap(body, "C")
ledger("rollback:C", f"误操作落地（演示用）｜指纹 {fp_c}｜verts 变化 {fp_b['verts']}→{fp_c['verts']}",
       gate="ROLLBACK", ok=False)

# D 回退：按 WAL replay 重执行白名单事件（跳过 modify.oops）
events = wal.replay()
replay_builds = [e for e in events if e["kind"].startswith("build.")]
ledger("rollback:replay", f"WAL replay {len(events)} 事件，重执行 {len(replay_builds)} 个 build.*，"
       f"跳过 {[e['kind'] for e in events if e['kind'].startswith('modify.')]}")
bpy.data.objects.remove(body, do_unlink=True)
for e in events:
    if e["kind"] == "build.body":
        body = build_body()
    elif e["kind"] == "build.handle":
        add_handle(body)
fp_d = fingerprint(body)
sha_d = mesh_sha(body)
match_fp = fp_d == fp_b
match_sha = sha_d == sha_b
wal.append("rollback", {"to": "B", "skipped": ["modify.oops"],
                        "fingerprint_match": match_fp, "sha_match": match_sha})
snap(body, "D")
ledger("rollback:D", f"重放回退完成｜指纹 D==B {match_fp}（{fp_d}）｜逐顶点 sha D==B {match_sha}",
       gate="ROLLBACK")
wal.append("checkpoint", {"stage": "D", "desc": "回退后状态 == B"})
chain_ok = wal.verify()
ledger("rollback:verify", f"WAL 哈希链 verify = {chain_ok}（{len(wal.replay())} 事件链）",
       gate="ROLLBACK")

print(f"\n══ ROLLBACK DEMO: fp_match={match_fp} sha_match={match_sha} chain={chain_ok} ══")
print(f"  A {fp_a}  sha={sha_a}")
print(f"  B {fp_b}  sha={sha_b}")
print(f"  C {fp_c}  sha={sha_c}   <- 破坏")
print(f"  D {fp_d}  sha={sha_d}   == B ?")
out = {
    "script": "A body -> B handle -> C oops(gouge) -> replay(skip oops) -> D == B",
    "frames": {k: f"showcase/rollback/{k}.png" for k in "ABCD"},
    "fingerprints": {"A": fp_a, "B": fp_b, "C": fp_c, "D": fp_d},
    "sha16": {"A": sha_a, "B": sha_b, "C": sha_c, "D": sha_d},
    "fingerprint_match": match_fp, "sha_match": match_sha,
    "wal_chain_ok": chain_ok, "wal_events": len(wal.replay()),
    "wal_path": str(WAL_PATH.relative_to(ROOT)),
}
RESULT.parent.mkdir(parents=True, exist_ok=True)
RESULT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("result ->", RESULT.name)
