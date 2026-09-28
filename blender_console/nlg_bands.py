"""nlg_bands.py — 谓词 diff → 中文带化判词（NLG v0，纯模板零 LLM）
================================================================================
依据：深度调研《NLG_几何变更描述》——数值带化（NWS 式阈值表）+ 多谓词融合 +
"模板保真、LLM 润色后置"。本模块只做**确定性模板**，不调 LLM（回查零幻觉）。

带化规则（|rel| 相对变化）：
  <2%   → 带内（不主动报）
  2-10% → 偏移一点
  10-30% → 明显偏离
  >30%  → 大幅偏离
"""
from __future__ import annotations

import json
from typing import Any

__all__ = ["band_of", "verdict_zh", "verdict_report"]

_BANDS = ((0.02, "带内"), (0.10, "偏移一点"), (0.30, "明显偏离"), (float("inf"), "大幅偏离"))


def band_of(rel: float) -> str:
    """相对变化 → 带化措辞（人类惯例：先模糊后精确，档位 ≈3）"""
    a = abs(rel)
    for hi, word in _BANDS:
        if a < hi:
            return word
    return _BANDS[-1][1]


def verdict_zh(pred: dict[str, Any]) -> str:
    """单条谓词 → 一句中文判词（模板槽位：谓词名/实际/期望/带化）"""
    name = pred.get("predicate", "?")
    actual = pred.get("actual_mm", pred.get("actual", "?"))
    expect = pred.get("expect_mm", pred.get("expect", "?"))
    rel = pred.get("rel_pct")
    ok = pred.get("ok", True)
    if not ok:
        return f"[FAIL] {name}: 实测 {actual}，期望 {expect}（{pred.get('band', '超差')}）"
    if rel is not None and abs(rel) >= 2:
        return f"{name}: {actual}（期望 {expect}，{pred.get('band', '带内')} {rel:+.1f}%）"
    return f"{name}: {actual}（带内）"


def verdict_report(preds: list[dict[str, Any]]) -> str:
    """谓词清单 → 多行判词报告（问题类排前，尺寸类其次——NLG 调研优先级规则）"""
    if not preds:
        return "(无谓词结果)"
    fails = [p for p in preds if not p.get("ok", True)]
    lines = []
    for p in fails:
        lines.append(verdict_zh(p))
    for p in preds:
        if p.get("ok", True):
            lines.append(verdict_zh(p))
    head = "⛔ %d 项超差" % len(fails) if fails else "✅ 全部带内"
    return head + "\n" + "\n".join("  " + l for l in lines)


if __name__ == "__main__":
    demo = [
        {"predicate": "hull_length", "actual_mm": 180.57, "expect_mm": 180.57,
         "rel_pct": 0.0, "band": "带内", "ok": True},
        {"predicate": "hull_height_total", "actual_mm": 86.79, "expect_mm": 85.71,
         "rel_pct": 1.14, "band": "带内", "ok": True},
        {"predicate": "roadwheel_count", "actual": 14, "expect": 16, "ok": False},
    ]
    print(verdict_report(demo))
