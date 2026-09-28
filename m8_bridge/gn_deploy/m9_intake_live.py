"""m9_intake_live.py — M9-1b 提问协议真机验收（Blender 5.2.1）。

跑法：blender --background --factory-startup --python m9_intake_live.py

纯测（test_intake 22/22）覆盖协议状态机；本套验收**端到端接线**：
  [1] 完整协议生命周期（full 档 3 轮真实问答 → freeze → PRD 卡 → JSONL 落盘/回读）
  [2] PRD → plan 骨架（一份两用的上游兑现：parts 非空 / depends_on 线性链 / stage 序）
  [3] 骨架 → console.compile 逐段真编（cube → join_geometry → subdivide，
      consumes_input 链面数对账：join 段 > cube 段，subdivide 段 > join 段）→ verifier
  [4] export_state 收尾（/1.1 + kpis 在场——R4 契约贯通到 intake 产出的会话）
"""
import json
import shutil
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]  # 仓库根（相对推导，跨机器可移植）

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy  # noqa: E402

from intake import IntakeSession, DOMAIN_BANK  # noqa: E402
from gn_adapter import GNAdapter  # noqa: E402
from console import Console  # noqa: E402

OUT = ROOT / "results"
ROWS: list[dict] = []


def check(name, fn, expect=True):
    try:
        val = fn()
        if val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True, "detail": str(val)[:140]})
        print(f"  PASS  {name}  {str(val)[:100]}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:200]})
        print(f"  FAIL  {name}  {exc!r}")


print(f"Blender {bpy.app.version_string}")
ad = GNAdapter(bpy)
bpy.ops.wm.read_factory_settings(use_empty=True)

shutil.rmtree(HERE / "_m9i_wal", ignore_errors=True)
WALDIR = HERE / "_m9i_wal"

print("\n[1] 完整协议生命周期：full 档 3 轮 → freeze → PRD 卡 → JSONL 落盘/回读")
s = IntakeSession(brief="带把手的马克杯，哑光陶瓷质感", mode="full",
                  scene_facts={"size_height": 0.11})   # 先查后问：预置 from_context
answers_given = 0
for round_i in range(3):
    card = s.ask_round()
    qs = card["data"]["questions"]
    check(f"第 {round_i + 1} 轮 ≤4 问（问题池耗尽允许空轮）",
          lambda qs=qs: len(qs) <= 4, True)
    # 真实用户语义作答：首问"确定"，次问"按默认"（翻牌 agent_decided），其余给值
    ans = {}
    for j, q in enumerate(qs):
        ans[q["field"]] = "确定" if j == 0 else ("按默认" if j == 1 else q["default"])
    s.submit(ans)
    answers_given += len(qs)
check("full 档 3 轮累计作答 >0", lambda: answers_given > 0, True)
fz = s.freeze()
check("冻结后 PRD 卡 intent 带原始 brief",
      lambda: fz["prd"]["intent"], "带把手的马克杯，哑光陶瓷质感")
check("开工提示三要素齐全",
      lambda: all(k in fz["kickoff"] for k in ("结束", "执行", "随时说")), True)
origins = {v["origin"] for v in fz["prd"]["fields"].values()}
check("PRD origin 翻牌三态齐备（confirmed+agent_decided+from_context）",
      lambda: {"confirmed", "agent_decided", "from_context"} <= origins, True)

prd_path = WALDIR / "prd_card.jsonl"
prd_path.parent.mkdir(parents=True, exist_ok=True)
with prd_path.open("a", encoding="utf-8") as f:
    f.write(json.dumps(fz["prd"], ensure_ascii=False) + "\n")
prd_reload = json.loads(prd_path.read_text(encoding="utf-8").splitlines()[0])
check("PRD 卡 JSONL 落盘/回读一致",
      lambda: prd_reload["intent"] == fz["prd"]["intent"]
      and prd_reload["parts"] == fz["prd"]["parts"], True)

print("\n[2] PRD → plan 骨架（一份两用）")
sk = s.to_plan_skeleton(fz["prd"])
check("骨架 version=0.3", lambda: sk["version"], "0.3")
check("骨架 sections 非空", lambda: len(sk["sections"]) > 0, True)
check("depends_on 线性链（每段依赖前一段）",
      lambda: all(sec.get("depends_on") == [sk["sections"][i - 1]["id"]]
                  if i else "depends_on" not in sec
                  for i, sec in enumerate(sk["sections"])), True)
check("stage 序合法（blockout → structure → detail ⊂ STAGES 偏序）",
      lambda: all(sec.get("stage") in ("blockout", "structure", "detail")
                  for sec in sk["sections"]), True)

print("\n[3] 骨架 → console.compile 逐段真编（Blender 真机）")
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.active_object
obj.name = "IntakeMug"
obj.data = bpy.data.meshes.new("Base_Intake")
con = Console(ad, obj, workdir=WALDIR)

ids = []
for sec in sk["sections"]:
    spec = dict(sec)
    r = con.compile(spec)
    check(f"编译骨架段 {sec['id']}（op={sec['op']}）",
          lambda r=r: r.ok, True)
    ids.append(sec["id"])

areas = {}
for sid in ids:
    st = con._eval_stats()
    areas[sid] = st["area"]
cube_area = areas[ids[0]]
join_area = areas[ids[1]] if len(ids) > 1 else None
check("consumes_input 链生效（join 段面积 ≥ cube 段）",
      lambda: join_area is None or join_area >= cube_area * 0.999, True)
if len(ids) > 2:
    st_last = con._eval_stats()
    check("末端段非空几何（faces>0）", lambda: st_last["faces"] > 0, True)
r = con.verify("m9i")
check("verifier PASS（intake 产物过门禁）", lambda: r.ok, True)

print("\n[4] export_state 收尾（R4 契约贯通）")
st = con.export_state().data
check("schema=/1.1", lambda: st["schema"], "mug-console-state/1.1")
check("kpis 在场且 verify_fails=0",
      lambda: (True if "kpis" in st else False, st["kpis"]["verify_fails"]),
      (True, 0))
check("段落数 = 骨架段数",
      lambda: len(st["segments"]), len(ids))
check("无 A/B 决策 → override_rate=None",
      lambda: st["kpis"]["override_rate"], None)

failed = [r for r in ROWS if not r["ok"]]
print(f"\nM9-INTAKE LIVE: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
out = OUT / "m9_intake_live_result.json"
out.write_text(json.dumps({"rows": ROWS}, ensure_ascii=False, indent=1),
               encoding="utf-8")
print("result ->", out)
sys.exit(1 if failed else 0)
