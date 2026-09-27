"""
core_types.py — Blender AI 建模控制台 · 核心对象骨架

纯 Python，不依赖 bpy，可直接单测。真实接入时只需把 Context 换成 bpy 门面。

设计北极星
----------
把「定位成本」和「回退成本」压到接近零。逐条审批只是这两项成本昂贵时的劣质替代品。

    可回退  ←  Command 可反演（undo）
    可寻址  ←  Step 有 id、可序列化、可被引用
    可质疑  ←  Thought 可被 GoodPoint 锚定、可被推翻并向下游传播
    可换策  ←  TrustPolicy 可注入（AUTOPILOT / STRICT 只是换实例）

分层
----
    L0 原语   Command / ExecResult / Context / CommandFailed
    L1 记录   Step / Thought / GoodPoint / Locatable
    L2 结构   FlowAxis / ThoughtGraph / QualityTrail
    L3 机制   Transaction / SnapshotStore / TrustPolicy
    L4 编排   DirectorConsole / ReviewCheckpoint
    L5 黑盒   ExperienceLibrary（仅接口，内部自由演化，上游不感知）
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, IntEnum, auto
from typing import Any, Callable, NewType, Protocol, Sequence

# ══════════════════════════════════════════════════════════════════
# 标识符 —— 可寻址性的地基
# ══════════════════════════════════════════════════════════════════

StepId = NewType("StepId", str)
ThoughtId = NewType("ThoughtId", str)
SegmentId = NewType("SegmentId", str)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ══════════════════════════════════════════════════════════════════
# L0 原语
# ══════════════════════════════════════════════════════════════════


class CommandFailed(Exception):
    """命令执行失败。由 Transaction 静默捕获并回滚，不打扰人。"""

    def __init__(self, command: "Command", message: str = "") -> None:
        self.command = command
        self.message = message
        super().__init__(f"{command.op_path}: {message}")


@dataclass(frozen=True)
class ExecResult:
    ok: bool
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Context:
    """Blender 场景的抽象门面。真实实现把它包在 bpy 上。"""

    objects: dict[str, dict[str, Any]] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy({"objects": self.objects, "meta": self.meta})

    def restore(self, snap: dict[str, Any]) -> None:
        self.objects = copy.deepcopy(snap["objects"])
        self.meta = copy.deepcopy(snap["meta"])


class Command(ABC):
    """
    可反演的最小执行单元 —— 回退能力的根源。

    铁律：任何进系统的操作都必须是 Command 子类并实现 undo()。
    没有 undo() 的操作不允许进入 FlowAxis（否则回退链条断在它身上）。
    """

    @property
    @abstractmethod
    def op_path(self) -> str:
        """如 'bpy.ops.mesh.primitive_cube_add'。TrustPolicy 用它做粗分。"""

    @abstractmethod
    def execute(self, ctx: Context) -> ExecResult:
        ...

    @abstractmethod
    def undo(self, ctx: Context) -> None:
        ...

    # ── TrustPolicy 需要的元信息（有默认值，子类按需覆盖）──────────

    @property
    def is_readonly(self) -> bool:
        return False

    @property
    def estimated_steps(self) -> int:
        return 1

    def affected_objects(self, ctx: Context) -> Sequence[str]:
        """影响面 —— TrustPolicy 精算分档时用它，比 op_path 准得多。"""
        return ()

    def to_dict(self) -> dict[str, Any]:
        return {"op_path": self.op_path}

    def fingerprint(self) -> str:
        """去重 / 变更检测用。内容相同 → 指纹相同。"""
        blob = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha1(blob.encode()).hexdigest()[:16]


class CompositeCommand(Command):
    """
    语义段落 —— 一个"意图"对应的一组命令，整段原子提交。

    组合模式：它自己也是 Command，所以可以嵌套。
    这是"流程轴上按段落折叠、不按步骤展开"的载体。
    """

    def __init__(
        self,
        commands: Sequence[Command],
        intent: str = "",
        thought_refs: tuple[ThoughtId, ...] = (),
    ) -> None:
        self.commands: list[Command] = list(commands)
        self.intent = intent
        self.thought_refs = thought_refs

    @property
    def op_path(self) -> str:
        return f"composite({self.intent or 'unnamed'})"

    @property
    def estimated_steps(self) -> int:
        return sum(c.estimated_steps for c in self.commands) or 1

    def execute(self, ctx: Context) -> ExecResult:
        done: list[Command] = []
        try:
            for cmd in self.commands:
                res = cmd.execute(ctx)
                if not res.ok:
                    raise CommandFailed(cmd, res.message)
                done.append(cmd)
            return ExecResult(ok=True, data={"steps": len(done)})
        except Exception:
            for cmd in reversed(done):
                cmd.undo(ctx)
            raise

    def undo(self, ctx: Context) -> None:
        for cmd in reversed(self.commands):
            cmd.undo(ctx)

    def to_dict(self) -> dict[str, Any]:
        return {
            "op_path": self.op_path,
            "intent": self.intent,
            "commands": [c.to_dict() for c in self.commands],
        }


# ══════════════════════════════════════════════════════════════════
# L1 记录层
# ══════════════════════════════════════════════════════════════════


class TrustTier(IntEnum):
    """风险分级。审批密度与风险成正比 —— 唯一幸存的人闸门只挡 Tier 3。"""

    READ = 0           # 查询：直接跑，连快照都不用
    SAFE_WRITE = 1     # 常规建模：加图元、调材质、加修改器
    DESTRUCTIVE = 2    # 破坏性但可逆：布尔挖洞、删物体、改拓扑
    IRREVERSIBLE = 3   # 大代价/不可逆：批量几百步、外部覆盖写盘


@dataclass(frozen=True)
class Step:
    """流程轴节点 —— What 层。可寻址、可序列化、可引用 Thought。"""

    step_id: StepId
    command: Command
    tier: TrustTier
    segment: SegmentId | None = None
    thought_refs: tuple[ThoughtId, ...] = ()
    result: ExecResult | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tier": int(self.tier),
            "segment": self.segment,
            "thought_refs": list(self.thought_refs),
            "created_at": self.created_at,
            **self.command.to_dict(),
        }


class ThoughtStatus(Enum):
    ACTIVE = auto()
    SUPERSEDED = auto()
    REJECTED = auto()


@dataclass
class Thought:
    """
    思维图节点 —— Why 层。

    只外化「可争议的假设」：AI 自己拍的判断、无硬依据的选择、有多走向的分叉。
    确定性推导不进图（否则人会被淹死）。
    """

    thought_id: ThoughtId
    claim: str                                   # "把手直径 22mm 握感舒适"
    kind: str = "assumption"                     # assumption | decision | constraint
    depends_on: tuple[ThoughtId, ...] = ()
    status: ThoughtStatus = ThoughtStatus.ACTIVE
    evidence: str = ""
    created_at: float = field(default_factory=time.time)

    def supersede(self, new_claim: str) -> "Thought":
        """被推翻 → 返回替代它的新 Thought（原节点标记 SUPERSEDED）。"""
        self.status = ThoughtStatus.SUPERSEDED
        return Thought(
            thought_id=ThoughtId(new_id("tht")),
            claim=new_claim,
            kind=self.kind,
            depends_on=self.depends_on,
            evidence=f"supersedes {self.thought_id}",
        )


@dataclass(frozen=True)
class GoodPoint:
    """
    质量锚点 —— 人标记的「到这里为止是好的」。

    关键修正：必须带 thought_refs。只记缩略图的话，回退后 AI 不知道这版
    基于什么假设，重跑会掉进同一个坑。带上 thought_refs，旗子就从
    「一个截图」变成「一个可复用的决策包」。
    """

    step_id: StepId
    thought_refs: tuple[ThoughtId, ...] = ()
    thumbnail: str = ""
    note: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Locatable:
    """一句话反馈的解析结果 —— 审美信号转结构信号。"""

    level: str                                   # "thought" | "step"
    thought_id: ThoughtId | None = None
    step_id: StepId | None = None
    confidence: float = 0.0

    @property
    def is_thought_level(self) -> bool:
        return self.level == "thought"


# ══════════════════════════════════════════════════════════════════
# L2 结构层
# ══════════════════════════════════════════════════════════════════


class FlowAxis:
    """
    流程轴 —— What 的时间线。

    ⚠️ **M1 起退役**（2026-09-27）：线性 list 结构被 `m1_core.FlowDAG` 取代
    （显式 DAG + 依赖边 + 环拒绝——Rhino 4 隐式历史的教训）。保留本类仅作
    历史参照与未迁移字段的过渡；新代码一律用 FlowDAG（gn_session 已切换）。

    设计要点：
      1. 按语义段落折叠，人扫段落不扫步骤
      2. Tier 2 高亮而非拦截（事前拦截成本比事后回退高一个数量级）
      3. 每个段落挂 Thought 锚点 —— 这是 FlowAxis 与 ThoughtGraph 的接缝
    """

    def __init__(self) -> None:
        self._steps: list[Step] = []
        self._segments: dict[SegmentId, list[StepId]] = {}

    def append(self, step: Step) -> Step:
        self._steps.append(step)
        if step.segment:
            self._segments.setdefault(step.segment, []).append(step.step_id)
        return step

    @property
    def steps(self) -> Sequence[Step]:
        return tuple(self._steps)

    @property
    def head(self) -> StepId | None:
        return self._steps[-1].step_id if self._steps else None

    def segments(self) -> dict[SegmentId, Sequence[Step]]:
        out: dict[SegmentId, list[Step]] = {}
        for seg, ids in self._segments.items():
            out[seg] = [s for s in self._steps if s.step_id in set(ids)]
        return out

    def steps_for_thought(self, tid: ThoughtId) -> Sequence[Step]:
        """反向索引：这个假设支撑了哪些步骤。改假设时用它圈定重跑范围。"""
        return [s for s in self._steps if tid in s.thought_refs]

    def destructive_steps(self) -> Sequence[Step]:
        return [s for s in self._steps if s.tier >= TrustTier.DESTRUCTIVE]

    def get(self, sid: StepId) -> Step | None:
        for s in self._steps:
            if s.step_id == sid:
                return s
        return None

    def truncate_after(self, sid: StepId) -> None:
        """回退时裁剪轴。被裁掉的 Step 进墓碑日志，不弹窗。"""
        idx = next(i for i, s in enumerate(self._steps) if s.step_id == sid)
        del self._steps[idx + 1 :]


class ThoughtGraph:
    """
    思维图 —— Why 的推导结构。

    与 FlowAxis 正交：轴是线性/操作级，图是有向/决策级。
    靠 Step.thought_refs 做多对多映射。
    """

    def __init__(self) -> None:
        self._nodes: dict[ThoughtId, Thought] = {}

    def add(self, thought: Thought) -> Thought:
        self._nodes[thought.thought_id] = thought
        return thought

    def get(self, tid: ThoughtId) -> Thought | None:
        return self._nodes.get(tid)

    def active(self) -> Sequence[Thought]:
        return [t for t in self._nodes.values() if t.status is ThoughtStatus.ACTIVE]

    def propagate(self, tid: ThoughtId) -> Sequence[ThoughtId]:
        """
        影响传播：直接或间接依赖 tid 的全部下游 Thought。

        这是「假设层定位」的核心 —— 推翻一个假设，自动圈定所有
        需要重新推导的假设，而不是只改一个参数。
        """
        out: list[ThoughtId] = []
        frontier = [tid]
        seen = {tid}
        while frontier:
            cur = frontier.pop()
            for t in self._nodes.values():
                if cur in t.depends_on and t.thought_id not in seen:
                    seen.add(t.thought_id)
                    out.append(t.thought_id)
                    frontier.append(t.thought_id)
        return out

    def match(self, comment: str) -> Locatable | None:
        """一句话反馈 → 命中哪个 Thought。真实实现交给 LLM/经验库，这里是启发式。"""
        best: tuple[ThoughtId, float] | None = None
        toks = set(comment)
        for t in self.active():
            overlap = len(toks & set(t.claim))
            score = overlap / max(len(set(t.claim)), 1)
            if score > 0 and (best is None or score > best[1]):
                best = (t.thought_id, score)
        if best is None:
            return None
        return Locatable(level="thought", thought_id=best[0], confidence=best[1])


class QualityTrail:
    """GoodPoint 序列 —— 项目真正的时间轴语义。"""

    def __init__(self, axis: FlowAxis, store: "SnapshotStore") -> None:
        self._axis = axis
        self._store = store
        self._points: list[GoodPoint] = []

    @property
    def points(self) -> Sequence[GoodPoint]:
        return tuple(self._points)

    def mark_good(
        self,
        note: str = "",
        thought_refs: tuple[ThoughtId, ...] = (),
        thumbnail: str = "",
    ) -> GoodPoint:
        head = self._axis.head
        if head is None:
            raise ValueError("流程轴为空，无法立旗")
        gp = GoodPoint(
            step_id=head,
            thought_refs=thought_refs,
            thumbnail=thumbnail,
            note=note,
        )
        self._points.append(gp)
        return gp

    def latest_good(self) -> GoodPoint:
        if not self._points:
            raise ValueError("还没有任何 GoodPoint")
        return self._points[-1]

    def director_revert(self) -> StepId:
        """导演式回退：默认回到最近 GoodPoint，而不是任意 step 编号。"""
        target = self.latest_good().step_id
        self._store.rebuild_to(target)
        self._axis.truncate_after(target)
        return target


# ══════════════════════════════════════════════════════════════════
# L3 机制层
# ══════════════════════════════════════════════════════════════════


class Transaction:
    """
    原子性 —— 自动执行的底气所在。

    失败整段自动回滚，零人工介入。这是「敢放开跑」的资本，
    也是导演模式能取代逐条审批的技术前提。
    """

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._done: list[Command] = []

    def __enter__(self) -> "Transaction":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc_type is not None:
            self.rollback()
        return False

    def apply(self, command: Command) -> ExecResult:
        res = command.execute(self.ctx)
        self._done.append(command)
        if not res.ok:
            raise CommandFailed(command, res.message)
        return res

    def rollback(self) -> None:
        for cmd in reversed(self._done):
            try:
                cmd.undo(self.ctx)
            except Exception:
                pass  # 墓碑静默化：回滚失败只写日志，不打断人
        self._done.clear()


class SnapshotStore(ABC):
    """自动留痕。零人力成本 —— 它便宜，回退才便宜。"""

    @abstractmethod
    def after_commit(self, step: Step, ctx: Context) -> None:
        ...

    @abstractmethod
    def rebuild_to(self, step_id: StepId) -> None:
        ...

    @abstractmethod
    def has(self, step_id: StepId) -> bool:
        ...


class InMemorySnapshotStore(SnapshotStore):
    """参考实现。真实版本写 .blend 增量 + delta JSONL。"""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx
        self._snaps: dict[StepId, dict[str, Any]] = {}

    def after_commit(self, step: Step, ctx: Context) -> None:
        if step.tier >= TrustTier.SAFE_WRITE:  # READ 不浪费快照
            self._snaps[step.step_id] = ctx.snapshot()

    def rebuild_to(self, step_id: StepId) -> None:
        if step_id in self._snaps:
            self._ctx.restore(self._snaps[step_id])

    def has(self, step_id: StepId) -> bool:
        return step_id in self._snaps


class Decision(Enum):
    EXECUTE_NOW = auto()
    ASK_HUMAN = auto()


class TrustPolicy:
    """
    风险门控 —— 唯一幸存的那道门，且只挡 Tier 3。

    修正：不要只按 op_path 分档。同一个 bpy.ops.mesh.delete，
    删一个顶点和删半个模型风险差百倍 —— 必须按影响面精算。
    """

    DESTRUCTIVE_PREFIXES = (
        "bpy.ops.object.delete",
        "bpy.ops.mesh.delete",
        "bpy.ops.mesh.dissolve",
        "bpy.ops.object.modifier_apply",
    )

    def __init__(self, impact_threshold: int = 8) -> None:
        self.impact_threshold = impact_threshold

    def classify(self, command: Command, ctx: Context) -> TrustTier:
        if command.is_readonly:
            return TrustTier.READ
        if command.estimated_steps > 200:
            return TrustTier.IRREVERSIBLE
        if command.op_path.startswith(self.DESTRUCTIVE_PREFIXES):
            # 影响面精算：粗分档之后再看实际波及多少对象
            if len(command.affected_objects(ctx)) > self.impact_threshold:
                return TrustTier.IRREVERSIBLE
            return TrustTier.DESTRUCTIVE
        return TrustTier.SAFE_WRITE

    def gate(self, command: Command, ctx: Context) -> Decision:
        if self.classify(command, ctx) < TrustTier.IRREVERSIBLE:
            return Decision.EXECUTE_NOW
        return Decision.ASK_HUMAN


# ══════════════════════════════════════════════════════════════════
# L5 黑盒
# ══════════════════════════════════════════════════════════════════


class ExperienceLibrary(Protocol):
    """
    经验库 —— 纯接口，内部自由演化，上游不感知。

    按你的要求：不用管它怎么演化，只保证这三个能力可用。
    """

    def locate(self, comment: str) -> Locatable | None: ...
    def suggest(self, step: Step) -> Sequence[str]: ...
    def record(self, step: Step, adopted: bool | None) -> None: ...


class NullExperience(ExperienceLibrary):
    """占位实现，让骨架能跑。真实版本接 Weaviate + Neo4j + 本地 embedding。"""

    def locate(self, comment: str) -> Locatable | None:
        return None

    def suggest(self, step: Step) -> Sequence[str]:
        return ()

    def record(self, step: Step, adopted: bool | None) -> None:
        return None


# ══════════════════════════════════════════════════════════════════
# L4 编排层
# ══════════════════════════════════════════════════════════════════


class ConsoleMode(Enum):
    """开闭原则：同一套 Command/快照/回退底座，只是门的开合程度不同。"""

    AUTOPILOT = auto()   # 默认：导演模式
    STRICT = auto()      # 交付前 / 接不可信模型时切换


class AIProvider(Protocol):
    def repropose(self, target: Locatable, comment: str) -> CompositeCommand: ...


class Director(Protocol):
    def nods(self, command: Command) -> bool: ...


class AlwaysYesDirector:
    def nods(self, command: Command) -> bool:
        return True


@dataclass(frozen=True)
class Preview:
    """段落边界交给人的东西：一张图 + 一个可定位的锚。"""

    last_step_id: StepId | None
    thumbnail: str = ""
    notes: tuple[str, ...] = ()

    @classmethod
    def skipped(cls, at: StepId | None = None) -> "Preview":
        return cls(last_step_id=at, notes=("skipped by director",))


class DirectorConsole:
    """
    导演模式编排者。

    人不批准操作，人评价结果。
    段内实时流式推进、不可中断；段末才交图给人看。
    """

    def __init__(
        self,
        ctx: Context,
        axis: FlowAxis | None = None,
        graph: ThoughtGraph | None = None,
        policy: TrustPolicy | None = None,
        store: SnapshotStore | None = None,
        experience: ExperienceLibrary | None = None,
        ai: AIProvider | None = None,
        director: Director | None = None,
        mode: ConsoleMode = ConsoleMode.AUTOPILOT,
    ) -> None:
        self.ctx = ctx
        self.axis = axis or FlowAxis()
        self.graph = graph or ThoughtGraph()
        self.policy = policy or TrustPolicy()
        self.store = store or InMemorySnapshotStore(ctx)
        self.experience = experience or NullExperience()
        self._ai = ai
        self._director = director or AlwaysYesDirector()
        self.mode = mode
        self.trail = QualityTrail(self.axis, self.store)

    # ── 主循环 ────────────────────────────────────────────────

    def run_plan(self, plan: CompositeCommand) -> Preview:
        seg = SegmentId(new_id("seg"))
        try:
            with Transaction(self.ctx) as txn:
                for cmd in plan.commands:
                    if self._needs_human(cmd):
                        if not self._director.nods(cmd):
                            return Preview.skipped(self.axis.head)
                    res = txn.apply(cmd)
                    step = Step(
                        step_id=StepId(new_id("step")),
                        command=cmd,
                        tier=self.policy.classify(cmd, self.ctx),
                        segment=seg,
                        thought_refs=plan.thought_refs,
                        result=res,
                    )
                    self.axis.append(step)
                    self.store.after_commit(step, self.ctx)
        except CommandFailed as exc:
            # 墓碑静默化：写日志喂经验库，不弹窗、不等人
            self.experience.record(
                Step(
                    step_id=StepId(new_id("tomb")),
                    command=exc.command,
                    tier=TrustTier.SAFE_WRITE,
                ),
                adopted=False,
            )
            return Preview(last_step_id=self.axis.head, notes=(f"rolled back: {exc.message}",))
        return Preview(last_step_id=self.axis.head)

    def _needs_human(self, cmd: Command) -> bool:
        if self.mode is ConsoleMode.STRICT:
            return True
        return self.policy.gate(cmd, self.ctx) is Decision.ASK_HUMAN

    # ── 导演反馈回路 ──────────────────────────────────────────

    def feedback(self, comment: str) -> Preview:
        """
        导演一句话 → 定位 → 修正 → 重跑。

        定位优先落到 Thought 层（修一类），落不到才退到 Step 层（修一次）。
        """
        target = self._locate(comment)
        if self._ai is None:
            return Preview(last_step_id=self.axis.head, notes=("no AI provider",))
        plan = self._ai.repropose(target, comment)
        return self.run_plan(plan)

    def _locate(self, comment: str) -> Locatable:
        hit = self.experience.locate(comment)      # 黑盒优先
        if hit is not None:
            return hit
        hit = self.graph.match(comment)            # 思维图：哪个假设相关
        if hit is not None:
            return hit
        return Locatable(                          # 兜底：最近一步
            level="step", step_id=self.axis.head, confidence=0.0
        )

    def blast_radius(self, tid: ThoughtId) -> dict[str, Any]:
        """给 UI 用：推翻这个假设会波及多少 Thought 和 Step。"""
        thoughts = self.graph.propagate(tid)
        steps = [s.step_id for t in thoughts for s in self.axis.steps_for_thought(t)]
        return {"thoughts": thoughts, "steps": steps}


# ══════════════════════════════════════════════════════════════════
# 冒烟自检
# ══════════════════════════════════════════════════════════════════


class AddObject(Command):
    def __init__(self, name: str, **props: Any) -> None:
        self.name = name
        self.props = props

    @property
    def op_path(self) -> str:
        return "bpy.ops.mesh.primitive_add"

    def execute(self, ctx: Context) -> ExecResult:
        ctx.objects[self.name] = dict(self.props)
        return ExecResult(ok=True, data={"name": self.name})

    def undo(self, ctx: Context) -> None:
        ctx.objects.pop(self.name, None)

    def affected_objects(self, ctx: Context) -> Sequence[str]:
        return (self.name,)

    def to_dict(self) -> dict[str, Any]:
        return {"op_path": self.op_path, "name": self.name, "props": self.props}


class Scale(Command):
    def __init__(self, name: str, factor: float) -> None:
        self.name = name
        self.factor = factor

    @property
    def op_path(self) -> str:
        return "bpy.ops.transform.resize"

    def execute(self, ctx: Context) -> ExecResult:
        if self.name not in ctx.objects:
            return ExecResult(ok=False, message=f"{self.name} 不存在")
        obj = ctx.objects[self.name]
        obj["scale"] = obj.get("scale", 1.0) * self.factor
        return ExecResult(ok=True)

    def undo(self, ctx: Context) -> None:
        if self.name in ctx.objects:
            obj = ctx.objects[self.name]
            obj["scale"] = obj.get("scale", 1.0) / self.factor

    def affected_objects(self, ctx: Context) -> Sequence[str]:
        return (self.name,)

    def to_dict(self) -> dict[str, Any]:
        return {"op_path": self.op_path, "name": self.name, "factor": self.factor}


class _Boom(Command):
    @property
    def op_path(self) -> str:
        return "bpy.ops.test.boom"

    def execute(self, ctx: Context) -> ExecResult:
        return ExecResult(ok=False, message="故意失败")

    def undo(self, ctx: Context) -> None:
        return None


class _EchoAI:
    """AI 侧占位：把「把手太粗」翻译成缩小 scale 的修正段落。"""

    def repropose(self, target: Locatable, comment: str) -> CompositeCommand:
        thoughts = (target.thought_id,) if target.thought_id else ()
        return CompositeCommand(
            [Scale("handle", 0.7)], intent=f"fix: {comment}", thought_refs=thoughts
        )


def _smoke() -> None:
    ctx = Context()
    console = DirectorConsole(ctx, ai=_EchoAI())

    # 1) 建两段
    t_handle = console.graph.add(
        Thought(thought_id=ThoughtId(new_id("tht")), claim="把手直径 22mm 握感舒适")
    )
    t_style = console.graph.add(
        Thought(
            thought_id=ThoughtId(new_id("tht")),
            claim="日式风格走圆角过渡",
            depends_on=(t_handle.thought_id,),
        )
    )

    p1 = console.run_plan(
        CompositeCommand(
            [AddObject("body"), AddObject("handle", scale=1.0)],
            intent="建主体与把手",
            thought_refs=(t_handle.thought_id,),
        )
    )
    assert len(ctx.objects) == 2, ctx.objects
    assert p1.notes == (), p1.notes

    gp = console.trail.mark_good(
        note="比例对了", thought_refs=(t_handle.thought_id, t_style.thought_id)
    )
    assert gp.thought_refs, "GoodPoint 必须带 thought_refs"

    p2 = console.run_plan(
        CompositeCommand([Scale("handle", 2.0)], intent="加粗把手")
    )
    assert ctx.objects["handle"]["scale"] == 2.0

    # 2) 事务性：失败整段回滚，不打扰人
    p3 = console.run_plan(
        CompositeCommand([Scale("handle", 9.9), _Boom()], intent="必定失败")
    )
    assert ctx.objects["handle"]["scale"] == 2.0, "失败必须回滚"
    assert "rolled back" in p3.notes[0], p3.notes

    # 3) 导演式回退：回到上一面旗，而不是某个 step 编号
    console.trail.director_revert()
    assert ctx.objects["handle"]["scale"] == 1.0, ctx.objects
    assert len(console.axis.steps) == 2, len(console.axis.steps)

    # 4) 假设层定位：一句话 → 命中 Thought → 波及下游
    loc = console.graph.match("把手太粗了")
    assert loc is not None and loc.is_thought_level, loc
    radius = console.blast_radius(ThoughtId(str(t_handle.thought_id)))
    assert t_style.thought_id in radius["thoughts"], radius

    p4 = console.feedback("把手太粗了")
    assert ctx.objects["handle"]["scale"] == 0.7, ctx.objects

    # 5) Tier 分级：同一个 delete，影响面决定挡不挡
    class BulkDelete(Command):
        @property
        def op_path(self) -> str:
            return "bpy.ops.object.delete"

        def execute(self, ctx: Context) -> ExecResult:
            return ExecResult(ok=True)

        def undo(self, ctx: Context) -> None:
            return None

        def affected_objects(self, ctx: Context) -> Sequence[str]:
            return tuple(f"obj{i}" for i in range(50))

    class TinyDelete(BulkDelete):
        def affected_objects(self, ctx: Context) -> Sequence[str]:
            return ("obj0",)

    assert console.policy.gate(BulkDelete(), ctx) is Decision.ASK_HUMAN
    assert console.policy.gate(TinyDelete(), ctx) is Decision.EXECUTE_NOW

    print("SMOKE OK")
    print(f"  steps on axis     : {len(console.axis.steps)}")
    print(f"  segments          : {len(console.axis.segments())}")
    print(f"  good points       : {len(console.trail.points)}")
    print(f"  located at        : {loc.level} / {loc.thought_id}")
    print(f"  blast radius      : {len(radius['thoughts'])} thoughts, {len(radius['steps'])} steps")


if __name__ == "__main__":
    _smoke()
