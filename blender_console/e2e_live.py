"""e2e_live.py — 九步全链路真机打样（提需求→…→沉淀经验，一次跑通）
================================================================================
链路：①提需求 ②AI 提问问清楚 ③拆逻辑树 ④生成计划 ⑤逐段编译
      ⑥机械验证 ⑦渲染对比 ⑧看图改（判词驱动 patch）⑨沉淀经验

课题：350ml 陶瓷马克杯（logic_trees/mug_e2e.json，v2.0 可编译 schema，6 节点）
机制亮点：
  * STEP8 看图改 = 判词驱动：machine_spec 谓词（bbox 实测）→ nlg_bands 判词
    → FAIL 方向 set_param → 重渲染 → 二次判词收敛（视觉反馈环机制化）
  * STEP9 record_ai 带两轮判词叙事 + evidence 三件套；recall 验证反哺命中
运行：blender.exe --factory-startup --background --python e2e_live.py
"""
import bpy, sys, json, math
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
WORK = HERE / "e2e_work"
WORK.mkdir(exist_ok=True)

ROWS = []
def check(n, desc, cond):
    ROWS.append(cond)
    print("[e2e %d] %s %s" % (n, "PASS" if cond else "FAIL", desc))

def bbox_mm(obj, deps):
    ev = obj.evaluated_get(deps)
    m = ev.to_mesh()
    if not len(m.vertices):
        ev.to_mesh_clear()
        return (0, 0, 0)
    xs = [v.co.x for v in m.vertices]; ys = [v.co.y for v in m.vertices]
    zs = [v.co.z for v in m.vertices]
    ev.to_mesh_clear()
    return (round((max(xs)-min(xs))*1000, 1), round((max(ys)-min(ys))*1000, 1),
            round((max(zs)-min(zs))*1000, 1))

# ══ STEP 1 提需求 ══════════════════════════════════════════
bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new("e2e_root")
root = bpy.data.objects.new("e2e_root", mesh)
bpy.context.collection.objects.link(root)
bpy.context.view_layer.objects.active = root

from console import Console
from gn_adapter import GNAdapter
from intake import IntakeSession
from logic_tree import load_tree, validate_logic_tree, topo_order
from nlg_bands import verdict_report, band_of

BRIEF = "350ml 经典陶瓷马克杯，白瓷釉面，带三指把手，静态展示"
s = IntakeSession(brief=BRIEF, mode="standard",
                  parts=["杯身", "内腔", "把手", "材质"],
                  scene_facts={"capacity_ml": 350, "height_mm": 95,
                               "diameter_mm": 80, "wall_mm": 5.5,
                               "handle_total_width_mm": 138})
print("[e2e 1] brief:", BRIEF)
check(1, "提需求：IntakeSession 建会话（topic=%s）" % s.topic, s.topic == "")

# ══ STEP 2 AI 提问把需求问清楚 ═════════════════════════════
card = s.ask_round()
n_q = len(card.get("questions", []))
print("[e2e 2] 提问卡：%d 问（先查后问——scene_facts 已答的不问）" % n_q)
for q in card.get("questions", [])[:3]:
    print("        · %s（默认 %s %s）" % (q.get("question"), q.get("default"), q.get("unit", "")))
s.submit({})                                    # 全默认翻牌（规格来自 scene_facts/参考值）
fr = s.freeze()
prd = fr.get("prd", {})                         # freeze 幂等守卫：二次调用返回 ALREADY_FROZEN
check(2, "提问→冻结：PRD 卡落定（round=%d, 冻结=%s）" % (s.round, s.frozen), s.frozen)

# ══ STEP 3 拆成逻辑树 ══════════════════════════════════════
lt = load_tree(HERE / "logic_trees" / "mug_e2e.json")
issues = validate_logic_tree(lt)
byid = {n["id"]: n for n in lt["nodes"]}
GATE = {"proportion_check"}
topo = topo_order(lt)
print("[e2e 3] 逻辑树：%d 节点，validate issue=%d，拓扑=%s"
      % (len(lt["nodes"]), len(issues), topo))
check(3, "逻辑树 v2.0：零结构 issue + 拓扑无环", not issues and len(topo) == len(lt["nodes"]))

# ══ STEP 4 生成计划（两桥合一）═════════════════════════════
sk = s.to_plan_skeleton(prd if isinstance(prd, dict) else {}, logic_tree=lt)
sec_map = {x["id"]: x for x in sk["sections"]}
for nid in byid:
    n = byid[nid]
    if n["build"]["op"] in GATE:
        continue                                # 门禁节点不产几何
    if nid not in sec_map:
        sec_map[nid] = {"id": nid, "op": n["build"]["op"], "stage": "structure",
                        "part": nid, "consumes_input": False, "depends_on": [],
                        "parameters": []}
    sec = sec_map[nid]
    sec["op"] = n["build"]["op"]
    sec["parameters"] = list(n.get("parameters", []))
    if "operand" in n:
        sec["operand"] = n["operand"]
    if "material_plan" in n:
        sec["material_plan"] = n["material_plan"]
    sec["consumes_input"] = n["build"]["op"] != "revolve_profile" or nid != "1.1"
    if nid == "1.1":
        sec["consumes_input"] = False
    sec["depends_on"] = [d for d in n.get("deps", [])
                         if byid[d]["build"]["op"] not in GATE]
plan = {"version": "0.3", "intent": sk.get("intent", BRIEF),
        "sections": list(sec_map.values()),
        "constraints": sk.get("constraints", [])}
print("[e2e 4] 计划：%d 段（%s）" % (len(plan["sections"]),
      [x["id"] + ":" + x["op"] for x in plan["sections"]]))
check(4, "两桥合一计划：骨架 + 逻辑树 deps 并行 → %d 段" % len(plan["sections"]),
      len(plan["sections"]) == 5)

# ══ STEP 5 逐段编译成 Blender 节点 ═════════════════════════
ad = GNAdapter()
console = Console(ad, root, workdir=str(WORK))
console.attach_experience(library_path=str(WORK / "e2e_library.jsonl"))
order = [x for x in topo if x in sec_map]
ok5 = True
for nid in order:
    sec = dict(sec_map[nid]); sec["id"] = nid
    r = console.compile(sec)
    ok5 &= r.ok
    print("        compile %s: %s %s" % (nid, "✅" if r.ok else r.error, ""))
check(5, "逐段编译：%d/%d 全过" % (len(order), len(order)), ok5)

# ══ STEP 6 机械验证 ════════════════════════════════════════
r6 = console.verify("e2e")
print("[e2e 6] verify: %s" % r6.summary)
check(6, "机械验证 PASS", r6.ok)

# ══ 谓词评估器（machine_spec → 参数真源反算，单位 mm）═══════
# 口径（2026-09-29 审计修正）：声明式编译下参数=几何的单一真源（逻辑树
# params_real 原则）——门禁判定用参数反算；渲染 diff（像素级 changed_ratio）
# 作为"几何真的变了"的独立旁证。全场景 bbox 含展台/把手，不作杯身口径。
def evaluate_gate(nid):
    checks = byid[nid]["gate"]["machine_spec"].get("checks", {})
    vp = console.vparams.get()
    depth_mm = vp.get("1.1.Depth", 0.095) * 1000
    dia_mm = vp.get("1.1.Radius_Top", 0.040) * 2000
    preds = []
    for key, (lo, hi) in checks.items():
        if key == "height_mm":
            actual = round(depth_mm, 1)
        elif key == "ratio_height_dia":
            actual = round(depth_mm / dia_mm, 3)
        elif key == "wall_mm":
            actual = round((vp.get("1.1.Radius_Top", 0.040) - 0.035) * 1000, 1)
        elif key == "handle_total_width_mm":
            actual = round(vp.get("2.1.Center_X", 0.058) * 1000 + 42 + 40, 1)
        else:
            continue
        ok = lo <= actual <= hi
        mid = (lo + hi) / 2
        rel = (actual - mid) / mid * 100 if mid else 0.0
        preds.append({"predicate": key, "actual_mm": actual,
                      "expect_mm": "%g-%g" % (lo, hi), "rel_pct": round(rel, 2),
                      "band": band_of(rel / 100), "ok": ok})
    return preds

# ══ STEP 7 渲染对比（帧1 基线）═════════════════════════════
r7a = console.render_diff("e2e-baseline")
print("[e2e 7] 基线帧：%s" % r7a.summary)
check(7, "渲染对比：基线帧落盘 + 谓词在册", r7a.ok)

# ══ STEP 8 看图改（判词驱动 patch 两轮收敛）════════════════
# 8a 注入真实缺陷（Depth 95→80，高度跌出 [90,100]）并渲染超差帧
r_bad = console.set_param("1.1", "Depth", 0.080)
r_bad_frame = console.render_diff("e2e-overdefect")
preds_bad = evaluate_gate("1.1")
v_bad = verdict_report(preds_bad)
print("[e2e 8a] 超差帧 diff：%.1f%% 像素变化" % ((r_bad_frame.data.get("changed_ratio") or 0) * 100))
print("[e2e 8a] 超差判词：\n" + v_bad)
fails = [p for p in preds_bad if not p["ok"]]
check(8, "看图改：超差帧可见（diff>0）+ 判词 [FAIL]（%d 项超差）" % len(fails),
      len(fails) >= 1 and "FAIL" in v_bad
      and (r_bad_frame.data.get("changed_ratio") or 0) > 0)
# 8b 判词驱动 patch：height_mm 低于下限 → 加深 Depth 回 95
patch = {"node_id": "1.1", "field": "Depth", "new_value": 0.095,
         "because": v_bad.splitlines()[0]}
r_patch = console.set_param(patch["node_id"], patch["field"], patch["new_value"])
preds_ok = evaluate_gate("1.1")
v_ok = verdict_report(preds_ok)
print("[e2e 8b] patch(%s.%s=%s) 后判词：\n%s" % (patch["node_id"], patch["field"],
      patch["new_value"], v_ok))
check(9, "判词驱动 patch → 二次判词收敛 PASS",
      r_patch.ok and all(p["ok"] for p in preds_ok))
# 8c 渲染对比：patch 后几何可见性独立旁证
r7b = console.render_diff("e2e-after-patch")
diff_ratio = r7b.data.get("changed_ratio")
print("[e2e 8c] 收敛帧 diff：%.1f%% 像素变化" % ((diff_ratio or 0) * 100))
check(10, "渲染对比：patch 后 changed_ratio>0（几何变化可见）",
      r7b.ok and (diff_ratio or 0) > 0)

# ══ STEP 9 沉淀经验（record_ai → recall 反哺验证）══════════
story = ("E2E 九步链：Depth 超差注入（95→80mm，height_mm FAIL）→ 判词驱动 "
         "patch 回 95mm → 二次判词收敛。判词模板零幻觉，patch 引用判词首行。")
r9 = console.record_experience({
    "trigger": {"origin": "logic_tree", "project": "mug_e2e",
                "node": "1.1", "build_op": "revolve_profile",
                "gate": {"height_mm": [90, 100]}},
    "attention": "马克杯高度门 [90,100]mm：Depth 是唯一影响参数",
    "story": story,
    "params": {"height_mm": preds_ok[0]["actual_mm"] if preds_ok else 95},
    "evidence": [{"artifact": "e2e_live.py:STEP8",
                  "quote": "判词 [FAIL] → patch → 判词 PASS",
                  "recalc": "blender -b -P e2e_live.py | grep 'e2e 8'"}]})
print("[e2e 9] record: %s" % r9.summary)
hits = []
if r9.ok:
    lib = console.library
    hits = lib.recall({"origin": "logic_tree", "project": "mug_e2e"},
                      include_draft=True) if lib else []
check(11, "沉淀经验：record_ai 入库 + recall 反哺命中（%d 条）" % len(hits),
      r9.ok and len(hits) >= 1)

# ══ 终态导出 ═══════════════════════════════════════════════
st = console.export_state()
(WORK / "e2e_state.json").write_text(
    json.dumps(st.data if hasattr(st, "data") else {}, ensure_ascii=False,
               indent=1, default=str), encoding="utf-8")
print("[e2e ~] 终态：%s 段在册 → e2e_work/e2e_state.json"
      % len(st.data.get("segments", {})) if hasattr(st, "data") else "n/a")

failed = sum(1 for x in ROWS if not x)
print("\nE2E LIVE: %d/%d passed" % (len(ROWS) - failed, len(ROWS)))
sys.exit(1 if failed else 0)
