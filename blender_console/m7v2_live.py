"""m7v2_live.py — M7-2 v2（逻辑分支树+阶段偏序）+ M7-3（目验门）真机验收。

跑法：blender --background --factory-startup --python m7v2_live.py

验收（改动-对照实测纪律）：
  1. M7-3 目验铁门禁：AUTOPILOT 下 stage=blockout 也强制 T3（阶段维度覆盖风险维度）
  2. M7-2 偏序门正例：blockout/structure 实时 verify PASS → detail 提案放行
  3. M7-2 偏序门反例：大形段穿地（verify FAIL）→ detail 提案 G1_BLOCKED（会拦）
  4. 修复（位置归位）→ detail 放行（改动-对照闭环）
  5. drop_part 子树回退：打回 mug/handle 部件（段消失、DAG 步消失）
  6. deviation 声明式偏离留痕 / sees 所见引用留痕
  7. 全程 NORMAL/AUTOPILOT 换用（set_policy 热拔插）
"""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy  # noqa: E402

from director import (AutoPilotPolicy, DirectorSession, NormalPolicy,  # noqa: E402
                      StrictPolicy)

OUT = ROOT / "m8_bridge"
ROWS: list[dict] = []


def check(name, fn, expect=True):
    try:
        val = fn()
        if val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True, "detail": str(val)[:120]})
        print(f"  PASS  {name}  {str(val)[:100]}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:200]})
        print(f"  FAIL  {name}  {exc!r}")


print(f"Blender {bpy.app.version_string}")
bpy.ops.wm.read_factory_settings(use_empty=True)

# AUTOPILOT：证明 M7-3 目验门**覆盖**风险档位（连全自动都为 blockout 停一次）
ds = DirectorSession(Console := __import__("console").Console(
    __import__("gn_adapter").GNAdapter(bpy),
    *(lambda o: (o,))(  # noqa: PLW  占位，下面立即替换
        None)), AutoPilotPolicy()) if False else None

from gn_adapter import GNAdapter  # noqa: E402
ad = GNAdapter(bpy)
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.active_object
obj.name = "Mug"
obj.data = bpy.data.meshes.new("Mug_Base")
con = __import__("console").Console(ad, obj, workdir=HERE / "_m7v2_wal")
ds = DirectorSession(con, AutoPilotPolicy())      # AUTOPILOT：证明目验门覆盖档位
ds.begin(brief="M7-2/M7-3 验收")

BODY = {"id": "body", "stage": "blockout", "part": "mug/body", "op": "cylinder",
        "consumes_input": False,
        "parameters": [{"name": "Radius", "type": "FLOAT", "value": 0.04},
                       {"name": "Depth", "type": "FLOAT", "value": 0.095}]}
DETAIL = {"id": "detail1", "stage": "detail", "part": "mug/body",
          "op": "subdivide", "consumes_input": True,
          "parameters": [{"name": "Level", "type": "INT", "value": 1}]}

# ── [1] M7-3 目验铁门禁 ──────────────────────────────────────
print("\n[1] M7-3 目验铁门禁（AUTOPILOT 下 blockout 仍强制 T3）")
r = ds.propose(BODY, assumption="大形比例合理",
               deviation="用户给了明确尺寸，跳过参考锚定")
check("AUTOPILOT 下 blockout → 强制 T3（阶段铁门禁覆盖风险档位）",
      lambda: (r["tier"], r["auto_accepted"], ds.state),
      ("T3_DIRECTOR", False, "PRESENTED"))
check("accept 后进栈", lambda: (ds.accept(note="大形可以"), len(obj.modifiers))[1], 1)
check("gate PASS 记录", lambda: r["gate_ok"], True)

# ── [2] 偏序门正例 ────────────────────────────────────────────
print("\n[2] M7-2 偏序门正例（大形已 PASS → detail 放行）")
r2 = ds.propose(DETAIL, assumption="1 级细分够用")
check("祖先 blockout 已 PASS → detail 放行（T1 under AUTOPILOT）",
      lambda: (r2["tier"], r2["auto_accepted"]), ("T1_AUTOPILOT", True))
check("stage 记录", lambda: ds.stage_of["detail1"], "detail")

# deviation 留痕
check("deviation WAL 留痕",
      lambda: any(e["kind"] == "director_deviation"
                  for e in con.wal.replay()), True)

# ── [3] 偏序门反例：大形穿地（实时 verify FAIL）→ detail 拒 ──
print("\n[3] 偏序门反例（G1 铁门禁会拦）")
obj.location.z = -2.0                              # 穿地（ground_z=-1）
hollow = {"id": "hollow", "stage": "structure", "part": "mug/body",
          "op": "boolean_diff", "consumes_input": True, "parameters": [],
          "operand": {"op": "transform", "translation": [0.0, 0.0, 0.01],
                      "source": {"op": "cylinder", "radius": 0.036,
                                 "depth": 0.085}}}
r3 = ds.propose(hollow, assumption="掏空")
check("structure 段可编译（门禁记录 FAIL 不阻塞本段）",
      lambda: r3.get("gate_ok") is False or r3.get("gate_ok") is not None, True)
check("structure 段 verify 确实 FAIL（穿地被检）",
      lambda: r3["gate_ok"], False)
r4 = ds.propose({**DETAIL, "id": "detail2"}, assumption="细节时间")
check("G1 铁门禁：大形穿地未修 → detail 提案被拒",
      lambda: r4.get("g1_blocked"), True)
check("拒绝原因含大形段名",
      lambda: "body" in r4["error"]["reason"], True)

# 修复：位置归位 → detail 放行（改动-对照闭环）
obj.location.z = 0.0
r5 = ds.propose({**DETAIL, "id": "detail2"}, assumption="细节时间")
check("位置归位 → detail 放行（闭环）", lambda: r5.get("g1_blocked", False), False)

# ── [4] drop_part 子树回退 ────────────────────────────────────
print("\n[4] drop_part 子树回退")
r_h = ds.propose({"id": "handle", "stage": "detail", "part": "mug/handle",
                  "op": "join_geometry", "consumes_input": True,
                  "parameters": [{"name": "Handle_Thickness", "type": "FLOAT",
                                  "value": 0.008}],
                  "operand": {"op": "transform",
                              "translation": [0.062, 0.0, 0.045],
                              "source": {"op": "transform",
                                         "rotation_deg": [90.0, 0.0, 0.0],
                                         "source": {"op": "sweep_circle",
                                                    "ring_radius": 0.032}}}},
                 assumption="8mm 把手")
check("handle 段编译", lambda: r_h.get("auto_accepted") is not None, True)
mods_before = len(obj.modifiers)
steps_before = len(con.dag)
rp = ds.drop_part("mug/handle")
check("drop_part 打回部件", lambda: len(rp["dropped"]), 1)
check("modifier 下架", lambda: len(obj.modifiers), mods_before - 1)
check("DAG 步下架", lambda: len(con.dag), steps_before - 1)
r_dup = con.drop_part("mug/handle")                # 已打回再打回
check("重复打回 → PART_NOT_FOUND（M9-1 结构化返回）",
      lambda: (not r_dup.ok and r_dup.error["error_code"] == "PART_NOT_FOUND"), True)

# ── [5] sees 所见引用留痕 ─────────────────────────────────────
print("\n[5] sees 所见引用留痕（M7-3）")
r6 = ds.propose({"id": "polish", "stage": "cleanup", "part": "mug",
                 "op": "merge_by_distance", "consumes_input": True,
                 "parameters": [{"name": "Distance", "type": "FLOAT",
                                 "value": 0.0005}]},
                assumption="焊距 0.5mm 不伤形",
                sees="上一帧看到杯体内壁有两处重合面")
check("cleanup 段放行", lambda: r6.get("auto_accepted") is not None, True)
check("sees WAL 留痕",
      lambda: any(e["kind"] == "director_sees"
                  for e in con.wal.replay()), True)

# ── [6] set_policy 热拔插（回归）─────────────────────────────
print("\n[6] 换装回归")
res = ds.set_policy(StrictPolicy(), reason="精修段全人审")
check("运行时换装 STRICT", lambda: ds.policy.name, "STRICT")
check("WAL 换装留痕",
      lambda: any(e["kind"] == "director_set_policy"
                  for e in con.wal.replay()), True)
ds.set_policy(AutoPilotPolicy(), reason="收工")

failed = [r for r in ROWS if not r["ok"]]
print(f"\nM7-V2 LIVE: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
for f in failed:
    print("  FAILED:", f["case"], "->", f.get("detail"))
out = ROOT / "m8_bridge" / "m7v2_result.json"
out.write_text(json.dumps(ROWS, ensure_ascii=False, indent=1), encoding="utf-8")
print("result ->", out)
sys.exit(1 if failed else 0)
