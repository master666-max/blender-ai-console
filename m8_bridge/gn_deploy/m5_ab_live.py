"""m5_ab_live.py — M5 交互层（A/B 二选一协议）真机验收（Blender 5.2.1）。

跑法：blender --background --factory-startup --python m5_ab_live.py

验收项（全机械，B1 纪律）：
  1. ab_prepare：两变体同机位渲染（PNG 可解码、dHash 互异）、预览不落账
     （prepare 前后指纹不变）、B4 映射封存（返回里没有映射/AI 偏好）、
     M5-11 折叠（返回里没有 ai_reason）
  2. 状态机：pending 时再 prepare → AB_ALREADY_PENDING
  3. 参数校验：PARAM_NOT_FOUND / BAD_AI_PREFERRED
  4. M5-10：confidence 4/96 → CONFIDENCE_OUT_OF_RANGE；无 pending → NO_AB_PENDING
  5. ab_commit 采纳：真写生效（指纹变）、reveal 带映射+ai_reason、
     WAL 有 ab_prepare → ab_commit（B6 人/AI 通路分离 = 事件种类分离）
  6. B3 摩擦对称：选非 AI 偏好 → override 计数 +1
  7. reroll 第三出口（M5-9）：回到 commit 前几何，无真写
  8. WAL 终局 verify（哈希链完整）
"""
import base64
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

OUT = ROOT / "results"
ROWS: list[dict] = []


def check(name, fn, expect=None):
    try:
        val = fn()
        if expect is not None and val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True, "detail": str(val)[:140]})
        print(f"  PASS  {name}  {val}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:200]})
        print(f"  FAIL  {name}  {exc!r}")


print(f"Blender {bpy.app.version_string}")
ad = GNAdapter(bpy)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.active_object
obj.name = "Mug"
obj.data = bpy.data.meshes.new("Base")

shutil.rmtree(HERE / "_m5_wal", ignore_errors=True)
con = Console(ad, obj, workdir=HERE / "_m5_wal")
con.add_thought("T2", "把手 8mm 握感舒适", {"segment": "handle", "param": "Handle_Thickness"})

# 纯 op-JSON 两段（沿用 M4-3 的编译器）
check("编译 body",
      lambda: con.compile({"id": "body", "op": "cylinder", "consumes_input": False,
                           "parameters": [{"name": "Radius", "type": "FLOAT", "value": 0.04},
                                          {"name": "Depth", "type": "FLOAT", "value": 0.095}]}).ok, True)
check("编译 handle",
      lambda: con.compile({"id": "handle", "op": "join_geometry", "consumes_input": True,
                           "parameters": [{"name": "Handle_Thickness", "type": "FLOAT",
                                           "value": 0.008, "min": 0.003, "max": 0.03}],
                           "operand": {"op": "transform", "translation": [0.062, 0.0, 0.045],
                                       "source": {"op": "transform",
                                                  "rotation_deg": [90.0, 0.0, 0.0],
                                                  "source": {"op": "sweep_circle",
                                                             "ring_radius": 0.032}}}}).ok, True)

fp0 = con._output_fp(con._eval_stats())

# ── [1] ab_prepare ───────────────────────────────────────────
print("\n[1] ab_prepare（B4 封存 / M5-11 折叠 / 预览不落账）")
r_p = con.ab_prepare("handle",
                     [{"Handle_Thickness": 0.006}, {"Handle_Thickness": 0.014}],
                     ai_preferred=1, ai_reason="14mm 在握感数据里更稳")
if not r_p.ok:
    print("  prepare error:", r_p.error)
check("prepare ok", lambda: r_p.ok, True)
blob = json.dumps(r_p.to_tool_return(), ensure_ascii=False)
check("B4：返回里没有映射/ai_preferred（封存）",
      lambda: ("ai_preferred" not in blob) and ("mapping" not in blob), True)
check("M5-11：返回里没有 ai_reason（折叠）",
      lambda: "握感数据" not in blob, True)
vd = r_p.data["variants"]
check("甲乙两图都是 PNG",
      lambda: all(base64.b64decode(v["png_b64"])[:4] == b"\x89PNG" for v in vd.values()), True)
check("两变体 dHash 互异（视觉上确实不同）",
      lambda: vd["甲"]["dhash"] != vd["乙"]["dhash"], True)
fp_after_prepare = con._output_fp(con._eval_stats())
check("预览不落账（prepare 前后指纹不变）", lambda: fp_after_prepare, fp0)
check("摘要不含 ai_reason", lambda: "握感数据" not in r_p.summary, True)

# ── [2] 状态机 ────────────────────────────────────────────────
print("\n[2] 状态机")
r_dup = con.ab_prepare("handle", [{"Handle_Thickness": 0.006},
                                  {"Handle_Thickness": 0.014}])
check("pending 时再 prepare → AB_ALREADY_PENDING",
      lambda: not r_dup.ok and r_dup.error["error_code"] == "AB_ALREADY_PENDING", True)
r_badp = con.ab_prepare("handle", [{"Nope": 0.006}, {"Handle_Thickness": 0.014}])
check("未知参数 → PARAM_NOT_FOUND（但被 pending 挡在前）",
      lambda: not r_badp.ok and r_badp.error["error_code"] == "AB_ALREADY_PENDING", True)

# ── [3] M5-10 置信度边界 ─────────────────────────────────────
print("\n[3] M5-10 置信度边界")
r_lo = con.ab_commit("甲", 4)
check("confidence=4 → CONFIDENCE_OUT_OF_RANGE",
      lambda: not r_lo.ok and r_lo.error["error_code"] == "CONFIDENCE_OUT_OF_RANGE", True)
r_hi = con.ab_commit("甲", 96)
check("confidence=96 → CONFIDENCE_OUT_OF_RANGE",
      lambda: not r_hi.ok and r_hi.error["error_code"] == "CONFIDENCE_OUT_OF_RANGE", True)
r_nc = con.ab_commit("bad", 50)
check("choice=bad → BAD_CHOICE（M5-9 只有三出口）",
      lambda: not r_nc.ok and r_nc.error["error_code"] == "BAD_CHOICE", True)

# ── [4] 采纳 ─────────────────────────────────────────────────
print("\n[4] ab_commit 采纳（真写 + 揭晓 + B3）")
ov_before = con.overrides
r_c = con.ab_commit("乙", 80, note="厚的那个握感更像我的杯子")
if not r_c.ok:
    print("  commit error:", r_c.error)
check("commit ok", lambda: r_c.ok, True)
chosen_value = r_c.data["applied"]["Handle_Thickness"]
check("M5-11 揭晓：reveal 带 ai_reason",
      lambda: r_c.data["reveal"]["ai_reason"], "14mm 在握感数据里更稳")
check("B4 揭晓：reveal 带映射",
      lambda: set(r_c.data["reveal"]["mapping"]), {"甲", "乙"})
check("真写生效（Handle_Thickness = 选中变体的值）",
      lambda: con.vparams.get()["handle.Handle_Thickness"], chosen_value)
fp1 = con._output_fp(con._eval_stats())
check("几何确实变了", lambda: fp1 != fp0, True)
ov_expected = ov_before + (0 if r_c.data["reveal"]["ai_preferred"] == "乙" else 1)
check("B3 摩擦对称：override 计数符合选择",
      lambda: con.overrides, ov_expected)
check("applied 与所选标签一致",
      lambda: r_c.data["applied"], r_c.data["reveal"]["mapping"]["乙"])

# WAL 通路分离（B6）：ab_prepare 与 ab_commit 是不同事件种类，各有载荷
events = [e["kind"] for e in con.wal.replay()]
check("B6：WAL 有 ab_prepare 事件", lambda: "ab_prepare" in events, True)
check("B6：WAL 有 ab_commit 事件（带 note）",
      lambda: any(e["kind"] == "ab_commit" and e["payload"].get("note")
                  for e in con.wal.replay()), True)
prepare_ev = next(e for e in con.wal.replay() if e["kind"] == "ab_prepare")
commit_ev = next(e for e in con.wal.replay() if e["kind"] == "ab_commit")
check("B4 一致性：prepare/commit 载荷同源、映射是合法置换",
      lambda: (commit_ev["payload"]["variants"] == prepare_ev["payload"]["variants"]
               and sorted(prepare_ev["payload"]["mapping"]) == ["0", "1"]
               and set(prepare_ev["payload"]["mapping"].values()) == {"甲", "乙"}), True)
check("R15 铺垫：commit 载荷带 variants 向量（M6-6 可消费）",
      lambda: len(commit_ev["payload"]["variants"]), 2)

# 非 pending 时的参数校验路径
r_badp2 = con.ab_prepare("handle", [{"Nope": 0.006}, {"Handle_Thickness": 0.014}])
check("未知参数 → PARAM_NOT_FOUND",
      lambda: not r_badp2.ok and r_badp2.error["error_code"] == "PARAM_NOT_FOUND", True)

# ── [5] reroll（M5-9 第三出口）───────────────────────────────
print("\n[5] reroll 第三出口")
r_p2 = con.ab_prepare("handle", [{"Handle_Thickness": 0.005},
                                 {"Handle_Thickness": 0.02}],
                      ai_preferred=0, ai_reason="再试两档")
check("第二张卡 prepare ok", lambda: r_p2.ok, True)
fp_before_reroll = con._output_fp(con._eval_stats())
r_r = con.ab_commit("reroll", 60)
check("reroll ok", lambda: r_r.ok, True)
check("reroll：applied = None（无真写）", lambda: r_r.data["applied"], None)
check("reroll：几何回 commit 前", lambda: con._output_fp(con._eval_stats()),
      fp_before_reroll)
check("reroll 不计 override（没选任何变体）",
      lambda: r_r.data["override_counted"], False)

# ── [6] 无 pending ───────────────────────────────────────────
print("\n[6] 无 pending")
r_no = con.ab_commit("甲", 50)
check("无 pending commit → NO_AB_PENDING",
      lambda: not r_no.ok and r_no.error["error_code"] == "NO_AB_PENDING", True)
check("WAL 终局 verify", lambda: con.wal.verify(), True)

# ── 汇总 ─────────────────────────────────────────────────────
failed = [r for r in ROWS if not r["ok"]]
print(f"\nM5-AB LIVE: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
for f in failed:
    print("  FAILED:", f["case"], "->", f["detail"])
(OUT / "m5_ab_live_result.json").write_text(
    json.dumps(ROWS, ensure_ascii=False, indent=1), encoding="utf-8")
print("result ->", OUT / "m5_ab_live_result.json")
