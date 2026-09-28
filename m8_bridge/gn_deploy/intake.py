"""intake.py — M9-1b · 提问协议实现（导演会话的前置询问层，纯 Python 无 bpy）
================================================================================
规范：《M9-1b提问协议.md》（吸收上游 00-prd-intake，适配 MCP 工具面 + 导演模式）。

组成：
  IntakeSession —— 四档状态机（direct/quick/full/unlimited）+ 提问卡 + PRD 卡
  PRD 卡 —— 一份两用：确认 = 方案批准 = to_plan_skeleton() 实例化 plan 骨架
  纪律（全部来自上游 00 分册 + 本项目 M6-6/B1 联动）：
    * 先查后问：scene_facts 已有的字段标 from_context，绝不问
    * 每轮 ≤4 问，每问带 default + why（默认值也是假设，可质疑）
    * 默认值翻牌制：origin ∈ confirmed | agent_decided | from_context
      ——origin=confirmed 的字段才进 M6-6 偏好训练集（R15 中介）
    * 无限挡收敛 = 五域覆盖 + 部件覆盖（不靠"觉得差不多了"）
    * 开工提示三要素（freeze 时返回）
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

__all__ = ["IntakeSession", "DOMAIN_BANK"]

MODES = ("direct", "quick", "full", "unlimited")
_DOMAINS = ("物理", "功能", "视觉", "工程", "叙事")

# ── 域问题库（通用骨架；具体项目可替换）─────────────────────
DOMAIN_BANK: dict[str, list[dict[str, Any]]] = {
    "物理": [
        {"field": "size_height", "question": "整体高度大约多少？",
         "default": 0.095, "unit": "m", "range": [0.02, 0.5],
         "why": "0.095m 是马克杯常用高度"},
        {"field": "wall_thickness", "question": "壁厚多少？",
         "default": 0.004, "unit": "m", "range": [0.002, 0.02],
         "why": "4mm 兼顾手感与保温"},
    ],
    "功能": [
        {"field": "with_lid", "question": "需要盖子吗？",
         "default": False, "options": [True, False], "why": "多数马克杯不带盖"},
    ],
    "视觉": [
        {"field": "handle_style", "question": "把手什么形态？",
         "default": "round", "options": ["round", "square", "none"],
         "why": "圆环把手最通用"},
    ],
    "工程": [
        {"field": "detail_level", "question": "细节深度档位？",
         "default": "standard", "options": ["draft", "standard", "fine"],
         "why": "standard 到结构细节为止；清理/交付恒走"},
        {"field": "export_target", "question": "交付目标？",
         "default": "render", "options": ["render", "print", "game"],
         "why": "决定面数预算口径"},
    ],
    "叙事": [
        {"field": "context", "question": "陈列语境？",
         "default": "solo", "options": ["solo", "scene"], "why": "单件陈列最常见"},
    ],
}


class IntakeSession:
    """一次询问会话。用法：
        s = IntakeSession(brief="做一个马克杯")
        card = s.ask_round()            # 提问卡（tool return）
        s.submit({"Handle_Thickness": 0.008, "size_height": "按默认"})
        s.freeze()                      # PRD 卡冻结 → to_plan_skeleton()
    """

    def __init__(self, brief: str = "", mode: str | None = None,
                 parts: list[str] | None = None,
                 scene_facts: dict[str, Any] | None = None) -> None:
        self.brief = brief
        self.mode = mode or "quick"
        self.parts = parts or ["mug"]     # 部件路径（M7-2 part 的来源）
        self.scene_facts = dict(scene_facts or {})
        self.fields: dict[str, dict[str, Any]] = {}   # field → {value, origin, why}
        self.domain_done: dict[str, int] = {d: 0 for d in _DOMAINS}
        self.domain_state = {d: "open" for d in _DOMAINS}
        self.round = 0
        self.frozen = False
        self.frozen_at = ""
        self.log: list[dict[str, Any]] = []
        self._absorb_facts()                   # 先查后问：构造时即吸收上下文

    # ── 先查后问：scene_facts 已有的字段直接落账 ─────────────
    def _absorb_facts(self) -> None:
        for k, v in self.scene_facts.items():
            self.fields[k] = {"value": v, "origin": "from_context", "why": "上下文推断"}

    # ── 域问题选取（≤4，未答的优先，按域序）─────────────────
    def _pending_questions(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for dom in _DOMAINS:
            if self.domain_state[dom] == "done":
                continue
            for q in DOMAIN_BANK.get(dom, []):
                f = q["field"]
                if f in self.fields:
                    continue
                if f in self.scene_facts:      # 先查后问：上下文已推断 → 绝不问
                    self.fields[f] = {"value": self.scene_facts[f],
                                      "origin": "from_context",
                                      "why": "上下文推断"}
                    continue
                out.append({**q, "domain": dom})
        return out

    # ── 提问卡（tool return，M9-1 契约）─────────────────────
    def ask_round(self) -> dict[str, Any]:
        """出一轮提问卡（≤4 问，带 default/range/why + 域覆盖进度）。"""
        if self.frozen:
            return {"action": "intake_ask", "ok": False,
                    "error": {"error_code": "ALREADY_FROZEN", "reason": "卡片已冻结"}}
        self.round += 1
        pending = self._pending_questions()
        qs = pending[:4]
        for q in qs:                            # 上游翻牌制：出题即占位（默认值待翻牌）
            self.fields.setdefault(q["field"],
                                   {"value": q["default"], "origin": "pending_default",
                                    "why": q.get("why", "")})
        prog = {d: s for d, s in self.domain_state.items()}
        card = {"action": "intake_ask", "ok": True,
                "data": {"round": self.round, "mode": self.mode,
                         "domain_progress": prog,
                         "open_points": len(pending) - len(qs),
                         "questions": [{k: v for k, v in q.items() if k != "domain"}
                                       for q in qs],
                         "note": "可逐问回答，或回「按默认」整体跳过；说「开工」立即冻结"}}
        self.log.append({"round": self.round, "asked": [q["field"] for q in qs]})
        return card

    # ── 回答提交（翻牌制）────────────────────────────────────
    def submit(self, answers: dict[str, Any]) -> dict[str, Any]:
        """answers: {field: value}。特殊值：
        "按默认"/None → 采纳默认（origin=agent_decided）；"确定" → confirmed。"""
        for f, val in answers.items():
            cur = self.fields.get(f)
            why = cur["why"] if cur else ""
            if val in ("按默认", None):
                self.fields[f] = {"value": cur["value"] if cur else None,
                                  "origin": "agent_decided", "why": why}
            elif val == "确定":
                self.fields[f] = {"value": cur["value"] if cur else val,
                                  "origin": "confirmed", "why": why}
            else:
                self.fields[f] = {"value": val, "origin": "confirmed", "why": why}
        # 域收敛：域内问题全答 → 该域 done（unlimited 挡用"没有了"×2 显式收敛）
        for dom in _DOMAINS:
            qs = DOMAIN_BANK.get(dom, [])
            if qs and all(q["field"] in self.fields for q in qs):
                self.domain_state[dom] = "done"
        return {"ok": True, "fields": len(answers)}

    def set_mode(self, mode: str) -> None:
        """换档（升级跨档直达；档位选择权在用户）。"""
        if mode not in MODES:
            raise ValueError(f"未知档位 {mode!r}；合法：{list(MODES)}")
        self.mode = mode
        self.log.append({"mode_switch": mode})

    def domain_exhausted(self, dom: str) -> None:
        """无限挡：用户连续两答「没有了」→ 域问透。"""
        self.domain_done[dom] = self.domain_done.get(dom, 0) + 1
        if self.domain_done[dom] >= 2:
            self.domain_state[dom] = "done"

    def freeze(self) -> dict[str, Any]:
        """冻结卡片 → PRD 卡（含开工提示三要素与 to_plan_skeleton 入口）。"""
        if self.frozen:                        # M6-2b 治理：冻结幂等守卫
            return {"action": "intake_freeze", "ok": False,
                    "error": {"error_code": "ALREADY_FROZEN",
                              "reason": "卡片已冻结——重复 freeze 无意义"}}
        if self.mode in ("quick", "full", "unlimited"):
            pending = [q["field"] for q in self._pending_questions()]
            if pending and self.mode != "unlimited":
                pass                              # 快速/完整档允许带开放点冻结（留痕）
        self.frozen = True
        self.frozen_at = time.strftime("%Y-%m-%d %H:%M")
        prd = self.prd_card()
        self.log.append({"frozen": True, "fields": len(self.fields)})
        return {"action": "intake_freeze", "ok": True,
                "prd": prd,
                "kickoff": self._kickoff_text(),
                "next": "to_plan_skeleton(prd) → gn_begin → gn_compile 逐段流"}

    def _kickoff_text(self) -> str:
        return (f"——问答到此结束 ✅。以下按 **{self.mode}** 档进入真实建模执行："
                "逐段编译（每段出渲染 diff，T3 段会请您过目）→ 验证 → 交付。"
                "需要调整随时说，我会停下。")

    # ── PRD 卡 ───────────────────────────────────────────────
    def prd_card(self) -> dict[str, Any]:
        return {"intent": self.brief, "mode": self.mode,
                "fields": {k: {"value": v["value"], "origin": v["origin"]}
                           for k, v in self.fields.items()},
                "domain_progress": dict(self.domain_state),
                "parts": list(self.parts),
                "frozen": self.frozen, "frozen_at": self.frozen_at,
                "rounds": self.round}

    # ── PRD → plan 骨架（一份两用）──────────────────────────
    def to_plan_skeleton(self, prd: dict[str, Any] | None = None) -> dict[str, Any]:
        """PRD 卡 → plan-JSON 骨架：部件清单 → sections[]（part/stage/depends_on）。

        骨架的 op/参数细节由下游 AI 填充（fill 的依据 = fields 的语义名）——
        本函数只保证**结构合法**（plan_schema 白名单内）与**依赖顺序**（depends_on 链）。
        """
        prd = prd or self.prd_card()
        dl = self.fields.get("detail_level", {}).get("value", "standard")
        stage_plan = {"draft": ["blockout"], "standard": ["blockout", "structure"],
                      "fine": ["blockout", "structure", "detail"]}.get(dl,
                                                                       ["blockout", "structure"])
        sections = []
        prev = None
        for part in prd["parts"]:
            for j, stage in enumerate(stage_plan):
                sec: dict[str, Any] = {
                    "id": f"{part}_{stage}" if j else f"{part}",
                    "op": "join_geometry" if stage == "structure" and j == 0
                          else ("subdivide" if stage == "detail" else "cube"),
                    "stage": stage, "part": part,
                    "consumes_input": bool(prev or j > 0),
                    "parameters": [],
                }
                if prev:
                    sec["depends_on"] = [prev]   # 线性骨架：每段依赖前一段
                sections.append(sec)
                prev = sec["id"]
        # detail_level 不是 plan 顶层合法键——放进 constraints（check 自由文本）
        return {"version": "0.3", "intent": prd["intent"],
                "sections": sections,
                "constraints": [{"check": f"DETAIL_LEVEL={dl!r}"}],
        }
