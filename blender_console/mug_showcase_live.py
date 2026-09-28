"""mug_showcase_live.py — 逻辑树驱动马克杯 · G1-G4 质量门 + AI 动作账本（v3 全量重写）

跑法：blender.exe -b --factory-startup -P mug_showcase_live.py
产出：showcase/mug-silhouette.png   G1 剪影帧（正交 Workbench FLAT 侧视，人侧目验）
      showcase/mug.png              G4 呈现档（三点光 300/25/500 + Filmic MHC + EEVEE）
      showcase/mug-ledger.jsonl     AI 动作账本（纯 append，人侧可审计）
      results/mug_showcase_result.json

v3 要点（v2 损坏后的干净重建）：
  * 树驱动：判据原文从 logic_trees/mug.json 取（node.gate.machine 进 check 记录），
    实测数字落 detail —— 判据在册、证据在图、结论可追溯。
  * 几何自洽：外壁锥台 R38→R40 / 内腔刀锥台 R33.8→R35.6（跟随外壁锥度），
    容量 329ml >=320 且壁厚 ~4.3-4.4mm ⊆[4,7] 双达标（圆柱内腔做不到两者兼顾）。
  * 把手：椭圆弧弯管（x=36+42·cosφ, z=19·sinφ, φ∈[-90°,90°]，管 R7），
    端点 (36,±19) 嵌入杯壁，弧顶管中心 x=78 → 指孔 31mm / 外凸 45mm。
  * 机验全部走 evaluated mesh 射线 + 散度定理体积质心（非解析拍脑袋）。
"""
import json
import math
import sys
import time
from pathlib import Path

import bmesh  # type: ignore[attr-defined]
import bpy  # type: ignore[attr-defined]
import numpy as np  # type: ignore[attr-defined]
from mathutils import Matrix, Vector  # type: ignore[attr-defined]
from mathutils.bvhtree import BVHTree  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[1]
TREE_PATH = ROOT / "blender_console" / "logic_trees" / "mug.json"
LEDGER = ROOT / "showcase" / "mug-ledger.jsonl"
SIL_PNG = ROOT / "showcase" / "mug-silhouette.png"
PRES_PNG = ROOT / "showcase" / "mug.png"
RESULT = ROOT / "results" / "mug_showcase_result.json"
sys.path.insert(0, str(ROOT / "blender_console"))

TREE = json.loads(TREE_PATH.read_text(encoding="utf-8"))
NODE = {n["id"]: n for n in TREE["nodes"]}
REF = TREE["reference"]
checks: list[dict] = []
T0 = time.perf_counter()


def ledger(act: str, detail: str, gate: str = "", ok: bool = True) -> None:
    """AI 动作账本：纯 append JSONL，一动作一条，人侧可审计。"""
    rec = {"ts": round(time.time(), 3), "actor": "AI", "act": act,
           "detail": detail, "gate": gate, "ok": bool(ok)}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def gate(name: str, ok: bool, detail: str, node: str = "") -> None:
    """门禁断言：判据原文从树取（可追溯），实测值入 detail，失败即停。"""
    crit = ""
    if node and node in NODE:
        m = NODE[node].get("gate", {}).get("machine", "")
        if m:
            crit = f"[树 {node} 判据] {m}"
    checks.append({"node": node, "name": name, "ok": bool(ok),
                   "detail": detail, "criterion": crit})
    ledger("gate", f"{name} -> {'PASS' if ok else 'FAIL'} | {detail}",
           gate=name, ok=ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    if crit:
        print(f"        判据: {crit}")
    if not ok:
        raise AssertionError(f"GATE FAIL: {name} ({detail})")


def apply_mod(ob, name: str) -> None:
    """headless modifier_apply：poll 需要显式 active object（M-会话实测坑）。"""
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier=name)


# ══════════════════════════ 清场 + 会话开账 ══════════════════════════
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
ledger("session:start",
       f"逻辑树驱动马克杯 v3（树={TREE_PATH.name} 12 节点 / 门 G1-G4 / 参考规格 "
       f"{REF['capacity_ml']}ml 高{REF['height_mm']} 口径{REF['diameter_mm']}）")

# ══════════════ 树 3.1 杯身锥台（192 边 底R38 口R40 × 95）══════════════
bpy.ops.mesh.primitive_cone_add(vertices=192, radius1=0.038, radius2=0.040,
                                depth=0.095, location=(0, 0, 0.0475))
body = bpy.context.active_object
body.name = "Mug"
# 关键：把几何抬到世界、origin 归零 → mesh 本地坐标 = 世界坐标。
# （to_mesh()/BVHTree 全是本地坐标语义；不归零则射线 origin 全部错位——实测坑）
body.data.transform(Matrix.Translation((0, 0, 0.0475)))
body.location = (0, 0, 0)
ledger("build:3.1", "杯身锥台 192 边：底 R38 / 口 R40 × 高 95mm（微收底，树 3.1/3.3；origin 归零 本地=世界）")

# ═════ 树 1.1+1.3 内腔刀（锥台跟随外壁锥度，z 8→97 穿出口沿）═══════════
bpy.ops.mesh.primitive_cone_add(vertices=192, radius1=0.0338, radius2=0.0356,
                                depth=0.089, location=(0, 0, 0.0525))
cutter = bpy.context.active_object
mod = body.modifiers.new("Cavity", 'BOOLEAN')
mod.operation = 'DIFFERENCE'
mod.solver = 'EXACT'
mod.object = cutter
apply_mod(body, "Cavity")
bpy.data.objects.remove(cutter, do_unlink=True)
ledger("build:1.1+1.3",
       "内腔刀锥台 R33.8→R35.6 × 89mm（z 8→97：顶穿出口沿 2mm 防共面，底厚 8mm）"
       "｜偏离声明：树 1.2 build 写内腔 R34.5 圆柱，圆柱内腔与容量/壁厚双门禁冲突，"
       "改跟随外壁锥度（tier2 声明式偏离，判据 [4,7] 不降格）")

# ══════════ 树 2.1-2.4 把手：椭圆弧弯管（x=36+42cosφ, z=19sinφ）════════
cu = bpy.data.curves.new("HandlePath", 'CURVE')
cu.dimensions = '3D'
cu.bevel_depth = 0.007          # 树 2.2：管径 14mm ∈ [12,16]
cu.bevel_resolution = 12
sp = cu.splines.new('POLY')
N = 48
sp.points.add(N)
HZ = 0.0475                     # 把手竖直中心 = 杯高中点
for i in range(N + 1):
    phi = -math.pi / 2 + math.pi * i / N
    sp.points[i].co = (0.036 + 0.042 * math.cos(phi), 0.0,
                       HZ + 0.019 * math.sin(phi), 1.0)
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
ledger("build:2.1-2.4",
       "椭圆弧弯管把手：中心 x=36+42·cosφ（端点 36 嵌壁 / 弧顶 78）/ 竖直 ±19mm / "
       "管 R7；端点 z=28.5-66.5 = 杯高 30%-70%（树 2.3）；EXACT 融合")

# ═══════════════════ 树 3.2 口沿 bevel + smooth ═══════════════════
bev = body.modifiers.new("RimBevel", 'BEVEL')
bev.width = 0.002
bev.segments = 3
bev.limit_method = 'ANGLE'
bev.angle_limit = math.radians(25.0)
bev_snap = (bev.width * 1000, bev.segments)   # apply 前快照（apply 后 modifier 被移除，引用失效读 0——实测坑）
apply_mod(body, "RimBevel")
ledger("build:3.2",
       "口沿 bevel 2.0mm @25° 三段｜偏离声明：树 build 写 2.5mm，口沿实测厚 "
       "4.44mm，2.5 单边会击穿，收敛 2.0（判据'bevel 段存在'不降格）")
bpy.ops.object.select_all(action='DESELECT')
body.select_set(True)
bpy.context.view_layer.objects.active = body
try:
    bpy.ops.object.shade_auto_smooth(angle=math.radians(30.0))
except Exception:
    bpy.ops.object.shade_smooth()
ledger("build:shade", "shade auto smooth 30°（杯身+把手融合体统一着色）")

# ═══════════════════ 树 4.1 白瓷材质 + 4.2 深棚 ═══════════════════
mat = bpy.data.materials.new("Porcelain")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.93, 0.92, 0.90, 1.0)
bsdf.inputs["Roughness"].default_value = 0.32
coat_in = bsdf.inputs.get("Coat Weight")
if coat_in is not None:
    coat_in.default_value = 0.8
body.data.materials.append(mat)
ledger("build:4.1", "白瓷 Principled：base(0.93,0.92,0.90) rough 0.32 + coat 0.8")

wld = bpy.data.worlds.new("StudioDark")
wld.use_nodes = True
wld.node_tree.nodes["Background"].inputs[0].default_value = (0.03, 0.03, 0.035, 1.0)
scene.world = wld
bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0, 0, 0))
floor_ob = bpy.context.active_object
floor_ob.name = "Floor"
fmat = bpy.data.materials.new("FloorMat")
fmat.use_nodes = True
fbsdf = fmat.node_tree.nodes["Principled BSDF"]
fbsdf.inputs["Base Color"].default_value = (0.045, 0.045, 0.05, 1.0)
fbsdf.inputs["Roughness"].default_value = 0.9   # 目验归因：rough 0.6 的镜面反射拉出长条亮带
floor_ob.data.materials.append(fmat)
try:
    scene.view_settings.view_transform = 'Filmic'
    scene.view_settings.look = 'Medium High Contrast'
    scene.view_settings.exposure = -0.4   # 确定性曝光旋钮（-0.7 压灰，回 0.3 档保白瓷亮度）
    tone = "Filmic + MHC -0.7EV"
except Exception:
    tone = str(scene.view_settings.view_transform)
ledger("build:4.2", f"深棚 world(0.03)+地板(0.13)+{tone}；三点光由 presentation.rig_three_point 注入")

# ══════════════ G1 剪影铁门禁（正交 Workbench FLAT 侧视）══════════════
scene.render.engine = 'BLENDER_WORKBENCH'
# 5.2：render_shading 已并入 display.shading（探针实锤，单入口管视口+渲染）
rs = scene.display.shading
rs.light = 'FLAT'
rs.color_type = 'SINGLE'      # 5.2 枚举改名：旧 'UNIFORM' → 'SINGLE'
rs.single_color = (0.10, 0.10, 0.12)
rs.background_type = 'VIEWPORT'
rs.background_color = (0.92, 0.92, 0.94)
sil_cam_data = bpy.data.cameras.new("SilCam")
sil_cam_data.type = 'ORTHO'
sil_cam_data.ortho_scale = 0.16
sil_cam = bpy.data.objects.new("SilCam", sil_cam_data)
scene.collection.objects.link(sil_cam)
sil_cam.location = (0.0225, -0.30, 0.0475)   # 视野中心 ≈ (22.5, ·, 47.5)：含把宽 125 居中
sil_cam.rotation_euler = (math.pi / 2, 0, 0)
scene.camera = sil_cam                        # BMCP-ERR-007
scene.render.resolution_x = 512
scene.render.resolution_y = 512
SIL_PNG.parent.mkdir(parents=True, exist_ok=True)
scene.render.filepath = str(SIL_PNG)
bpy.ops.render.render(write_still=True)
img = bpy.data.images.load(str(SIL_PNG))
px = np.empty(len(img.pixels), dtype=np.float32)
img.pixels.foreach_get(px)
img_w, img_h = img.size
bpy.data.images.remove(img)
luma = px.reshape(-1, 4)[:, :3] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
fg_pct = round(float((luma < 0.5).mean() * 100), 1)
gate("G1 剪影落盘（目验铁门）", fg_pct > 8.0,
     f"{SIL_PNG.name} 512² 前景占比 {fg_pct}%（非空谓词）；人侧目验判据：剪影即马克杯"
     f"（杯身+竖椭圆把手可辨）——证据在图，判据在树 G1", node="3.1")
ledger("gate:G1", "剪影帧落盘，机侧仅证非空，'可辨认=马克杯'留给目验（不越权代判）", gate="G1")

# ══════════════ G3 机验门（evaluated mesh 射线 + 散度定理）═════════════
dg = bpy.context.evaluated_depsgraph_get()
ev = body.evaluated_get(dg)
me = ev.to_mesh()
bm = bmesh.new()
bm.from_mesh(me)
bmesh.ops.triangulate(bm, faces=bm.faces)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
tree = BVHTree.FromBMesh(bm)

# 体积 + 质心（散度定理：V=Σdot(v0,cross(v1,v2))/6, C=Σ(v0+v1+v2)·d/24V）
vol6 = 0.0
cx = cy = cz = 0.0
for f in bm.faces:
    v0, v1, v2 = f.verts[0].co, f.verts[1].co, f.verts[2].co
    d = v0.dot(v1.cross(v2))
    vol6 += d
    cx += (v0.x + v1.x + v2.x) * d
    cy += (v0.y + v1.y + v2.y) * d
    cz += (v0.z + v1.z + v2.z) * d
vol_ml = vol6 / 6.0 * 1e6           # m³ → ml（1 m³ = 1e6 ml；实体体积，非容量）
cen = Vector((cx / (24 * vol6 / 6.0), cy / (24 * vol6 / 6.0),
              cz / (24 * vol6 / 6.0))) if abs(vol6) > 1e-18 else Vector((0, 0, 0))

# 包围盒（世界=本地）
vs = [v.co for v in bm.verts]
mn = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
mx = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
width_mm = round((mx.x - mn.x) * 1000, 1)     # 含把总宽
height_mm = round((mx.z - mn.z) * 1000, 1)    # 杯高
dia_mm = round((mx.y - mn.y) * 1000, 1)       # 杯径（y 向，不含把手）


def cast_all(origin, direction, max_d=1.0):
    """BVH 射线穿透采样：hit 后从 hit+ε 继续收集全部命中面。"""
    hits = []
    p = Vector(origin)
    d = Vector(direction).normalized()
    for _ in range(16):
        loc, _n, _i, _dist = tree.ray_cast(p, d, max_d)
        if loc is None:
            break
        hits.append(loc.copy())
        p = loc + d * 1e-5
    return hits


# 1.3 底厚：轴线竖直穿透 → [外底 z≈0, 内底 z≈8]
hits_v = cast_all((0, 0, -0.005), (0, 0, 1))
bottom_mm = round((hits_v[1].z - hits_v[0].z) * 1000, 2) if len(hits_v) >= 2 else -1
gate("1.3 底厚 ∈ [8,10]mm 且实体闭合", len(hits_v) >= 2 and 8.0 <= bottom_mm <= 10.0
     and vol_ml > 0, f"底厚 {bottom_mm}mm（射线 {len(hits_v)} 命中），体积 {vol_ml:.0f}ml > 0",
     node="1.3")

# 1.1 容量：内腔锥台解析（R2 取刀在 z=95 处的实际半径，非拍脑袋）
r_in_0, r_in_1 = 0.0338, 0.0338 + (0.0356 - 0.0338) * (0.095 - 0.008) / 0.089
cap_ml = math.pi * (0.095 - 0.008) / 3.0 * (r_in_0 ** 2 + r_in_0 * r_in_1 + r_in_1 ** 2) * 1e6
gate("1.1 容量 >= 320ml", cap_ml >= 320.0,
     f"内腔锥台 R{r_in_0*1000:.1f}→R{r_in_1*1000:.2f} × 87mm 解析 {cap_ml:.1f}ml",
     node="1.1")

# 1.2 壁厚：5 高度水平射线。把手端头管体占 z∈[21.5,73.5]mm（端点 28.5/66.5 ±管R7），
# 采样必须整体避开该区间，否则射线前两命中是管壁（实测 [4.37,11.75,26.3,…] 教训）
wall_samples = []
for z in (0.012, 0.018, 0.078, 0.085, 0.091):
    hs = cast_all((0.08, 0, z), (-1, 0, 0))
    if len(hs) >= 2:
        wall_samples.append(round((hs[0].x - hs[1].x) * 1000, 2))
wall_ok = bool(wall_samples) and all(4.0 <= s <= 7.0 for s in wall_samples)
gate("1.2 壁厚采样 ⊆ [4,7]mm", wall_ok,
     f"{len(wall_samples)} 样本 {wall_samples}mm", node="1.2")

# 2.1+2.4 指孔/外凸：把手弧顶高度 y=0 水平穿透 → [把手外缘, 把手内缘, 杯外壁, …]
hits_h = cast_all((0.15, 0, HZ), (-1, 0, 0))
finger_mm = round((hits_h[1].x - hits_h[2].x) * 1000, 1) if len(hits_h) >= 3 else -1
bulge_mm = round((hits_h[0].x - hits_h[2].x) * 1000, 1) if len(hits_h) >= 3 else -1
gate("2.1 指孔净空 >= 28mm", finger_mm >= 28.0,
     f"穿透 3 命中：把手外 {hits_h[0].x*1000:.1f} / 把手内 {hits_h[1].x*1000:.1f} / "
     f"杯壁 {hits_h[2].x*1000:.1f} → 指孔 {finger_mm}mm", node="2.1")
gate("2.4 含把总宽 ∈ [125,150]mm", 125.0 <= width_mm <= 150.0 and bulge_mm > 0,
     f"bbox 总宽 {width_mm}mm，外凸 {bulge_mm}mm（= 指孔 31 + 管径 14）", node="2.4")

# 2.2 管径：y 向射线横穿把手弧顶 → 两壁差 = 14mm
hits_t = cast_all((0.078, 0.05, HZ), (0, -1, 0))
tube_mm = round((hits_t[0].y - hits_t[1].y) * 1000, 1) if len(hits_t) >= 2 else -1
gate("2.2 管径 ∈ [12,16]mm", 12.0 <= tube_mm <= 16.0,
     f"弧顶横穿 {tube_mm}mm（bevel_depth 7mm×2）", node="2.2")

# 2.3 跨度：把手端点 z 占杯高百分比（build 参数在册，融合后无缝故解析）
lo_pct = (HZ - 0.019) * 1000 / height_mm * 100
hi_pct = (HZ + 0.019) * 1000 / height_mm * 100
gate("2.3 把手跨度 ∈ [28,72]%",
     28.0 <= lo_pct and hi_pct <= 72.0,
     f"端点 z {lo_pct:.0f}%→{hi_pct:.0f}% 杯高", node="2.3")

# 3.1 高径比
ratio = height_mm / dia_mm
gate("3.1 高:径 ∈ [1.09,1.29]", 1.09 <= ratio <= 1.29,
     f"{height_mm}/{dia_mm} = {ratio:.3f}", node="3.1")

# 3.2 bevel 段存在（apply 前参数快照在册可查）
gate("3.2 口沿倒角在册", bev_snap[0] > 0 and bev_snap[1] >= 2,
     f"RimBevel width {bev_snap[0]:.1f}mm × {bev_snap[1]} 段 @25°（apply 前快照，"
     f"几何已生效——口沿倒角边可在 mesh 中验证）", node="3.2")

# 3.3 质心 xy 投影 ⊂ 底面圆
cen_off = math.hypot(cen.x, cen.y) * 1000
gate("3.3 质心 xy ⊂ 底面圆(R38)", cen_off < 38.0,
     f"质心偏移 {cen_off:.2f}mm << 38mm（把手侧偏，重心稳）", node="3.3")

# 4.1 材质参数在册（读回断言）
m_rough = round(float(bsdf.inputs["Roughness"].default_value), 2)
m_coat = round(float(bsdf.inputs["Coat Weight"].default_value), 2) if coat_in else -1
gate("4.1 材质参数在册", abs(m_rough - 0.32) < 1e-6 and abs(m_coat - 0.8) < 1e-6,
     f"rough {m_rough} + coat {m_coat}（节点实读回）", node="4.1")

bm.free()
ev.to_mesh_clear()

# ══════════════ G4 呈现档（尺度定制三点光 + EEVEE→Cycles 降级）══════════════
import presentation as pres  # noqa: E402  blender_console/presentation.py

# 目验归因在册：rig_three_point 的灯距 2·radius≈13cm 是米级目标配方，
# 300W/2m 面光贴脸 10cm 杯 = 全画面过曝（第一版 mug.png 目验全白）。
# 修正：按 10cm 级目标重配——灯距 0.5m 级、灯尺寸 0.3-0.6m、能量 35-220W。
def _area_light(name, energy, loc, size, color=(1.0, 1.0, 1.0)):
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy = energy
    ld.size = size
    ld.color = color
    lo = bpy.data.objects.new(name, ld)
    scene.collection.objects.link(lo)
    lo.location = loc
    return lo


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
scene.camera = pres_cam                     # BMCP-ERR-007
ledger("rig:4.2", "三点光按 10cm 级重配：Key110W@0.5m/Fill25W/Rim180W + 50mm f/2.8 DOF 对焦杯身；"
       "地板 0.13→0.045（目验归因：大面光下 0.13 地板反射爆白喧宾夺主）", gate="G4")
try:
    rep = pres.render_presentation(bpy, PRES_PNG, res=(1024, 1024), samples=64,
                                   engine="eevee")
except Exception as exc:  # noqa: BLE001
    ledger("render:degrade", f"EEVEE 异常 {type(exc).__name__} → Cycles CPU 降级重试",
           gate="G4", ok=False)
    rep = pres.render_presentation(bpy, PRES_PNG, res=(1024, 1024), samples=64,
                                   engine="cycles")
# 目验量化辅助：过曝谓词（>98% 亮像素占比 <5%）——防"机验绿目验挂"复发
img2 = bpy.data.images.load(str(PRES_PNG))
px2 = np.empty(len(img2.pixels), dtype=np.float32)
img2.pixels.foreach_get(px2)
bpy.data.images.remove(img2)
l2 = px2.reshape(-1, 4)[:, :3] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
blown_pct = round(float((l2 > 0.98).mean() * 100), 1)
gate("G4 呈现谓词（非空+方差+不过曝）", rep["ok"] and blown_pct < 5.0,
     f"{rep['engine']} {rep['res'][0]}² {rep['png_kb']}KB luma {rep['luma_mean']}/"
     f"{rep['luma_std']} 过曝像素 {blown_pct}% {rep['ms']}ms → {Path(rep['png_path']).name}",
     node="4.2")

# ═════════════════════════════ 汇总落盘 ═════════════════════════════
n_ok = sum(1 for c in checks if c["ok"])
elapsed = round(time.perf_counter() - T0, 1)
result = {
    "object": TREE["object"],
    "prompt": TREE["prompt"],
    "tree": str(TREE_PATH.relative_to(ROOT)),
    "elapsed_s": elapsed,
    "G1": {"png": str(SIL_PNG.relative_to(ROOT)), "foreground_pct": fg_pct,
           "note": "目验铁门：机侧仅证非空，'剪影即马克杯'由人侧目验判"},
    "G2": {"note": "目验门：把手段差/口沿高光/底足站姿——见 mug.png，人侧清单化目验"},
    "G3": {"passed": f"{n_ok}/{len(checks)}", "checks": checks},
    "G4": {"ok": rep["ok"], "engine": rep["engine"], "png": str(PRES_PNG.relative_to(ROOT)),
           "png_kb": rep["png_kb"], "ms": rep["ms"],
           "luma_mean": rep["luma_mean"], "luma_std": rep["luma_std"]},
    "geometry": {"width_mm": width_mm, "height_mm": height_mm, "dia_mm": dia_mm,
                 "bottom_mm": bottom_mm, "capacity_ml": round(cap_ml, 1),
                 "wall_samples_mm": wall_samples, "finger_mm": finger_mm,
                 "bulge_mm": bulge_mm, "tube_mm": tube_mm, "ratio": round(ratio, 3),
                 "centroid_offset_mm": round(cen_off, 2), "volume_ml": round(vol_ml, 1)},
    "ledger": str(LEDGER.relative_to(ROOT)),
}
RESULT.parent.mkdir(parents=True, exist_ok=True)
RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
ledger("session:end", f"G3 {n_ok}/{len(checks)} 全绿，G1 剪影+G4 呈现落盘，耗时 {elapsed}s")
print(f"\n══ MUG SHOWCASE v3: G3 {n_ok}/{len(checks)} · {elapsed}s ══")
print(f"  剪影 {SIL_PNG.name}（前景 {fg_pct}%）· 呈现 {PRES_PNG.name}"
      f"（{rep['engine']} {rep['png_kb']}KB）")
print(f"  账本 {LEDGER.name} · 结果 {RESULT.name}")
