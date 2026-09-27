"""render_diff.py — M9-3 · 段落边界渲染 diff 管线（机械 / 同机位 / 确定性）
====================================================================

北极星锚点：反馈速度（迭代上限 = min(1/定位成本, 1/回退成本)，渲染是反馈链第一环）。
probe_render 实测（Blender 5.2.1 LTS headless，256px）：
  * Workbench 首帧 3158ms（GL 冷启动，一次性）→ 稳态 **17ms/帧**
  * 确定性：同场景重渲 **0 像素差** → diff 门禁零误报
  * 敏感性：参数变化 → 17.7% 像素变化；alpha 通道分离背景 → 目标占比可测

提供：
  * RenderDiffer.render(label)      → 同机位渲染帧（PNG 落盘 + dHash/aHash/占比/方差/耗时）
  * RenderDiffer.render_diff(label) → 渲染 + 对上一帧 diff：changed_ratio + 红色高亮 diff 图（b64 PNG）
  * RenderDiffer.check_predicates   → M2-3 渲染谓词：非空 / 有方差 / 目标占比 / 哈希转移
  * dhash / ahash / hamming         → 纯 numpy 感知哈希（EXP-4 的 pHash 侧），零外部依赖

设计决定：
  * 相机在**首次构造时拟合当前包围盒后冻结**——此后所有帧同机位（M9-5 闪烁 diff 的前提）。
    几何长出画面 = diff 里看得见，这本身是信号，不是缺陷。
  * Workbench + film_transparent：背景 alpha=0 机械可分，不加灯光（STUDIO）。
  * 全部判定是谓词（verifier's law，D7），不给 LLM 打分留位置。
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["RenderDiffer", "dhash", "ahash", "hamming"]


# ══════════════════════════════════════════════════════════════
# 感知哈希（纯 numpy，EXP-4 双分布之一）
# ══════════════════════════════════════════════════════════════
def _luma(px: np.ndarray) -> np.ndarray:
    """px: (N,4) float RGBA（0-1）→ (H,W) 亮度。"""
    size = int(round(px.shape[0] ** 0.5))
    rgb = px[:, :3].reshape(size, size, 3)
    return rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def dhash(px: np.ndarray) -> int:
    """差异哈希：块均降采样到 8×9，横向梯度 → 64 bit。"""
    lum = _luma(px)
    h, w = lum.shape
    bh, bw = h // 8, w // 9
    blocks = lum[:bh * 8, :bw * 9].reshape(8, bh, 9, bw).mean(axis=(1, 3))
    bits = blocks[:, 1:] > blocks[:, :-1]          # 8×8 = 64 bit
    v = 0
    for bit in bits.flatten():
        v = (v << 1) | int(bit)
    return v


def ahash(px: np.ndarray) -> int:
    """均值哈希：块均降采样到 8×8，>均值 → 64 bit。"""
    lum = _luma(px)
    h, w = lum.shape
    bh, bw = h // 8, w // 8
    blocks = lum[:bh * 8, :bw * 8].reshape(8, bh, 8, bw).mean(axis=(1, 3))
    bits = blocks > blocks.mean()
    v = 0
    for bit in bits.flatten():
        v = (v << 1) | int(bit)
    return v


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# ══════════════════════════════════════════════════════════════
# RenderDiffer
# ══════════════════════════════════════════════════════════════
class RenderDiffer:
    """一个会话一个实例：冻结相机 + 上一帧基线 + M2-3 渲染谓词。

    用法（console 内）：
        d = RenderDiffer(bpy, obj, workdir)
        f0 = d.render_diff("初始")     # 首帧 = 基线（无 diff 图）
        f1 = d.render_diff("改把手")   # changed_ratio / diff_b64 / hamming
    """

    def __init__(self, bpy: Any, obj: Any, workdir: Path | str | None = None,
                 res: int = 256, changed_thresh: float = 8 / 255,
                 fit_margin: float = 1.35) -> None:
        self.bpy = bpy
        self.obj = obj
        self.res = res
        self.changed_thresh = changed_thresh
        self.workdir = Path(workdir) if workdir else Path.cwd() / "_console_renders"
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._frame_n = 0
        self._last_px: np.ndarray | None = None
        self._prev_px: np.ndarray | None = None
        self._prev_dhash: int | None = None
        self.cold_start_ms = 0.0
        self._setup_scene()
        self._fit_camera(fit_margin)

    # ── 场景设置（幂等，只跑一次）────────────────────────────
    def _setup_scene(self) -> None:
        scene = self.bpy.context.scene
        scene.render.engine = 'BLENDER_WORKBENCH'
        sh = scene.display.shading
        sh.light = 'STUDIO'
        sh.color_type = 'SINGLE'
        sh.single_color = (0.78, 0.72, 0.65)
        scene.render.film_transparent = True
        scene.render.resolution_x = scene.render.resolution_y = self.res
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = 'PNG'

    def _fit_camera(self, margin: float) -> None:
        """按当前**求值网格顶点**拟合相机并冻结（后续几何变化不再改机位）。

        ⚠️ 不能用 evaluated 对象的 bound_box：GN modifier 生成的几何不一定
        反映进去（实测拿到 ≈零包围盒 → 相机贴到几何中心，画面全废）。
        顶点坐标是 object 局部空间，必须乘 matrix_world。
        """
        from mathutils import Vector
        self.bpy.context.view_layer.update()
        deps = self.bpy.context.evaluated_depsgraph_get()
        ev = self.obj.evaluated_get(deps)
        m = ev.to_mesh()
        if len(m.vertices) == 0:
            ev.to_mesh_clear()
            mn, mx = Vector((-0.05, -0.05, -0.05)), Vector((0.05, 0.05, 0.05))
        else:
            mw = ev.matrix_world
            world = [mw @ v.co for v in m.vertices]
            mn = Vector((min(p.x for p in world), min(p.y for p in world),
                         min(p.z for p in world)))
            mx = Vector((max(p.x for p in world), max(p.y for p in world),
                         max(p.z for p in world)))
            ev.to_mesh_clear()
        center = (mn + mx) / 2
        radius = max((mx - mn).length / 2, 1e-3)
        scene = self.bpy.context.scene
        cam_data = self.bpy.data.cameras.new("ConsoleDiffCam")
        cam_data.lens = 50
        cam_data.clip_start = 0.001
        cam = self.bpy.data.objects.new("ConsoleDiffCam", cam_data)
        scene.collection.objects.link(cam)
        direction = Vector((1.0, -1.0, 0.75)).normalized()
        # 水平 fov/2 = atan(36/2/50)；距离 = r / tan(fov/2) × margin
        dist = radius / (18.0 / 50.0) * margin
        cam.location = center + direction * dist
        cam.rotation_euler = (center - cam.location).to_track_quat('-Z', 'Y').to_euler()
        scene.camera = cam

    # ── 渲染一帧 ─────────────────────────────────────────────
    def render(self, label: str) -> dict[str, Any]:
        """同机位渲染 → PNG 落盘 → 像素回读 → 哈希/占比/耗时。"""
        self._frame_n += 1
        png_path = self.workdir / f"frame_{self._frame_n:03d}_{label}.png"
        scene = self.bpy.context.scene
        scene.render.filepath = str(png_path)
        t0 = time.perf_counter()
        self.bpy.ops.render.render(write_still=True)
        ms = (time.perf_counter() - t0) * 1000
        if self._frame_n == 1:
            self.cold_start_ms = round(ms, 1)
        img = self.bpy.data.images.load(str(png_path))
        px = np.empty(len(img.pixels), dtype=np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(-1, 4)
        self.bpy.data.images.remove(img)
        lum = _luma(px)
        opaque = px[:, 3] > 0.5
        frame = {
            "n": self._frame_n, "label": label,
            "png_path": str(png_path),
            "png_kb": round(png_path.stat().st_size / 1024, 1),
            "ms": round(ms, 1),
            "dhash": dhash(px), "ahash": ahash(px),
            "opaque_ratio": round(float(opaque.mean()), 4),
            "luma_mean": round(float(lum.mean()), 4),
            "luma_std": round(float(lum.std()), 4),
        }
        self._last_px = px
        return frame

    def render_preview(self, label: str) -> dict[str, Any]:
        """渲染一帧但**不动 diff 基线**（A/B 预览用——基线只属于 render_diff 序列）。"""
        saved = self._last_px
        frame = self.render(label)
        self._last_px = saved
        return frame

    # ── 渲染 + 对上一帧 diff ─────────────────────────────────
    def render_diff(self, label: str) -> dict[str, Any]:
        """渲染 + 与上一帧 diff（首帧 = 基线，无 diff 图）。

        基线滚动：diff 永远相对上一帧（段落边界语义）；
        全部帧 PNG 都在 workdir/renders 留档（M9-5 闪烁 diff / A-B 回放用）。
        """
        prev_px = self._last_px if self._frame_n > 0 else None
        prev_dhash = self._prev_dhash
        frame = self.render(label)
        if prev_px is None:
            frame.update({"changed_ratio": None, "changed_px": None,
                          "diff_b64": "", "hamming": None})
        else:
            changed = np.abs(prev_px - self._last_px).max(axis=1) > self.changed_thresh
            n_changed = int(changed.sum())
            ratio = round(n_changed / prev_px.shape[0], 4)
            diff_b64 = self._compose_diff(changed, self._last_px)
            frame.update({"changed_ratio": ratio, "changed_px": n_changed,
                          "diff_b64": diff_b64,
                          "hamming": hamming(prev_dhash, frame["dhash"])
                          if prev_dhash is not None else None})
        self._prev_px = prev_px
        self._prev_dhash = frame["dhash"]
        return frame

    def _compose_diff(self, changed: np.ndarray, px_b: np.ndarray) -> str:
        """合成 diff 图：灰度底 + 红色高亮变化区（人眼直读，PNG 压缩友好）。

        ⚠️ changed 是 (N,) 像素级掩码——_luma 返回 (H,W) 二维，必须先拉平。
        """
        lum = _luma(px_b).reshape(-1)
        base = np.repeat((lum * 0.85 + 0.1)[:, None], 3, axis=1)
        overlay = base.copy()
        overlay[changed] = (0.92, 0.15, 0.15)
        rgba = np.concatenate([overlay, np.ones((len(overlay), 1), dtype=np.float32)],
                              axis=1)
        side = int(round(rgba.shape[0] ** 0.5))
        img = np.flipud(rgba.reshape(side, side, 4))   # Blender 像素底朝上 → 翻正
        im = self.bpy.data.images.new("console_diff", side, side, alpha=True)
        im.pixels.foreach_set(img.ravel())
        out = self.workdir / f"diff_{self._frame_n:03d}.png"
        im.filepath_raw = str(out)
        im.file_format = 'PNG'
        im.save()
        self.bpy.data.images.remove(im)
        return base64.b64encode(out.read_bytes()).decode()

    # ── M2-3 渲染谓词（全机械）────────────────────────────────
    def check_predicates(self, frame: dict[str, Any],
                         geom_changed: bool | None = None) -> dict[str, Any]:
        """非空 / 有方差 / 目标占比 / （可选）哈希转移一致性。

        哈希转移（geom_changed 给定时判定）：
          * 几何未变 → dHash 必须不变（确定性回归门禁；违反 = 渲染不确定）
          * 几何已变 → dHash 允许不变（像素级才是灵敏信号；dHash 是粗粒度
            结构信号——不变时记录 hamming=0 供 EXP-4 标定分离度，不算失败）
        """
        hash_reg = None
        if self._prev_dhash is not None and geom_changed is not None:
            h = hamming(self._prev_dhash, frame["dhash"])
            if not geom_changed:
                hash_reg = {"ok": h == 0, "hamming": h,
                            "why": "" if h == 0 else "几何未变但感知哈希变了（渲染不确定？）"}
            else:
                hash_reg = {"ok": True, "hamming": h,
                            "why": "" if h > 0 else "几何已变但 dHash 未动——粗粒度信号不灵敏，记录供 EXP-4"}
        preds = {"not_black": frame["opaque_ratio"] > 0.001,
                 "has_variance": frame["luma_std"] > 0.005,
                 "occupancy_ok": 0.02 < frame["opaque_ratio"] < 0.95,
                 "hash_transition": hash_reg}
        frame["predicates"] = preds
        return preds

    @staticmethod
    def ok(preds: dict[str, Any]) -> bool:
        """None = 谓词不适用（如基线帧无哈希转移），视为通过。"""
        return all((v["ok"] if isinstance(v, dict) else v)
                   for v in preds.values() if v is not None)
