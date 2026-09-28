"""m7_director_live.py — M7 导演模式真机验收（Blender 5.2.1）。

跑法：blender --background --factory-startup --python m7_director_live.py

验收项（全机械，B1 纪律）：
  1. NormalPolicy 分档：自产图元 → T1 自动通过；吃上游 <3 参 → T2 通知式；
     结构 op（boolean/join）→ T3 阻塞等导演
  2. 提案纪律：无假设 → ValueError（B1/B5）；T3 待决时再提案 → RuntimeError
  3. accept 落账；override：删层 + override 计数 + M6-3 经验库回写 + D9 建议
  4. override 无 note → ValueError（R15 语言化）
  5. StrictPolicy 全阻塞 / AutoPilotPolicy 全自动（开闭原则：换实例不改代码）
  6. finish：export_state + override 率统计；WAL 终局 verify
"""
import json
import shutil
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]  # 仓库根（相对推导，跨机器可移植）

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy

from gn_adapter import GNAdapter
from console import Console
from director import AutoPilotPolicy, DirectorSession, NormalPolicy, StrictPolicy

OUT = ROOT / "results"
ROWS: list[dict] = []


def check(name, fn, expect=True):
    try:
        val = fn()
        if val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True, "detail": str(val)[:140]})
        print(f"  PASS  {name}  {val}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:200]})
        print(f"  FAIL  {name}  {exc!r}")


def expect_raise(name, et, fn):
    try:
        fn()
    except et:
        ROWS.append({"case": name, "ok": True})
        print(f"  PASS  {name}（正确拒绝：{et.__name__}）")
        return
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": f"抛错类型 {exc!r}"})
        print(f"  FAIL  {name}  抛错类型 {exc!r}")
        return
    ROWS.append({"case": name, "ok": False, "detail": "未抛错"})
    print(f"  FAIL  {name}  未抛错")


print(f"Blender {bpy.app.version_string}")
ad = GNAdapter(bpy)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.active_object
obj.name = "Mug"
obj.data = bpy.data.meshes.new("Base")

shutil.rmtree(HERE / "_m7_wal", ignore_errors=True)
con = Console(ad, obj, workdir=HERE / "_m7_wal")
con.attach_experience()
ds = DirectorSession(con, NormalPolicy())
ds.begin(brief="做一个导演能放手的马克杯")

# 预置一条经验（让 override 后的 D9 建议有素材）
con.library.add(__import__("experience").ExperienceEntry(
    trigger={"seg": "handle", "kind": "director_override"},
    attention="把手环先立再挪：rotation 90° 后再 translate",
    story="直接 translate 的环是躺平的；先转 90° 立起来，再挪到杯侧",
    params={"Handle_Thickness": 0.008}, outcome="verified_success"))

# ── [1] NormalPolicy 分档 ────────────────────────────────────
print("\n[1] 分档（影响面）")
p1 = ds.propose({"id": "body", "op": "cylinder", "consumes_input": False,
                 "parameters": [{"name": "Radius", "type": "FLOAT", "value": 0.04},
                                {"name": "Depth", "type": "FLOAT", "value": 0.095}]},
                assumption="圆柱杯体 0.04/0.095 比例在手感范围")
check("自产图元 → T1 自动通过",
      lambda: (p1["tier"], p1["auto_accepted"], ds.state), (T1 := "T1_AUTOPILOT", True, "IDLE"))
check("三件套之图在场", lambda: len(p1["render_diff_b64"]) > 1000, True)
check("假设被原样记录", lambda: p1["assumption"].startswith("圆柱杯体"), True)

p2 = ds.propose({"id": "hollow", "op": "boolean_diff", "consumes_input": True,
                 "parameters": [],
                 "operand": {"op": "transform", "translation": [0.0, 0.0, 0.01],
                             "source": {"op": "cylinder", "radius": 0.036,
                                        "depth": 0.085}}},
                assumption="掏空后壁厚 ~4mm，verifier 应放行")
check("结构 op → T3 阻塞",
      lambda: (p2["tier"], p2["auto_accepted"], ds.state),
      ("T3_DIRECTOR", False, "PRESENTED"))

# ── [2] 提案纪律 ─────────────────────────────────────────────
print("\n[2] 提案纪律")
expect_raise("T3 待决时再提案 → 拒绝", RuntimeError,
             lambda: ds.propose({"id": "x", "op": "cube"}, assumption="y"))

# ── [3] accept ───────────────────────────────────────────────
print("\n[3] accept（导演通过）")
r = ds.accept(note="壁厚比例可以")
check("accept 回 IDLE", lambda: (r["state"], r["accepted"]), ("IDLE", "hollow"))
check("段落真在栈上", lambda: len(obj.modifiers), 2)
expect_raise("IDLE 下无假设提案 → 拒绝（B1/B5）", ValueError,
             lambda: ds.propose({"id": "y", "op": "cube"}, assumption="  "))

# ── [4] T2 通知式 ────────────────────────────────────────────
print("\n[4] T2 通知式（吃上游 <3 参）")
p3 = ds.propose({"id": "place", "op": "transform", "consumes_input": True,
                 "parameters": [{"name": "Translation", "type": "VECTOR",
                                 "value": [0.0, 0.0, 0.0]}]},
                assumption="整体不动，占位段验证 T2 通道")
check("吃上游 <3 参 → T2 自动通过",
      lambda: (p3["tier"], p3["auto_accepted"]), ("T2_NOTIFY", True))

# ── [5] override（打回 + 回写 + 建议）────────────────────────
print("\n[5] override（导演打回）")
p4 = ds.propose({"id": "handle", "op": "join_geometry", "consumes_input": True,
                 "parameters": [{"name": "Handle_Thickness", "type": "FLOAT",
                                 "value": 0.02}],
                 "operand": {"op": "transform", "translation": [0.062, 0.0, 0.045],
                             "source": {"op": "transform",
                                        "rotation_deg": [90.0, 0.0, 0.0],
                                        "source": {"op": "sweep_circle",
                                                   "ring_radius": 0.032}}}},
                assumption="20mm 把手够粗——可反驳：可能粗到失真")
check("join → T3 阻塞", lambda: (p4["tier"], ds.state),
      ("T3_DIRECTOR", "PRESENTED"))
mods_before = len(obj.modifiers)
ov_before = con.overrides
expect_raise("override 无 note → 拒绝（R15）", ValueError,
             lambda: ds.override(""))
r5 = ds.override("把手粗到失真了，打回重提")
check("打回删层", lambda: len(obj.modifiers), mods_before - 1)
check("override 计数 +1", lambda: con.overrides, ov_before + 1)
check("M6-3 回写：经验库多了 verified_failure",
      lambda: any(e.outcome == "verified_failure"
                  for e in con.library.entries.values()), True)
check("D9 建议在场（≥1 条）", lambda: len(r5["suggestions"]) >= 1, True)
check("打回后回 IDLE", lambda: ds.state, "IDLE")

# ── [6] 重提（带经验修正）───────────────────────────────────
print("\n[6] 重提把手（吸收打回意见）")
p5 = ds.propose({"id": "handle", "op": "join_geometry", "consumes_input": True,
                 "parameters": [{"name": "Handle_Thickness", "type": "FLOAT",
                                 "value": 0.008}],
                 "operand": {"op": "transform", "translation": [0.062, 0.0, 0.045],
                             "source": {"op": "transform",
                                        "rotation_deg": [90.0, 0.0, 0.0],
                                        "source": {"op": "sweep_circle",
                                                   "ring_radius": 0.032}}}},
                assumption="8mm——打回意见：细一点不失真")
check("重提 T3", lambda: p5["tier"], "T3_DIRECTOR")
ds.accept(note="这版可以")
check("把手段在栈上", lambda: len(obj.modifiers), mods_before)

# ── [7] 策略对象（开闭原则）─────────────────────────────────
print("\n[7] StrictPolicy / AutoPilotPolicy（换实例不改代码）")
ds_strict = DirectorSession(con, StrictPolicy())
p6 = ds_strict.propose({"id": "finish", "op": "subdivide", "consumes_input": True,
                        "parameters": [{"name": "Level", "type": "INT", "value": 1}]},
                       assumption="细分 1 级即可圆滑")
check("STRICT：非结构 op 也阻塞", lambda: (p6["tier"], ds_strict.state),
      ("T3_DIRECTOR", "PRESENTED"))
ds_strict.accept()
ds_auto = DirectorSession(con, AutoPilotPolicy())
p7 = ds_auto.propose({"id": "weld", "op": "merge_by_distance",
                      "consumes_input": True,
                      "parameters": [{"name": "Distance", "type": "FLOAT",
                                      "value": 0.0005}]},
                     assumption="焊接距离 0.5mm 不伤形")
check("AUTOPILOT：全部 T1 自动", lambda: (p7["tier"], p7["auto_accepted"]),
      ("T1_AUTOPILOT", True))

# ── [8] finish ───────────────────────────────────────────────
print("\n[8] finish（统计 + 导出）")
fin = ds.finish()
check("导出在场", lambda: "export" in fin and fin["export"].get("schema"),
      "mug-console-state/1")
check("override 率 = 1/5", lambda: fin["session"]["override_rate"], 0.2)
check("WAL 终局 verify", lambda: con.wal.verify(), True)

# ── [9] 运行时换装（热拔插治理内核）─────────────────────────
print("\n[9] set_policy 运行时换装（换装 = 登记动作）")
check("换前 NORMAL", lambda: ds.policy.name, "NORMAL")
res_sp = ds.set_policy(StrictPolicy(), reason="进入精修阶段，全段人审")
check("换装生效 → STRICT", lambda: ds.policy.name, "STRICT")
check("WAL 留痕 director_set_policy",
      lambda: any(e["kind"] == "director_set_policy"
                  for e in con.wal.replay()), True)
p9 = ds.propose({"id": "guard", "op": "cube"}, assumption="STRICT 下图元也阻塞")
check("STRICT 下图元也 T3", lambda: (p9["tier"], ds.state),
      ("T3_DIRECTOR", "PRESENTED"))
expect_raise("T3 待决时拒绝换装", RuntimeError,
             lambda: ds.set_policy(NormalPolicy(), "试探"))
ds.accept(note="守卫段通过")
ds.set_policy(NormalPolicy(), "收工换回")
check("换回 NORMAL", lambda: ds.policy.name, "NORMAL")

failed = [r for r in ROWS if not r["ok"]]
print(f"\nM7 DIRECTOR LIVE: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
for f in failed:
    print("  FAILED:", f["case"], "->", f.get("detail"))
(OUT / "m7_director_live_result.json").write_text(
    json.dumps(ROWS, ensure_ascii=False, indent=1), encoding="utf-8")
print("result ->", OUT / "m7_director_live_result.json")
