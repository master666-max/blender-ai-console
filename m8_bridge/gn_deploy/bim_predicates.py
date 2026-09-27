"""bim_predicates.py — M2-8 BIM 语义谓词（d4-bim 建筑扩展）
===========================================================

最小 Ifc 语义投影（v1）——AI 产 plan 的 BIM 元数据由编译期谓词把关。
纯 Python 零 bpy（对齐 plan_schema/mat_compiler 校验层传统：预校验可移植）。

数据模型：
    {"walls": [{"id": "W1",
                "is_external": true,             # 谓词以此判定外墙集合
                "psets": {"Pset_WallCommon": {"IsExternal": true}},
                "thickness": 0.24,               # 米（键缺失 = 不做层和检查）
                "material_layers": [{"name": "brick", "thickness": 0.12}, ...]}],
     "doors":   [{"id": "D1", "host_wall": "W1"}],
     "windows": [{"id": "Win1", "host_wall": "W1"}]}

三谓词（工单 M2-8 口径，正反例验收）：
  ① Pset 完备性：is_external=true 的墙必须有 Pset_WallCommon.IsExternal 非空
     （缺 pset / 缺键 / None / 空串 = FAIL；内墙不要求——语义只管外墙）
  ② 关系一致性：door/window.host_wall 必须指向已声明墙
  ③ 材料层：sum(layer.thickness) == wall.thickness（容差 1e-6）
     （键存在但空层表且 thickness>0 = FAIL——声称有厚度无构成；
       material_layers 键缺失 = 跳过——诚实边界：非分层构造墙合法）

错误模型：收集式（一面墙的错不阻断其它检查——建筑模型批量修更实用），
issue = {"code", "target", "reason", "suggestions"}；check_bim 返回 [] 即 PASS。
结构错误（model 非 dict / 墙缺 id）单独 BIM_MODEL_INVALID。
"""

from __future__ import annotations

from typing import Any

__all__ = ["check_bim", "BIM_PREDICATE_CODES"]

TOL = 1e-6

BIM_MODEL_INVALID = "BIM_MODEL_INVALID"
BIM_PSET_INCOMPLETE = "BIM_PSET_INCOMPLETE"
BIM_HOST_MISSING = "BIM_HOST_MISSING"
BIM_LAYER_MISMATCH = "BIM_LAYER_MISMATCH"

BIM_PREDICATE_CODES = (BIM_MODEL_INVALID, BIM_PSET_INCOMPLETE,
                       BIM_HOST_MISSING, BIM_LAYER_MISMATCH)


def _issue(code: str, target: str, reason: str,
           suggestions: list[dict] | None = None) -> dict:
    return {"code": code, "target": target, "reason": reason,
            "suggestions": suggestions or []}


def _check_structure(model: Any) -> list[dict]:
    if not isinstance(model, dict):
        return [_issue(BIM_MODEL_INVALID, "$",
                       f"BIM 模型必须是 dict，实得 {type(model).__name__}")]
    issues: list[dict] = []
    walls = model.get("walls", [])
    if not isinstance(walls, list):
        issues.append(_issue(BIM_MODEL_INVALID, "$.walls", "walls 必须是数组"))
        walls = []
    for i, w in enumerate(walls):
        if not isinstance(w, dict) or not isinstance(w.get("id"), str) or not w["id"]:
            issues.append(_issue(BIM_MODEL_INVALID, f"$.walls[{i}]",
                                 "墙必须是含非空 id 的对象"))
    for key in ("doors", "windows"):
        for i, d in enumerate(model.get(key) or []):
            if not isinstance(d, dict) or not isinstance(d.get("id"), str) or not d["id"]:
                issues.append(_issue(BIM_MODEL_INVALID, f"$.{key}[{i}]",
                                     f"{key[:-1]} 必须是含非空 id 的对象"))
            elif not isinstance(d.get("host_wall"), str) or not d["host_wall"]:
                issues.append(_issue(BIM_MODEL_INVALID, f"$.{key}[{i}].host_wall",
                                     f"{key[:-1]} 缺 host_wall"))
    return issues


def check_bim(model: Any) -> list[dict]:
    """M2-8 全量检查：返回 issues 列表，空 = PASS（收集式——批量修实用）。"""
    issues = _check_structure(model)
    if any(i["code"] == BIM_MODEL_INVALID for i in issues):
        return issues          # 结构坏了语义检查无意义（fail-fast 只对 INVALID）

    walls: list[dict] = model.get("walls") or []
    wall_ids = {w["id"] for w in walls}

    # ① Pset 完备性（只管外墙）
    for w in walls:
        if not w.get("is_external"):
            continue
        psets = w.get("psets") or {}
        val = (psets.get("Pset_WallCommon") or {}).get("IsExternal")
        if val is None or (isinstance(val, str) and not val.strip()):
            issues.append(_issue(
                BIM_PSET_INCOMPLETE, f"wall:{w['id']}",
                "外墙缺 Pset_WallCommon.IsExternal（Pset 完备性——下游能耗/围护"
                "统计依赖该标记）",
                [{"action": "add_field",
                  "target": f"walls[{w['id']}].psets.Pset_WallCommon.IsExternal",
                  "value": "true | false"}]))

    # ② 关系一致性
    for key in ("doors", "windows"):
        kind = key[:-1]
        for d in model.get(key) or []:
            host = d.get("host_wall")
            if host not in wall_ids:
                issues.append(_issue(
                    BIM_HOST_MISSING, f"{kind}:{d['id']}",
                    f"host_wall {host!r} 不存在于 walls（悬空开洞——IfcRelFillsElement "
                    f"要求宿主存在）",
                    [{"action": "fix_reference", "target": f"{kind}[{d['id']}].host_wall",
                      "known": sorted(wall_ids)[:20]}]))

    # ③ 材料层厚度和 == 壁厚
    for w in walls:
        th = w.get("thickness")
        layers = w.get("material_layers")
        if layers is None:
            continue                       # 键缺失 = 非分层构造，跳过（诚实边界）
        if not isinstance(layers, list):
            issues.append(_issue(BIM_MODEL_INVALID, f"wall:{w['id']}.material_layers",
                                 "material_layers 必须是数组"))
            continue
        total = 0.0
        bad_layer = None
        for i, lay in enumerate(layers):
            try:
                t = float(lay["thickness"])
            except (KeyError, TypeError, ValueError):
                bad_layer = f"material_layers[{i}] 厚度缺失或非数值"
                break
            if t <= 0:
                bad_layer = f"material_layers[{i}] 厚度 {t} ≤ 0"
                break
            total += t
        if bad_layer:
            issues.append(_issue(BIM_LAYER_MISMATCH, f"wall:{w['id']}", bad_layer))
            continue
        if th is None:
            issues.append(_issue(
                BIM_LAYER_MISMATCH, f"wall:{w['id']}",
                "有 material_layers 但墙缺 thickness（层和无从对账）",
                [{"action": "add_field", "target": f"walls[{w['id']}].thickness",
                  "value": total}]))
            continue
        if abs(total - float(th)) > TOL:
            issues.append(_issue(
                BIM_LAYER_MISMATCH, f"wall:{w['id']}",
                f"材料层厚度之和 {total:.6g} ≠ 壁厚 {float(th):.6g}"
                f"（差 {total - float(th):+.6g} m）",
                [{"action": "fix_value", "target": f"walls[{w['id']}]",
                  "hint": "调层厚或壁厚使 sum(layers) == thickness"}]))
    return issues
