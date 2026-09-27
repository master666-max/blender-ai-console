"""gn_session_live.py — M1 集成层的真机验收（Blender 5.2.1）。

跑法：blender --background --factory-startup --python gn_session_live.py

B1 纪律：**每个 check 都带 expect（或 expect_raise）**——返回值不匹配即 FAIL，
不允许任何 vacuous assertion（返回 False 也记 PASS 的洞）。

验收项（对应工单 M1-1/2/3/4/6/7 + A16/A28/A29/A33 + B2/B3 + M4-9）：
  1. 三段编译 → FlowDAG 3 步、依赖链正确、gn_delta 初始记录
  2. WAL 哈希链 verify + 事件数
  3. steps_for_object / steps_for_thought（A2 区域反查）
  4. set_param → 置脏传播（S2 改 → S2/S3 脏，S1 净）→ 同值再 touch → 零失效
  5. backdating：report_output 输出未变 → False（级联截断）
  6. gn_delta：重编译段 → 新旧树 diff 非空（A16/A33）
  7. GoodPoint checkpoint → 参数回滚 → 几何回到锚点（A19：几何量断言）
  8. override 埋点 + pivot 拒绝回退（A29）
  9. 依赖不存在 → 响亮失败（A1 集成路径）
 10. B3 回归：重编译后 modifier 栈序不变
 11. M2 门禁：M2-7 区域局部性（改把手只动把手 + 谎报拦截，M4-9 归属驱动）+ A24 物体数 + B2 对照
 12. M4-9：named attribute 段落归属（first-creator-wins，100% 归属）
 13. export_state → mug-console-state/1（喂 M9-4b 页面，含 attribution 映射）
"""
import copy
import json
import shutil
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]  # 仓库根（相对推导，跨机器可移植）
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy

from gn_adapter import GNAdapter, ParamSpec  # noqa: E402
from gn_console import SPECS  # noqa: E402  复用已验证的三个段落构建器
from gn_session import GNSession, PivotBlocked  # noqa: E402

ROWS: list[dict] = []


def check(name: str, fn, expect: Any = None):
    """断言式 check：expect 必填语义——expect=None 仅用于"能跑不抛错"的冒烟。"""
    try:
        val = fn()
        if expect is not None and val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True, "detail": str(val)[:160]})
        print(f"  PASS  {name}  {val}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:200]})
        print(f"  FAIL  {name}  {exc!r}")


def expect_raise(name: str, exc_type, fn):
    try:
        fn()
    except exc_type as exc:
        ROWS.append({"case": name, "ok": True, "detail": f"正确拒绝：{str(exc)[:110]}"})
        print(f"  PASS  {name}  正确拒绝：{str(exc)[:100]}")
        return
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": f"抛了错误类型 {exc!r}"})
        print(f"  FAIL  {name}  抛了错误类型 {exc!r}")
        return
    ROWS.append({"case": name, "ok": False, "detail": "本应抛错但没有"})
    print(f"  FAIL  {name}  本应抛错但没有")


def main() -> None:
    print(f"Blender {bpy.app.version_string}")
    ad = GNAdapter(bpy)
    # A2 区域键：把手段落标记为影响 Handle（SPECS 默认全是 Mug）
    SPECS[1].obj = "Handle"
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.active_object
    obj.name = "Mug"
    obj.data = bpy.data.meshes.new("Mug_Base")     # 几何完全由 GN 生成

    # WAL 只属本回合：跨回合累积会让"gn_delta 初始记录 ×3"等全量回放断言翻倍
    shutil.rmtree(HERE / "_session_wal", ignore_errors=True)
    ses = GNSession(ad, obj, workdir=HERE / "_session_wal")
    ses.add_thought("T1", "把手粗 7mm 握感舒适",
                    {"segment": "S2_把手", "param": "Handle_Thickness"})
    ses.add_thought("T2", "细分 2 级足够圆滑",
                    {"segment": "S3_收尾", "param": "Subdiv_Level"})

    # ── 1. 三段编译（spec 路线）──────────────────────────────
    print("\n[1] 编译三段")
    for spec in SPECS:
        t0 = time.perf_counter()
        ses.compile_segment(spec)
        print(f"  compile {spec.name}  {(time.perf_counter()-t0)*1000:.1f} ms")
    check("段落注册数 = 3", lambda: len(ses.segments), 3)
    check("DAG 步数 = 3", lambda: len(ses.dag), 3)
    check("拓扑序 3 步", lambda: len(ses.dag.topo_order()), 3)
    check("拓扑序末位 = S3", lambda: ses.dag.topo_order()[-1], "step:S3_收尾")
    check("WAL 哈希链 verify", lambda: ses.wal.verify(), True)
    check("gn_delta 初始记录 ×3",
          lambda: sum(1 for r in ses.wal.replay()
                      if r["kind"] == "compile" and r["payload"]["gn_delta"].get("initial")), 3)

    # ── 2. 区域反查（A2）────────────────────────────────────
    print("\n[2] 区域反查")
    check("steps_for_object('Handle') → S2",
          lambda: [s.step_id for s in ses.dag.steps_for_object("Handle")],
          ["step:S2_把手"])
    check("steps_for_thought('T1') → S2",
          lambda: [s.step_id for s in ses.dag.steps_for_thought("T1")],
          ["step:S2_把手"])

    # ── 3. 求值 + verifier ──────────────────────────────────
    print("\n[3] 求值 + 机械 verifier")
    st0 = ses.evaluate()
    check("初始几何非空（面>0 面积>0）",
          lambda: st0["faces"] > 0 and st0["area"] > 0, True)
    v0 = ses.verify("初始")
    check("verifier 初始 PASS", lambda: v0["ok"], True)

    # ── 4. 置脏传播（A28）───────────────────────────────────
    print("\n[4] 置脏传播")
    d = ses.set_param("S2_把手", "Handle_Thickness", 0.007)
    check("改 S2 → S2/S3 脏、S1 净（内容断言）",
          lambda: d["dirty"] == ["S2_把手", "S3_收尾"] and "S1_杯体" not in d["dirty"], True)
    st = ses.evaluate()
    changed = ses.report_output("S2_把手", ses.output_fingerprint(st))
    check("report_output 首次 = True", lambda: changed, True)
    ses.report_output("S3_收尾", ses.output_fingerprint(st))

    # 同值再 touch → 零失效（同值赋值不传播）
    d2 = ses.set_param("S2_把手", "Handle_Thickness", 0.007)
    check("同值再写 → 零失效", lambda: d2["dirty"], [])

    # ── 5. backdating（A28 核心）────────────────────────────
    print("\n[5] backdating：输出未变 → 级联截断")
    st_before = ses.evaluate()
    fp_before = ses.output_fingerprint(st_before)
    ses.table.touch("S2_把手", "fp_same")     # 参数指纹变化（假 redesign）
    ses.set_param("S2_把手", "Handle_Thickness", 0.007)   # 但值回到相同 → fp 同
    st_after = ses.evaluate()
    fp_after = ses.output_fingerprint(st_after)
    check("几何未变（指纹一致）", lambda: fp_before == fp_after, True)
    changed = ses.report_output("S2_把手", fp_after)
    check("backdating：输出未变 → False（截断）", lambda: changed, False)

    # ── 6. gn_delta（A16/A33）+ B3 回归（栈序）──────────────
    print("\n[6] 重编译 S2 → gn_delta + B3 栈序")
    spec2 = copy.deepcopy(SPECS[1])
    spec2.params.append(ParamSpec("Handle_Fillet", "FLOAT", 0.002, 0.0, 0.02, "m"))
    delta = ses.recompile_segment("S2_把手", spec2)
    check("gn_delta 非空（接口差异检出）", lambda: len(json.dumps(delta)) > 2, True)
    check("diff 报告 params_added", lambda: bool(delta.get("params_added")), True)
    # B3 回归：重编译后 modifier 栈序必须与段落顺序一致
    check("B3 栈序恢复 = [S1, S2, S3]",
          lambda: [m.name for m in ses.obj.modifiers], ["S1_杯体", "S2_把手", "S3_收尾"])

    # ── 7. GoodPoint + 参数回滚（L2，几何量断言 A19）────────
    print("\n[7] GoodPoint checkpoint + 参数回滚")
    ms = ses.checkpoint("GP1", ("T1", "T2"))
    st_cp = ses.evaluate()
    faces_cp, area_cp = st_cp["faces"], st_cp["area"]
    check("checkpoint 有耗时记录", lambda: ms >= 0, True)
    ses.set_param("S3_收尾", "Subdiv_Level", 3)
    st_mut = ses.evaluate()
    check("改 S3 后面数确实变化", lambda: st_mut["faces"] != faces_cp, True)
    ms_r = ses.revert_to_checkpoint("GP1")
    st_re = ses.evaluate()
    check("参数回滚 → 面数回到锚点", lambda: st_re["faces"], faces_cp)
    check("参数回滚 → 面积回到锚点（1e-9）",
          lambda: abs(st_re["area"] - area_cp) < 1e-9, True)

    # ── 8. override + pivot（A29）───────────────────────────
    print("\n[8] override 埋点 + pivot 纪律")
    ses.override("把手回退一轮")
    check("override 计数 ≥1", lambda: ses.overrides >= 1, True)
    ses.log_pivot("导出 glb（模拟）")
    expect_raise("pivot 后拒绝 revert", PivotBlocked,
                 lambda: ses.revert_to_checkpoint("GP1"))

    # ── 9. 依赖不存在 → 响亮失败（A1 集成路径）──────────────
    print("\n[9] 依赖不存在 → 响亮失败")
    class _BadSpec:
        name = "S9_幽灵"
        params: list = []
        build = lambda *a, **k: None      # noqa: E731
        consumes_input = False
        thought_refs: tuple = ()
        obj = "Mug"
    ses.set_deps("S9_幽灵", ("不存在的段",))
    expect_raise("依赖缺失被拒", ValueError, lambda: ses.compile_segment(_BadSpec()))

    # ── 11. M2 门禁：区域局部性（M4-9 驱动）+ A24 + B2 对照 ──
    print("\n[11] M2 门禁（M2-7 区域局部性，M4-9 归属驱动）")
    st_b = ses.evaluate()
    # (a) "改把手只动把手"：非把手面必须零移动（M2-7，语义正确形态）
    reg_before = ses.snapshot_region(upto_seg="S2_把手")
    ses.set_param("S2_把手", "Handle_Thickness", 0.006)
    tr = ses.verify_region_locality("把手变细", reg_before, "S2_把手",
                                    upto_seg="S2_把手")
    check("M2-7 改把手：非把手面零移动", lambda: tr["moved_out"], 0)
    check("M2-7 改把手：门禁放行", lambda: tr["gate"], True)
    # (b) 反例：动了杯体却谎称只改把手 → 门禁必须咬住
    reg_before2 = ses.snapshot_region(upto_seg="S2_把手")
    ses.set_param("S1_杯体", "Body_Radius", 0.041)
    tr_bad = ses.verify_region_locality("谎称只改把手", reg_before2, "S2_把手",
                                        upto_seg="S2_把手")
    check("M2-7 谎报改动段：门禁拦截", lambda: tr_bad["gate"], False)
    check("M2-7 谎报改动段：杯体面被检出移动", lambda: tr_bad["moved_out"] > 0, True)
    ses.set_param("S1_杯体", "Body_Radius", 0.040)   # 还原杯体
    # (c) A9 + B2 对照：坐标集局部性（段级 vs 全栈，下游平滑稀释被证实）
    before_seg = ses.snapshot_coords(upto_seg="S2_把手")
    before_full = ses.snapshot_coords()
    ses.set_param("S2_把手", "Handle_Thickness", 0.005)
    tr_seg = ses.verify_transition("段级对照", before_seg, st_b["faces"],
                                   upto_seg="S2_把手")
    tr_full = ses.verify_transition("全栈对照", before_full, st_b["faces"])
    check("A9 改/加比已记录", lambda: tr_seg["edit_add_ratio"] > 0, True)
    check("B2 对照：全栈 moved > 段级 moved（下游平滑稀释被证实）",
          lambda: tr_full["moved"] > tr_seg["moved"], True)
    ses.set_param("S2_把手", "Handle_Thickness", 0.007)   # 还原把手粗细
    # (d) A24 反例：多出无关物体
    bpy.ops.mesh.primitive_cube_add(location=(3, 3, 3))
    tr2 = ses.verify_transition("多余物体", before_full, st_b["faces"])
    check("A24 物体数不一致被检出", lambda: tr2["objects_ok"], False)
    for o in list(ses.ad.bpy.data.objects):
        if o.name.startswith("Cube"):
            ses.ad.bpy.data.objects.remove(o, do_unlink=True)
    tr3 = ses.verify_transition("移除后", before_full, st_b["faces"])
    check("A24 移除后恢复一致", lambda: tr3["objects_ok"], True)

    # ── 12. M4-9：段落归属（first-creator-wins）─────────────
    print("\n[12] M4-9 named attribute 段落归属")
    check("归属图 3 项", lambda: len(ses.attribution), 3)
    check("归属索引从 1 起", lambda: sorted(ses.attribution), [1, 2, 3])
    q = ses.query_attribution()
    check("全部面都有归属（unattributed=0）", lambda: q["unattributed"], 0)
    check("归属面数总和 = 总面数",
          lambda: sum(q["by_segment"].values()), q["total"])
    check("杯体面来自 S1（归属>0）", lambda: q["by_segment"].get("S1_杯体", 0) > 0, True)
    check("把手面来自 S2（归属>0）", lambda: q["by_segment"].get("S2_把手", 0) > 0, True)
    # B3 修复后重编译段沿用原索引：S2 归属仍在
    check("重编译后 S2 归属保留", lambda: q["by_segment"].get("S2_把手", 0) > 0, True)

    # ── 10. export_state（M9-4a）────────────────────────────
    print("\n[10] export_state → Web 契约")
    st = ses.export_state()
    out = ROOT.parent / "2026-09-26-blender" / "gn_session_state.json"
    out.write_text(json.dumps(st, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    check("schema = mug-console-state/1.1", lambda: st["schema"], "mug-console-state/1.1")
    check("kpis 在场（M10-4）", lambda: "kpis" in st, True)
    check("steps ≥3", lambda: len(st["steps"]) >= 3, True)
    check("thoughts = 2", lambda: len(st.get("thoughts", [])), 2)
    check("overrides ≥1", lambda: (st.get("overrides") or 0) >= 1, True)
    check("attribution 映射 3 项", lambda: len(st.get("attribution", {})), 3)
    check("WAL 终局 verify", lambda: ses.wal.verify(), True)

    failed = [r for r in ROWS if not r["ok"]]
    print(f"\nGN-SESSION LIVE: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
    for f in failed:
        print("  FAILED:", f["case"], "->", f["detail"])
    out2 = ROOT.parent / "2026-09-26-blender" / "gn_session_live_result.json"
    out2.write_text(json.dumps(ROWS, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("result ->", out2)


if __name__ == "__main__":
    main()
