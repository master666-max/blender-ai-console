"""m5_spec_live.py — R3 · M5 spec 级 A/B 真机验收（Blender 5.2.1）。

跑法：blender --background --factory-startup --python m5_spec_live.py

工单验收（R3）：
  结构变体 A/B 全协议真机过——洗牌 / 封存 / 预览不落账 / reroll /
  override 计数 / 通路分离 / commit 真写走 recompile 全链。
附加（项目纪律）：spec 级 commit 不喂 PreferenceModel（BT 权重空间是参数值，
  结构变体塞进去会污染——诚实分流）；反例（坏变体/重复开卡/无卡提交/置信度越界）。
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

OUT = ROOT / "results"
ROWS: list[dict] = []


def check(name, fn, expect=None):
    try:
        val = fn()
        if expect is not None and val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True, "detail": str(val)[:140]})
        print(f"  PASS  {name}  {str(val)[:100]}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:200]})
        print(f"  FAIL  {name}  {exc!r}")


print(f"Blender {bpy.app.version_string}")
ad = GNAdapter(bpy)
bpy.ops.wm.read_factory_settings(use_empty=True)

BODY = {"id": "body", "op": "cylinder", "consumes_input": False,
        "parameters": [
            {"name": "Radius", "type": "FLOAT", "value": 0.04, "min": 0.02, "max": 0.12},
            {"name": "Depth", "type": "FLOAT", "value": 0.095, "min": 0.05, "max": 0.3}]}
VAR_A = {"op": "cube", "consumes_input": False,          # 结构变体甲候选：立方
         "parameters": [{"name": "Size", "type": "FLOAT", "value": 0.09,
                         "min": 0.02, "max": 0.12}]}
VAR_B = {"op": "sphere", "consumes_input": False,         # 结构变体乙候选：球
         "parameters": [{"name": "Radius", "type": "FLOAT", "value": 0.06,
                         "min": 0.02, "max": 0.12}]}
# ⚠️ VAR_B 必须与 body（cylinder）异构：若变体与原段落同 op，recompile 的
# 参数重放会把账面值全部回填 → 几何保恒是正确行为，"几何确实变了" 无从断言。

shutil.rmtree(HERE / "_m5s_wal", ignore_errors=True)

bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.active_object
obj.name = "MugSpecAB"
obj.data = bpy.data.meshes.new("Base_SpecAB")
con = Console(ad, obj, workdir=HERE / "_m5s_wal")
con.attach_experience()                                   # 激活 M6 库（回写 + 偏好分流验证）

r = con.compile(dict(BODY))
check("编译 body", lambda: r.ok, True)
con.set_param("body", "Radius", 0.045)                    # 用户已写参数（还原保真验证）
st_orig = con._eval_stats()
vp_before = dict(con.vparams.get())
wal_lines = lambda: (HERE / "_m5s_wal" / "events.jsonl").read_text(
    encoding="utf-8").splitlines()
n_param_events = lambda: sum(1 for x in wal_lines() if '"kind": "param"' in x)
n_setup = n_param_events()                                # setup 期 set_param 已 1 条
n_before = n_setup                                        # prepare 前基准（delta 断言用）

print("\n[1] spec A/B prepare：双变体现编 + 树上换预览 + 还原")
r = con.ab_prepare_spec("body", [VAR_A, VAR_B], ai_preferred=0,
                        ai_reason="方块更马克杯")
print(f"  prepare  {'ok' if r.ok else f'FAIL {r.error}'}")
check("prepare ok", lambda: r.ok, True)
check("卡片 kind=spec", lambda: r.data.get("kind"), "spec")
check("甲乙两帧都在", lambda: sorted(r.data["variants"]), ["乙", "甲"])
dhashes = {lab: v["dhash"] for lab, v in r.data["variants"].items()}
check("两结构预览帧确实不同", lambda: dhashes["甲"] != dhashes["乙"], True)
check("映射封存（返回里无 ai_preferred）",
      lambda: "ai_preferred" in json.dumps(r.data), False)
check("预览不落账（vparams 未增键）",
      lambda: set(con.vparams.get()) == set(vp_before), True)
check("预览不落账（WAL param 事件零新增）",
      lambda: n_param_events() - n_before, 0)
st_after = con._eval_stats()
check("原树已还原（几何回到 prepare 前）",
      lambda: (st_after["faces"], round(st_after["area"], 6)),
      (st_orig["faces"], round(st_orig["area"], 6)))
prep_ev = [json.loads(x) for x in wal_lines() if '"ab_prepare"' in x]
check("WAL 有 kind=spec 的 ab_prepare（映射在账不在返回）",
      lambda: prep_ev and prep_ev[-1]["payload"]["kind"], "spec")
con.render_diff("m5s_base")                               # 打 diff 基线帧（首帧 = baseline）

print("\n[2] commit 非偏好变体：recompile 真写 + override 计数 + 偏好分流")
mapping = prep_ev[-1]["payload"]["mapping"]               # {"0": 甲/乙, ...}
non_pref_label = next(lab for k, lab in mapping.items()
                      if lab != prep_ev[-1]["payload"]["ai_preferred_label"])
non_pref_idx = int(next(k for k, lab in mapping.items() if lab == non_pref_label))
chosen_spec = (VAR_A, VAR_B)[non_pref_idx]
n_overrides_before = con.overrides
r = con.ab_commit(non_pref_label, 70, note="人觉得圆柱更顺眼")
print(f"  commit {non_pref_label}  {'ok' if r.ok else f'FAIL {r.error}'}")
check("commit ok", lambda: r.ok, True)
check("reveal 揭晓映射", lambda: r.data["reveal"]["mapping"] is not None, True)
check("applied 是选中结构 spec",
      lambda: r.data["applied"].get("op"), chosen_spec["op"])
check("真写生效（段落 spec 已换）",
      lambda: con.segments["body"]["spec"].get("op"), chosen_spec["op"])
st_new = con._eval_stats()
check("几何确实变了（结构替换非参数微调）",
      lambda: round(st_new["area"], 6) != round(st_orig["area"], 6), True)
check("override 已计数（人选了非 AI 偏好）",
      lambda: r.data["override_counted"], True)
check("override 计数器 +1", lambda: con.overrides, n_overrides_before + 1)
check("spec 级不喂 PreferenceModel（pref.n==0）", lambda: con.pref.n, 0)
check("library 记录 override 回写",
      lambda: len(con.library.entries) >= 1, True)
rd = con.render_diff("m5s_committed")
check("commit 后渲染 diff 出图（>0）",
      lambda: rd.data["changed_ratio"] is not None
      and rd.data["changed_ratio"] > 0, True)

print("\n[3] reroll 路：预览后重掷，几何零残留")
st_before_reroll = con._eval_stats()
r = con.ab_prepare_spec("body", [VAR_A, VAR_B], ai_preferred=0)
check("第二张卡 prepare ok", lambda: r.ok, True)
r = con.ab_commit("reroll", 40)
check("reroll ok", lambda: r.ok, True)
check("reroll 不计 override", lambda: r.data["override_counted"], False)
st_reroll = con._eval_stats()
check("reroll 几何零残留（回到 commit 后状态）",
      lambda: (st_reroll["faces"], round(st_reroll["area"], 6)),
      (st_before_reroll["faces"], round(st_before_reroll["area"], 6)))
r = con.ab_prepare_spec("body", [VAR_A, VAR_B], ai_preferred=0)
check("卡已清（可开下一张）", lambda: r.ok, True)
con.ab_commit("reroll", 30)                               # 收尾清卡

print("\n[4] 反例（响亮失败，M4-8 结构化）")
r = con.ab_prepare_spec("ghost", [VAR_A, VAR_B])
check("不存在段落 → SEG_NOT_FOUND",
      lambda: (r.error or {}).get("error_code"), "SEG_NOT_FOUND")
r = con.ab_prepare_spec("body", [VAR_A])
check("单变体 → BAD_VARIANTS",
      lambda: (r.error or {}).get("error_code"), "BAD_VARIANTS")
r = con.ab_prepare_spec("body", [{"op": "sdf_smooth"}, VAR_B])
check("坏变体编译失败 → VARIANT_0_BUILD_FAIL",
      lambda: (r.error or {}).get("error_code"), "VARIANT_0_BUILD_FAIL")
check("坏变体后无残留卡（可再开）",
      lambda: con.ab_prepare_spec("body", [VAR_A, VAR_B]).ok, True)
r = con.ab_commit("甲", 200)
check("置信度越界 → CONFIDENCE_OUT_OF_RANGE",
      lambda: (r.error or {}).get("error_code"), "CONFIDENCE_OUT_OF_RANGE")
con.ab_commit("reroll", 30)                               # 清卡
r = con.ab_commit("甲", 50)
check("无卡提交 → NO_AB_PENDING",
      lambda: (r.error or {}).get("error_code"), "NO_AB_PENDING")

print("\n[5] 收尾：verifier + 参数级通路完好（set_param 仍工作）")
check("verifier PASS", lambda: con.verify("m5s").ok, True)
r = con.set_param("body", next(iter(con.segments["body"]["sid"])), 0.05)
check("参数级通路仍工作（新结构参数可写）", lambda: r.ok, True)
check("WAL param 事件在 prepare 基准之上有新增",
      lambda: n_param_events() > n_before, True)
kpis = con.export_state().data["kpis"]                    # M10-4：KPI 数链真机正例
check("KPI override 率（1 override / 4 次决策）",
      lambda: (kpis["override_rate"], kpis["overrides"], kpis["ab_decisions"]),
      (0.25, 1, 4))
check("KPI 曲线末点 = 0.25（4 采样点）",
      lambda: (len(kpis["override_curve"]),
               kpis["override_curve"][-1]["rate"]), (4, 0.25))
check("KPI verify_fails=0（本套全过门禁）",
      lambda: kpis["verify_fails"], 0)

failed = [r for r in ROWS if not r["ok"]]
print(f"\nM5-SPEC LIVE: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
out = OUT / "m5_spec_result.json"
out.write_text(json.dumps({"rows": ROWS}, ensure_ascii=False, indent=1),
               encoding="utf-8")
print("result ->", out)
sys.exit(1 if failed else 0)
