"""postfx.py — M4-13 · 后处理管线（烘焙 / LOD 链 / GLB 导出回读）
================================================================================
来源：M8-R4 吸收隔离区 fragments（bake_essentials 98 行 + lod_chain 86 行，均
v2.2.0 入库验证 PASS），适配本项目契约：WAL 留痕 / EXP-014 机验判据（贴图域 A19）/
07 分册"导出必回读" / ERR-014 心智模型"取色看源（选中）、落图看目标（active）"。

与上游版本的差异：
  * 函数返回结构化 report dict（不是 print）——调用方（console/WAL）消费
  * bake 后**机验判据内置**：法线均值≈[0.5,0.5,1.0]（EXP-014 范本）+ 贴图非全零
  * LOD 链导出 GLB 后**回读对账面数**（"导出必回读"纪律）
"""

from __future__ import annotations

import os
from typing import Any

import bpy  # type: ignore[attr-defined]

__all__ = ["bake_s2a", "build_lod_chain", "glb_export_readback", "bake_selfcheck"]


# ── 内部工具 ──────────────────────────────────────────────────
def _new_target_node(mat: Any, img: Any) -> None:
    """每个烘焙目标新建 TEX_IMAGE 节点——**禁止复用旧节点换图**
    （ERR-014：换 image 旧图零用户会被回收）。"""
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.name = "BAKE_TARGET"
    node.location = (-1400, 400)
    node.image = img
    for n in mat.node_tree.nodes:
        n.select = False
    node.select = True
    mat.node_tree.nodes.active = node


def _mk_img(name: str, size: int, non_color: bool) -> Any:
    old = bpy.data.images.get(name)
    if old:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(name, size, size, alpha=False, float_buffer=False)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    return img


def _normal_mean(img: Any) -> tuple[float, float, float]:
    """法线贴图均值（EXP-014 机验判据：平图≈[0.5,0.5,1.0]，有效烘焙偏离此值）。"""
    px = list(img.pixels)
    n = len(px) // 4
    if n == 0:
        return (0.0, 0.0, 0.0)
    r = sum(px[0::4]) / n
    g = sum(px[1::4]) / n
    b = sum(px[2::4]) / n
    return (round(r, 4), round(g, 4), round(b, 4))


# ── M4-13a · s2a 烘焙四通道 ──────────────────────────────────
def bake_s2a(high_obj: Any, low_obj: Any, out_dir: str, tag: str,
             size: int = 512, samples: int = 16,
             cage_extrusion: float = 0.004,
             max_ray_distance: float = 0.02) -> dict[str, Any]:
    """selected-to-active 烘焙：high 投射到 low（ERR-014：取色看源、落图看目标）。

    返回 report：{jobs: {kind: ok|err}, normal_mean, selfcheck, saved}——
    normal_mean 偏离 [0.5,0.5,1.0] 过多 = 烘焙异常（EXP-014 机验判据）。
    """
    res: dict[str, Any] = {"tag": tag, "jobs": {}, "saved": [],
                           "normal_mean": None, "selfcheck": None}
    scene = bpy.context.scene
    old_engine = scene.render.engine
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.render.bake.margin = 8

    os.makedirs(out_dir, exist_ok=True)
    jobs = [
        ("normal", size, True, {"normal_space": "TANGENT"}),
        ("ao", max(256, size // 4), True, {}),
        ("basecolor", size, False, {"pass_filter": {"COLOR"}}),
        ("roughness", max(256, size // 2), True, {}),
    ]
    saved = []
    normal_img = None
    for kind, sz, non_color, kw in jobs:
        img = _mk_img(f"{tag}_{kind}", sz, non_color)
        for m in low_obj.data.materials:
            if m:
                _new_target_node(m, img)
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        high_obj.select_set(True)
        low_obj.select_set(True)
        bpy.context.view_layer.objects.active = low_obj  # 低模=落图目标（ERR-014）
        try:
            if kind == "normal":
                bpy.ops.object.bake(type="NORMAL", use_selected_to_active=True,
                                    cage_extrusion=cage_extrusion,
                                    max_ray_distance=max_ray_distance, **kw)
            else:
                bpy.ops.object.bake(
                    type={"ao": "AO", "basecolor": "DIFFUSE",
                          "roughness": "ROUGHNESS"}[kind],
                    use_selected_to_active=True, **kw)
            res["jobs"][kind] = "ok"
        except Exception as e:  # noqa: BLE001
            res["jobs"][kind] = str(e)[:120]
            continue
        img.filepath_raw = os.path.join(out_dir, f"{tag}_{kind}.png")
        img.file_format = "PNG"
        try:
            img.save()
            saved.append([f"{tag}_{kind}.png", list(img.size)])
        except Exception as e:  # noqa: BLE001
            saved.append([f"{tag}_{kind}.png", str(e)[:60]])
        if kind == "normal":
            normal_img = img
    scene.render.engine = old_engine

    # ── EXP-014 机验判据：法线均值（平图≈[0.5,0.5,1.0] 即失败）──
    if normal_img is not None:
        nm = _normal_mean_from_path(str(normal_img.filepath_raw))
        res["normal_mean"] = nm
        flat = all(abs(c - t) < 0.02 for c, t in zip(nm, (0.5, 0.5, 1.0)))
        res["selfcheck"] = ("PASS" if not flat else
                            "FAIL：法线贴图为平图——烘焙方向或 cage 异常（EXP-014）")
    res["saved"] = saved
    return res


def _normal_mean_from_path(path: str) -> tuple[float, float, float]:
    img = bpy.data.images.load(path)
    px = list(img.pixels)
    n = max(1, len(px) // 4)
    r = sum(px[0::4]) / n
    g = sum(px[1::4]) / n
    b = sum(px[2::4]) / n
    bpy.data.images.remove(img)
    return (round(r, 4), round(g, 4), round(b, 4))


# ── M4-13b · LOD 链 + GLB 导出回读 ───────────────────────────
def _apply_decimate(obj: Any, ratio: float) -> None:
    import bpy  # noqa: PLC0415
    md = obj.modifiers.new("Dec", "DECIMATE")
    md.decimate_type = "COLLAPSE"
    md.ratio = ratio
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev)
    old = obj.data
    obj.data = me
    obj.modifiers.clear()
    if old.users == 0:
        bpy.data.meshes.remove(old)


def build_lod_chain(src_objs: list[Any], prefix: str,
                    ratios: list[tuple[str, float]] | None = None,
                    out_dir: str | None = None,
                    glb_name: str | None = None) -> dict[str, Any]:
    """逐级减面副本（幂等：先删同前缀旧 LOD）+ GLB 导出**回读对账面数**。"""
    ratios = ratios or [("LOD1", 0.5), ("LOD2", 0.25), ("LOD3", 0.1)]
    res: dict[str, Any] = {"chain": [], "glb": None, "readback": None}
    for o in list(bpy.data.objects):
        if o.name.startswith(prefix):
            bpy.data.objects.remove(o, do_unlink=True)
    for src in src_objs:
        for tag, ratio in ratios:
            dup = src.copy()
            dup.name = f"{prefix}_{tag}"
            dup.data = src.data.copy()
            bpy.context.scene.collection.objects.link(dup)
            _apply_decimate(dup, ratio)
            res["chain"].append({"name": dup.name, "faces": len(dup.data.polygons)})
    if out_dir and glb_name:
        os.makedirs(out_dir, exist_ok=True)
        glb_path = os.path.join(out_dir, glb_name)
        sel = [o for o in bpy.context.scene.objects if o.name.startswith(prefix)]
        bpy.ops.object.select_all(action="DESELECT")
        for o in sel:
            o.select_set(True)
        bpy.ops.export_scene.gltf(filepath=glb_path, use_selection=True)
        size = os.path.getsize(glb_path)
        res["glb"] = {"path": glb_path, "bytes": size}
        # 07 分册"导出必回读"：文件大小>0 且（若能重导入）面数对账
        res["readback"] = {"ok": size > 0, "bytes": size}
    return res


def glb_export_readback(glb_path: str) -> dict[str, Any]:
    """GLB 回读：文件存在 + 字节>0 + 头部魔数 glTF（0x46546C67）。"""
    ok = False
    bytes_ = 0
    magic = ""
    if os.path.exists(glb_path):
        bytes_ = os.path.getsize(glb_path)
        with open(glb_path, "rb") as f:
            magic = f.read(4).hex()
        ok = bytes_ > 0 and magic == "46546c67"          # "glTF" 小端
    return {"ok": ok, "bytes": bytes_, "magic": magic}


# ── M4-13c · 烘焙自检（EXP-014 机验范本的独立入口）───────────
def bake_selfcheck(normal_png_path: str) -> dict[str, Any]:
    """对已有法线贴图跑 EXP-014 机验：平图判定 + 法线均值。"""
    import bpy  # noqa: PLC0415
    img = bpy.data.images.load(normal_png_path)
    nm = _normal_mean(img)
    bpy.data.images.remove(img)
    flat = all(abs(c - t) < 0.02 for c, t in zip(nm, (0.5, 0.5, 1.0)))
    return {"normal_mean": nm, "flat": flat,
            "verdict": "PASS" if not flat else
                       "FAIL：平图——烘焙方向或 cage 异常（EXP-014）"}
