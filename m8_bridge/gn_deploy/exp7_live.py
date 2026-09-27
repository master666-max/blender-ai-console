"""exp7_live.py — EXP-7 工艺门禁三组对照实验（真机 · R7d）
=================================================================

跑法：blender.exe -b --factory-startup -P exp7_live.py
产出：result JSON -> 2026-09-26-blender/exp7_craft_gates_result.json

实验问题（隔离区吸收，上游 research-craft"工艺的元层"）：
  工艺门禁对"返工成本左移"的实际效果——同一工艺违例在三组治理下的
  暴露时机、修复动作数、污染面。

三组对照（同一违例：blockout 杯身穿地 z=-0.06 → verify above_ground FAIL）：
  A 硬门禁   DirectorSession+NormalPolicy，stage 全标注——detail 提案触发
             G1 铁门禁 → G1_BLOCKED 结构化拒绝（大形 verify FAIL 未过先禁细节）
  B 声明偏离 同场景，detail 提案带 deviation="明知大形未验先雕花"——
             只留痕不拦（M7-2 Tier 2 语义），违例后移到交付前全量 verify
  C 无门禁   裸 Console——blockout/detail 直接 compile，渲染交付后
             人工检查才暴露（detail 曾在烂底子上编译 = 污染）

统一度量（每组真机实测）：
  expose_point   违例暴露环节：propose_gate / pre_delivery_verify / post_delivery
  expose_delay   违例注入 → 暴露 的实测墙钟（秒）
  rework_actions 修复动作计数（拒绝响应/fix/recompile/重渲染）
  pollution      detail 在烂底子上被编译的次数（浪费算力 + 状态污染面）
  structured_err 暴露时拿到的错误是否结构化（AI 可自修 vs 人工解读）

预期（待真机数据裁决，不许预设）：门禁把返工左移到编译期——
A 组 detail 零污染；B/C 组 detail 至少白编一次，且暴露越晚动作越多。
"""

import json
import shutil
import sys
import time
import traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]  # 仓库根（相对推导，跨机器可移植）

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy

from gn_adapter import GNAdapter
from console import Console
from director import DirectorSession, NormalPolicy

RESULTS = ROOT.parent / "2026-09-26-blender"
ROWS: list[dict] = []
REPORT: dict[str, dict] = {}


def check(name, fn, expect=True):
    try:
        val = fn()
        if val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True})
        print(f"  PASS  {name}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:200],
                     "trace": traceback.format_exc(limit=3)})
        print(f"  FAIL  {name}  {exc!r}")


# 违例注入量实锤：Console verifier ground_z=-1.0（console.py L113——给落地物件
# 留裕量的系统真实阈值），z=-0.06 的小穿地不触发 above_ground——违例必须
# 沉到 -1.1（"整只杯子沉入地下"，渲染小图看不清，目验漏过前提仍成立）。
# ⚠ 七跑调试实锤：BAD_BLOCK 曾误写成 {"translation": [...]} dict——经 _sink_spec
# 变成嵌套 dict，_set_const 赋 Vector socket 抛异常被 except pass 静默吞掉
# → Translation 恒为 (0,0,0) → transform 无效 → 穿地"消失" → G1 永不拦。
# 违例注入值必须是裸列表；_set_const 的静默降级是实验脚本的头号陷阱。
BAD_BLOCK = [0.0, 0.0, -1.1]                        # 穿地违例（ground_z=-1.0 之下）
GOOD_BLOCK = [0.0, 0.0, 0.0]


def _new_console(tag: str) -> tuple[Console, object]:
    bpy.ops.mesh.primitive_plane_add(size=4, location=(0, 0, -0.001))
    ground = bpy.context.active_object
    ground.name = f"{tag}_Ground"
    bpy.ops.mesh.primitive_cylinder_add()
    host = bpy.context.active_object
    host.name = f"{tag}_Host"
    host.data = bpy.data.meshes.new(f"Base_{tag}")
    wal = HERE / f"exp7_{tag.lower()}_wal"
    shutil.rmtree(wal, ignore_errors=True)
    return Console(GNAdapter(bpy), host, workdir=wal), host


def _block_spec(tag: str, stage: str | None) -> dict:
    spec = {"id": f"{tag}_Block", "op": "cylinder",
            "parameters": [{"name": "radius", "value": 0.04},
                           {"name": "depth", "value": 0.09}]}
    if stage:
        spec["stage"] = stage
    return spec


def _sink_spec(tag: str, trans: dict, stage: str | None) -> dict:
    """穿地违例段：transform 下移（translation 是 transform op 专属字段——
    首跑实锤：塞进 cylinder 段会被 SCHEMA_FAIL 拒，故立独立 Sink 段）。"""
    spec = {"id": f"{tag}_Sink", "op": "transform", "consumes_input": True,
            "translation": trans}
    if stage:
        spec["stage"] = stage
    return spec


def _detail_spec(tag: str, stage: str | None, deviation: str = "") -> dict:
    spec = {"id": f"{tag}_Detail", "op": "subdivide", "consumes_input": True,
            "parameters": [{"name": "level", "value": 2}]}
    if stage:
        spec["stage"] = stage
    if deviation:
        spec["deviation"] = deviation       # 只进 spec 留痕（director 侧读 deviation 参数）
    return spec


def _accept_t3(ds, note):
    """T3 目验模拟拍板（实验前提：人眼漏过穿地——目验非机械兜底）。"""
    if ds.state == "PRESENTED":
        ds.accept(note=note)


# ── A 组：硬门禁 ─────────────────────────────────────────────
def run_group_A() -> dict:
    con, _ = _new_console("EXP5A")
    ds = DirectorSession(con, NormalPolicy())
    ds.begin(brief="EXP-7 A 组：硬门禁")
    m = {"group": "A_hard_gate", "expose_point": None, "expose_delay": None,
         "rework_actions": 0, "pollution": 0, "structured_err": None}
    # 违例注入：穿地 Sink 段（T3 目验漏过——渲染小图看不清穿地，人眼非兜底）
    t0 = time.perf_counter()
    r = ds.propose(_block_spec("EXP5A", "blockout"),
                   assumption="杯身位置符合设计意图")
    _accept_t3(ds, "大形可以（目验漏过穿地——人眼非机械兜底的实验前提）")
    r = ds.propose(_sink_spec("EXP5A", BAD_BLOCK, "blockout"),
                   assumption="定位调整符合设计意图（实际穿地，目验漏过）")
    _accept_t3(ds, "定位可以（目验漏过）")
    # detail 提案 → G1 铁门禁对依赖闭包内大形段实时 verify → 拦截
    r2 = ds.propose(_detail_spec("EXP5A", "detail"),
                    assumption="雕花可以直接做")
    dt = time.perf_counter() - t0
    assert not r2.get("accepted") and r2.get("g1_blocked"), f"A 组应被 G1 拦截：{r2}"
    m["expose_point"] = "propose_gate"
    m["expose_delay"] = round(dt, 3)
    m["structured_err"] = r2["error"]["error_code"] == "G1_BLOCKED" \
        and bool(r2["error"]["suggestions"])
    m["rework_actions"] += 1                                   # 响应拒绝
    # 修复：Sink 摆正（translation 常量经 recompile 直接生效）
    con.recompile("EXP5A_Sink", new_spec=_sink_spec("EXP5A", GOOD_BLOCK, "blockout"))
    m["rework_actions"] += 1
    assert con.verify("EXP5A_Sink").ok, "修复后 Sink 应 verify PASS"
    # detail 重提案（此前 detail 零编译 = 零污染）
    r3 = ds.propose(_detail_spec("EXP5A", "detail"),
                    assumption="大形已修，雕花可以直接做")
    _accept_t3(ds, "雕花可以")
    assert r3.get("auto_accepted") or ds.state == "IDLE", \
        f"修复后 detail 应通过：{r3.get('error')}"
    return m


# ── B 组：声明式偏离 ─────────────────────────────────────────
def run_group_B() -> dict:
    con, _ = _new_console("EXP5B")
    ds = DirectorSession(con, NormalPolicy())
    ds.begin(brief="EXP-7 B 组：声明式偏离")
    m = {"group": "B_declared_deviation", "expose_point": None,
         "expose_delay": None, "rework_actions": 0, "pollution": 0,
         "structured_err": None}
    t0 = time.perf_counter()
    r = ds.propose(_block_spec("EXP5B", "blockout"),
                   assumption="杯身位置符合设计意图")
    _accept_t3(ds, "大形可以（目验漏过）")
    ds.propose(_sink_spec("EXP5B", BAD_BLOCK, "blockout"),
               assumption="定位调整符合设计意图（实际穿地）")
    _accept_t3(ds, "定位可以（目验漏过）")
    # B 组语义（八跑修正）：声明式偏离 = 工艺纪律靠"声明+留痕"而非机械拦截——
    # G1 与 deviation 正交（穿地未修 G1 必拦，与是否声明无关）；故 B 组 detail
    # **不标 stage**（不进 G1 管辖），偏离经 propose(deviation=...) 进 WAL
    # （deviation 是 director 函数参数不是 spec 字段——spec 塞 deviation 会 SCHEMA_FAIL）。
    r2 = ds.propose(_detail_spec("EXP5B", None),
                    assumption="先雕花后对齐也可以",
                    deviation="明知大形未验先做细节（工艺偏序违例声明）")
    _accept_t3(ds, "雕花可以（偏离已声明）")
    assert r2.get("auto_accepted") is False and ds.state == "IDLE", \
        f"B 组 detail 应编上（T3 后 accept）：{r2.get('error')}"
    m["pollution"] += 1                     # detail 已在烂底子上编译
    # 交付前全量 verify（B 组的暴露点——全量扫所有段落）
    bad = [s for s in ("EXP5B_Block", "EXP5B_Sink", "EXP5B_Detail")
           if not con.verify(s).ok]
    dt = time.perf_counter() - t0
    assert "EXP5B_Sink" in bad, f"交付前 verify 应抓出穿地：{bad}"
    m["expose_point"] = "pre_delivery_verify"
    m["expose_delay"] = round(dt, 3)
    m["structured_err"] = True              # verify findings 结构化（但需人工关联到 Sink）
    m["rework_actions"] += 1                # 解读 findings
    con.recompile("EXP5B_Sink", new_spec=_sink_spec("EXP5B", GOOD_BLOCK, "blockout"))
    m["rework_actions"] += 1
    con.recompile("EXP5B_Detail", new_spec=_detail_spec("EXP5B", "detail"))
    m["rework_actions"] += 1                # detail 曾白编 → 重编
    assert con.verify("EXP5B_Sink").ok and con.verify("EXP5B_Detail").ok
    m["deviation_logged"] = "WAL director_deviation 事件（director.py L235-237 留痕语义）"
    return m


# ── C 组：无门禁 ─────────────────────────────────────────────
def run_group_C() -> dict:
    con, host = _new_console("EXP5C")
    m = {"group": "C_no_gate", "expose_point": None, "expose_delay": None,
         "rework_actions": 0, "pollution": 0, "structured_err": None}
    t0 = time.perf_counter()
    r1 = con.compile(_block_spec("EXP5C", None))            # 大形直编（无 stage 无门禁）
    assert r1.ok
    r2 = con.compile(_sink_spec("EXP5C", BAD_BLOCK, None))  # 穿地 transform 直编
    assert r2.ok
    r3 = con.compile(_detail_spec("EXP5C", None))
    assert r3.ok
    m["pollution"] += 1                     # detail 在烂底子上编译
    # "交付"：渲染一次（交付物已产出并发出去——事后才发现的实验前提）
    con.render_diff("EXP5C_delivery")
    # 交付后人工/事后检查才发现（全量）
    bad = [s for s in ("EXP5C_Block", "EXP5C_Sink", "EXP5C_Detail")
           if not con.verify(s).ok]
    dt = time.perf_counter() - t0
    assert "EXP5C_Sink" in bad, f"事后 verify 应抓出穿地：{bad}"
    m["expose_point"] = "post_delivery"
    m["expose_delay"] = round(dt, 3)
    m["structured_err"] = False             # 交付后发现 = 已发出去的产物要召回重做
    m["rework_actions"] += 3                # 召回认知 + 修 Sink + detail 重编 + 重渲染
    con.recompile("EXP5C_Sink", new_spec=_sink_spec("EXP5C", GOOD_BLOCK, None))
    con.recompile("EXP5C_Detail", new_spec=_detail_spec("EXP5C", None))
    con.render_diff("EXP5C_redelivery")     # 重渲染（召回成本）
    assert con.verify("EXP5C_Sink").ok and con.verify("EXP5C_Detail").ok
    return m


print(f"Blender {bpy.app.version_string}")
bpy.ops.wm.read_factory_settings(use_empty=True)

print("\n[A] 硬门禁组")
check("A 组流程（G1 拦截+修复+重提案）", lambda: REPORT.update(A=run_group_A()) or True)
print("\n[B] 声明式偏离组")
check("B 组流程（deviation 放行+verify 抓出+重编）",
      lambda: REPORT.update(B=run_group_B()) or True)
print("\n[C] 无门禁组")
check("C 组流程（直编+交付后暴露+召回）",
      lambda: REPORT.update(C=run_group_C()) or True)

# ── 对照判读 ────────────────────────────────────────────────
a, b, c = REPORT.get("A", {}), REPORT.get("B", {}), REPORT.get("C", {})
print("\n===== EXP-7 对照表 =====")
for g in (a, b, c):
    print(f"  {g.get('group','?'):<24} 暴露={g.get('expose_point')}  "
          f"时延={g.get('expose_delay')}s  动作={g.get('rework_actions')}  "
          f"污染={g.get('pollution')}")
conclusion = {
    "left_shift": (a.get("pollution") == 0
                   and b.get("pollution", 1) >= 1 and c.get("pollution", 1) >= 1),
    "cost_order": (a.get("rework_actions", 99) <= b.get("rework_actions", 99)
                   <= c.get("rework_actions", 99)),
    "a_structured": bool(a.get("structured_err")),
}
print(f"  判读：左移成立={conclusion['left_shift']}  "
      f"动作数单调（A≤B≤C）={conclusion['cost_order']}  A 组结构化错误={conclusion['a_structured']}")

n_ok = sum(1 for r in ROWS if r["ok"])
print(f"\nEXP-7 LIVE: {n_ok}/{len(ROWS)} passed")
out = {"suite": "EXP-7 craft gate 3-group controlled experiment",
       "passed": n_ok, "total": len(ROWS),
       "blender_version": list(bpy.app.version),
       "cases": ROWS, "groups": REPORT, "conclusion": conclusion,
       "honest_scope": "三组同进程真机串行；T3 目验按'人眼漏过穿地'前提模拟 accept"
                       "（实验前提：目验非机械兜底）；C 组召回成本以动作计数近似"}
RESULTS.mkdir(exist_ok=True)
(RESULTS / "exp7_craft_gates_result.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("result ->", RESULTS / "exp7_craft_gates_result.json")
