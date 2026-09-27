"""m64_lpips_live.py — M6-4 LPIPS 视觉多样性标定 · 渲染侧（R7h）

跑法：blender.exe -b --factory-startup -P m64_lpips_live.py
产出：results/_m64_lpips_renders/<variant>_az<k>.png（8 变体 × 8 方位角 = 64 帧）
      results/m64_lpips_render_result.json（28 对几何 V + 渲染清单）

分工（torch 不进 Blender——自带 Python 是 embedded 环境不污染）：
  本脚本（Blender 内）：清场 → 8 变体重建（与 m64_offline_calib.py 完全同 spec：
  同 primitive 参数 / 同 REMESH VOXEL 0.015 / 同 cube2 bevel 0.06）→ 128³ 体素
  几何距离 V（28 对，口径同 v2.14）→ Workbench 8 方位角渲染 64 PNG。
  m64_lpips_score.py（项目 venv python + torch）：LPIPS(alex) 两两打分 →
  8 视角均值 L → Spearman(V, L) 对账 + 近/远分离 → m64_lpips_result.json。

踩坑预埋（前辈会话实锤）：
  * read_factory_settings 必须是首动作且之前不持有任何 depsgraph 引用
    （否则 factory 重置销毁 view layer → 原生 EXCEPTION_ACCESS_VIOLATION 段错误）。
  * use_empty=True 顺手清掉默认 Cube——渲染会入镜（度量不受影响但画面受）。
  * 8 变体同场会互相入镜 → hide_render 全遮，渲染谁亮谁。
  * --factory-startup 下 primitive ops 不收 name kwarg（5.2 实锤）→ 建后改名。
"""
import json
import math
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

import bpy
import bmesh
from mathutils import Vector

RESULTS = ROOT / "results"
REN_DIR = RESULTS / "_m64_lpips_renders"
RES = 128          # 几何体素分辨率（与 m64_offline_calib 同口径）
VIEWS = 8          # 方位角数（工单口径：8 视角）
ELEV_DEG = 30.0    # 俯仰角固定
RES_PX = 256       # 渲染分辨率（与 render_diff.py 同口径）
checks: list[dict] = []


def check(name, fn):
    rec = {"name": name}
    try:
        rec["ok"] = True
        rec["detail"] = fn()
        print(f"  PASS  {name}  {str(rec['detail'])[:140]}")
    except Exception as e:  # noqa: BLE001
        rec["ok"] = False
        rec["error"] = f"{type(e).__name__}: {e}"
        print(f"  FAIL  {name}  {type(e).__name__}: {str(e)[:140]}")
    checks.append(rec)


# ── [1] 变体族（与 m64_offline_calib.py 逐字段同源）──────────────
def make_variants():
    """8 变体统一中心摆放、同一尺度级。近邻=同 primitive 参数 ±10%；远邻=跨 primitive。"""
    spec = {
        "cyl":  (bpy.ops.mesh.primitive_cylinder_add, dict(vertices=32, radius=0.5, depth=1.0)),
        "cyl2": (bpy.ops.mesh.primitive_cylinder_add, dict(vertices=32, radius=0.55, depth=1.0)),
        "sph":  (bpy.ops.mesh.primitive_uv_sphere_add, dict(segments=32, ring_count=16, radius=0.5)),
        "sph2": (bpy.ops.mesh.primitive_ico_sphere_add, dict(subdivisions=3, radius=0.52)),
        "cone": (bpy.ops.mesh.primitive_cone_add, dict(vertices=32, radius1=0.5, radius2=0.0, depth=1.0)),
        "cone2": (bpy.ops.mesh.primitive_cone_add, dict(vertices=32, radius1=0.55, radius2=0.0, depth=1.05)),
        "cube": (bpy.ops.mesh.primitive_cube_add, dict(size=0.9)),
        "cube2": (bpy.ops.mesh.primitive_cube_add, dict(size=0.9)),
    }
    objs = {}
    for name, (op, kw) in spec.items():
        op(location=(0, 0, 0), **kw)
        ob = bpy.context.active_object
        ob.name = name
        # REMESH VOXEL：保形 + 均匀表面密集化（SUBSURF 会把 cylinder/cone 端面收缩成球状——首跑实锤）
        rm = ob.modifiers.new("rm", 'REMESH')
        rm.mode = 'VOXEL'
        rm.voxel_size = 0.015
        ob.hide_render = True   # 渲染谁亮谁（同场互不入镜）
        objs[name] = ob
    bev = objs["cube2"].modifiers.new("bev", 'BEVEL')
    bev.width = 0.06
    bev.segments = 3
    return objs


# ── 几何度量（原样搬 m64_offline_calib.py，保证 V 同口径）─────────
def evaluated_mesh_tree(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    mesh = ev.to_mesh()
    bm = bmesh.new()
    bm.from_mesh(mesh)
    tree = __import__("mathutils").bvhtree.BVHTree.FromBMesh(bm)
    verts = [v.co.copy() for v in bm.verts]
    ev.to_mesh_clear()
    return tree, verts, bm


def voxel_solid(tree, origin, cell, dims):
    """128³ solid 体素化：列扫描（每 (x,y) 列 1 条 ray 收集全部穿越 z，奇偶区间填充）。"""
    occ = set()
    for ix in range(dims[0]):
        x = origin[0] + (ix + 0.5) * cell
        for iy in range(dims[1]):
            y = origin[1] + (iy + 0.5) * cell
            z = origin[2] - cell * 2.0
            zs = []
            while True:
                loc, _n, _i, _d = tree.ray_cast(Vector((x, y, z)), Vector((0, 0, 1)), 1e6)
                if loc is None:
                    break
                zs.append(loc.z)
                z = loc.z + 1e-4
            for k in range(0, len(zs) - 1, 2):
                z0, z1 = zs[k], zs[k + 1]
                iz0 = max(0, int((z0 - origin[2]) / cell))
                iz1 = min(dims[2] - 1, int((z1 - origin[2]) / cell))
                for iz in range(iz0, iz1 + 1):
                    occ.add((ix, iy, iz))
    return occ


def jac_dist(a: set, b: set) -> float:
    u = len(a | b)
    return 1.0 - (len(a & b) / u if u else 1.0)


NEAR_PAIRS = [("cyl", "cyl2"), ("sph", "sph2"), ("cone", "cone2"), ("cube", "cube2")]


def geometry_pairs(objs, trees, all_verts):
    lo = [min(v[i] for vs in all_verts.values() for v in vs) for i in range(3)]
    hi = [max(v[i] for vs in all_verts.values() for v in vs) for i in range(3)]
    margin = 0.02
    lo = [lo[i] - margin for i in range(3)]
    hi = [hi[i] + margin for i in range(3)]
    dims = [RES] * 3
    cell = max((hi[i] - lo[i]) / RES for i in range(3))
    origin = tuple(lo[i] for i in range(3))
    vox = {}
    for name in objs:
        vox[name] = voxel_solid(trees[name], origin, cell, dims)
    names = sorted(objs)
    rows = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            v = jac_dist(vox[a], vox[b])
            rows.append({"pair": f"{a}|{b}", "V_voxel128": round(v, 6),
                         "near": (a, b) in NEAR_PAIRS or (b, a) in NEAR_PAIRS})
    meta = {
        "vert_counts": {k: len(all_verts[k]) for k in sorted(objs)},
        "vox_counts": {k: len(vox[k]) for k in sorted(objs)},
        "global_bbox": {"lo": [round(x, 4) for x in lo], "hi": [round(x, 4) for x in hi]},
    }
    return rows, meta


# ── [2] 渲染（确定性口径同 render_diff.py：Workbench + STUDIO + 单色）──
def setup_render(scene):
    scene.render.engine = 'BLENDER_WORKBENCH'
    sh = scene.display.shading
    sh.light = 'STUDIO'
    sh.color_type = 'SINGLE'
    sh.single_color = (0.78, 0.72, 0.65)
    # LPIPS 吃满帧 RGB：不用 film_transparent（alpha 黑底），统一浅灰世界背景
    w = bpy.data.worlds.new("CalibWorld")
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.85, 0.85, 0.85, 1.0)
    scene.world = w
    sh.background_type = 'WORLD'
    scene.render.film_transparent = False
    scene.render.resolution_x = scene.render.resolution_y = RES_PX
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    cd = bpy.data.cameras.new("CalibCam")
    cd.lens = 50
    cd.clip_start = 0.001
    cam = bpy.data.objects.new("CalibCam", cd)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def orbit_frames(scene, cam, objs, center, dist, out_dir):
    """8 方位角 × 8 变体 = 64 帧。机位组对全部变体冻结（同一 bbox 拟合，公平对账）。"""
    el = math.radians(ELEV_DEG)
    frames = []
    t_all = time.perf_counter()
    for name in sorted(objs):
        ob = objs[name]
        ob.hide_render = False
        for k in range(VIEWS):
            az = math.radians(360.0 / VIEWS * k)
            d = Vector((math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el)))
            cam.location = center + d * dist
            cam.rotation_euler = (center - cam.location).to_track_quat('-Z', 'Y').to_euler()
            png = out_dir / f"{name}_az{k:02d}.png"
            scene.render.filepath = str(png)
            t0 = time.perf_counter()
            bpy.ops.render.render(write_still=True)
            frames.append({"variant": name, "az_deg": round(math.degrees(az), 1),
                           "png": png.name, "ms": round((time.perf_counter() - t0) * 1000, 1)})
        ob.hide_render = True
    return frames, round((time.perf_counter() - t_all) * 1000, 1)


# ── 主流程 ────────────────────────────────────────────────────
def run():
    # 首动作清场（exp3 实锤：此前不持有任何 DG 引用）
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    objs = make_variants()
    bpy.context.view_layer.update()

    trees, all_verts = {}, {}
    for name, ob in objs.items():
        tree, verts, bm = evaluated_mesh_tree(ob)
        trees[name] = tree
        all_verts[name] = verts
        bm.free()

    rows, meta = geometry_pairs(objs, trees, all_verts)

    # 相机拟合（全局 bbox，RenderDiffer 同式：dist = r / tan(hfov/2) × margin）
    lo = Vector(meta["global_bbox"]["lo"])
    hi = Vector(meta["global_bbox"]["hi"])
    center = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 1e-3)
    dist = radius / (18.0 / 50.0) * 1.35
    cam = setup_render(scene)
    REN_DIR.mkdir(parents=True, exist_ok=True)
    frames, total_ms = orbit_frames(scene, cam, objs, center, dist, REN_DIR)

    return {
        "n_variants": len(objs), "n_pairs": len(rows), "res": RES,
        "views": VIEWS, "elev_deg": ELEV_DEG, "res_px": RES_PX,
        "cam_dist": round(dist, 4), **meta,
        "pairs": rows,
        "renders_dir": str(REN_DIR.relative_to(ROOT)),
        "n_frames": len(frames), "render_total_ms": total_ms,
        "frames": frames,
    }


check("M6-4 LPIPS 渲染侧：8 变体 + 28 对 V + 64 帧渲染", run)

n_ok = sum(1 for c in checks if c["ok"])
print(f"\nM6-4 LPIPS RENDER SIDE: {n_ok}/{len(checks)} passed")
d = checks[0].get("detail") or {}
if d:
    near = [r["V_voxel128"] for r in d["pairs"] if r["near"]]
    far = [r["V_voxel128"] for r in d["pairs"] if not r["near"]]
    print(f"  64 帧 / {d['render_total_ms']}ms · 近对 V 均值 {sum(near)/len(near):.4f} · 远对 V 均值 {sum(far)/len(far):.4f}")

out = {"suite": "M6-4 LPIPS calibration · render side",
       "passed": n_ok, "total": len(checks), "checks": checks,
       "honest_scope": "本脚本只产 V + PNG；LPIPS 打分与对账在 m64_lpips_score.py（venv torch）"}
RESULTS.mkdir(exist_ok=True)
(RESULTS / "m64_lpips_render_result.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("result ->", RESULTS / "m64_lpips_render_result.json")
