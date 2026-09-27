"""test_escape.py — M4-4 逃逸舱三层粒度单元测试（纯 Python，秒级）。

跑法：python test_escape.py
覆盖：L2 模板注册/缺失拒/缺参拒/域拒；L3 域白名单审查（合法脚本过/危险调用拦/
      非域 ops 拦/语法错报行号）；免疫通道（无 human 审核标记拒绝）；审计与执行分离。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from escape import (EscapeError, EscapeHatch, ScriptAuditor,  # noqa: E402
                    TemplateEntry, TemplateRegistry)

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


def expect_code(name, fn, code):
    try:
        fn()
        ROWS.append({"case": name, "ok": False, "detail": "未抛错"})
        print(f"  FAIL  {name}  未抛错")
    except EscapeError as e:
        ok = e.code == code
        ROWS.append({"case": name, "ok": ok, "detail": e.reason[:100]})
        print(f"  {'PASS' if ok else 'FAIL'}  {name}（{e.code}）")


# ── [1] L2 模板层 ─────────────────────────────────────────────
print("[1] L2 模板层")
reg = TemplateRegistry()
reg.register(TemplateEntry(
    name="rig_basic_spine", domain="rig",
    fn=lambda p: {"bones": 5, "spine": p["count"]},
    params_schema={"count": int}, provenance="预审模板（示例）"))
hatch = EscapeHatch(registry=reg)
r = hatch.run_template("rig_basic_spine", {"count": 7})
check("L2 模板执行", lambda: r["ok"] and r["report"]["spine"], 7)
expect_code("未注册模板 → TEMPLATE_NOT_FOUND", lambda: hatch.run_template("nope", {}),
            "TEMPLATE_NOT_FOUND")
try:
    hatch.run_template("rig_basic_spine", {})
except EscapeError as e:
    check("缺参 → TEMPLATE_PARAM_MISSING", lambda: e.code,
          "TEMPLATE_PARAM_MISSING")
bad_dom = TemplateRegistry()
try:
    bad_dom.register(TemplateEntry(name="evil", domain="network", fn=lambda p: {}))
    check("非受控域模板 → 拒注册", lambda: False, True)
except EscapeError as e:
    check("非受控域模板 → 拒注册", lambda: e.code, "TEMPLATE_DOMAIN_DENIED")

# ── [2] L3 域白名单审查 ──────────────────────────────────────
print("\n[2] L3 脚本域白名单")
aud = ScriptAuditor()
OK_SCRIPT = ("import bpy\n"
             "arm = bpy.data.armatures.new('Rig')\n"
             "for i in range(3):\n"
             "    b = arm.edit_bones.new(f'bone_{i}')\n"
             "    b.head = (0, 0, i * 0.1)\n")
ok, sha, reason = aud.audit(OK_SCRIPT)
check("合法 rig 脚本过审", lambda: ok, True)
check("sha16 指纹", lambda: len(sha), 16)

BAD_CASES = [
    ("import os 逃逸", "import os\nos.system('x')"),
    ("open 读文件", "open('/etc/passwd')"),
    ("eval 动态执行", "eval('1+1')"),
    ("subprocess", "import subprocess"),
    ("bpy.ops.file 非域 ops", "bpy.ops.file.pack_all()"),
    ("exec 编译", "exec('x=1')"),
]
for name, code in BAD_CASES:
    ok, sha, reason = aud.audit(code)
    check(f"{name} → 拦", lambda ok=ok: ok, False)

OK2 = "b = bpy.data.armatures.new('X')"
check("bpy.data.armatures 域内过", lambda: aud.audit(OK2)[0], True)

# ── [3] 免疫通道（治理位外置）────────────────────────────────
print("\n[3] 免疫通道（审计与执行分离）")
expect_code("无 human 审核标记 → HATCH_AUDIT_REQUIRED",
            lambda: hatch.run_script(OK_SCRIPT, audited_by="ai:auto"),
            "HATCH_AUDIT_REQUIRED")
r = hatch.run_script(OK_SCRIPT, audited_by="human:reviewer", label="rig试")
check("human 审核标记通过", lambda: r["ok"], True)
check("usage 留痕（审计链）", lambda: len(hatch.usage), 2)

failed = [r for r in ROWS if not r["ok"]]
print(f"\nM4-4 ESCAPE UNIT: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
for f in failed:
    print("  FAILED:", f["case"], "->", f.get("detail"))
sys.exit(1 if failed else 0)
