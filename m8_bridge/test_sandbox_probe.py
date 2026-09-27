"""test_sandbox_probe.py — M8-R2a · 沙箱白名单实测（未核实点验证）

用上游自己的 safe_mode.is_safe（deny-by-default AST 校验器）实测本项目
Tier-1 桩所需的全部代码模式，产出通行/拦截矩阵。

跑法：python test_sandbox_probe.py（纯 Python，无需 Blender——safe_mode 独立于 bpy）
"""
import importlib.util  # noqa: E402
from pathlib import Path as _P  # noqa: E402
ROOT = _P(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

_spec = importlib.util.spec_from_file_location(
    "safe_mode",
    ROOT / "m8_bridge/brickfly_mcp_src/brickfly_mcp/safe_mode.py")
safe_mode = importlib.util.module_from_spec(_spec)  # noqa: E402  上游原版校验器（未改一行）
_spec.loader.exec_module(safe_mode)  # noqa: E402  自足模块（仅 ast/os/typing，见其 §imports）

ROWS: list[dict] = []


def probe(name: str, code: str, expect_ok: bool | None = None):
    ok, reason = safe_mode.is_safe(code)
    verdict = "PASS" if ok else f"BLOCK({reason[:60]})"
    mark = ""
    if expect_ok is not None:
        mark = "  ✓预期" if ok == expect_ok else "  ✗反预期!"
    print(f"  [{'过' if ok else '拦'}] {name}{mark}")
    if reason and not ok:
        print(f"        └─ {reason[:100]}")
    ROWS.append({"case": name, "ok": ok, "reason": reason[:160],
                 "expect_ok": expect_ok, "match": (expect_ok is None or ok == expect_ok)})


print("== M8-R2a 沙箱实测矩阵（BLENDER_MCP_SAFE_MODE=1 时的校验行为）==\n")

print("── 对照组（上游设计意图内）──")
probe("bpy 基本操作", "import bpy\nbpy.ops.mesh.primitive_cube_add()", True)
probe("白名单模块 import", "import json\nimport math", True)
probe("bmesh + mathutils", "import bmesh, mathutils", True)

print("\n── Tier-1 桩：部署模块 import（未核实点本体）──")
probe("import 部署模块 mug_compiler", "import mug_compiler", False)
probe("五行桩：import + run", "import mug_compiler\nmug_compiler.run({})", False)
probe("import sys（逃逸面）", "import sys", False)
probe("import os（逃逸面）", "import os", False)
probe("import pathlib（我们的依赖）", "import pathlib", False)
probe("import hashlib（我们的依赖）", "import hashlib", False)
probe("class 定义（console 结构）", "class Foo:\n    pass", False)
probe("contextlib import", "from contextlib import contextmanager", False)

print("\n── Tier-1.5 候选：注入式桩（无 import，名字由插件预注入 exec globals）──")
probe("纯名字调用 mug_console.run(plan)",
      "mug_console.run(plan_json)", False)
probe("注入名 + bpy 混用",
      "mug_console.attach(bpy)\nbpy.ops.mesh.primitive_cube_add()", False)
probe("注入名取属性字典",
      "r = mug_console.export_state()\nprint(r)", False)

print("\n── Tier-1.5 最终形态：bpy.app.driver_namespace 字典注入（SAFE_MODE=1 合法通道）──")
probe("driver_namespace 通道",
      "bpy.app.driver_namespace['mug_console'].run(plan_json)", False)
probe("driver_namespace 通道（bpy 预注入名）",
      "ns = bpy.app.driver_namespace\nns['mug'].run(plan_json)", False)

print("\n── 攻击面对照（验证沙箱判别力：这些必须拦）──")
probe("__import__ 直调", "__import__('os')", False)
probe("globals 逃逸", "globals()['__builtins__']", False)
probe("空代码", "", True)

failed = [r for r in ROWS if r["expect_ok"] is not None and not r["match"]]
print(f"\nM8-R2a SANDBOX PROBE: {len(ROWS) - len(failed)}/{len(ROWS)} 与预期一致")
for f in failed:
    print("  反预期:", f["case"], "->", f["reason"])

# 结论落盘
import json  # noqa: E402
out = ROOT / "m8_bridge/sandbox_probe_result.json"
out.write_text(json.dumps(ROWS, ensure_ascii=False, indent=1), encoding="utf-8")
print("result ->", out)
