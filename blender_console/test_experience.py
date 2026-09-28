"""test_experience.py — M6 经验库核心单元测试（纯 Python，无 bpy，秒级）。

跑法：python test_experience.py
覆盖：M6-2 条目契约往返 / 降权 / recall D9 禁 top-1 /
      M6-1 bin_features+iou+select_diverse（MMR）/ M6-6 BT 学习收敛+收缩+冷启动+可解释。
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from experience import (ExperienceEntry, ExperienceLibrary, ExperienceStore,
                        PreferenceModel, bin_features, iou, select_diverse)

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


tmp = Path(tempfile.mkdtemp(prefix="m6_test_"))
try:
    # ── [1] 条目契约（M6-2/M6-5 + M6-2b 治理字段）───────────────
    print("[1] 条目契约")
    EV = [{"artifact": "test_experience.py", "quote": "JSONL 往返一致",
           "recalc": "python test_experience.py"}]
    lib = ExperienceLibrary(tmp / "lib.jsonl")
    e1 = ExperienceEntry(
        trigger={"param": "Handle_Thickness", "scene": "mug"},
        attention="看环与杯壁的相贯线——警惕零厚度搭接",
        story="把手环半径 0.032 时相贯线沉进壁里，视觉上像贴纸；抬到 0.045 出现双线",
        params={"Handle_Thickness": 0.008, "Ring_Radius": 0.032},
        outcome="verified_success", status="verified", evidence=EV)
    eid1 = lib.add(e1, author="human:otto", source="session-2026-09-27")
    e2 = ExperienceEntry(
        trigger={"param": "Handle_Thickness", "scene": "mug"},
        attention="杯口椭圆度随壁厚反向变化",
        story="verify_fail 一次：壁厚 0.02 时杯口在 render 里变椭圆——subdiv 前 mirror 翻面没做",
        params={"Handle_Thickness": 0.02},
        outcome="verified_failure", status="verified", evidence=EV)
    eid2 = lib.add(e2, author="human:otto", source="session-2026-09-27")
    check("add 返回内容寻址 eid（16 hex）",
          lambda: len(eid1) == 16 and all(c in "0123456789abcdef" for c in eid1), True)
    check("两条入库", lambda: len(lib.entries), 2)
    check("幂等去重（同内容再 add 不增）",
          lambda: (lib.add(ExperienceEntry(**{**e1.to_dict(), "eid": ""})), len(lib.entries))[1], 2)

    # 持久化往返
    lib2 = ExperienceLibrary(tmp / "lib.jsonl")
    check("JSONL 往返（重开条目数一致）", lambda: len(lib2.entries), 2)
    check("往返字段一致",
          lambda: lib2.entries[eid1].attention == e1.attention
          and lib2.entries[eid1].provenance["author"] == "human:otto", True)

    # ── [2] recall D9（禁 top-1）────────────────────────────────
    print("\n[2] recall D9")
    got = lib2.recall({"param": "Handle_Thickness", "scene": "mug"}, n=3)
    check("命中两条（D9 永不只回 1 条）", lambda: len(got), 2)
    got1 = ExperienceLibrary(tmp / "empty.jsonl").recall({"x": 1})
    check("空库召回 = 空列表", lambda: got1, [])
    got_single = ExperienceLibrary(tmp / "one.jsonl")
    got_single.add(ExperienceEntry(trigger={"a": 1}, attention="x", story="y",
                                   status="verified", evidence=EV),
                  author="test")          # W-12：带主件才可召回（无主件防毒过滤）
    check("单条库召回退化为 1 条（无法凭空造第二条）",
          lambda: len(got_single.recall({"a": 1})), 1)
    check("outcome 标记保留",
          lambda: sorted(e.outcome for e in got), ["verified_failure", "verified_success"])

    # ── [3] 差异化衰减（M6-2b：成功/失败不过期，未复核加速贬值）──
    print("\n[3] 差异化衰减")
    w1_before = lib2.entries[eid1].weight
    lib2.mark_reuse(eid1, success=True, had_variant=False)
    check("verified_success 复用不衰减",
          lambda: lib2.entries[eid1].weight == w1_before, True)
    check("provenance.reused +1",
          lambda: lib2.entries[eid1].provenance["reused"], 1)
    w2_before = lib2.entries[eid2].weight
    lib2.mark_reuse(eid2, success=False, had_variant=True)
    check("verified_failure 不衰减（失败教训一票）但记 variants",
          lambda: (lib2.entries[eid2].weight == w2_before,
                   lib2.entries[eid2].provenance["variants"]), (True, 1))
    e3 = ExperienceEntry(trigger={"param": "Handle_Thickness"},
                         attention="未复核条目", story="s",
                         outcome="unverified", status="verified", evidence=EV)
    eid3 = lib2.add(e3, author="human:otto")
    w3_before = lib2.entries[eid3].weight
    lib2.mark_reuse(eid3, success=True, had_variant=False)
    check("unverified 无变体复用 → weight ×0.8（加速贬值）",
          lambda: abs(lib2.entries[eid3].weight - w3_before * 0.8) < 1e-9, True)
    got3 = lib2.recall({"param": "Handle_Thickness"}, n=3)
    check("衰减后未复核条目沉底", lambda: got3[-1].eid, eid3)

    # ── [4] 多样性闸门（M6-1/M6-4）──────────────────────────────
    print("\n[4] 多样性闸门")
    fa = bin_features([(0.1 * i, 0.0, 0.0) for i in range(10)],
                      origin=(-0.05, -0.5, -0.5), cell=0.1)
    fb = bin_features([(0.1 * i, 0.5, 0.0) for i in range(10)],
                      origin=(-0.05, -0.5, -0.5), cell=0.1)
    fc = bin_features([(0.1 * i + 0.06, 0.0, 0.0) for i in range(10)],
                      origin=(-0.05, -0.5, -0.5), cell=0.1)
    check("IoU(自身)=1", lambda: round(iou(fa, fa), 6), 1.0)
    check("错位带部分重叠（0<IoU<1，错位被检出）",
          lambda: 0 < iou(fa, fc) < 1, True)
    check("平行错开带完全不交（IoU=0 < 错位带）",
          lambda: iou(fa, fb) < iou(fa, fc), True)
    pick = select_diverse([fa, fb, fc], k=2, lam=0.5)
    check("MMR k=2 选中两个（D9）", lambda: len(pick), 2)
    check("MMR 选出的是最远对（0 与 1，而非近似重复的 0/2）",
          lambda: set(pick), {0, 1})
    try:
        select_diverse([fa], k=2)
        check("k=2 但候选 1 → 拒绝", lambda: False, True)
    except ValueError:
        check("k=2 但候选 1 → 拒绝", lambda: True, True)
    try:
        select_diverse([fa, fb], k=1)
        check("k=1 → D9 拒绝", lambda: False, True)
    except ValueError:
        check("k=1 → D9 拒绝", lambda: True, True)

    # ── [5] 偏好学习（M6-6）──────────────────────────────────────
    print("\n[5] 偏好学习")
    pm = PreferenceModel()
    check("冷启动：needs_exploration=True（n=0）",
          lambda: pm.needs_exploration(), True)
    # 10 次：都选更粗的把手
    for i in range(10):
        pm.observe({"Handle_Thickness": 0.014}, {"Handle_Thickness": 0.006})
    check("选大 10 次 → w > 0", lambda: pm.w["Handle_Thickness"] > 0, True)
    check("score(大) > score(小)",
          lambda: pm.score({"Handle_Thickness": 0.014})
          > pm.score({"Handle_Thickness": 0.006}), True)
    check("冷启动结束（n=10 仍 <15？是）→ needs_exploration=True",
          lambda: pm.needs_exploration(), True)
    for i in range(6):
        pm.observe({"Handle_Thickness": 0.014}, {"Handle_Thickness": 0.006})
    check("n=16 > 15 → 冷启动结束", lambda: pm.needs_exploration(), False)
    rep = pm.report()
    check("可解释句产出（16 次全选大）",
          lambda: len(rep) == 1 and "更大" in rep[0], True)
    # 反向冲击 20 次（全选小）→ w 应被拉回负区（在线学习的可逆性）
    for i in range(20):
        pm.observe({"Handle_Thickness": 0.006}, {"Handle_Thickness": 0.014})
    check("反向 20 次 → w < 0（可逆）", lambda: pm.w["Handle_Thickness"] < 0, True)
    # 收缩：新模型 + 先验 0.8，1 次反例观察后 w 仍偏正（样本少 → 偏向先验）
    pm2 = PreferenceModel(prior={"Handle_Thickness": 0.8})
    pm2.observe({"Handle_Thickness": 0.006}, {"Handle_Thickness": 0.014})
    check("收缩：1 次反例不足以翻越强先验（w 仍 >0）",
          lambda: pm2.w["Handle_Thickness"] > 0, True)
    # 中性观察（Δx=0）= 无信息：不更新、不计数、不进 tally
    w_snapshot = dict(pm2.w)
    n_snapshot = pm2.n
    pm2.observe({"Handle_Thickness": 0.01}, {"Handle_Thickness": 0.01})
    check("Δx=0 不更新（w 不动）", lambda: pm2.w == w_snapshot, True)
    check("Δx=0 不计次数（n 不动）", lambda: pm2.n, n_snapshot)
    check("tally 方向统计与观察一致（1 次选小）",
          lambda: pm2.tally["Handle_Thickness"], [0, 1])

    # ── [6] 热拔插协议（M8）──────────────────────────────────────
    print("\n[6] 热拔插协议（ExperienceStore）")
    check("缺省实现满足协议（isinstance）",
          lambda: isinstance(lib2, ExperienceStore), True)

    class MemStore:
        """最小自定义实现——任何鸭子类型对象都可替换缺省库（热拔插）。"""
        def __init__(self):
            self.entries = {}
        def add(self, entry, author="", source=""):
            entry.eid = entry.content_eid()
            self.entries[entry.eid] = entry
            return entry.eid
        def recall(self, query, n=3):
            return list(self.entries.values())[:max(2, n)]
        def mark_reuse(self, eid, success, had_variant):
            pass
        def record_override(self, trigger, note, params=None):
            e = ExperienceEntry(trigger=trigger, attention=note[:40],
                                story=note, params=params or {},
                                outcome="verified_failure")
            return self.add(e, author="mem")

    mem = MemStore()
    check("自定义鸭子类型实现也满足协议",
          lambda: isinstance(mem, ExperienceStore), True)
    mem.add(ExperienceEntry(trigger={"a": 1}, attention="t1", story="s1"))
    mem.add(ExperienceEntry(trigger={"a": 1}, attention="t2", story="s2"))
    check("自定义实现 recall 正常（D9 同样约束调用方）",
          lambda: len(mem.recall({"a": 1})), 2)

    # ── [7] M6-2b 写入分权 / 状态机 / 墓碑（免疫通道）────────────
    print("\n[7] M6-2b 写入分权（治理位外置）")
    lib3 = ExperienceLibrary(tmp / "lib3.jsonl")
    ai_eid = lib3.record_ai(trigger={"param": "Handle_Thickness"},
                            attention="AI 猜测：14mm 也行",
                            story="AI 未经复核的尝试记录",
                            params={"Handle_Thickness": 0.014})
    check("免疫通道：record_ai → 强制 draft",
          lambda: lib3.entries[ai_eid].status, "draft")
    check("未复核条目默认不进 recall（未复核不进分册）",
          lambda: lib3.recall({"param": "Handle_Thickness"}), [])
    check("include_draft=True 可见（供 AI 自查）",
          lambda: len(lib3.recall({"param": "Handle_Thickness"},
                                  include_draft=True)), 1)
    expect_raise("AI actor 晋升 → 拒绝（无权自宣验收）", ValueError,
                 lambda: lib3.promote(ai_eid, actor="engine:evo"))
    lib3.promote(ai_eid, actor="human:reviewer")
    check("human 晋升 → verified 且进 recall",
          lambda: (lib3.entries[ai_eid].status,
                   len(lib3.recall({"param": "Handle_Thickness"}))),
          ("verified", 1))
    # 无出处三件套的条目：声称 verified 也会被压到 draft
    noev = lib3.add(ExperienceEntry(trigger={"a": 1}, attention="x", story="y",
                                    status="verified"))
    check("无 evidence → 强制 draft（三件套缺一不收）",
          lambda: lib3.entries[noev].status, "draft")
    # supersedes + 墓碑（只增不改）
    e_sup = ExperienceEntry(trigger={"param": "Handle_Thickness"},
                            attention="修订版：把 0.045 修正为 0.042",
                            story="上一条的比例数字抄错，重测后修正",
                            params={"Handle_Thickness": 0.008},
                            status="verified", evidence=EV,
                            supersedes=ai_eid)
    sup_eid = lib3.add(e_sup, author="human:otto")
    lib3.tombstone(ai_eid, reason="被修订版取代")
    check("墓碑后 recall 跳过旧条目",
          lambda: all(e.eid != ai_eid
                      for e in lib3.recall({"param": "Handle_Thickness"})), True)
    check("墓碑条目保留不删（只增不改）",
          lambda: lib3.entries[ai_eid].tombstone, True)
    check("新条目带 supersedes 指向旧条目",
          lambda: lib3.entries[sup_eid].supersedes, ai_eid)

    # ── [7b] verified_failure 入账（war stories 通道）────────────
    print("\n[7b] verified_failure：AI 声明机器验证过的失败")
    lib4 = ExperienceLibrary(tmp / "lib4.jsonl")
    ev_gate = [{"artifact": "gate3.1", "quote": "height=87.86mm 期望 82-86",
                "recalc": "blender -b -P x.py | grep 'gate 3.1'"}]
    wf_eid = lib4.record_ai(trigger={"node": "3.1", "build_op": "proportion_check"},
                            attention="比例门超差：挡泥板抬高 bbox",
                            story="gate 3.1 FAIL：87.86mm > 86mm 上限",
                            params={"height_mm": 87.86},
                            evidence=ev_gate, verified_failure=True)
    check("verified_failure=True → outcome=verified_failure",
          lambda: lib4.entries[wf_eid].outcome, "verified_failure")
    check("但 status 仍强制 draft（AI 无权自宣验收，晋升过人）",
          lambda: lib4.entries[wf_eid].status, "draft")
    ok_eid = lib4.record_ai(trigger={"node": "3.1"}, attention="a", story="s")
    check("不传 verified_failure → 默认 unverified（兼容不变）",
          lambda: lib4.entries[ok_eid].outcome, "unverified")
    check("verified_failure 条目 include_draft 召回可见",
          lambda: any(e.eid == wf_eid for e in
                      lib4.recall({"node": "3.1"}, include_draft=True)), True)
    # 失败教训不过期：mark_reuse 无变体复用 → verified_failure 不衰减
    before_w = lib4.entries[wf_eid].weight
    lib4.mark_reuse(wf_eid, success=False, had_variant=False)
    check("mark_reuse：verified_failure 不衰减（war stories 不过期）",
          lambda: lib4.entries[wf_eid].weight, before_w)
    before_u = lib4.entries[ok_eid].weight
    lib4.mark_reuse(ok_eid, success=False, had_variant=False)
    check("mark_reuse：unverified 衰减 ×0.8（对照组）",
          lambda: lib4.entries[ok_eid].weight, round(before_u * 0.8, 4))

    # ── [7c] W-12 owner 防毒（Orr 孤机：无主件不进召回）─────────
    print("\n[7c] W-12 owner 防毒")
    lib5 = ExperienceLibrary(tmp / "lib5.jsonl")
    o1 = lib5.record_ai(trigger={"proj": "w12"}, attention="有主件", story="s",
                        evidence=EV)
    check("record_ai 自动落 owner=ai:ai-channel",
          lambda: lib5.entries[o1].owner, "ai:ai-channel")
    ov1 = lib5.record_override(trigger={"proj": "w12"}, note="人工打回")
    check("record_override 自动落 owner=user-override",
          lambda: lib5.entries[ov1].owner, "user-override")
    lib5.add(ExperienceEntry(trigger={"proj": "w12"}, attention="无主毒件",
                             story="poison"))    # 低层 add 无 author → 无主
    got5 = lib5.recall({"proj": "w12"}, include_draft=True)
    check("无主件被 recall 防毒过滤（有主 2 条在、毒件不在）",
          lambda: (len(got5), all(e.owner for e in got5)), (2, True))
    # 存量迁移：旧条目 owner 缺失 → legacy 有主
    old = ExperienceEntry.from_dict({"trigger": {"a": 1}, "attention": "旧",
                                     "story": "s"})
    check("from_dict 迁移：owner 缺失 → legacy:pre-W12",
          lambda: old.owner, "legacy:pre-W12")

    # ── [7d] W-9 存活率闭环（Orr 地位经济学：价值由流通度量）─────
    print("\n[7d] W-9 存活率索引")
    lib6 = ExperienceLibrary(tmp / "lib6.jsonl")
    s1 = lib6.record_ai(trigger={"proj": "w9"}, attention="流通计数", story="s",
                        evidence=EV)
    check("未被讲述 → survival_rate=None（没有流通就没有存活率）",
          lambda: lib6.survival_rate(s1) is None)
    before = lib6.entries[s1].provenance.get("recall_hits", 0)
    got6 = lib6.recall({"proj": "w9"}, include_draft=True)
    after = lib6.entries[s1].provenance.get("recall_hits", 0)
    check("recall 命中自动计数（recall_hits %s→%s）" % (before, after),
          lambda: after == before + 1 and len(got6) >= 1)
    lib6.mark_reuse(s1, success=True, had_variant=False)
    rate = lib6.survival_rate(s1)
    check("讲述 1 次+复用成功 → survival_rate=%.2f" % (rate or 0), lambda: rate == 1.0)
    lib6.recall({"proj": "w9"}, include_draft=True)     # 第二次讲述 → hits=2
    lib6.mark_reuse(s1, success=False, had_variant=False)
    rate2 = lib6.survival_rate(s1)
    check("再讲述+复用失败 → survival_rate=%.2f（如实反映）" % (rate2 or 0),
          lambda: rate2 == 0.5)

    # ── 汇总 ────────────────────────────────────────────────────
    failed = [r for r in ROWS if not r["ok"]]
    print(f"\nM6 EXPERIENCE UNIT: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
    for f in failed:
        print("  FAILED:", f["case"], "->", f.get("detail"))
    sys.exit(1 if failed else 0)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
