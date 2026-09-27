"""mat_compiler.py — M4-11 材质编译器（d3-material 路线）
====================================================================

M8-R4 素材转正（2026-09-28 R7e）：隔离区 nodes/WD_wood.py → procedural
木纹路径。plan 增加可选 "procedural" 字段（{"type": "wood", ...}），
编译期把 WD 纹理链（Wave BANDS/X/SIN + Noise 扰动 + Mix RGBA + Bump）
**内联进材质节点树**（不建 ShaderNodeGroup——省掉 4.0+ interface API
漂移面；EXP-006 纪律不变：材质=编译器管理资产，禁材质槽）。
吸收源码教训：Mix RGBA 端口索引 Factor=inputs[0]/A=[6]/B=[7]/Color=outputs[2]；
V-04 幂等（本编译器"同名复用+参数重放"天然覆盖）；编译器命名节点
（WD_Wave/WD_Noise/WD_Mix/WD_Bump）使重放可寻址不重建。


为什么存在（EXP-006 设计约束）：**材质必须编译进节点树，禁走 bpy 材质槽**——
材质作为受编译器管理的资产（plan-JSON → Principled BSDF 节点图），
由 set_material op 挂进 GN 树末端。重编译删树重建时，材质引用随段落
一起走编译器路径重建——结构性免疫"槽位引用静默丢失"。

plan 形态（AI 写语义 + 偏差，编译器填全参数）：
    {"preset": "ceramic",                    # 必填：预设表键（完整默认参数）
     "surface": {"roughness": 0.2},          # 可选：AI 偏差覆盖（物理约束校验后生效）
     "layers": {"coat": true},               # 可选：清漆层（Coat Weight）
     "assignment": {"mode": "per_object"}}   # 可选：per_object（现役）/ per_face（留后续）

物理约束 verifier（工单 M4-11 验收口径，编译期响亮失败）：
    * Metallic ∈ [0, 1]
    * Roughness ∈ [0, 1]
    * IOR ∈ [1.0, 2.0]
    * metallic=1 时 base_color 亮度 > 0.9 → 警告（物理上趋黑无漫反射；铝等亮金属合法）

5.2 API 漂移防御（EXP-014 教训）：Principled socket 名按候选列表探测
（'Coat Weight' ← 5.0 由 'Clearcoat' 改名），找不到即报错不静默。
"""

from __future__ import annotations

import hashlib
import json as _json
from typing import Any

__all__ = ["MaterialConstraintError", "MAT_PRESETS", "MATERIAL_PRESET_KEYS",
           "validate_material_plan", "compile_material", "material_fingerprint"]


class MaterialConstraintError(Exception):
    """材质物理约束校验失败（结构化信息，console 转成 M4-8 格式）。"""

    def __init__(self, reason: str, code: str = "MATERIAL_CONSTRAINT",
                 suggestions: list[dict] | None = None) -> None:
        self.reason = reason
        self.code = code
        self.suggestions = suggestions or []
        super().__init__(reason)


# ─────────────────────────────────────────────────────────────
# 预设表（d3-material：Principled BSDF 物理范围；键对齐 plan_schema._MATERIAL_PRESETS）
# base_color 为线性 RGB [0,1]；coat 为 Coat Weight [0,1]
# ─────────────────────────────────────────────────────────────
MAT_PRESETS: dict[str, dict[str, Any]] = {
    "ceramic": {"base_color": [0.87, 0.85, 0.81], "roughness": 0.12,
                "metallic": 0.0, "ior": 1.5, "coat": 0.6, "coat_roughness": 0.08},
    "porcelain": {"base_color": [0.92, 0.91, 0.89], "roughness": 0.08,
                  "metallic": 0.0, "ior": 1.54, "coat": 0.8, "coat_roughness": 0.05},
    "metal": {"base_color": [0.75, 0.75, 0.76], "roughness": 0.30,
              "metallic": 1.0, "ior": 2.0, "coat": 0.0},
    "aluminum": {"base_color": [0.91, 0.92, 0.92], "roughness": 0.25,
                 "metallic": 1.0, "ior": 2.0, "coat": 0.0},
    "plastic": {"base_color": [0.80, 0.30, 0.20], "roughness": 0.40,
                "metallic": 0.0, "ior": 1.46, "coat": 0.0},
    "glass": {"base_color": [0.95, 0.97, 0.97], "roughness": 0.02,
              "metallic": 0.0, "ior": 1.45, "coat": 0.0},
    "wood": {"base_color": [0.55, 0.36, 0.20], "roughness": 0.55,
             "metallic": 0.0, "ior": 1.5, "coat": 0.0},
    "fabric": {"base_color": [0.60, 0.55, 0.50], "roughness": 0.85,
               "metallic": 0.0, "ior": 1.4, "coat": 0.0},
}

MATERIAL_PRESET_KEYS = frozenset(MAT_PRESETS)

# procedural 纹理类型（M8-R4：WD_wood 转正；后续可扩 marble 等）
PROCEDURAL_TYPES = frozenset({"wood"})

# WD 源配方默认（隔离区 WD_wood.py 实测值：Distortion=6.0"木纹的灵魂"）
_WD_DEFAULTS = {"scale": 2.0, "distortion": 6.0, "detail": 3.0,
                "color_light": [0.72, 0.55, 0.35],
                "color_dark": [0.35, 0.18, 0.06],
                "bump_strength": 0.15}


# ─────────────────────────────────────────────────────────────
# 物理约束校验（纯 Python，无 bpy——预校验可移植）
# ─────────────────────────────────────────────────────────────
def _luminance(rgb: list[float]) -> float:
    r, g, b = (rgb + [0, 0, 0])[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def normalize_material_plan(mat_plan: dict) -> tuple[dict, list[str]]:
    """plan → 完整参数 dict + warnings 列表（preset 填全 + surface/layers 覆盖）。"""
    if not isinstance(mat_plan, dict):
        raise MaterialConstraintError(
            f"material_plan 必须是 dict，实得 {type(mat_plan).__name__}",
            code="MATERIAL_PLAN_TYPE")
    unknown = [k for k in mat_plan
               if k not in {"preset", "surface", "layers", "assignment",
                            "procedural"}]
    if unknown:
        raise MaterialConstraintError(
            f"material_plan 未知字段 {unknown}；允许 preset/surface/layers/"
            "assignment/procedural",
            code="MATERIAL_PLAN_FIELD",
            suggestions=[{"action": "remove_field", "target": str(unknown)}])
    preset = mat_plan.get("preset", "")
    if preset not in MAT_PRESETS:
        raise MaterialConstraintError(
            f"未知材质预设 {preset!r}；合法：{sorted(MAT_PRESETS)}",
            code="MATERIAL_PRESET_UNKNOWN",
            suggestions=[{"action": "replace_value", "target": "preset",
                          "value": sorted(MAT_PRESETS)}])
    params: dict[str, Any] = dict(MAT_PRESETS[preset])
    warnings: list[str] = []

    surface = mat_plan.get("surface") or {}
    if not isinstance(surface, dict):
        raise MaterialConstraintError("surface 必须是 dict", code="MATERIAL_SURFACE")
    for k, v in surface.items():
        if k not in params:
            raise MaterialConstraintError(
                f"surface 未知参数 {k!r}；该预设可覆盖：{sorted(params)}",
                code="MATERIAL_SURFACE_FIELD")
        params[k] = v

    layers = mat_plan.get("layers") or {}
    if not isinstance(layers, dict):
        raise MaterialConstraintError("layers 必须是 dict", code="MATERIAL_LAYERS")
    if layers.get("coat") is True:
        params["coat"] = max(float(params.get("coat", 0.0)), 0.5)
    elif isinstance(layers.get("coat"), (int, float)):
        params["coat"] = float(layers["coat"])

    # procedural（M8-R4：WD_wood 转正——纯 Python 校验层，编译期在 bpy 侧内联）
    proc = mat_plan.get("procedural")
    if proc is not None:
        if not isinstance(proc, dict):
            raise MaterialConstraintError(
                f"procedural 必须是 dict，实得 {type(proc).__name__}",
                code="MATERIAL_PROCEDURAL_FIELD")
        ptype = proc.get("type", "")
        if ptype not in PROCEDURAL_TYPES:
            raise MaterialConstraintError(
                f"未知 procedural 类型 {ptype!r}；合法：{sorted(PROCEDURAL_TYPES)}",
                code="MATERIAL_PROCEDURAL_TYPE",
                suggestions=[{"action": "replace_value", "target":
                              "procedural.type", "value": sorted(PROCEDURAL_TYPES)}])
        pkeys = {"type", "scale", "distortion", "detail",
                 "color_light", "color_dark", "bump_strength"}
        pk_unknown = [k for k in proc if k not in pkeys]
        if pk_unknown:
            raise MaterialConstraintError(
                f"procedural 未知字段 {pk_unknown}；允许 {sorted(pkeys)}",
                code="MATERIAL_PROCEDURAL_FIELD",
                suggestions=[{"action": "remove_field", "target": str(pk_unknown)}])
        if "scale" in proc and not (0.0 <= float(proc["scale"]) <= 100.0):
            raise MaterialConstraintError(
                f"procedural.scale={proc['scale']} 超出 [0, 100]",
                code="MATERIAL_PROCEDURAL_RANGE")
        if "detail" in proc and not (0.0 <= float(proc["detail"]) <= 16.0):
            raise MaterialConstraintError(
                f"procedural.detail={proc['detail']} 超出 [0, 16]",
                code="MATERIAL_PROCEDURAL_RANGE")
        for ck in ("color_light", "color_dark"):
            if ck in proc:
                c = proc[ck]
                if (not isinstance(c, (list, tuple)) or len(c) != 3
                        or any(not (0.0 <= float(x) <= 1.0) for x in c)):
                    raise MaterialConstraintError(
                        f"procedural.{ck} 必须是 [r,g,b] 且各分量 ∈ [0,1]",
                        code="MATERIAL_PROCEDURAL_RANGE")
        if "bump_strength" in proc and not (0.0 <= float(proc["bump_strength"]) <= 1.0):
            raise MaterialConstraintError(
                f"procedural.bump_strength={proc['bump_strength']} 超出 [0, 1]",
                code="MATERIAL_PROCEDURAL_RANGE")
        params["procedural"] = dict(proc)   # 完整传给编译段（含默认值回填）

    # 物理约束（编译期响亮失败——工单 M4-11 verifier 口径）
    if not (0.0 <= float(params["metallic"]) <= 1.0):
        raise MaterialConstraintError(
            f"Metallic={params['metallic']} 超出 [0, 1]", code="METALLIC_RANGE")
    if not (0.0 <= float(params["roughness"]) <= 1.0):
        raise MaterialConstraintError(
            f"Roughness={params['roughness']} 超出 [0, 1]", code="ROUGHNESS_RANGE")
    if not (1.0 <= float(params["ior"]) <= 2.0):
        raise MaterialConstraintError(
            f"IOR={params['ior']} 超出 [1.0, 2.0]", code="IOR_RANGE",
            suggestions=[{"action": "set_field", "target": "surface.ior",
                          "value": "[1.0, 2.0]（常见：玻璃 1.45 / 塑料 1.46 / 陶瓷 1.5）"}])
    if float(params["metallic"]) == 1.0 and _luminance(params["base_color"]) > 0.9:
        warnings.append("metallic=1 且 base_color 亮度 >0.9——金属无漫反射（趋黑），"
                        "亮色仅作 F0 反射率（铝/铬类合法，纯白可疑）")
    return params, warnings


def validate_material_plan(mat_plan: dict) -> tuple[dict, list[str]]:
    """公开入口：校验 + 归一化（不碰 bpy，纯 Python）。"""
    return normalize_material_plan(mat_plan)


# ─────────────────────────────────────────────────────────────
# Principled socket 探测（5.2 漂移防御——EXP-014 教训）
# ─────────────────────────────────────────────────────────────
_SOCKET_CANDIDATES = {
    "base_color": ["Base Color"],
    "metallic": ["Metallic"],
    "roughness": ["Roughness"],
    "ior": ["IOR"],
    "coat": ["Coat Weight", "Clearcoat"],
    "coat_roughness": ["Coat Roughness", "Clearcoat Roughness"],
}


def _set_principled(bsdf, key: str, value) -> None:
    """按候选名探测 socket 并赋值；全找不到 → 响亮失败（不静默）。"""
    names = _SOCKET_CANDIDATES[key]
    for nm in names:
        sock = bsdf.inputs.get(nm)
        if sock is not None:
            sock.default_value = value
            return
    raise MaterialConstraintError(
        f"Principled BSDF 无 {'/'.join(names)} socket（Blender API 漂移？）",
        code="SOCKET_NOT_FOUND")


# ─────────────────────────────────────────────────────────────
# 编译：plan → bpy.data.materials（幂等：同名复用 + 参数重放）
# ─────────────────────────────────────────────────────────────
def compile_material(bpy, mat_plan: dict, name: str | None = None) -> Any:
    """编译材质 plan → bpy Material（ShaderNodeTree：Principled + Output）。

    幂等语义：name 或 plan 指纹派生材质名；已存在则**参数重放**（复用不重建），
    与"清理后重建"纪律一致——重编译后参数不被静默重置（EXP-006 免疫点）。
    """
    params, warnings = normalize_material_plan(mat_plan)
    preset = mat_plan.get("preset", "custom")
    if name is None:
        # plan 指纹派生稳定名（同 plan 复用同一材质；surface/procedural 覆盖参与指纹）
        fp = hashlib.sha256(_json.dumps(mat_plan, sort_keys=True,
                                        ensure_ascii=False).encode()).hexdigest()[:8]
        name = f"MAT_{preset}_{fp}"
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        out.location = (300, 0)
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (0, 0)
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    else:
        bsdf = next((n for n in mat.node_tree.nodes
                     if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)
        if bsdf is None:
            raise MaterialConstraintError(
                f"材质 {name!r} 已存在但无 Principled BSDF——非本编译器产物，拒绝重放",
                code="MATERIAL_FOREIGN")
    nt = mat.node_tree
    _set_principled(bsdf, "base_color", (*params["base_color"], 1.0))
    _set_principled(bsdf, "metallic", float(params["metallic"]))
    _set_principled(bsdf, "roughness", float(params["roughness"]))
    _set_principled(bsdf, "ior", float(params["ior"]))
    coat = float(params.get("coat", 0.0) or 0.0)
    _set_principled(bsdf, "coat", coat)
    if "coat_roughness" in params:
        _set_principled(bsdf, "coat_roughness", float(params["coat_roughness"]))
    proc = params.get("procedural")
    if proc is not None:
        _build_wood_chain(mat, nt, bsdf, proc)
    mat["mat_plan_fp"] = hashlib.sha256(
        _json.dumps(params, sort_keys=True, ensure_ascii=False,
                    default=str).encode()).hexdigest()[:16]
    mat["mat_warnings"] = warnings
    return mat


# ─────────────────────────────────────────────────────────────
# M8-R4 · WD 木纹链内联（隔离区 WD_wood.py → 编译器管理资产）
# 节点带编译器命名（WD_*）——重放按名寻址改参数，不重建不累积。
# 端口索引教训（源码实锤）：Mix RGBA Factor=inputs[0]/A=[6]/B=[7]/Color=outputs[2]。
# ─────────────────────────────────────────────────────────────
def _wd_cfg(proc: dict) -> dict:
    cfg = dict(_WD_DEFAULTS)
    for k in ("scale", "distortion", "detail", "bump_strength"):
        if k in proc:
            cfg[k] = float(proc[k])
    for k in ("color_light", "color_dark"):
        if k in proc:
            cfg[k] = [float(x) for x in proc[k]]
    return cfg


def _build_wood_chain(mat, nt, bsdf, proc: dict) -> None:
    cfg = _wd_cfg(proc)
    wave = next((n for n in nt.nodes if n.name == "WD_Wave"), None)
    if wave is None:
        # 首建：Wave(BANDS/X/SIN) ← Noise(Fac 扰动向量)；Mix 混双色 → Base
        # Color + Bump → Normal（源配方拓扑，V-04 幂等语义由重放路径承担）
        wave = nt.nodes.new("ShaderNodeTexWave")
        wave.name = "WD_Wave"
        wave.location = (-600, 100)
        wave.wave_type = 'BANDS'
        wave.bands_direction = 'X'
        wave.wave_profile = 'SIN'
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.name = "WD_Noise"
        noise.location = (-600, -200)
        mix = nt.nodes.new("ShaderNodeMix")
        mix.name = "WD_Mix"
        mix.location = (-350, 0)
        mix.data_type = 'RGBA'
        mix.blend_type = 'MIX'
        bump = nt.nodes.new("ShaderNodeBump")
        bump.name = "WD_Bump"
        bump.location = (-100, -250)
        nt.links.new(noise.outputs['Fac'], wave.inputs['Vector'])
        nt.links.new(wave.outputs['Fac'], mix.inputs[0])
        nt.links.new(mix.outputs[2], bsdf.inputs['Base Color'])
        nt.links.new(mix.outputs[2], bump.inputs['Height'])
        nt.links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])
    noise = nt.nodes["WD_Noise"]
    mix = nt.nodes["WD_Mix"]
    bump = nt.nodes["WD_Bump"]
    # 参数重放（每次都写——幂等：同 plan 同值，异 plan 校正）
    wave.inputs['Scale'].default_value = cfg["scale"]
    wave.inputs['Distortion'].default_value = cfg["distortion"]
    wave.inputs['Detail'].default_value = cfg["detail"]
    noise.inputs['Scale'].default_value = 2.0
    noise.inputs['Detail'].default_value = 3.0
    mix.inputs[6].default_value = (*cfg["color_light"], 1.0)
    mix.inputs[7].default_value = (*cfg["color_dark"], 1.0)
    bump.inputs['Strength'].default_value = cfg["bump_strength"]
    mat["wd_fp"] = hashlib.sha256(str(sorted(cfg.items())).encode()).hexdigest()[:16]


def material_fingerprint(mat) -> str:
    """编译产物对账：读 Principled 实际参数 → 稳定指纹（幂等/丢失检测用）。"""
    bsdf = next(n for n in mat.node_tree.nodes
                if n.bl_idname == "ShaderNodeBsdfPrincipled")
    parts = []
    for key, names in (("base_color", ["Base Color"]),
                       ("metallic", ["Metallic"]),
                       ("roughness", ["Roughness"]),
                       ("ior", ["IOR"]),
                       ("coat", ["Coat Weight", "Clearcoat"])):
        sock = next((bsdf.inputs[nm] for nm in names
                     if nm in bsdf.inputs), None)
        v = tuple(sock.default_value) if sock is None or sock.type == "RGBA" \
            else sock.default_value
        if hasattr(v, "__len__"):
            v = tuple(round(float(x), 5) for x in v)
        else:
            v = round(float(v), 5)
        parts.append(f"{key}={v}")
    # M8-R4：WD 木纹链对账（存在 WD_Wave 即为 procedural 产物——读回实参）
    wave = next((n for n in mat.node_tree.nodes if n.name == "WD_Wave"), None)
    if wave is not None:
        mix = mat.node_tree.nodes["WD_Mix"]
        bump = mat.node_tree.nodes["WD_Bump"]
        light = tuple(round(float(x), 5) for x in mix.inputs[6].default_value[:3])
        dark = tuple(round(float(x), 5) for x in mix.inputs[7].default_value[:3])
        parts.append(
            "proc=wood"
            f"/scale={wave.inputs['Scale'].default_value:.4f}"
            f"/dist={wave.inputs['Distortion'].default_value:.4f}"
            f"/detail={wave.inputs['Detail'].default_value:.4f}"
            f"/light={light}/dark={dark}"
            f"/bump={bump.inputs['Strength'].default_value:.4f}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
