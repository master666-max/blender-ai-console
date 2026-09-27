"""m6_live.py — M6 经验库真机端到端验收（Blender 5.2.1）。

跑法：blender --background --factory-startup --python m6_live.py

验收项（全机械，B1 纪律）：
  1. attach_experience 激活（库+偏好模型就位）
  2. ab_commit 采纳 → PreferenceModel 自动消费（M6-6）：方向与"人总是选更粗"
     一致（读 WAL 映射模拟人类选择）；needs_exploration 冷启动语义
  3. override（选非 AI 偏好）→ M6-3 回写：库自动多一条 verified_failure
  4. 库 recall D9：命中 ≥2 条
  5. 真实网格顶点直方图 → select_diverse：4 个候选参数里选出的两变体
     其 IoU 低于全体候选对的最大 IoU（多样性闸门有牙齿）
  6. export_state 携带 preference 快照与库计数（M9-4 可见）
  7. WAL 终局 verify
"""
import json
import shutil
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy

from gn_adapter import GNAdapter
from console import Console
from experience import bin_features, iou, select_diverse

OUT = ROOT.parent / "2026-09-26-blender"
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


print(f"Blender {bpy.app.version_string}")
ad = GNAdapter(bpy)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.active_object
obj.name = "Mug"
obj.data = bpy.data.meshes.new("Base")

shutil.rmtree(HERE / "_m6_wal", ignore_errors=True)
con = Console(ad, obj, workdir=HERE / "_m6_wal")

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

# ── [1] 激活经验库 ────────────────────────────────────────────
print("\n[1] attach_experience")
con.attach_experience()
check("库就位", lambda: con.library is not None, True)
check("偏好模型就位（冷启动）",
      lambda: con.pref is not None and con.pref.needs_exploration(), True)

# 模拟"人类总选更粗"的辅助：从 WAL 最近一张 A/B 卡读映射，返回更粗变体的标签
def thicker_label() -> str:
    card = next(e for e in reversed(con.wal.replay())
                if e["kind"] == "ab_prepare")
    mapping = card["payload"]["mapping"]          # {"0": "甲", "1": "乙"}
    variants = card["payload"]["variants"]
    return mapping[str(0)] if variants[0]["Handle_Thickness"] > variants[1]["Handle_Thickness"] \
        else mapping["1"] if "1" in mapping else mapping[1]


def thinner_label() -> str:
    return "乙" if thicker_label() == "甲" else "甲"

# ── [2] 两轮 A/B：人都选更粗 → M6-6 方向学习 ─────────────────
print("\n[2] 两轮 A/B 采纳（人总选更粗 → w 方向为正）")
conf = con.ab_prepare("handle", [{"Handle_Thickness": 0.006},
                                 {"Handle_Thickness": 0.014}],
                      ai_preferred=0, ai_reason="8mm 基线")
check("round1 prepare ok", lambda: conf.ok, True)
lab1 = thicker_label()
r1 = con.ab_commit(lab1, 80, note="粗的这版握感满手")
check("round1 commit ok", lambda: r1.ok, True)
check("M6-6 自动消费（n=1）", lambda: con.pref.n, 1)
check("方向为正（人选择被学进去）", lambda: con.pref.w["Handle_Thickness"] > 0, True)

conf = con.ab_prepare("handle", [{"Handle_Thickness": 0.007},
                                 {"Handle_Thickness": 0.013}],
                      ai_preferred=1, ai_reason="AI 仍偏好细把")
check("round2 prepare ok", lambda: conf.ok, True)
r2 = con.ab_commit(thicker_label(), 75, note="还是粗的舒服")
check("round2 commit ok", lambda: r2.ok, True)
check("M6-6 n=2", lambda: con.pref.n, 2)
check("方向仍为正", lambda: con.pref.w["Handle_Thickness"] > 0, True)
check("冷启动语义（n=2 < 15）", lambda: con.pref.needs_exploration(), True)

# ── [3] override 回写（M6-3）─────────────────────────────────
print("\n[3] override 回写经验库")
entries_before = len(con.library.entries)
conf = con.ab_prepare("handle", [{"Handle_Thickness": 0.006},
                                 {"Handle_Thickness": 0.014}],
                      ai_preferred=0, ai_reason="AI 偏好细把")
# ai_preferred=0 = 细的那版 → 选更粗的 = 与 AI 偏好相悖 → 必然触发 override
r3 = con.ab_commit(thicker_label(), 65, note="试下来还是粗的更平衡，打回 AI 的选择")
check("round3 commit ok", lambda: r3.ok, True)
override_counted = r3.data["override_counted"]
entries_expected = entries_before + (1 if override_counted else 0)
check("override 回写条目数符合（选非 AI 偏好 → verified_failure 入库）",
      lambda: len(con.library.entries), entries_expected)
check("round3 确实触发了 override", lambda: override_counted, True)
if override_counted:
    fail_entries = [e for e in con.library.entries.values()
                    if e.outcome == "verified_failure"]
    check("回写条目 outcome = verified_failure",
          lambda: len(fail_entries) > 0 and all("override" in (e.provenance.get("author") or "")
                                                for e in fail_entries), True)

# ── [4] recall D9 ────────────────────────────────────────────
print("\n[4] recall D9")
check("库召回 ≥2（D9 禁 top-1）",
      lambda: len(con.library.recall({"seg": "handle"})), 2)

# ── [5] 真实网格多样性闸门（M6-1/M6-4）───────────────────────
print("\n[5] 顶点直方图多样性闸门（4 候选 → MMR 选 2）")


def vertex_bins(thickness: float) -> frozenset:
    con.set_param("handle", "Handle_Thickness", thickness)
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    m = ev.to_mesh()
    pts = [tuple(v.co) for v in m.vertices]
    ev.to_mesh_clear()
    return bin_features(pts, origin=(-0.1, -0.1, -0.1), cell=0.006,
                        dims=(40, 40, 40))


cands = [0.006, 0.010, 0.014, 0.018]
feats = [vertex_bins(v) for v in cands]
check("四特征互不相同", lambda: len({tuple(sorted(f)) for f in feats}), 4)
pick = select_diverse(feats, k=2, lam=0.5)
check("闸门选出 2 个（D9）", lambda: len(pick), 2)
pairwise = [iou(feats[i], feats[j]) for i in range(4) for j in range(i + 1, 4)]
check("选中对的相似度 < 全体候选对的最大相似度（闸门有牙齿）",
      lambda: iou(feats[pick[0]], feats[pick[1]]) < max(pairwise), True)
print(f"  pairwise IoU = {[round(x, 3) for x in pairwise]}，picked = {pick}")

# ── [6] export_state 携带 M6 ─────────────────────────────────
print("\n[6] export_state")
st = con.export_state().data
check("preference 快照在场", lambda: "preference" in st, True)
check("偏好 w 有 Handle_Thickness 维度",
      lambda: "Handle_Thickness" in st.get("preference", {}).get("w", {}), True)
check("库计数在场", lambda: st.get("experience", {}).get("entries", 0) > 0, True)
check("WAL 终局 verify", lambda: con.wal.verify(), True)

# ── [7] 热拔插：注入自定义 ExperienceStore（M8）──────────────
print("\n[7] 热拔插（console 只依赖 ExperienceStore 协议）")
from experience import ExperienceStore as _ExpStore


class MemStore:
    """最小自定义实现：内存 dict，不落盘——证明缺省 JSONL 可被任意替换。"""
    def __init__(self):
        self.entries = {}
        self.overrides = []
    def add(self, entry, author="", source=""):
        entry.eid = entry.content_eid()
        self.entries[entry.eid] = entry
        return entry.eid
    def recall(self, query, n=3):
        return list(self.entries.values())[:max(2, n)]
    def mark_reuse(self, eid, success, had_variant):
        pass
    def record_override(self, trigger, note, params=None):
        from experience import ExperienceEntry
        e = ExperienceEntry(trigger=trigger, attention=note[:40], story=note,
                            params=params or {}, outcome="verified_failure")
        self.overrides.append(e)
        return self.add(e, author="mem-override")


check("MemStore 满足协议", lambda: isinstance(MemStore(), _ExpStore), True)
jsonl_lib = con.library
jsonl_count_before = len(jsonl_lib.entries)
mem = MemStore()
con.attach_experience(store=mem)
check("注入后 library 即 MemStore（零依赖缺省实现）",
      lambda: con.library is mem, True)
conf = con.ab_prepare("handle", [{"Handle_Thickness": 0.006},
                                 {"Handle_Thickness": 0.014}],
                      ai_preferred=0, ai_reason="热拔插探针")
card = next(e for e in reversed(con.wal.replay()) if e["kind"] == "ab_prepare")
mapping = card["payload"]["mapping"]
variants = card["payload"]["variants"]
thick = mapping["0"] if variants[0]["Handle_Thickness"] > variants[1]["Handle_Thickness"] else mapping["1"]
r_swap = con.ab_commit(thick, 70, note="热拔插期间的打回")
check("热拔插后 commit 照常", lambda: r_swap.ok, True)
check("override 记录进了 MemStore（协议依赖生效）",
      lambda: len(mem.overrides), 1)
check("JSONL 缺省库未被写入（替换是隔离的）",
      lambda: len(jsonl_lib.entries), jsonl_count_before)
check("偏好学习照常消费（n 增长）", lambda: con.pref.n >= 3, True)

# ── 汇总 ─────────────────────────────────────────────────────
failed = [r for r in ROWS if not r["ok"]]
print(f"\nM6 LIVE: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
for f in failed:
    print("  FAILED:", f["case"], "->", f["detail"])
(OUT / "m6_live_result.json").write_text(
    json.dumps(ROWS, ensure_ascii=False, indent=1), encoding="utf-8")
print("result ->", OUT / "m6_live_result.json")
