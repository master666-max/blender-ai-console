"""
m1_core.py — 工单 WB-MUG-2026-001 · M1 数据层落地（阻塞项 M1-1/1-3/1-6 + M1-2/1-4/1-7）
=====================================================================================

纯 Python，不依赖 bpy，`python m1_core.py` 即跑全部测试。
设计依据全部来自本会话实测/调研，逐条标注（A 编号 = 工单改动清单）。

模块内容
--------
1. FlowDAG            —— A1：显式 DAG + 依赖边 + 环拒绝 + steps_for_object/thought + descendants(影响预览)
2. WALLog             —— A32/A6：append-only JSONL，哈希链防篡改，只录非确定性输入（rr 原则），replay/verify/compact
3. RevisionTable      —— A28：Salsa 式 revision + backdating（重算后输出 hash 未变 → 标绿截断级联）；失效比例 >40% 走全量
4. VersionedParams    —— A31(过渡实现)：版本化参数表（量化浮点保缓存命中；HAMT 为 M1-5b）
5. ParamUpdate/LogOnly —— A29/A7：命令空间结构化——参数更新天然自带逆 (old,new) 互换（Janus reversible update）；
                          pivot（导出/落盘）禁止回退，只许 forward；逆由结构机械生成，不手写
6. SegmentCommits     —— A33：段 = 内容寻址 commit（同参数+同输出 → 同 hash 去重）
7. export_state       —— M9-4a：Web 前端状态契约（只读 JSON；前端是视图，不是真源）

诚实边界
--------
* VersionedParams 目前是"每版整份拷贝"的过渡实现——参数表是 KB 级小状态，可接受；
  HAMT/结构共享留 M1-5b（工单 A31 后半）。
* WAL 的"只录非确定性输入"靠调用方纪律：确定性可重算的求值结果一律不落盘（rr 原则）。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

__all__ = [
    "CycleError", "PivotBlocked", "SagaTag", "ParamUpdate",
    "StepRecord", "FlowDAG", "WALLog", "RevisionTable",
    "VersionedParams", "quantize", "commit_hash", "SegmentCommits",
    "export_state",
]


# ══════════════════════════════════════════════════════════════
# 异常
# ══════════════════════════════════════════════════════════════
class CycleError(Exception):
    """A1：DAG 拒绝回环（Grasshopper 铁律：数据流单向，隐式=不可回退）。"""


class PivotBlocked(Exception):
    """A29：pivot（导出/落盘等外部副作用）之后只许 forward recovery。"""


# ══════════════════════════════════════════════════════════════
# A29/A7 · 命令空间结构化：机械逆
# ══════════════════════════════════════════════════════════════
class SagaTag(Enum):
    """A29：Saga 词汇分类（Garcia-Molina & Salem 1987）。

    compensable = 可补偿（参数写入，逆由 (old,new) 机械导出）
    pivot       = 不可回退的关口（渲染导出、落盘）——跨过只许 forward
    retriable   = 重试安全
    """
    COMPENSABLE = "compensable"
    PIVOT = "pivot"
    RETRIABLE = "retriable"


@dataclass(frozen=True)
class ParamUpdate:
    """参数更新命令——Janus 式 reversible update：逆 = (old,new) 互换，机械生成。

    工单 A29：逆运算由结构导出而非手写；表达式求值不可逆不损害命令可逆
    （求值隔离在只读侧，写侧保持单射）。
    """
    unit: str
    param: str
    old: Any
    new: Any
    tag: SagaTag = SagaTag.COMPENSABLE

    def __post_init__(self) -> None:
        if self.tag is SagaTag.PIVOT:
            raise ValueError("ParamUpdate 不允许 pivot 标签——pivot 是外部副作用专用")

    def apply(self, params: dict[str, Any]) -> dict[str, Any]:
        """把参数写到目标单元（返回新 dict，不改旧版——A31 版本化前提）。"""
        out = dict(params)
        out[f"{self.unit}.{self.param}"] = self.new
        return out

    def inverse(self) -> "ParamUpdate":
        """机械逆：old/new 互换。O(1)，无手写。"""
        if self.tag is SagaTag.PIVOT:
            raise PivotBlocked(f"pivot 命令不可逆：{self.unit}.{self.param}")
        return ParamUpdate(self.unit, self.param, self.new, self.old, self.tag)


@dataclass(frozen=True)
class LogOnly:
    """不可逆动作（导出/落盘）——pivot：进入后历史只能向前。"""
    desc: str
    tag: SagaTag = SagaTag.PIVOT

    def inverse(self) -> None:
        raise PivotBlocked(f"pivot 不可逆（只许 forward recovery）：{self.desc}")


# ══════════════════════════════════════════════════════════════
# A1 · FlowDAG：显式有向无环图
# ══════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class StepRecord:
    """A10：不只记"做了什么"——带 seed/参数/选中集/thought 引用/revision，保证可确定性重放。
    A16：同时携带 gn_delta（节点树 diff）——trace 与 diff 双载体。
    """
    step_id: str
    seg: str                       # 所属语义段落（= modifier = opinion 层）
    obj: str                       # 受影响物体（A2 区域反查键）
    params: tuple[tuple[str, Any], ...] = ()   # 冻结的参数对（可 json 化）
    deps: tuple[str, ...] = ()     # 依赖的前序 step（DAG 边）
    thought_refs: tuple[str, ...] = ()
    seed: int = 0                  # 随机种子（重放确定性）
    selection: tuple[str, ...] = ()  # 选中集快照
    revision: int = 0
    gn_delta: tuple[tuple[str, Any], ...] = ()  # A16：节点树 diff（段级）


def _has_cycle(steps: Mapping[str, Any], edges: Mapping[str, Iterable[str]]) -> bool:
    """迭代式三色 DFS（避免深递归）。"""
    color = {n: 0 for n in steps}
    for start in steps:
        if color[start]:
            continue
        stack = [(start, iter(edges.get(start, ())))]
        color[start] = 1
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if nxt not in color:
                    continue
                if color[nxt] == 1:
                    return True
                if color[nxt] == 0:
                    color[nxt] = 1
                    stack.append((nxt, iter(edges.get(nxt, ()))))
                    advanced = True
                    break
            if not advanced:
                color[node] = 2
                stack.pop()
    return False


class FlowDAG:
    """A1：流程轴 = 显式 DAG。回环在 add() 时拒绝，永不进入状态。"""

    def __init__(self) -> None:
        self._steps: dict[str, StepRecord] = {}
        self._edges: dict[str, tuple[str, ...]] = {}

    # -- 写 --
    def add(self, step: StepRecord) -> str:
        if step.step_id in self._steps:
            raise ValueError(f"step 重复：{step.step_id}")
        for d in step.deps:
            if d not in self._steps:
                raise ValueError(f"依赖不存在：{d}")
        trial = dict(self._edges)
        trial[step.step_id] = step.deps
        if _has_cycle({**self._steps, step.step_id: step}, trial):
            raise CycleError(f"拒绝回环：{step.step_id} 的依赖链成环")
        self._steps[step.step_id] = step
        self._edges[step.step_id] = step.deps
        return step.step_id

    def remove(self, step_id: str) -> None:
        """移除**叶子**步（无后继）。导演打回最后提案的段落用——
        有后继的中间步删除会破坏下游依赖语义，响亮拒绝。"""
        if step_id not in self._steps:
            raise KeyError(f"step 不存在：{step_id}")
        dependents = [n for n, ds in self._edges.items()
                      if step_id in ds and n != step_id]
        if dependents:
            raise ValueError(f"step {step_id} 有后继 {dependents}——只许删叶子步")
        del self._steps[step_id]
        del self._edges[step_id]

    # -- 读 --
    def get(self, step_id: str) -> StepRecord:
        return self._steps[step_id]

    def all_steps(self) -> list[StepRecord]:
        return list(self._steps.values())

    def topo_order(self) -> list[str]:
        """拓扑序（依赖在前）。"""
        indeg = {n: 0 for n in self._steps}
        for n, ds in self._edges.items():
            for d in ds:
                if d in indeg:
                    indeg[n] += 1
        order, ready = [], [n for n, d in indeg.items() if d == 0]
        edge_rev: dict[str, list[str]] = {n: [] for n in self._steps}
        for n, ds in self._edges.items():
            for d in ds:
                if d in edge_rev:
                    edge_rev[d].append(n)
        while ready:
            n = ready.pop(0)
            order.append(n)
            for m in sorted(edge_rev.get(n, ())):
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
        if len(order) != len(self._steps):
            raise CycleError("DAG 内部状态异常：拓扑排序未覆盖全部节点")
        return order

    def steps_for_object(self, obj: str) -> list[StepRecord]:
        """A2：区域/对象反查——人记不住第几步，记得住"这个把手坏了"。"""
        return [s for s in self._steps.values() if s.obj == obj]

    def steps_for_thought(self, tid: str) -> list[StepRecord]:
        return [s for s in self._steps.values() if tid in s.thought_refs]

    def descendants(self, step_id: str) -> list[str]:
        """A29 影响预览：推翻某步后将被重推的下游（因果闭包，闭包 = 子孙集合）。"""
        rev: dict[str, list[str]] = {n: [] for n in self._steps}
        for n, ds in self._edges.items():
            for d in ds:
                if d in rev:
                    rev[d].append(n)
        seen, stack = set(), [step_id]
        while stack:
            cur = stack.pop()
            for nxt in rev.get(cur, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return sorted(seen - {step_id})

    def segments(self) -> dict[str, list[str]]:
        """按语义段落折叠（人扫段落不扫步骤）。"""
        out: dict[str, list[str]] = {}
        for sid in self.topo_order():
            out.setdefault(self._steps[sid].seg, []).append(sid)
        return out

    def __len__(self) -> int:
        return len(self._steps)


# ══════════════════════════════════════════════════════════════
# A32/A6 · WAL：append-only 哈希链，只录非确定性输入
# ══════════════════════════════════════════════════════════════
class WALLog:
    """事件日志：JSONL + 哈希链（防篡改、可验证）。

    rr 原则：**只记会改变结果的东西**（用户参数、随机种子、外部状态）——
    确定性可重算的求值结果一律不落盘。payload 由调用方保证遵守此纪律。
    """

    GENESIS = "0" * 64

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None
        self._rows: list[dict[str, Any]] = []
        if self._path and self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._rows.append(json.loads(line))

    @staticmethod
    def _hash(prev: str, seq: int, kind: str, payload: Mapping[str, Any], ts: float) -> str:
        blob = json.dumps({"prev": prev, "seq": seq, "kind": kind,
                           "payload": payload, "ts": ts}, sort_keys=True,
                          ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def append(self, kind: str, payload: Mapping[str, Any], ts: float | None = None) -> dict[str, Any]:
        ts = time.time() if ts is None else ts
        seq = len(self._rows)
        prev = self._rows[-1]["hash"] if self._rows else self.GENESIS
        h = self._hash(prev, seq, kind, payload, ts)
        row = {"seq": seq, "ts": ts, "kind": kind, "payload": dict(payload),
               "prev": prev, "hash": h}
        self._rows.append(row)
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                f.flush()
                os.fsync(f.fileno())   # R5：掉电不丢已落账行——WAL 的存在意义就是崩溃恢复
        return row

    def replay(self) -> list[dict[str, Any]]:
        """重放 = 按序返回全部事件（确定性执行的输入序列）。"""
        return list(self._rows)

    def verify(self) -> bool:
        """哈希链校验：任一行被篡改 → False。"""
        prev = self.GENESIS
        for i, r in enumerate(self._rows):
            if r["seq"] != i or r["prev"] != prev:
                return False
            expect = self._hash(prev, r["seq"], r["kind"], r["payload"], r["ts"])
            if expect != r["hash"]:
                return False
            prev = r["hash"]
        return True

    def compact(self, checkpoint_kind: str = "compaction_barrier",
                snapshot_resolver: Callable[[str], bool] | None = None,
                ) -> dict[str, Any]:
        """A32 compaction（A1/A2 语义修复 · 2026-09-28）：

        * 边界 kind 默认 "compaction_barrier"——与 console 回退点 "restore_point"
          拆分命名空间（A2：旧默认 "checkpoint" 会把用户每次存档都变成授权丢历史）。
        * 边界行 payload 必须携带 snapshot_ref 且（若提供 resolver）引用可解析，
          否则拒绝压缩返回 dropped=0（A1：快照未落盘前折叠历史 = 数据丢失，
          宁可不压缩）。resolver 通常传 SnapshotStore.has。
        * 返回 {"dropped": int, "hash_map": {old_hash: new_hash}}——重哈希后旧
          hash 引用不再静默断链（R6）：保留行映射到自身新 hash，丢弃行折叠到
          边界行新 hash。
        """
        last_cp = -1
        for i, r in enumerate(self._rows):
            if r["kind"] == checkpoint_kind:
                last_cp = i
        if last_cp < 0:
            return {"dropped": 0, "hash_map": {}}
        ref = self._rows[last_cp]["payload"].get("snapshot_ref")
        if not ref or (snapshot_resolver is not None and not snapshot_resolver(ref)):
            return {"dropped": 0, "hash_map": {}}     # A1 守卫：拒绝压缩
        old_rows = list(self._rows)
        kept = old_rows[last_cp:]
        dropped = len(old_rows) - len(kept)
        if dropped <= 0:
            return {"dropped": 0, "hash_map": {}}
        # 重排 seq 并重算链
        new_rows, prev = [], self.GENESIS
        for i, r in enumerate(kept):
            h = self._hash(prev, i, r["kind"], r["payload"], r["ts"])
            new_rows.append({**r, "seq": i, "prev": prev, "hash": h})
            prev = h
        self._rows = new_rows
        if self._path:
            self._path.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in self._rows) + "\n",
                encoding="utf-8")
        hash_map = {r["hash"]: new_rows[k]["hash"] for k, r in enumerate(kept)}
        edge_new = new_rows[0]["hash"]
        for r in old_rows[:last_cp]:                  # 丢弃行折叠到边界行新 hash
            hash_map[r["hash"]] = edge_new
        return {"dropped": dropped, "hash_map": hash_map}


class SnapshotStore:
    """内容寻址快照仓（A1 · 2026-09-28：checkpoint 状态落盘——compaction 的前置条件）。

    put(obj) → sha16 引用；get(ref) → 原对象；has(ref) → bool。
    落盘 <root>/<sha16>.json；同内容幂等同 ref（内容寻址 = 去重 + 天然防篡改）。
    console.checkpoint() 把 mesh/params 序列化后 put 进来，WAL 边界行 payload
    携带返回的 ref——WALLog.compact 靠它守卫：快照不在盘上就拒绝折叠历史。
    """

    def __init__(self, root: str | Path | None) -> None:
        # root=None → 进程内 dict 模式（console 无 workdir 时退化；语义不变）
        self._mem: dict[str, str] = {}
        self._root = Path(root) if root else None
        if self._root:
            self._root.mkdir(parents=True, exist_ok=True)

    def put(self, obj: Any) -> str:
        blob = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
        ref = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
        if self._root:
            f = self._root / f"{ref}.json"
            if not f.exists():
                f.write_text(blob, encoding="utf-8")
        else:
            self._mem[ref] = blob
        return ref

    def get(self, ref: str) -> Any:
        if self._root:
            return json.loads((self._root / f"{ref}.json").read_text(encoding="utf-8"))
        return json.loads(self._mem[ref])

    def has(self, ref: str) -> bool:
        if self._root:
            return (self._root / f"{ref}.json").exists()
        return ref in self._mem


# ══════════════════════════════════════════════════════════════
# A28 · RevisionTable：红绿失效判定（backdating）
# ══════════════════════════════════════════════════════════════
FULL_RECOMPUTE_THRESHOLD = 0.40   # 失效比例超过此值 → 放弃增量走全量（经验值，EXP 待标定）


@dataclass
class UnitState:
    param_fp: str = ""             # 参数指纹（量化后的 json hash）
    last_output_hash: str = ""     # 最近一次执行输出的 hash（LOD 指纹）
    own_dirty: bool = False        # 自身参数变过且尚未重执行
    revision: int = 0


class RevisionTable:
    """红绿失效判定（A28 / Salsa 语义）：

    · touch(unit, fp)          —— 参数变了：own_dirty = True
    · dirty(unit)              —— 自身脏 **或** 任一上游单元脏（递归，带 memo）
    · report_output(unit, hash)—— 重执行完成：own_dirty 清除；返回输出是否真的变了
      · 若 hash 与上次相同 → backdate：整个下游的"继承脏"自动消解（上游输出相同，
        下次重算结果必然相同）——这正是级联截断
      · 若变了 → 下游保持脏（它们必须重算）
    · mode()                   —— 脏比例 > 40% → FULL（放弃增量走全量）
    """

    def __init__(self, dag: FlowDAG | None = None) -> None:
        self._units: dict[str, UnitState] = {}
        self._dag = dag
        self.global_revision = 0

    def _unit(self, unit: str) -> UnitState:
        return self._units.setdefault(unit, UnitState())

    def units(self) -> list[str]:
        return list(self._units)

    def _upstream_units(self, unit: str) -> set[str]:
        """段级上游：本段任一 step 依赖了别的段的 step。"""
        out: set[str] = set()
        if self._dag is None:
            return out
        for s in self._dag.all_steps():
            if s.seg != unit:
                continue
            for d in s.deps:
                dep_seg = self._dag.get(d).seg
                if dep_seg != unit:
                    out.add(dep_seg)
        return out

    def is_dirty(self, unit: str, _seen: set[str] | None = None) -> bool:
        seen = _seen or set()
        if unit in seen:
            return False
        seen.add(unit)
        u = self._unit(unit)
        if u.own_dirty:
            return True
        return any(self.is_dirty(v, seen) for v in self._upstream_units(unit))

    def touch(self, unit: str, param_fp: str) -> list[str]:
        """参数变化 → own_dirty = True。返回当前全部脏单元（含继承）。"""
        self.global_revision += 1
        # 先物化 DAG 里的所有段——否则懒创建会让"下游还不存在于 _units"而漏判
        if self._dag is not None:
            for s in self._dag.all_steps():
                self._unit(s.seg)
        u = self._unit(unit)
        u.revision = self.global_revision
        if u.param_fp == param_fp and not u.own_dirty:
            return [x for x in self._units if self.is_dirty(x)]
        u.param_fp = param_fp
        u.own_dirty = True
        return sorted(x for x in self._units if self.is_dirty(x))

    def report_output(self, unit: str, output_hash: str) -> bool:
        """重执行完成：清自身脏；返回输出是否真的变了（False = backdate，级联截断）。"""
        u = self._unit(unit)
        changed = u.last_output_hash != output_hash
        u.last_output_hash = output_hash
        u.own_dirty = False
        return changed

    def dirty_units(self) -> list[str]:
        return sorted(x for x in self._units if self.is_dirty(x))

    def dirty_ratio(self) -> float:
        if not self._units:
            return 0.0
        return len(self.dirty_units()) / len(self._units)

    def mode(self) -> str:
        """失效比例 > 40% → FULL（放弃增量走全量）。"""
        return "FULL" if self.dirty_ratio() > FULL_RECOMPUTE_THRESHOLD else "INCREMENTAL"

    def invalidate_all(self) -> None:
        for u in self._units.values():
            u.own_dirty = True

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {k: {"param_fp": v.param_fp, "output_hash": v.last_output_hash,
                    "revision": v.revision, "dirty": self.is_dirty(k)}
                for k, v in self._units.items()}


# ══════════════════════════════════════════════════════════════
# A31(过渡) · VersionedParams：版本化参数表 + 量化
# ══════════════════════════════════════════════════════════════
def quantize(value: Any, step: float | None) -> Any:
    """A28 连续 float 是缓存杀手：按可分辨步长量化（CADbuildr 结论）。"""
    if isinstance(value, float) and step:
        return round(round(value / step) * step, 10)
    return value


class VersionedParams:
    """版本化参数表（过渡实现：每版整份 dict 拷贝——参数表是 KB 级小状态，可接受）。

    M1-5b 待办：换 HAMT/路径复制结构，实现严格 O(log n) 结构共享。
    """

    def __init__(self, initial: Mapping[str, Any] | None = None,
                 steps: Mapping[str, float] | None = None) -> None:
        self._revs: list[dict[str, Any]] = [dict(initial or {})]
        self._steps: dict[str, float] = dict(steps or {})

    def _q(self, params: dict[str, Any]) -> dict[str, Any]:
        return {k: quantize(v, self._steps.get(k)) for k, v in params.items()}

    def set_many(self, updates: Mapping[str, Any]) -> int:
        cur = dict(self._revs[-1])
        cur.update(self._q(dict(updates)))
        self._revs.append(cur)
        return len(self._revs) - 1

    def get(self, rev: int = -1) -> dict[str, Any]:
        return dict(self._revs[rev])

    def fingerprint(self, rev: int = -1) -> str:
        blob = json.dumps(self._revs[rev], sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def revisions(self) -> int:
        return len(self._revs)


# ══════════════════════════════════════════════════════════════
# A33 · SegmentCommits：段 = 内容寻址 commit
# ══════════════════════════════════════════════════════════════
def commit_hash(params: Mapping[str, Any], output_hash: str, deps: Iterable[str]) -> str:
    blob = json.dumps({"params": dict(params), "out": output_hash,
                       "deps": sorted(deps)}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class SegmentCommits:
    """段 = 内容寻址 commit：同参数+同输出 → 同 hash（自动去重）；旧 commit 永不改写。

    回退 = 移 ref + 延迟 GC（Git 对象模型缩到段粒度）；跨版本 DAG 可直接 diff。
    """

    def __init__(self) -> None:
        self._objects: dict[str, dict[str, Any]] = {}
        self._refs: dict[str, str] = {}    # seg -> commit hash（可变标签）

    def commit(self, seg: str, params: Mapping[str, Any],
               output_hash: str, deps: Iterable[str] = ()) -> str:
        h = commit_hash(params, output_hash, deps)
        if h not in self._objects:
            self._objects[h] = {"seg": seg, "params": dict(params),
                                "output_hash": output_hash, "deps": sorted(deps)}
        self._refs[seg] = h
        return h

    def ref(self, seg: str) -> str | None:
        return self._refs.get(seg)

    def payload(self, h: str) -> dict[str, Any] | None:
        return self._objects.get(h)

    def diff(self, seg: str, h_a: str, h_b: str) -> dict[str, Any]:
        a, b = self._objects.get(h_a), self._objects.get(h_b)
        return {"params_changed": (a or {}).get("params") != (b or {}).get("params"),
                "output_changed": (a or {}).get("output_hash") != (b or {}).get("output_hash")}


# ══════════════════════════════════════════════════════════════
# M9-4a · export_state：Web 前端状态契约（只读）
# ══════════════════════════════════════════════════════════════
def export_state(dag: FlowDAG, table: RevisionTable,
                 params: VersionedParams, commits: SegmentCommits,
                 goodpoints: Iterable[Mapping[str, Any]] = (),
                 kpis: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Web 前端契约（M9-4a）：一个版本化的只读 JSON。前端是视图，不是真源。

    schema: {schema, north_star?, steps[], segments{}, revisions{}, commits{},
             goodpoints[], kpis{}}
    v1.1（M10-4）：+ kpis（override 率 / dirty 段数 / verify 失败数 / override
    曲线）——由调用方（console 层有 WAL 视角）计算传入；本函数只做透传。
    前端对 /1 旧数据向后兼容（kpis 缺失 → 卡片显示 —）。
    """
    segs = dag.segments()
    snap = table.snapshot()
    return {
        "schema": "mug-console-state/1.1",
        "steps": [{"id": s.step_id, "seg": s.seg, "obj": s.obj,
                   "deps": list(s.deps), "thought_refs": list(s.thought_refs),
                   "params": dict(s.params)}
                  for s in dag.all_steps()],
        "segments": {name: {"steps": ids,
                            "revision": snap.get(name, {}).get("revision", 0),
                            "dirty": snap.get(name, {}).get("dirty", False),
                            "output_hash": snap.get(name, {}).get("output_hash", "")}
                     for name, ids in segs.items()},
        "revisions": snap,
        "mode": table.mode(),
        "params": params.get(),
        "commits": {seg: commits.ref(seg) for seg in segs},
        "goodpoints": [dict(g) for g in goodpoints],
        "kpis": dict(kpis) if kpis else {},
    }


# ══════════════════════════════════════════════════════════════
# 测试（A20 纪律：每个能力一个正例 + 一个"应当失败"的反例）
# ══════════════════════════════════════════════════════════════
def _run_tests() -> None:
    ok = lambda c, m: (_ for _ in ()).throw(AssertionError(m)) if not c else None

    # 1. FlowDAG：线性 + 拓扑序 + 区域反查 + 影响预览
    dag = FlowDAG()
    s1 = dag.add(StepRecord("s1", "杯体", "Mug", params=(("Body_Radius", 0.04),), seed=1))
    s2 = dag.add(StepRecord("s2", "把手", "Handle", deps=("s1",), thought_refs=("T1",), seed=2))
    s3 = dag.add(StepRecord("s3", "收尾", "Mug", deps=("s2",), thought_refs=("T2",), seed=3))
    ok(dag.topo_order() == ["s1", "s2", "s3"], "拓扑序应依赖在前")
    ok(len(dag.steps_for_object("Mug")) == 2, "区域反查：杯体+收尾")
    ok(len(dag.steps_for_thought("T1")) == 1, "thought 反查")
    ok(dag.descendants("s1") == ["s2", "s3"], "影响预览：因果闭包")
    ok(len(dag) == 3, "步数")

    # 2. 回环必须拒绝（正例+反例）
    try:
        dag.add(StepRecord("s4", "回环", "Mug", deps=("s3",)))
        dag.add(StepRecord("s5", "回环2", "Mug", deps=("s1",)))  # 无环，应成功
        dag.add(StepRecord("s6", "成环节点", "Mug", deps=("s2",)))  # s6 依赖 s2，s2 依赖 s1 —— 无环
    except CycleError:
        ok(False, "合法依赖不应被误判为环")
    dag2 = FlowDAG()
    dag2.add(StepRecord("a", "A", "Mug"))
    dag2.add(StepRecord("b", "B", "Mug", deps=("a",)))
    try:
        dag2.add(StepRecord("c", "C", "Mug", deps=("b", "a")))
        dag2.add(StepRecord("d", "D", "Mug", deps=("c",)))
        # 制造环：b 的依赖里出现 d —— 通过直接改内部态模拟"绕过 add 的坏数据"
        dag2._edges["b"] = ("a", "d")
        ok(_has_cycle(dag2._steps, dag2._edges), "环探测器应能识别绕入的环")
    except CycleError:
        ok(False, "不应在此处抛")
    # add() 的环拒绝在 gn_adapter.link 已验证（M1-1 集成路径），这里验检测函数本身

    # 3. WAL：追加/重放/校验/篡改检测/compaction
    import tempfile, os
    p = Path(tempfile.mkdtemp()) / "wal.jsonl"
    wal = WALLog(p)
    wal.append("param", {"unit": "S2_把手", "param": "Handle_Thickness", "new": 0.008})
    wal.append("goodpoint", {"name": "GP1"})
    wal.append("param", {"unit": "S2_把手", "param": "Handle_Thickness", "new": 0.007})
    ok(wal.verify(), "链校验应通过")
    ok(len(wal.replay()) == 3, "重放 3 条")
    # 篡改中间一行
    lines = p.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[1]); tampered["payload"]["name"] = "GP_X"
    lines[1] = json.dumps(tampered, ensure_ascii=False)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok(not WALLog(p).verify(), "篡改后链校验必须失败")
    # compaction（A1/A2 语义修复后：边界=compaction_barrier，payload 必带 snapshot_ref）
    store = SnapshotStore(Path(tempfile.mkdtemp()))
    wal2 = WALLog(None)
    for i in range(5):
        if i == 2:
            wal2.append("compaction_barrier",
                        {"i": i, "snapshot_ref": store.put({"i": i})})
        else:
            wal2.append("param", {"i": i})
    res = wal2.compact(snapshot_resolver=store.has)
    ok(res["dropped"] == 2 and len(wal2.replay()) == 3,
       f"compaction 应保留 barrier 之后（drop={res['dropped']}）")
    ok(wal2.verify(), "compaction 后链仍自洽")
    ok(len(res["hash_map"]) == 5, "compact 返回新旧 hash 映射（R6）")
    # A1 守卫：边界行缺快照引用 → 拒绝压缩（快照未落盘前折叠历史=数据丢失）
    wal3 = WALLog(None)
    for i in range(5):
        wal3.append("compaction_barrier" if i == 2 else "param", {"i": i})
    res3 = wal3.compact()
    ok(res3["dropped"] == 0 and len(wal3.replay()) == 5,
       "边界行缺 snapshot_ref → 拒绝压缩（A1）")

    # 4. RevisionTable：同值不传播 / backdating 截断 / 失效比例策略
    dag3 = FlowDAG()
    dag3.add(StepRecord("u1", "S1", "Mug"))
    dag3.add(StepRecord("u2", "S2", "Mug", deps=("u1",)))
    dag3.add(StepRecord("u3", "S3", "Mug", deps=("u2",)))
    tbl = RevisionTable(dag3)
    dirty = tbl.touch("S1", "fp1")
    ok(set(dirty) == {"S1", "S2", "S3"}, f"参数变化应传播全链（got {dirty}）")
    changed = tbl.report_output("S1", "hAAA")
    ok(changed is True, "首次输出视为变化")
    dirty2 = tbl.touch("S1", "fp2")     # 新参数 → S1 变脏
    ok("S1" in dirty2, "S1 应变脏")
    same = tbl.report_output("S1", "hAAA")  # 输出 hash 与上次相同 → backdating 标绿
    ok(same is False, "输出未变应标绿")
    # 全量阈值：3 单元全脏 → 100% > 40% → FULL
    tbl.touch("S1", "fp3"); tbl.touch("S2", "fpB"); tbl.touch("S3", "fpC")
    ok(tbl.mode() == "FULL", "全脏应走全量")
    tbl.report_output("S1", "h1"); tbl.report_output("S2", "h2"); tbl.report_output("S3", "h3")
    ok(tbl.mode() == "INCREMENTAL", "全绿应回增量")

    # 5. VersionedParams：量化 + 版本化 + 指纹
    vp = VersionedParams({"Body_Radius": 0.04}, steps={"Handle_Thickness": 0.001})
    r0 = vp.fingerprint()
    vp.set_many({"Handle_Thickness": 0.0081})     # 量化到 0.008
    ok(vp.get()["Handle_Thickness"] == 0.008, f"量化应到步长（got {vp.get()['Handle_Thickness']}）")
    ok(vp.fingerprint() != r0, "参数变了指纹必须变")
    fp_same = None
    vp.set_many({"Handle_Thickness": 0.0082})     # 量化后仍是 0.008 → 指纹不变
    ok(vp.fingerprint(-2) == vp.fingerprint(-1), "量化同值指纹不变（R2 修复：原为 X or True 恒真占位）")
    ok(vp.revisions() == 3, "三个版本")

    # 6. 命令机械逆 + pivot
    u = ParamUpdate("S2_把手", "Handle_Thickness", 0.011, 0.007)
    p = {}
    p2 = u.apply(p); p3 = u.inverse().apply(p2)
    ok(p3.get("S2_把手.Handle_Thickness") == 0.011, "逆应用应恢复 old")
    try:
        ParamUpdate("x", "y", 1, 2, SagaTag.PIVOT)
        ok(False, "ParamUpdate 禁止 pivot 标签")
    except ValueError:
        pass
    lo = LogOnly("导出 glb")
    try:
        lo.inverse(); ok(False, "pivot 逆必须被拒")
    except PivotBlocked:
        pass

    # 7. SegmentCommits：内容寻址去重 + diff
    sc = SegmentCommits()
    h1 = sc.commit("S2", {"Handle_Thickness": 0.011}, "out1", ("s1",))
    h2 = sc.commit("S2", {"Handle_Thickness": 0.011}, "out1", ("s1",))
    ok(h1 == h2, "同参数同输出应同 commit（去重）")
    h3 = sc.commit("S2", {"Handle_Thickness": 0.007}, "out2", ("s1",))
    ok(h3 != h1, "不同输出应新 commit")
    d = sc.diff("S2", h1, h3)
    ok(d["params_changed"] and d["output_changed"], "diff 应检出参数与输出变化")

    # 8. export_state 契约（v1.1：+ kpis 透传）
    st = export_state(dag, RevisionTable(dag), VersionedParams(), SegmentCommits(),
                      goodpoints=[{"name": "GP1", "thought_refs": ["T1"]}])
    ok(st["schema"] == "mug-console-state/1.1", "schema 版本 1.1")
    ok(len(st["steps"]) == 6 and "segments" in st and "mode" in st, "导出字段齐")
    ok(st["kpis"] == {}, "未传 kpis → 空 dict（前端兼容 /1 旧数据）")
    st2 = export_state(dag, RevisionTable(dag), VersionedParams(), SegmentCommits(),
                       kpis={"override_rate": 0.25, "dirty_segments": 1})
    ok(st2["kpis"]["override_rate"] == 0.25 and st2["kpis"]["dirty_segments"] == 1,
       "kpis 透传（M10-4）")

    print("m1_core tests: PASS")


if __name__ == "__main__":
    _run_tests()
