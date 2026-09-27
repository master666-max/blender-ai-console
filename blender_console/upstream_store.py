"""upstream_store.py — 上游经验条目的可拔插供给源（ExperienceStore 协议实现）
================================================================================

定位（用户指令：纯经验归于**可拔插的经验库**，谨慎吸收、人工审查）：
  把隔离区（上游隔离区/经验库条目/EXP-*.md）解析为 ExperienceEntry 投影，
  作为一个**独立于主库**的可拔插 ExperienceStore——通过
  `console.attach_experience(store=UpstreamExperienceStore(...))` 挂载/卸载。

治理语义（M6-2b 免疫通道，严格执行）：
  * 上游 status=promoted **在我们这里不算数**——外来经验未经本项目验证，
    全部投影为 `status=draft`（AI/主流程默认看不见，include_draft=True 供审查）
  * 人工审查通过 → `promote(eid, actor="human:...")`（原条目永不修改，只增不改）
  * record_override 不落本 store（打回回写属于主库）——本 store 是**只读投影**
    （协议方法 add/mark_reuse 显式拒绝写，fail-closed）

解析（EXP-*.md 格式：YAML-ish frontmatter + 正文两节）：
  id/date/source/status/legacy → provenance 与 legacy 字段
  claims[0] → attention（一句话教训）
  正文（现象与根因/规避法）→ story（全文保留）
  evidence 三件套原样保留 + recalc 指回隔离区文件
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from experience import ExperienceEntry, ExperienceStore

__all__ = ["UpstreamExperienceStore"]


def _parse_exp(md_path: Path) -> ExperienceEntry:
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    # ── frontmatter（首两个 --- 之间）──
    fm: dict[str, Any] = {}
    evidence: list[dict[str, str]] = []
    in_fm, in_ev = False, False
    cur_ev: dict[str, str] | None = None
    body_start = 0
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            if not in_fm:
                in_fm = True
                continue
            body_start = i + 1
            break
        if not in_fm:
            continue
        m = re.match(r"^(\w[\w-]*):\s*(.*)$", ln)
        if ln.startswith("  - ") or ln.startswith("- "):
            in_ev = True
            cur_ev = {}
            evidence.append(cur_ev)
            m2 = re.match(r"^\s*- (\w+):\s*(.*)$", ln)
            if m2 and cur_ev is not None:
                cur_ev[m2.group(1)] = m2.group(2).strip().strip('"')
            continue
        if in_ev and cur_ev is not None:
            m2 = re.match(r"^\s+(\w+):\s*(.*)$", ln)
            if m2:
                cur_ev[m2.group(1)] = m2.group(2).strip().strip('"')
                continue
            in_ev = False
        if m and not in_ev:
            fm[m.group(1)] = m.group(2).strip().strip('"')
    body = "\n".join(lines[body_start:]).strip()

    claims = fm.get("claims", "")
    attention = claims.split("\n")[0].lstrip("- ").strip() if claims \
        else (body.split("\n")[0] if body else md_path.stem)
    eid = f"upstream-{fm.get('id', md_path.stem)}"
    return ExperienceEntry(
        trigger={"origin": "blender-mcp-skill", "exp": fm.get("id", md_path.stem)},
        attention=attention[:120],
        story=body,
        params={},
        outcome="unverified",
        status="draft",                    # 免疫通道：外来经验一律 draft
        evidence=evidence or [{"artifact": str(md_path),
                               "quote": attention[:80],
                               "recalc": f"读 {md_path}"}],
        provenance={"author": f"upstream ({fm.get('source', '')[:40]})",
                    "source": str(md_path), "created": fm.get("date", ""),
                    "reused": 0, "reuse_success": 0, "variants": 0,
                    "legacy": fm.get("legacy", "")},
        weight=1.0,
        eid=eid)


class UpstreamExperienceStore:
    """上游经验条目的**只读投影** store（ExperienceStore 协议实现）。

    * 全部条目 `status=draft`——免疫通道：外来经验未经本项目验证，
      默认 recall 不可见（include_draft=True 供人工审查/AI 自查）
    * `promote(eid, actor="human:...")` = 人工审查通过的升级动作（登记在
      本 store 的覆盖表，原 md 文件永不修改——只增不改）
    * add/mark_reuse fail-closed：只读投影不接受写（打回回写属于主库）
    """

    def __init__(self, source_dir: Path | str,
                 promoted: dict[str, str] | None = None) -> None:
        self.source_dir = Path(source_dir)
        self.promoted = dict(promoted or {})   # eid → human actor
        self.entries: dict[str, ExperienceEntry] = {}
        for md in sorted(self.source_dir.glob("EXP-*.md")):
            e = _parse_exp(md)
            if e.eid in self.promoted:         # 人工审查已通过 → verified
                e.status = "verified"
            self.entries[e.eid] = e

    # ── ExperienceStore 协议（只读投影）─────────────────────
    def add(self, entry: Any, author: str = "", source: str = "") -> str:
        raise RuntimeError("UpstreamExperienceStore 是只读投影——"
                           "不接受追加（回写请走主库 ExperienceLibrary）")

    def recall(self, query: dict[str, Any], n: int = 3,
               include_draft: bool = False) -> list[ExperienceEntry]:
        """token 匹配 attention+story。draft 治理语义同主库：
        默认只出 verified（本 store 缺省为空——外来知识须人工晋升才可消费）。"""
        scored = []
        qtokens = {str(v).lower() for v in query.values()} | \
                  {str(k).lower() for k in query}
        for e in self.entries.values():
            if e.tombstone:
                continue
            if e.status == "draft" and not include_draft:
                continue
            hay = (e.attention + " " + e.story).lower()
            hit = sum(1 for t in qtokens if t in hay)
            match = hit / len(qtokens) if qtokens else 0.5
            w = e.weight * (0.5 if e.status == "draft" else 1.0)
            scored.append((w * (0.5 + 0.5 * match), e))
        scored.sort(key=lambda t: (-t[0], t[1].eid))
        return [e for _, e in scored[:max(2, n)]]

    def mark_reuse(self, eid: str, success: bool, had_variant: bool) -> None:
        raise RuntimeError("只读投影不支持复用回写——复用记录走主库")

    def record_override(self, trigger: dict[str, Any], note: str,
                        params: dict[str, Any] | None = None) -> str:
        raise RuntimeError("只读投影不接受打回回写——override 走主库")

    # ── 审查动作（人工）─────────────────────────────────────
    def promote(self, eid: str, actor: str) -> None:
        """人工审查通过：draft → verified（只接受 human:* actor）。"""
        e = self.entries.get(eid)
        if e is None:
            raise KeyError(f"条目 {eid!r} 不存在")
        if not str(actor).startswith("human:"):
            raise ValueError("晋升只接受 human:* actor——免疫通道（M6-2b）")
        e.status = "verified"
        self.promoted[eid] = actor

    def list_all(self) -> list[ExperienceEntry]:
        """审查视图：全部条目（含 draft）按编号排序。"""
        return sorted(self.entries.values(), key=lambda e: e.eid)
