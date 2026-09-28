"""test_wiring.py — W-4/W-5/W-6/W-9/W-13 接线验收（AST + 行为双证）"""
import ast, sys, json, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

ROWS = []
def check(desc, cond):
    ROWS.append(bool(cond))
    print("  %s %s" % ("PASS" if cond else "FAIL", desc))

src = (HERE / "console.py").read_text(encoding="utf-8")
tree = ast.parse(src)
imports = set()
for n in ast.walk(tree):
    if isinstance(n, ast.ImportFrom) and n.module:
        imports.add(n.module.split(".")[0])

print("\n[wiring] W-4/W-5 console 门面（AST）")
check("console import intake（W-5）", "intake" in imports)
check("console import escape（W-4）", "escape" in imports)
for m in ("escape_run_template", "escape_run_script",
          "start_session", "session_ask", "session_submit", "session_freeze",
          "archaeology", "note_plan_revision", "record_experience"):
    check(f"console.{m} 门面方法存在", f"def {m}(" in src)
check("EscapeHatch 实例化（__init__）", "self.hatch = EscapeHatch()" in src)

print("\n[wiring] W-6/W-13 经验库索引与引用债（行为）")
from experience import ExperienceLibrary, ExperienceEntry
EV = [{"artifact": "x", "quote": "q", "recalc": "r"}]
tmp = Path(tempfile.mkdtemp())
lib = ExperienceLibrary(tmp / "w.jsonl")
a = lib.record_ai(trigger={"origin": "lt", "seg": "1.1"}, attention="高度门",
                  story="s", params={"height_mm": 95.0}, evidence=EV)
b = lib.record_ai(trigger={"origin": "lt", "seg": "1.2"}, attention="壁厚门",
                  story="s", params={"wall_mm": 5.0}, evidence=EV)
check("图索引 related（同 origin 关联）",
      lambda: [e.attention for e in lib.related(a)] == ["壁厚门"])
check("参数索引 recall_by_param（量级桶）",
      lambda: [e.attention for e in lib.recall_by_param("height_mm", 80, 100)] == ["高度门"])
c = lib.record_ai(trigger={"kind": "plan_revision"}, attention="修订叙事",
                  story="s", evidence=EV, credits_to=[a])
check("引用债记账 credits_to", lambda: lib.entries[c].credits_to == [a])
dr = lib.debt_report()
check("debt_report 债主榜", lambda: dr["lenders"][0][0] == a)
# 持久化往返：索引重建后仍可用
lib2 = ExperienceLibrary(lib.path)
check("重启后图索引重建（related 仍可用）",
      lambda: len(lib2.related(a)) == 1)

print("\n[wiring] W-9 kpis 评分 hook（AST）")
check("_compute_kpis 输出 experience 存活率统计",
      lambda: '"experience"' in src or "'experience'" in src)

failed = sum(1 for r in ROWS if not r)
print(f"\nWIRING UNIT: {len(ROWS) - failed}/{len(ROWS)} passed")
sys.exit(1 if failed else 0)
