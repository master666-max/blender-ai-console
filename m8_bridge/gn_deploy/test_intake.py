"""test_intake.py — M9-1b 提问协议单元测试（纯 Python，秒级）。

跑法：python test_intake.py
覆盖：先查后问 / 四档 / 每轮 ≤4 问带 default+why / 翻牌制 origin /
      域覆盖收敛 / freeze 三要素 / PRD → plan 骨架（一份两用）/ 换档。
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from intake import IntakeSession, DOMAIN_BANK  # noqa: E402

ROWS: list[dict] = []


def check(name, fn, expect=True):
    try:
        val = fn()
        if val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True})
        print(f"  PASS  {name}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:160]})
        print(f"  FAIL  {name}  {exc!r}")


# ── [1] 先查后问 ─────────────────────────────────────────────
print("[1] 先查后问")
s1 = IntakeSession(brief="马克杯", scene_facts={"size_height": 0.11})
card = s1.ask_round()
q_fields = [q["field"] for q in card["data"]["questions"]]
check("上下文已有字段不再问", lambda: "size_height" in q_fields, False)
check("from_context 落账",
      lambda: s1.fields["size_height"]["origin"], "from_context")
check("提问卡含域覆盖进度", lambda: "domain_progress" in card["data"], True)

# ── [2] 快速档：1 轮 ≤4 问带 default+why ─────────────────────
print("\n[2] 快速档")
s2 = IntakeSession(brief="做个马克杯", mode="quick")
card2 = s2.ask_round()
qs = card2["data"]["questions"]
check("快速档 ≤4 问", lambda: len(qs) <= 4, True)
check("每问带 default", lambda: all("default" in q for q in qs), True)
check("每问带 why（默认值也是假设）",
      lambda: all(q.get("why") for q in qs), True)
check("mode=quick", lambda: card2["data"]["mode"], "quick")

# ── [3] 翻牌制 ───────────────────────────────────────────────
print("\n[3] 默认值翻牌制")
f0 = qs[0]["field"]
s2.submit({f0: "确定", qs[1]["field"]: "按默认" if len(qs) > 1 else 1,
           qs[-1]["field"]: 42})
check("「确定」→ confirmed",
      lambda: s2.fields[f0]["origin"], "confirmed")
check("具体值 → confirmed", lambda: s2.fields[qs[-1]["field"]]["origin"],
      "confirmed")

# ── [4] 完整档轮次上限 + 无限挡域收敛 ────────────────────────
print("\n[4] full 档 / unlimited 域收敛")
s3 = IntakeSession(brief="复杂场景", mode="full")
for i in range(5):                                  # 超过 3 轮上限 → 记录超限
    s3.ask_round()
check("full 档轮次记录（上限纪律由调用方执行，会话只记录）",
      lambda: s3.round, 5)
s4 = IntakeSession(brief="无限挡", mode="unlimited")
s4.ask_round()
for d in DOMAIN_BANK:
    s4.domain_exhausted(d)                          # 连续两答"没有了"
    s4.domain_exhausted(d)
check("无限挡五域全部收敛", lambda: all(s4.domain_state[d] == "done"
                                        for d in DOMAIN_BANK), True)

# ── [5] freeze 三要素 + PRD 卡 ───────────────────────────────
print("\n[5] freeze")
fz = s2.freeze()
check("冻结标志", lambda: s2.frozen, True)
check("开工提示含三要素（结束声明+执行预告+中断权）",
      lambda: all(k in fz["kickoff"] for k in ("结束", "执行", "随时说")), True)
check("PRD 卡 intent", lambda: fz["prd"]["intent"], "做个马克杯")
frozen_again = s2.freeze()
check("重复冻结拒绝", lambda: frozen_again["ok"], False)

# ── [6] PRD → plan 骨架（一份两用）───────────────────────────
print("\n[6] PRD → plan 骨架")
sk = s2.to_plan_skeleton()
check("version=0.3", lambda: sk["version"], "0.3")
check("sections 含 part", lambda: all("part" in sec for sec in sk["sections"]), True)
check("sections 含 stage", lambda: all("stage" in sec for sec in sk["sections"]), True)
check("依赖链：depends_on 指向前段",
      lambda: all(sec.get("depends_on", [None])[0] is not None or i == 0
                  for i, sec in enumerate(sk["sections"])), True)
from plan_schema import PlanSchema  # noqa: E402
_schema_issues = [i for i in PlanSchema().validate(sk)
                  if i.level == "error" and i.code != "UNKNOWN_OP"]
check("骨架可过 plan_schema（结构合法）", lambda: _schema_issues, [])

# ── [7] 换档（升级跨档直达）─────────────────────────────────
print("\n[7] 换档")
s5 = IntakeSession(brief="x", mode="quick")
s5.set_mode("unlimited")
check("quick → unlimited 跨档直达", lambda: s5.mode, "unlimited")
try:
    s5.set_mode("nope")
    check("非法档位拒绝", lambda: False, True)
except ValueError:
    check("非法档位拒绝", lambda: True, True)

# ── plan_schema 联动校验 ─────────────────────────────────────
def _check_schema(skeleton):
    from plan_schema import PlanSchema
    issues = PlanSchema().validate(skeleton)
    errs = [i for i in issues if i.level == "error" and i.code != "UNKNOWN_OP"]
    return errs == []

failed = [r for r in ROWS if not r["ok"]]
print(f"\nM9-1B INTAKE UNIT: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
for f in failed:
    print("  FAILED:", f["case"], "->", f.get("detail"))
sys.exit(1 if failed else 0)
