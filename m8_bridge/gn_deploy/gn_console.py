"""
gn_console.py — 架构概念的端到端代码可行性验证
================================================

⚠ 归档状态（2026-09-27 R5 裁决）：**已归档的原型依赖件（archive-in-place）**。
  功能已被 console.py（正式入口）全面替代，本文件不再演进、只读纪律；
  但仍被两套基线资产 import：gn_session_live.py（SPECS——M1 集成验收 46/47）
  与 gn_ab.py（GNConsole/SPECS——AB 错误面实验），删除即断基线，故原地保留。
  它同时是关键实测证据的原始载体（L1/L2/L3 = 0.7/0.6/50ms 三档回退、
  GN 无局部重算比值 1.10——证据索引多处指向）。
  可选去耦路径（登记于工单 M8-R6 注记，非承诺项）：把 SPECS 抽到
  specs_fixtures.py 后即可整体移入 archive/。

不是玩具，是把前面所有结论**接成一条能跑的链**，看它们到底站不站得住。

场景沿用对话里那个例子：一个马克杯，人说"把手太粗了"。

    S1 杯体  ──►  S2 把手  ──►  S3 收尾
                    ▲
                    └── T1: "把手粗 11mm 握感舒适"（一个可争议的假设）

验证的六件事（每条都对应一条待改清单）：
  A13  声明式段落 spec → 编译成 GN 节点组（而不是执行一串 bpy.ops）
  A1   段落之间是显式 DAG，回环被拒
  A15  机械几何 verifier 做门禁（不可攻破，不让 LLM 打分）
  A14  GoodPoint = 快照 = bake 边界，三合一
  L1   状态层回退：删一层 opinion，成本恒定
  L2   语义层回退：回到 GoodPoint
  L3   意图层回退：推翻一个 Thought → 影响预览 → 重推下游 ← **最难、最核心的那条**

跑法：
    blender --background --factory-startup --python gn_console.py
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]  # 仓库根（相对推导，跨机器可移植）
from typing import Any, Callable

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gn_adapter import GNAdapter, GNValidationError, ParamSpec  # noqa: E402
from gn_verify import GeometryVerifier  # noqa: E402

OUT = ROOT / "results" / "gn_feasibility.json"
LOG: list[str] = []
DATA: dict[str, Any] = {}


def say(msg: str) -> None:
    print(msg)
    LOG.append(msg)


def med(xs: list[float]) -> float:
    xs = sorted(xs)
    return round(xs[len(xs) // 2], 3)


# ══════════════════════════════════════════════════════════════
# 段落 spec：声明式，AI 产出这个，adapter 编译成节点树
# ══════════════════════════════════════════════════════════════
@dataclass
class SegmentSpec:
    name: str
    params: list[ParamSpec]
    build: Callable[[GNAdapter, Any, dict[str, str]], None]
    consumes_input: bool = False          # False = 自己生成几何（首段）
    thought_refs: tuple[str, ...] = ()
    obj: str = "Mug"                      # A2 区域反查键（受影响物体）


def build_body(ad: GNAdapter, tree: Any, sid: dict[str, str]) -> None:
    """S1 杯体：MeshCylinder → 平滑"""
    gi = ad.add_node(tree, "NodeGroupInput", "In")
    go = ad.add_node(tree, "NodeGroupOutput", "Out")
    cyl = ad.add_node(tree, "GeometryNodeMeshCylinder", "Cup_Body")
    smooth = ad.add_node(tree, "GeometryNodeSetShadeSmooth", "Body_Smooth")
    ad.link(tree, gi, sid["Body_Radius"], cyl, "Radius")
    ad.link(tree, gi, sid["Body_Depth"], cyl, "Depth")
    ad.link(tree, cyl, "Mesh", smooth, "Mesh")
    ad.link(tree, smooth, "Mesh", go, "Geometry")


def build_handle(ad: GNAdapter, tree: Any, sid: dict[str, str]) -> None:
    """S2 把手：曲线圆 → 扫掠出环 → 挪到杯侧 → 与上游几何 Join"""
    gi = ad.add_node(tree, "NodeGroupInput", "In")
    go = ad.add_node(tree, "NodeGroupOutput", "Out")
    ring = ad.add_node(tree, "GeometryNodeCurvePrimitiveCircle", "Handle_Ring")
    prof = ad.add_node(tree, "GeometryNodeCurvePrimitiveCircle", "Handle_Profile")
    sweep = ad.add_node(tree, "GeometryNodeCurveToMesh", "Handle_Sweep")
    xform = ad.add_node(tree, "GeometryNodeTransform", "Handle_Place")
    join = ad.add_node(tree, "GeometryNodeJoinGeometry", "Join_All")

    ad.link(tree, gi, sid["Handle_Ring_Radius"], ring, "Radius")
    ad.link(tree, gi, sid["Handle_Thickness"], prof, "Radius")
    ad.link(tree, ring, "Curve", sweep, "Curve")
    ad.link(tree, prof, "Curve", sweep, "Profile Curve")
    ad.link(tree, sweep, "Mesh", xform, "Geometry")
    ad.link(tree, xform, "Geometry", join, "Geometry")
    ad.link(tree, gi, "Incoming_Geometry", join, "Geometry")   # multi-input，同一个口连两次
    ad.link(tree, join, "Geometry", go, "Geometry")


def build_finish(ad: GNAdapter, tree: Any, sid: dict[str, str]) -> None:
    """S3 收尾：细分 → 平滑"""
    gi = ad.add_node(tree, "NodeGroupInput", "In")
    go = ad.add_node(tree, "NodeGroupOutput", "Out")
    subd = ad.add_node(tree, "GeometryNodeSubdivisionSurface", "Final_Subdiv")
    smooth = ad.add_node(tree, "GeometryNodeSetShadeSmooth", "Final_Smooth")
    ad.link(tree, gi, "Incoming_Geometry", subd, "Mesh")
    ad.link(tree, gi, sid["Subdiv_Level"], subd, "Level")
    ad.link(tree, subd, "Mesh", smooth, "Mesh")
    ad.link(tree, smooth, "Mesh", go, "Geometry")


SPECS: list[SegmentSpec] = [
    SegmentSpec(
        name="S1_杯体",
        params=[
            ParamSpec("Body_Radius", "FLOAT", 0.040, 0.005, 0.500, "m", "杯身半径"),
            ParamSpec("Body_Depth", "FLOAT", 0.095, 0.010, 0.500, "m", "杯身高"),
        ],
        build=build_body,
        consumes_input=False,
    ),
    SegmentSpec(
        name="S2_把手",
        params=[
            ParamSpec("Handle_Ring_Radius", "FLOAT", 0.032, 0.005, 0.300, "m", "把手环半径"),
            ParamSpec("Handle_Thickness", "FLOAT", 0.011, 0.001, 0.100, "m", "把手粗细"),
        ],
        build=build_handle,
        consumes_input=True,
        thought_refs=("T1",),
    ),
    SegmentSpec(
        name="S3_收尾",
        params=[ParamSpec("Subdiv_Level", "INT", 2, 0, 5, None, "最终细分级别")],
        build=build_finish,
        consumes_input=True,
        thought_refs=("T2",),
    ),
]


# ══════════════════════════════════════════════════════════════
# console
# ══════════════════════════════════════════════════════════════
class GNConsole:
    def __init__(self, ad: GNAdapter, obj: Any) -> None:
        self.ad = ad
        self.obj = obj
        self.deps = bpy.context.evaluated_depsgraph_get()
        self.segments: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self.verifier = GeometryVerifier(budget_faces=200_000, ground_z=-1.0)
        self.snapshots: dict[str, Any] = {}      # GoodPoint 快照（真网格）
        self.thoughts: dict[str, dict[str, Any]] = {}   # 极简 ThoughtGraph

    # ── 编译 + 挂载 ──────────────────────────────────────────
    def compile_and_mount(self, spec: SegmentSpec) -> dict[str, Any]:
        tree = self.ad.new_group(spec.name)
        sid: dict[str, str] = {}
        if spec.consumes_input:
            sid["Incoming_Geometry"] = self.ad.promote_input(
                tree, ParamSpec("Incoming_Geometry", "GEOMETRY"))
        for p in spec.params:
            sid[p.name] = self.ad.promote_input(tree, p)
        self.ad.promote_output(tree, "Geometry", "GEOMETRY")
        spec.build(self.ad, tree, sid)
        mod = self.ad.attach(self.obj, tree, spec.name)
        rec = {"spec": spec, "tree": tree, "sid": sid, "mod": mod}
        self.segments[spec.name] = rec
        self.order.append(spec.name)
        return rec

    def set_param(self, seg: str, param: str, value: Any) -> None:
        rec = self.segments[seg]
        self.ad.set_instance_input(rec["mod"], rec["sid"][param], value)

    # ── 求值 ─────────────────────────────────────────────────
    def evaluate(self, materialize: bool = True):
        self.deps.update()
        ev = self.obj.evaluated_get(self.deps)
        if not materialize:
            return None
        m = ev.to_mesh()
        return m

    def faces(self) -> int:
        m = self.evaluate()
        n = len(m.polygons)
        self.obj.evaluated_get(self.deps).to_mesh_clear()
        return n

    def stats(self) -> dict[str, float]:
        """面数**不能**用来判断"改了没有" —— 把把手改细，拓扑完全不变，面数一模一样。
        所以同时给表面积与包围盒：这两个才会真的动。"""
        m = self.evaluate()
        if m is None:
            return {"faces": 0, "verts": 0, "area": 0.0, "bbox": [0, 0, 0]}
        area = 0.0
        for p in m.polygons:
            try:
                area += p.area
            except Exception:  # noqa: BLE001
                pass
        xs = [v.co.x for v in m.vertices]
        ys = [v.co.y for v in m.vertices]
        zs = [v.co.z for v in m.vertices]
        st = {
            "faces": float(len(m.polygons)),
            "verts": float(len(m.vertices)),
            "area": round(area, 8),
            "bbox": [round(max(xs) - min(xs), 6),
                     round(max(ys) - min(ys), 6),
                     round(max(zs) - min(zs), 6)] if xs else [0, 0, 0],
        }
        self.obj.evaluated_get(self.deps).to_mesh_clear()
        return st

    def verify(self, label: str) -> dict[str, Any]:
        m = self.evaluate()
        rep = self.verifier.check(m, self.obj)
        nf = len(m.polygons)
        self.obj.evaluated_get(self.deps).to_mesh_clear()
        say(f"  verifier[{label}] → {'PASS' if rep.ok else 'FAIL'}  faces={nf}")
        if not rep.ok:
            for f in rep.failures:
                say(f"      {f}")
        return {"ok": rep.ok, "faces": nf, "failures": [str(f) for f in rep.failures]}

    # ── GoodPoint = 快照 = bake（三合一）──────────────────────
    def mark_goodpoint(self, name: str, thought_refs: tuple[str, ...]) -> None:
        t0 = time.perf_counter()
        mesh = self.ad.realize.__wrapped__ if False else None  # 不用 realize（它会拆 modifier）
        m = self.evaluate()
        snap = bpy.data.meshes.new_from_object(self.obj.evaluated_get(self.deps))
        t1 = time.perf_counter()
        self.snapshots[name] = {"mesh": snap, "thought_refs": list(thought_refs)}
        say(f"  GoodPoint[{name}] 快照 {len(snap.polygons)} 面，{(t1-t0)*1000:.2f} ms，"
            f"thought_refs={list(thought_refs)}")

    def revert_to_goodpoint(self, name: str) -> float:
        """L2 语义层回退：换回快照网格。"""
        t0 = time.perf_counter()
        self.obj.data = self.snapshots[name]["mesh"]
        self.deps.update()
        return round((time.perf_counter() - t0) * 1000, 3)

    # ── L1 状态层：删一层 opinion ────────────────────────────
    def pop_layer(self) -> tuple[str, float]:
        t0 = time.perf_counter()
        name = self.order[-1]
        self.obj.modifiers.remove(self.segments[name]["mod"])
        self.order.pop()
        self.ad.invalidate(obj=self.obj)
        self.deps.update()
        return name, round((time.perf_counter() - t0) * 1000, 3)

    # ── ThoughtGraph（极简）──────────────────────────────────
    def add_thought(self, tid: str, claim: str, governs: dict[str, str]) -> None:
        self.thoughts[tid] = {"claim": claim, "governs": governs, "status": "ACTIVE"}

    def impact_preview(self, tid: str) -> dict[str, Any]:
        """推翻一个 Thought 之前，先算因果闭包。

        第 2 组的推论：Cass 2006 实验说明人的默认心智模型是 cascading undo，
        所以**必须显式显示"将影响 N 个下游"**，否则就是背叛用户心智模型。
        """
        t = self.thoughts[tid]
        target_seg = t["governs"]["segment"]
        idx = self.order.index(target_seg)
        downstream = self.order[idx:]                       # 依赖图沿 modifier 栈向下
        uncertain = [s for s in downstream
                     if self.segments[s]["spec"].consumes_input]  # 吃上游几何的段才可能失败
        return {
            "thought": tid,
            "claim": t["claim"],
            "governs": t["governs"],
            "will_replay": downstream,
            "may_fail": uncertain,
            "n": len(downstream),
            "m": len(uncertain),
        }

    def overturn(self, tid: str, new_claim: str, new_value: float) -> dict[str, Any]:
        """L3 意图层回退：推翻假设 → 重推下游。"""
        t = self.thoughts[tid]
        seg = t["governs"]["segment"]
        param = t["governs"]["param"]
        before = self.stats()
        ts = []
        for _ in range(3):
            t0 = time.perf_counter()
            self.set_param(seg, param, new_value)
            self.deps.update()
            self.evaluate()
            ts.append((time.perf_counter() - t0) * 1000)
        after = self.stats()
        t["claim"] = new_claim
        t["status"] = "ACTIVE"
        changed = abs(after["area"] - before["area"]) > 1e-9 or after["bbox"] != before["bbox"]
        return {"param": f"{seg}.{param}", "value": new_value,
                "before": before, "after": after,
                "geometry_really_changed": changed,
                "ms": med(ts)}


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════
def main() -> None:
    say(f"Blender {bpy.app.version_string}")
    ad = GNAdapter(bpy)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.active_object
    obj.name = "Mug"
    # 删掉默认立方体的几何，让 S1 完全由 GN 生成
    obj.data = bpy.data.meshes.new("Mug_Base")
    con = GNConsole(ad, obj)

    # ── 0. 思维图 ────────────────────────────────────────────
    con.add_thought("T1", "把手粗 11mm 握感舒适",
                    {"segment": "S2_把手", "param": "Handle_Thickness"})
    con.add_thought("T2", "细分 2 级足够圆滑",
                    {"segment": "S3_收尾", "param": "Subdiv_Level"})
    say(f"\n[0] 思维图：{list(con.thoughts)}")

    # ── 1. 编译 + 挂载（A13）──────────────────────────────────
    say("\n[1] 编译段落 → GN 节点组 → 挂成 opinion 层")
    for spec in SPECS:
        t0 = time.perf_counter()
        rec = con.compile_and_mount(spec)
        dt = (time.perf_counter() - t0) * 1000
        fp = ad.fingerprint(rec["tree"])[:12]
        say(f"  {spec.name}: {len(rec['tree'].nodes)} 节点 / {len(rec['tree'].links)} 链接 "
            f"/ {dt:.1f} ms / fp={fp}")
    DATA["compile"] = {n: {"nodes": len(con.segments[n]["tree"].nodes),
                           "links": len(con.segments[n]["tree"].links),
                           "fp": ad.fingerprint(con.segments[n]["tree"])[:12]}
                       for n in con.order}

    # ── 2. 求值 + verifier 门禁（A15）─────────────────────────
    say("\n[2] 求值并跑机械 verifier")
    v0 = con.verify("初始")
    DATA["verify_initial"] = v0
    say(f"  面数 {v0['faces']}")

    # ── 3. GoodPoint = 快照 = bake（A14）──────────────────────
    say("\n[3] 打 GoodPoint（= 快照 = bake 边界，三合一）")
    con.mark_goodpoint("GP1", ("T1", "T2"))

    # ── 4. 人反馈"把手太粗了" → 定位到 Thought（L3 的前提）─────
    say("\n[4] 人反馈：『把手太粗了』")
    hit = None
    for tid, t in con.thoughts.items():
        if "把手" in t["claim"]:
            hit = tid
            break
    say(f"  定位到假设层 → {hit}（{con.thoughts[hit]['claim']}）")
    DATA["locate"] = hit

    # ── 5. 影响预览（Cass 2006 的推论）────────────────────────
    say("\n[5] 影响预览（推翻前必须先算因果闭包）")
    prev = con.impact_preview(hit)
    say(f"  将重推 {prev['n']} 段：{prev['will_replay']}")
    say(f"  其中 {prev['m']} 段可能失败：{prev['may_fail']}")
    DATA["impact_preview"] = prev

    # ── 6. 推翻 → 重推（L3 意图层回退）───────────────────────
    say("\n[6] 推翻假设并向下游重推")
    res = con.overturn(hit, "把手粗 7mm 握感舒适", 0.007)
    say(f"  {res['param']} = {res['value']}  耗时 {res['ms']} ms")
    say(f"    表面积 {res['before']['area']} → {res['after']['area']}")
    say(f"    包围盒 {res['before']['bbox']} → {res['after']['bbox']}")
    say(f"    面数   {res['before']['faces']} → {res['after']['faces']}（注意：改粗细不该变面数）")
    flag = "OK 几何确实变了" if res["geometry_really_changed"] else "FAIL 静默未生效"
    say(f"    判定：{flag}")
    DATA["overturn"] = res
    v1 = con.verify("重推后")
    DATA["verify_after_overturn"] = v1

    # ── 7. L1 状态层回退：删一层 opinion ──────────────────────
    say("\n[7] L1 状态层回退：删掉最上面一层 opinion")
    before = con.faces()
    name, dt = con.pop_layer()
    after = con.faces()
    say(f"  删掉 {name} → 面数 {before} → {after}，{dt} ms")
    DATA["L1_pop_layer"] = {"removed": name, "ms": dt, "before": before, "after": after}

    # ── 8. L2 语义层回退：回到 GoodPoint ──────────────────────
    say("\n[8] L2 语义层回退：回到 GoodPoint 快照")
    dt = con.revert_to_goodpoint("GP1")
    say(f"  回到 GP1，{dt} ms，面数 {len(obj.data.polygons)}")
    DATA["L2_goodpoint"] = {"ms": dt, "faces": len(obj.data.polygons)}

    # ── 9. 关键负面对照：改上游 vs 改下游 的成本 ──────────────
    say("\n[9] 负面对照：改上游参数 vs 改下游参数（验证 GN 到底有没有局部重算）")
    con2 = GNConsole(GNAdapter(bpy), None)  # 占位，重建一个干净场景
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    o2 = bpy.context.active_object
    o2.data = bpy.data.meshes.new("B")
    c2 = GNConsole(ad, o2)
    for spec in SPECS:
        c2.compile_and_mount(spec)
    c2.deps.update()
    ts_up, ts_down = [], []
    for i, v in enumerate((0.040, 0.045, 0.040, 0.045, 0.040, 0.045, 0.040)):
        t0 = time.perf_counter()
        c2.set_param("S1_杯体", "Body_Radius", v)
        c2.deps.update()
        m = c2.evaluate()
        c2.obj.evaluated_get(c2.deps).to_mesh_clear()
        ts_up.append((time.perf_counter() - t0) * 1000)
    for i, v in enumerate((2, 3, 2, 3, 2, 3, 2)):
        t0 = time.perf_counter()
        c2.set_param("S3_收尾", "Subdiv_Level", v)
        c2.deps.update()
        m = c2.evaluate()
        c2.obj.evaluated_get(c2.deps).to_mesh_clear()
        ts_down.append((time.perf_counter() - t0) * 1000)
    up, down = med(ts_up), med(ts_down)
    say(f"  改上游（S1 杯体半径）: {up} ms")
    say(f"  改下游（S3 细分级别）: {down} ms")
    say(f"  比值 {round(up/down, 2)}×  → 接近 1 就说明 GN 没有局部重算")
    DATA["no_local_recompute"] = {"upstream_ms": up, "downstream_ms": down,
                                  "ratio": round(up / down, 2)}

    # ── 9b. verifier 门禁必须真的会关门（只 PASS 过的门禁等于没有）──
    say("\n[9b] 故意把面数撑爆，看机械门禁会不会拦")
    c2.set_param("S3_收尾", "Subdiv_Level", 5)
    c2.deps.update()
    bad = c2.verify("撑爆")
    say(f"  面数 {bad['faces']}（预算 {c2.verifier.budget_faces}）")
    for f in bad["failures"]:
        say(f"      {f}")
    t0 = time.perf_counter()
    c2.set_param("S3_收尾", "Subdiv_Level", 2)   # 门禁不过 → 回退该段
    c2.deps.update()
    rollback_ms = round((time.perf_counter() - t0) * 1000, 3)
    good = c2.verify("回退后")
    say(f"  自动回退该段 {rollback_ms} ms → {'PASS' if good['ok'] else 'FAIL'}")
    DATA["gate"] = {"failed_as_expected": not bad["ok"], "faces_overflow": bad["faces"],
                    "failures": bad["failures"], "rollback_ms": rollback_ms,
                    "recovered": good["ok"]}

    # ── 10. 回环被拒（A1）────────────────────────────────────
    say("\n[10] A1：段落 DAG 能否杜绝回环")
    t = ad.new_group("Cycle_Probe")
    a = ad.add_node(t, "GeometryNodeSetPosition", "A")
    b = ad.add_node(t, "GeometryNodeSetPosition", "B")
    ad.link(t, a, "Geometry", b, "Geometry")
    try:
        ad.link(t, b, "Geometry", a, "Geometry")
        say("  FAIL：回环竟然被连上了")
        DATA["cycle_rejected"] = False
    except GNValidationError as e:
        say(f"  OK：{e}")
        DATA["cycle_rejected"] = True

    say("\n" + "=" * 60)
    say("可行性结论：见下方 JSON 与回复")
    OUT.write_text(json.dumps(DATA, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    say(f"result -> {OUT}")


if __name__ == "__main__":
    main()
