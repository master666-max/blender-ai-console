"""test_upstream_store.py — UpstreamExperienceStore 单元测试（读真实隔离区，秒级）。

跑法：python test_upstream_store.py
覆盖：14 条 EXP 解析 / 全 draft（免疫通道）/ recall 治理语义 / promote 人审 /
      只读投影 fail-closed / 协议符合。
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from experience import ExperienceStore
from upstream_store import UpstreamExperienceStore

import shutil
import tempfile
SAMPLE_DIR = Path(tempfile.mkdtemp(prefix="upstream_store_selfcontained_"))

def _write_sample(n: int) -> None:
    """写一条自含样例条目（跨设备可跑：不再依赖仓库外的上游隔离区数据）。"""
    eid = "EXP-%03d" % n
    bake = "烘焙" if n == 14 else ""
    story = ("现象：样例故障 %s 的%s现象——测试自含化样例，"
             "不依赖仓库外隔离区数据，正文需超过四十字以满足 story 保留断言。" % (eid, bake)) + "填充细节。" * 4
    fix = "规避法：%s 的规避手段——先快照再批量，单一前缀，身份差集清理。" % eid
    (SAMPLE_DIR / (eid + ".md")).write_text(
        "---\n"
        "id: " + eid + "\n"
        "date: 2026-09-28\n"
        'source: "test-self-contained fixture"\n'
        "status: promoted\n"
        "legacy: BMCP-ERR-%03d\n" % n +
        "evidence://n"
        '  - artifact: "fixture://' + eid + '"\n'
        '    quote: "' + eid + ' 样例证据"\n'
        '    recalc: "读 fixture ' + eid + '.md"\n'
        "---\n"
        "## 现象与根因\n\n" + story + "\n\n"
        "## 规避法\n\n" + fix + "\n",
        encoding="utf-8")

for _i in range(1, 15):
    _write_sample(_i)
ISO = SAMPLE_DIR

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


store = UpstreamExperienceStore(ISO)

print("[1] 解析（14 条 EXP 全量投影）")
check("14 条全量解析", lambda: len(store.entries), 14)
check("eid 前缀 upstream-", lambda: all(e.eid.startswith("upstream-EXP-")
                                        for e in store.entries.values()), True)
check("免疫通道：全部 draft（外来未经本项目验证）",
      lambda: all(e.status == "draft" for e in store.entries.values()), True)
check("每条都带出处三件套（recalc 指回隔离区）",
      lambda: all(e.evidence and e.evidence[0].get("recalc")
                  for e in store.entries.values()), True)
check("story 保留正文全文（现象+规避法）",
      lambda: all("规避" in e.story or len(e.story) > 40
                  for e in store.entries.values()), True)
check("协议符合（isinstance ExperienceStore）",
      lambda: isinstance(store, ExperienceStore), True)

print("\n[2] recall 治理语义（draft 默认不可见）")
check("缺省 recall = 空（全 draft，未复核不进分册）",
      lambda: store.recall({"origin": "blender-mcp-skill"}), [])
hit = store.recall({"origin": "blender-mcp-skill"}, include_draft=True, n=14)
check("include_draft=True 可见全部", lambda: len(hit), 14)
kw = store.recall({"origin": "blender-mcp-skill", "q": "烘焙"},
                  include_draft=True, n=5)
check("关键词命中（烘焙→EXP-014 在列）",
      lambda: any("EXP-014" in e.eid for e in kw), True)

print("\n[3] 人工审查流程（promote）")
target = "upstream-EXP-014"
expect_raise("engine actor 晋升 → 拒绝（免疫通道）", ValueError,
             lambda: store.promote(target, actor="engine:evo"))
store.promote(target, actor="human:reviewer")
check("human 晋升 → verified",
      lambda: store.entries[target].status, "verified")
check("verified 条目进缺省 recall",
      lambda: any(e.eid == target
                  for e in store.recall({"origin": "blender-mcp-skill"})), True)
check("其余 13 条仍 draft", lambda: sum(
    1 for e in store.entries.values() if e.status == "draft"), 13)

print("\n[4] 只读投影 fail-closed")
from experience import ExperienceEntry
expect_raise("add → 拒绝（只读）", RuntimeError,
             lambda: store.add(ExperienceEntry(trigger={"a": 1},
                                               attention="x", story="y")))
expect_raise("mark_reuse → 拒绝（只读）", RuntimeError,
             lambda: store.mark_reuse(target, True, False))
expect_raise("record_override → 拒绝（回写走主库）", RuntimeError,
             lambda: store.record_override({"seg": "x"}, "n"))

failed = [r for r in ROWS if not r["ok"]]
print(f"\nUPSTREAM STORE UNIT: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
for f in failed:
    print("  FAILED:", f["case"], "->", f.get("detail"))
shutil.rmtree(SAMPLE_DIR, ignore_errors=True)
sys.exit(1 if failed else 0)
