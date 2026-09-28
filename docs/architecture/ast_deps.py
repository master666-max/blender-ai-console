#!/usr/bin/env python3
"""ast_deps.py — AST 实测 import 依赖（架构图的数据锚，不手写）"""
import ast, json
from pathlib import Path

HERE = Path(__file__).resolve().parents[2] / "blender_console"
mods = sorted(p.stem for p in HERE.glob("*.py")
              if not p.stem.startswith("test") and p.stem not in
              {"revert_live", "tiger_console_run", "tiger_tank_build",
               "probe_loose", "probe_rotation_socket", "tiger_diag",
               "console_live", "m4_compile_live", "m45_live", "m411_live",
               "m7v2_live", "m7_director_live", "m8r4_live", "exp5_live",
               "ab_live"})

deps = {}
for p in sorted(HERE.glob("*.py")):
    name = p.stem
    if name not in mods:
        continue
    tree = ast.parse(p.read_text(encoding="utf-8"))
    s = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                root = a.name.split(".")[0]
                if root in mods:
                    s.add(root)
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in mods:
                s.add(root)
    deps[name] = sorted(s)

print("=== AST 实测 import 依赖（权威数据锚）===")
for m in sorted(deps):
    if deps[m]:
        print("%-18s <- %s" % (m, ", ".join(deps[m])))
    else:
        print("%-18s <- (无内部依赖)" % m)

# 反向表：谁依赖谁
rev = {}
for m, ds in deps.items():
    for d in ds:
        rev.setdefault(d, []).append(m)
print("\n=== 反向（被依赖方 <- 谁依赖）===")
for m in sorted(rev):
    print("%-18s <- %s" % (m, ", ".join(sorted(rev[m]))))
orphans = [m for m in mods if m not in rev]
print("\n孤儿模块（无人依赖）:", orphans)

# 关键裁决点
print("\n=== 关键裁决 ===")
print("logic_tree 依赖 plan_schema?", "plan_schema" in deps.get("logic_tree", []))
print("escape 被谁依赖:", sorted(rev.get("escape", [])))
print("nlg_bands 被谁依赖:", sorted(rev.get("nlg_bands", [])))
print("intake 依赖 plan_schema?", "plan_schema" in deps.get("intake", []))
print("director 依赖 console?", "console" in deps.get("director", []))
print("console 依赖 director?", "director" in deps.get("console", []))
