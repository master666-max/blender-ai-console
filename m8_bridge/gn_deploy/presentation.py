"""presentation.py — M7-3 呈现档 · 三点布光 + 相机 rig（M8-R4 素材转正）
================================================================================

来源：M8-R4 吸收隔离区 fragments/three_point_rig.py（skill v1.0 E2E PASS，
1280x720 EEVEE 出图回读验证）。与上游版本的差异：
  * 幂等清场按 prefix（源码同名硬删——保留语义，扩为前缀批量）
  * 返回结构化 report dict（不是 print）——调用方（console/WAL）消费
  * 机位按目标半径自适应（源码固定 (7,-7,4) 只适合米级目标）
  * 渲染后**恢复 engine / scene.camera / film_transparent**——M9-3 互证铁律：
    呈现档是"给人看的交付帧"，diff 管线是"给机器看的确定性帧"，两档并存
    但呈现档不得污染 diff 状态（Workbench + ConsoleDiffCam 冻结机位）。

吸收教训：
  * BMCP-ERR-007：视口截图非确定性——rig 后必须设 scene.camera 再渲染。
  * Workbench 引擎吃不到场景灯（STUDIO 视口光）——呈现档必须切 EEVEE
    （5.2 引擎 id 'BLENDER_EEVEE_NEXT'，4.2 前旧 id 探测兜底）。
  * DOF focus_object 挂 Aim 空物体（TRACK_TO 同目标）——机位动焦点不动。

呈现档语义（M7-3）：deliver 阶段的 T3 目验帧 = 三灯塑形 + 50mm 浅景深，
与 diff 帧正交（diff 帧管"哪里变了"，呈现帧管"看起来怎么样"）。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

__all__ = ["rig_three_point", "render_presentation", "PRESENTATION_PREFIX"]

PRESENTATION_PREFIX = "PRES_"


def _bbox_center_radius(bpy, obj) -> tuple[tuple[float, float, float], float]:
    """包围盒中心/半径（世界空间，源码 aim_of_object 逻辑）。"""
    from mathutils import Vector
    bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    center = (sum(v.x for v in bb) / 8.0,
              sum(v.y for v in bb) / 8.0,
              sum(v.z for v in bb) / 8.0)
    radius = max((Vector(p) - Vector(center)).length for p in bb) or 1e-3
    return center, radius


def rig_three_point(bpy, target_obj, prefix: str = PRESENTATION_PREFIX,
                    key_e: float = 150.0, fill_e: float = 40.0,
                    rim_e: float = 100.0, cam_pos=None,
                    lens: float = 50.0, dof_fstop: float = 2.8) -> dict[str, Any]:
    """三点布光 + 相机 rig（幂等：prefix 清场重建）。

    Key 暖光(1.0,0.95,0.88) 右前上 / Fill 冷光(0.85,0.9,1.0) 左前 /
    Rim 白光 正后方——源配方 150/40/100W。相机 TRACK_TO Aim + DOF f/2.8，
    scene.camera 必设（BMCP-ERR-007）。
    """
    names = [prefix + n for n in ("Key", "Fill", "Rim", "Cam", "Aim")]
    for name in names:
        old = bpy.data.objects.get(name)
        if old is not None:
            bpy.data.objects.remove(old, do_unlink=True)

    center, radius = _bbox_center_radius(bpy, target_obj)
    scene = bpy.context.scene
    if scene.collection.objects.get(target_obj.name) is None:
        scene.collection.objects.link(target_obj)

    def _light(name, energy, loc, size, color):
        ld = bpy.data.lights.new(name, type='AREA')
        ld.energy = energy
        ld.shape = 'SQUARE'
        ld.size = size
        ld.color = color
        lo = bpy.data.objects.new(name, ld)
        scene.collection.objects.link(lo)
        lo.location = loc
        return lo

    cx, cy, cz = center
    _light(prefix + "Key", key_e, (cx + 2.0 * radius, cy - 2.0 * radius, cz + 2.0 * radius),
           2.0, (1.0, 0.95, 0.88))
    _light(prefix + "Fill", fill_e, (cx - 2.0 * radius, cy - 1.5 * radius, cz + 1.0 * radius),
           3.0, (0.85, 0.9, 1.0))
    _light(prefix + "Rim", rim_e, (cx, cy + 2.5 * radius, cz + 1.5 * radius),
           1.0, (1.0, 1.0, 1.0))

    aim = bpy.data.objects.new(prefix + "Aim", None)
    scene.collection.objects.link(aim)
    aim.location = center

    cam_data = bpy.data.cameras.new(prefix + "Cam")
    cam_data.lens = lens
    cam_data.dof.use_dof = True
    cam_data.dof.focus_object = aim
    cam_data.dof.aperture_fstop = dof_fstop
    cam = bpy.data.objects.new(prefix + "Cam", cam_data)
    scene.collection.objects.link(cam)
    if cam_pos is None:
        from mathutils import Vector
        direction = Vector((1.0, -1.0, 0.55)).normalized()
        cam.location = Vector(center) + direction * (radius * 3.2 + 0.5)
    else:
        cam.location = cam_pos
    ctc = cam.constraints.new('TRACK_TO')
    ctc.target = aim
    ctc.track_axis = 'TRACK_NEGATIVE_Z'
    ctc.up_axis = 'UP_Y'
    scene.camera = cam          # BMCP-ERR-007：不设这个渲染报 No camera found
    return {"key": prefix + "Key", "fill": prefix + "Fill", "rim": prefix + "Rim",
            "camera": prefix + "Cam", "aim": prefix + "Aim",
            "center": [round(x, 4) for x in center], "radius": round(radius, 4),
            "dof_fstop": dof_fstop, "lens": lens}


def _pick_eevee(bpy) -> str:
    """5.2 引擎 id 探测（EEVEE Next 改名 'BLENDER_EEVEE_NEXT'）。"""
    for eid in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
        try:
            bpy.context.scene.render.engine = eid
            return eid
        except TypeError:
            continue
    raise ValueError("本机 Blender 无可用 EEVEE 引擎 id")


def render_presentation(bpy, png_path: str | Path,
                        res: tuple[int, int] = (1280, 720),
                        samples: int = 32,
                        engine: str = "eevee") -> dict[str, Any]:
    """呈现档渲染：切引擎 → 渲一帧 → 像素回读 → **恢复 diff 管线状态**。

    engine="eevee"（默认，5.2 id 探测）| "cycles"（CPU 兜底——headless 无
    GL 上下文时 EEVEE 会挂，调方降级重试）。恢复项（M9-3 互证）：
    render.engine / scene.camera / film_transparent / resolution。
    返回机验谓词（非空 + 有方差）——呈现帧也过 verifier's law。
    """
    import numpy as np
    scene = bpy.context.scene
    saved = {"engine": str(scene.render.engine),
             "camera": scene.camera,
             "film": scene.render.film_transparent,
             "res_x": scene.render.resolution_x,
             "res_y": scene.render.resolution_y,
             "pct": scene.render.resolution_percentage}
    used = engine
    if engine == "cycles":
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'
        scene.cycles.samples = samples
    else:
        used = _pick_eevee(bpy)
    try:
        if hasattr(scene, "eevee"):
            scene.eevee.taa_render_samples = samples
        scene.render.film_transparent = False   # 呈现帧要实底（浅景深氛围）
        scene.render.resolution_x, scene.render.resolution_y = res
        scene.render.resolution_percentage = 100
        png_path = Path(png_path)
        png_path.parent.mkdir(parents=True, exist_ok=True)
        scene.render.filepath = str(png_path)
        t0 = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        ms = (time.perf_counter() - t0) * 1000
        img = bpy.data.images.load(str(png_path))
        px = np.empty(len(img.pixels), dtype=np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(-1, 4)
        bpy.data.images.remove(img)
        luma = px[:, :3] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
        return {"ok": bool(luma.mean() > 0.01 and luma.std() > 0.005),
                "engine": used, "png_path": str(png_path),
                "png_kb": round(png_path.stat().st_size / 1024, 1),
                "ms": round(ms, 1), "res": list(res),
                "luma_mean": round(float(luma.mean()), 4),
                "luma_std": round(float(luma.std()), 4),
                "predicates": {"not_black": bool(luma.mean() > 0.01),
                               "has_variance": bool(luma.std() > 0.005)}}
    finally:
        # M9-3 互证：无论成败都还原 diff 管线状态
        scene.render.engine = saved["engine"]
        scene.camera = saved["camera"]
        scene.render.film_transparent = saved["film"]
        scene.render.resolution_x = saved["res_x"]
        scene.render.resolution_y = saved["res_y"]
        scene.render.resolution_percentage = saved["pct"]
