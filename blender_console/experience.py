"""experience.py — M6 经验库核心（M6-1/2/4/6 · 纯 Python，无 bpy，Blender 内外同源）
================================================================================

组成（对应工单 M6-1/2/4/5/6）：
  * ExperienceEntry / ExperienceLibrary —— M6-2 条目契约 + M6-5 双层结构：
      注意引导层（trigger + attention："看哪里/警惕什么"，Ingold 教育注意）
      + 叙事层（story：带失败分支的诊断故事，Orr war stories）
      + provenance（谁记录/被复用几次/成功几次/有无变体——对抗死库效应）
      + 降权（被复用后无变体记录 → weight ×0.9）
  * bin_features / iou / select_diverse —— M6-1/M6-4 多样性闸门：
      特征 = 顶点直方图 32³（在线代理；128³ 体素体积 + EMD/LPIPS 留离线标定）
      MMR 贪心（λ 可调：偏好未定 0.3，明确 0.7）；**D9：k ≥ 2，禁 top-1**
  * PreferenceModel —— M6-6 偏好学习 MVP（Bradley-Terry 在线逻辑回归，核心 ≤30 行）：
      w += η·σ(−w·Δx)·Δx（Δx = 被选变体 − 落选变体，来自 ab_commit 的 WAL 载荷）
      冷启动 needs_exploration（前 15 次随机覆盖，Qian PVLDB 2016）
      收缩 shrink（样本少 → 偏向经验库先验）
      可解释 report（方向统计句："9/10 次你选了更粗的把手"）

红线对应：D9（禁 top-1 同质化）、R14（度量是反思工具，不许反转为优化目标）、
R15（偏好信号必须带 note——人的语言化中介，本模块只消费带 note 的记录由调用方把关）。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol, runtime_checkable

__all__ = ["ExperienceEntry", "ExperienceLibrary", "ExperienceStore",
           "PreferenceModel", "bin_features", "iou", "select_diverse"]


# ══════════════════════════════════════════════════════════════
# M8 · 热拔插协议（治理内核/经验库 = 可替换黑盒）
# ══════════════════════════════════════════════════════════════
@runtime_checkable
class ExperienceStore(Protocol):
    """经验库的**可替换接口**（用户指令：治理内核与经验库需热拔插、可替换）。

    原则（M8 热拔插，对齐上游"缺省通路永不依赖增强"+"换装=登记动作"）：
      * console/ab_commit 只依赖本协议，不依赖 JSONL 缺省实现——换实现不改上游一行
      * 治理位外置（对齐 evo_seat GOVERNANCE_BOUNDARY）：本协议只提供治理面
        （存/取/回写）；条目的验收/晋升（status 机器）由实现自决——
        **console 无权替经验库宣验收**
      * 任何实现必须说契约面的话（R17）：add/recall/mark_reuse/record_override
    """

    entries: Any

    def add(self, entry: Any, author: str = "", source: str = "") -> str: ...

    def recall(self, query: dict[str, Any], n: int = 3) -> list: ...

    def mark_reuse(self, eid: str, success: bool, had_variant: bool) -> None: ...

    def record_override(self, trigger: dict[str, Any], note: str,
                        params: dict[str, Any] | None = None) -> str: ...


# ══════════════════════════════════════════════════════════════
# M6-2/M6-5 · 条目契约（双层结构 + provenance + 降权）
# ══════════════════════════════════════════════════════════════
@dataclass
class ExperienceEntry:
    """一条经验 = 注意引导层 + 叙事层 + 结构化参数 + provenance + M6-2b 治理字段。

    M6-2b（吸收上游演化内核思想，字段级）：
      * status 状态机 draft → verified（promoted 预留）——**未复核条目不进 recall**
      * evidence 出处三件套 [{artifact, quote, recalc}]——recalc 必须是可复算命令；
        **无 evidence 的条目最高只能 draft**
      * supersedes + tombstone——只增不改：修订=新条目指向旧条目，旧条目墓碑
        （weight 不变，recall 跳过；永不物理删除）
    """
    trigger: dict[str, Any]            # 注意引导层·条件：{"param": "Handle_Thickness", "scene": "mug"}
    attention: str                     # 注意引导层·"看哪里/警惕什么"（一句话）
    story: str                         # 叙事层：诊断故事（可带失败分支；Orr war stories）
    params: dict[str, float] = field(default_factory=dict)   # 结构化参数快照（M6-6 可消费）
    outcome: str = "unverified"        # "verified_success" | "verified_failure" | "unverified"
    status: str = "draft"              # M6-2b："draft" | "verified" | "promoted"
    evidence: list[dict[str, str]] = field(default_factory=list)  # 出处三件套
    supersedes: str | None = None      # 修订链：本条目取代哪条旧条目
    tombstone: bool = False            # 墓碑（被取代/撤销）：保留不删，recall 跳过
    provenance: dict[str, Any] = field(default_factory=lambda: {
        "author": "", "source": "", "created": "",
        "reused": 0, "reuse_success": 0, "variants": 0,
    })
    weight: float = 1.0                # 降权系数落在这里（差异化衰减，见 mark_reuse）
    eid: str = ""                      # 内容寻址（add 时自动算）
    owner: str = ""                    # W-12（Orr 领地与孤机）：归属会话/人——
                                       #   "ai:ai-channel" / "user-override" /
                                       #   "legacy:pre-W12"（存量语料迁移）。
                                       #   空 = 无主件，recall 防毒过滤器跳过

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExperienceEntry":
        # W-12 迁移（2026-09-29）：存量语料 owner 缺失 → "legacy:pre-W12"
        # （视为社区公共知识，有主——不被 recall 防毒过滤器误伤）
        owner = d.get("owner") or "legacy:pre-W12"
        return cls(
            trigger=d.get("trigger", {}),
            attention=d.get("attention", ""),
            story=d.get("story", ""),
            params=d.get("params", {}),
            outcome=d.get("outcome", "unverified"),
            status=d.get("status", "draft"),
            evidence=d.get("evidence", []),
            supersedes=d.get("supersedes"),
            tombstone=bool(d.get("tombstone", False)),
            provenance=d.get("provenance") or {
                "author": "", "source": "", "created": "",
                "reused": 0, "reuse_success": 0, "variants": 0},
            weight=float(d.get("weight", 1.0)),
            eid=d.get("eid", ""),
            owner=owner)

    def content_eid(self) -> str:
        blob = json.dumps({"t": self.trigger, "a": self.attention,
                           "p": self.params}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ══════════════════════════════════════════════════════════════
# M6-1/M6-4 · 多样性闸门（在线代理：顶点直方图 IoU + MMR）
# ══════════════════════════════════════════════════════════════
def bin_features(points: Iterable[Sequence[float]], origin: Sequence[float],
                 cell: float, dims: tuple[int, int, int] = (32, 32, 32)) -> frozenset:
    """顶点直方图特征：每个顶点落进 32³ 网格的一格，返回被占格集合。

    在线代理的取舍（写明，不装）：工单的 128³ 体素体积 IoU + EMD/LPIPS 属于
    离线标定；在线闸门用顶点直方图——便宜、确定性、对"形状分布差异"足够敏感。
    """
    out: set[tuple[int, int, int]] = set()
    ox, oy, oz = origin
    for p in points:
        ix = int((p[0] - ox) / cell)
        iy = int((p[1] - oy) / cell)
        iz = int((p[2] - oz) / cell)
        if 0 <= ix < dims[0] and 0 <= iy < dims[1] and 0 <= iz < dims[2]:
            out.add((ix, iy, iz))
    return frozenset(out)


def iou(fa: frozenset, fb: frozenset) -> float:
    """Jaccard IoU；两个空集视为相同（1.0）。"""
    if not fa and not fb:
        return 1.0
    union = len(fa | fb)
    return len(fa & fb) / union if union else 1.0


def select_diverse(features: list[frozenset], k: int = 2,
                   lam: float = 0.5, rel: list[float] | None = None) -> list[int]:
    """M6-1 多样性闸门：MMR 贪心选 k 个（λ·相关 − (1−λ)·最大相似）。

    D9：k ≥ 2（禁 top-1——同质化效应，Doshi & Hauser 2024）。
    rel 缺省全 1（无检索排序时退化为 farthest-point 最大化差异）。
    返回**有序**选中下标（第一个 = 相关性最高者，后续逐个最差异化）。
    """
    if k < 2:
        raise ValueError("D9：经验库禁 top-1——k 至少为 2")
    n = len(features)
    if n < k:
        raise ValueError(f"候选数 {n} 少于 k={k}")
    rel = list(rel) if rel else [1.0] * n
    first = max(range(n), key=lambda i: rel[i])
    chosen = [first]
    while len(chosen) < k:
        best_i, best_s = None, -1e18
        for i in range(n):
            if i in chosen:
                continue
            max_sim = max(iou(features[i], features[j]) for j in chosen)
            s = lam * rel[i] - (1 - lam) * max_sim
            if s > best_s:
                best_i, best_s = i, s
        chosen.append(best_i)
    return chosen


# ══════════════════════════════════════════════════════════════
# M6-6 · 偏好学习 MVP（Bradley-Terry 在线逻辑回归，核心 ≤30 行）
# ══════════════════════════════════════════════════════════════
def _sigmoid(z: float) -> float:
    if z < -30:
        return 0.0
    if z > 30:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


class PreferenceModel:
    """逐参数偏好权重。数据源 = ab_commit 的 WAL 载荷（R15：须带 note）。"""

    def __init__(self, eta: float = 0.15, prior: dict[str, float] | None = None,
                 cold_start: int = 15, prior_mu: float = 4.0) -> None:
        self.eta = eta
        self.cold_start = cold_start      # M6-6 冷启动：前 15 次随机覆盖（Qian 2016）
        self.prior_mu = prior_mu          # 收缩强度（样本少 → 偏向先验）
        self.prior = {k: float(v) for k, v in (prior or {}).items()}
        self.w: dict[str, float] = dict(self.prior)
        self.n = 0                        # 已消费的 A/B 决定数
        self.tally: dict[str, list[int]] = {}   # 可解释素材：{key: [选更大次数, 选更小次数]}

    def observe(self, chosen: dict[str, Any], other: dict[str, Any]) -> None:
        """一次 A/B 决定：Δx = 被选 − 落选。核心式（工单原文）：w += η·σ(−w·Δx)·Δx

        全部 Δx=0（两变体参数相同）= 无信息观察：不计次数、不收缩、不进 tally。
        """
        keys = {k for k in list(chosen) + list(other)
                if isinstance(chosen.get(k, 0), (int, float))
                and isinstance(other.get(k, 0), (int, float))}
        updates = []
        for k in keys:
            dx = float(chosen.get(k, 0.0)) - float(other.get(k, 0.0))
            if dx == 0.0:
                continue
            updates.append((k, dx))
        if not updates:
            return
        for k, dx in updates:
            w = self.w.get(k, self.prior.get(k, 0.0))
            self.w[k] = w + self.eta * _sigmoid(-w * dx) * dx
            t = self.tally.setdefault(k, [0, 0])
            t[0 if dx > 0 else 1] += 1
        self.n += 1
        self.shrink()

    def shrink(self) -> None:
        """收缩式：w ← λ·w + (1−λ)·prior，λ = n/(n+μ)。样本少 → 偏向经验库先验。"""
        lam = self.n / (self.n + self.prior_mu) if (self.n + self.prior_mu) else 0.0
        for k in list(self.w) + list(self.prior):
            self.w[k] = lam * self.w.get(k, 0.0) + (1 - lam) * self.prior.get(k, 0.0)

    def needs_exploration(self) -> bool:
        """冷启动：前 cold_start 次应随机覆盖式出 A/B（主动提问早期有害）。"""
        return self.n < self.cold_start

    def score(self, params: dict[str, Any]) -> float:
        """偏好打分（仅供排序/展示；不打几何分——R5 不越界）。"""
        return sum(self.w.get(k, 0.0) * float(v) for k, v in params.items()
                   if isinstance(v, (int, float)))

    def report(self, min_n: int = 5, split: float = 0.7) -> list[str]:
        """可解释句（MVP 用方向统计替代决策树代理）：
        "9/10 次你选了 Handle_Thickness 更大的变体（占比 90%）"。"""
        out: list[str] = []
        for k, (pos, neg) in sorted(self.tally.items()):
            total = pos + neg
            if total < min_n:
                continue
            if pos / total >= split:
                out.append(f"{pos}/{total} 次你选了 {k} 更大的变体（占比 {pos / total:.0%}）")
            elif neg / total >= split:
                out.append(f"{neg}/{total} 次你选了 {k} 更小的变体（占比 {neg / total:.0%}）")
        return out


# ══════════════════════════════════════════════════════════════
# M6-2 · 经验库（持久化 + recall D9 + 复用降权）
# ══════════════════════════════════════════════════════════════
class ExperienceLibrary:
    """JSONL 持久化的经验条目库（**ExperienceStore 协议的缺省实现**）。

    recall 永不 top-1（D9）。可被任何满足 ExperienceStore 协议的实现替换
    （console.attach_experience(store=...) 注入——热拔插，缺省通路零依赖）。
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.entries: dict[str, ExperienceEntry] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                e = ExperienceEntry.from_dict(json.loads(line))
                self.entries[e.eid] = e

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            "\n".join(json.dumps(e.to_dict(), ensure_ascii=False)
                      for e in self.entries.values()) + "\n",
            encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, entry: ExperienceEntry, author: str = "", source: str = "") -> str:
        # M6-2b 写入分权：**无出处三件套的条目最高只能 draft**（上游："缺一不收"）
        if entry.status in ("verified", "promoted") and not entry.evidence:
            entry.status = "draft"
        entry.eid = entry.content_eid()
        now = time.strftime("%Y-%m-%d %H:%M")
        p = entry.provenance
        p.setdefault("reused", 0)
        p.setdefault("reuse_success", 0)
        p.setdefault("variants", 0)
        if author:
            p["author"] = author
        if source:
            p["source"] = source
        if not p.get("created"):
            p["created"] = now
        # W-12（2026-09-29）：归属自动落账——写入通道（record_ai/record_override）
        # 的 author 即 owner；低层 add 无 author 时保持空 = 无主件
        # （recall 防毒过滤器跳过，见 recall）。
        if not entry.owner and author:
            entry.owner = (author if ":" in author
                           else "ai:ai-channel" if author == "ai" else author)
        if entry.eid in self.entries:          # 幂等（内容寻址去重）
            return entry.eid
        self.entries[entry.eid] = entry
        self._save()
        return entry.eid

    def recall(self, query: dict[str, Any], n: int = 3,
               include_draft: bool = False) -> list[ExperienceEntry]:
        """按 trigger 匹配召回，weight × 匹配度排序。**D9：永不只回 1 条**——
        至少 2 条（库够时），把"差异化候选"的责任压在调用方下游之前。

        M6-2b 治理语义：墓碑条目永跳；draft 条目默认不出现（"未复核不进分册"），
        include_draft=True 时以 ×0.5 权重出现（供 AI 自查，不冒充已复核知识）。
        """
        if not self.entries:
            return []
        n = max(2, n) if len(self.entries) >= 2 else n
        scored = []
        for e in self.entries.values():
            if e.tombstone:
                continue
            if e.status == "draft" and not include_draft:
                continue
            if not e.owner:
                continue          # W-12 防毒（Orr 孤机）：无主件不进召回——
                                  # WAL 能回滚现场，回滚不了被污染的检索
            hit = sum(1 for k, v in query.items() if e.trigger.get(k) == v)
            match = hit / len(query) if query else 0.5
            w = e.weight * (0.5 if e.status == "draft" else 1.0)
            scored.append((w * (0.5 + 0.5 * match), match, e))
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [e for _, _, e in scored[:n]]

    def mark_reuse(self, eid: str, success: bool, had_variant: bool) -> None:
        """复用回写（M6-3 的库侧）：无变体复用 → **差异化衰减**（M6-2b）——
        unverified ×0.8（未复核知识加速贬值）；verified_success / verified_failure
        不衰减（成功经验与失败教训都不过期——Orr war stories 一票）。"""
        e = self.entries.get(eid)
        if e is None:
            raise KeyError(f"经验条目 {eid!r} 不存在")
        e.provenance["reused"] = int(e.provenance.get("reused", 0)) + 1
        if success:
            e.provenance["reuse_success"] = int(e.provenance.get("reuse_success", 0)) + 1
        if had_variant:
            e.provenance["variants"] = int(e.provenance.get("variants", 0)) + 1
        elif e.outcome == "unverified":
            e.weight = round(e.weight * 0.8, 4)
        self._save()

    def record_override(self, trigger: dict[str, Any], note: str,
                        params: dict[str, float] | None = None) -> str:
        """M6-3 override 回写：人的打回 → 一条 verified 经验（R15 已语言化）。

        治理位外置：**人有权宣验收**——打回经人手，直接 verified（免疫通道的
        反向：AI 写入必须 draft，见 record_ai）。人的 note 本身就是出处证据：
        artifact=导演会话、quote=打回原话、recalc=WAL 检索——三件套齐全，
        不触发 add() 的"缺证据压 draft"。
        """
        e = ExperienceEntry(
            trigger=trigger,
            attention=f"警惕：此前方案在此触发条件下被打回——{note[:60]}",
            story=f"用户 override：{note}",
            params=params or {},
            outcome="verified_failure",
            status="verified",
            evidence=[{"artifact": "director/WAL:ab_override|director_override",
                       "quote": note,
                       "recalc": "grep 'override' events.jsonl"}])
        return self.add(e, author="user-override", source="ab_override")

    def record_ai(self, trigger: dict[str, Any], attention: str, story: str,
                  params: dict[str, float] | None = None,
                  evidence: list[dict[str, str]] | None = None,
                  supersedes: str | None = None,
                  verified_failure: bool = False) -> str:
        """**免疫通道**：AI 侧追加经验——强制 draft（M6-2b/上游：引擎只写 draft，
        晋升必须过人）。AI 无权自宣验收；带完整出处三件套的也只能到 draft，
        由 promote(actor="human:*") 升级。

        verified_failure=True（war stories 通道）：AI 可以声明"这是**机器门禁
        验证过的失败**"——outcome 写 verified_failure，因为失败事实由 gate 谓词
        （机器凭证）判定，非 AI 主观；但 status 仍强制 draft——"这条教训值得
        长期入库"仍由人晋升。mark_reuse 对 verified_failure 不衰减（失败教训
        不过期），include_draft 召回时以 ×0.5 权重出现。
        """
        e = ExperienceEntry(trigger=trigger, attention=attention, story=story,
                            params=params or {},
                            outcome="verified_failure" if verified_failure
                                    else "unverified",
                            status="draft", evidence=evidence or [],
                            supersedes=supersedes)
        return self.add(e, author="ai", source="ai-channel")

    def promote(self, eid: str, actor: str) -> None:
        """draft → verified（M6-2b 免疫通道的人工门）：**只接受 human:* actor**——
        AI/引擎无权自宣验收（上游"晋升必须过人"的 enforcement）。"""
        e = self.entries.get(eid)
        if e is None:
            raise KeyError(f"经验条目 {eid!r} 不存在")
        if not str(actor).startswith("human:"):
            raise ValueError("晋升只接受 human:* actor——AI/引擎无权自宣验收（免疫通道）")
        e.status = "verified"
        self._save()

    def tombstone(self, eid: str, reason: str = "") -> None:
        """墓碑（M6-2b 只增不改）：被取代/撤销的条目保留不删，recall 永跳。"""
        e = self.entries.get(eid)
        if e is None:
            raise KeyError(f"经验条目 {eid!r} 不存在")
        e.tombstone = True
        if reason:
            e.provenance["tombstone_reason"] = reason
        self._save()
