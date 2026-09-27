"""patch_m8r2b.py — M8-R2b · fork 工作副本补丁：8 个结构化工具（server + addon + 重打包 whl）

原则：只改 m8_bridge/ 下的**工作副本**（冻结快照不动）；每处补丁带锚点断言；改完静态验证。
"""
from pathlib import Path
import py_compile
import shutil
import zipfile

SRC = ROOT / "m8_bridge" / "brickfly_mcp_src" / "brickfly_mcp"
OUT_WHL = ROOT / "m8_bridge" / "brickfly_mcp-2.0.1-gn-py3-none-any.whl"

TOOLS = [
    ("gn_compile", "gn_compile", "提交一个段落提案（plan-JSON spec dict，走导演 propose）"),
    ("gn_verify", "gn_verify", "机械 verifier 门禁（面预算/DFM/非流形等，返回 PASS/FAIL 与 failures）"),
    ("gn_checkpoint", "gn_checkpoint", "GoodPoint 快照（=bake 边界，thought_refs 随行）"),
    ("gn_revert", "gn_revert", '回退：target=GoodPoint 名，或 "pop"（删最后一层 opinion）'),
    ("gn_render_diff", "gn_render_diff", "同机位渲染 diff（红色高亮变化像素 + 感知哈希）"),
    ("gn_ab_prepare", "gn_ab_prepare", 'A/B 二选一：variants_json=[{param:value},{...}]，AI 偏好与理由封存'),
    ("gn_ab_commit", "gn_ab_commit", "落 A/B 决定：choice ∈ 甲/乙/reroll，confidence 5-95，note 必填"),
    ("gn_export_state", "gn_export_state", "导出 mug-console-state/1（段落/偏好/归属/override 统计）"),
]

# ── ① server.py：8 个 @mcp.tool()（仿 execute_blender_code 风格）──
sp = SRC / "server.py"
st = sp.read_text(encoding="utf-8")
assert "gn_compile" not in st, "server.py 已打过补丁（幂等保护）"
block = "\n\n# ═══ M8-R2b · 结构化建模工具（blender_console 薄封装；R16 依赖单向）═══\n"
for name, cmd, doc in TOOLS:
    params = {
        "gn_compile": "spec_json: str, user_prompt: str = \"\"",
        "gn_verify": "ctx: Context, label: str = \"\"",
        "gn_checkpoint": "ctx: Context, name: str, user_prompt: str = \"\"",
        "gn_revert": "ctx: Context, target: str",
        "gn_render_diff": "ctx: Context, label: str = \"\"",
        "gn_ab_prepare": "ctx: Context, variants_json: str, ai_preferred: int = 0, ai_reason: str = \"\", user_prompt: str = \"\"",
        "gn_ab_commit": "ctx: Context, choice: str, confidence: int, note: str = \"\", user_prompt: str = \"\"",
        "gn_export_state": "ctx: Context",
    }[name]
    send = {
        "gn_compile": '{"spec_json": spec_json}',
        "gn_verify": '{"label": label}',
        "gn_checkpoint": '{"name": name}',
        "gn_revert": '{"target": target}',
        "gn_render_diff": '{"label": label}',
        "gn_ab_prepare": '{"variants_json": variants_json, "ai_preferred": ai_preferred, "ai_reason": ai_reason}',
        "gn_ab_commit": '{"choice": choice, "confidence": confidence, "note": note}',
        "gn_export_state": '{}',
    }[name]
    params = params.replace("ctx: Context, ", "").replace("ctx: Context", "")  # 模板已含 ctx，参数表剥重
    block += f'''

@mcp.tool()
async def {name}(ctx: Context, {params}) -> str:
    """{doc}

    Parameters:
    - 见参数表。所有返回为结构化 dict 的 JSON 文本（M9-1 tool return 契约）：
      ok/error_code/failed_node/reason/suggestions + 渲染 diff（base64 PNG）等。
    前置：先经 execute_blender_code 调 gn_bridge.begin(obj_name) 建会话（每会话一次）。
    """
    blender = get_blender_connection()
    result = blender.send_command("{cmd}", {send})
    return json.dumps(result.get("result", result), ensure_ascii=False)
'''
sp.write_text(st + block, encoding="utf-8")
print("server.py: +8 tools")

# ── ② bundled/addon.py：handlers dict +8 键 + 模块级部署加载器 ──
ap = SRC / "bundled" / "addon.py"
at = ap.read_text(encoding="utf-8")
assert "gn_compile" not in at, "addon.py 已打过补丁（幂等保护）"
anchor = '            "export_scene": self.export_scene,\n        }'
assert anchor in at, "handlers dict 锚点未找到"
at = at.replace(anchor, '''            "export_scene": self.export_scene,
            # M8-R2b：结构化建模工具（blender_console 薄封装；沙箱不适用——插件自有代码）
            "gn_compile": lambda **kw: _gn_call("gn_compile", kw),
            "gn_verify": lambda **kw: _gn_call("gn_verify", kw),
            "gn_checkpoint": lambda **kw: _gn_call("gn_checkpoint", kw),
            "gn_revert": lambda **kw: _gn_call("gn_revert", kw),
            "gn_render_diff": lambda **kw: _gn_call("gn_render_diff", kw),
            "gn_ab_prepare": lambda **kw: _gn_call("gn_ab_prepare", kw),
            "gn_ab_commit": lambda **kw: _gn_call("gn_ab_commit", kw),
            "gn_export_state": lambda **kw: _gn_call("gn_export_state", kw),
        }''', 1)
at += '''

# ═══ M8-R2b · gn_bridge 部署加载器（R16：上游──import──► blender_console，单向）═══
_GN_DEPLOY_ROOT = None  # blender_console 所在目录；由 install/用户配置注入


def _gn_deploy():
    """确保 blender_console 可 import：GN_DEPLOY_ROOT 环境变量或同目录 gn_deploy/。"""
    import os
    import sys
    global _GN_DEPLOY_ROOT
    if _GN_DEPLOY_ROOT is None:
        _GN_DEPLOY_ROOT = os.environ.get("GN_DEPLOY_ROOT") or os.path.join(
            os.path.dirname(__file__), "gn_deploy")
    if _GN_DEPLOY_ROOT not in sys.path:
        sys.path.insert(0, _GN_DEPLOY_ROOT)
    import gn_bridge  # blender_console 薄封装（R16：本文件──import──► blender_console）
    return gn_bridge


def _gn_call(cmd, params):
    gn = _gn_deploy()
    fn = getattr(gn, cmd)
    return fn(**params)
'''
ap.write_text(at, encoding="utf-8")
print("addon.py: +8 handlers + _gn_call")

# ── ③ 静态验证 ──
HERE = Path(__file__).resolve().parent
for f in (sp, ap, HERE / "gn_bridge.py"):
    py_compile.compile(str(f), doraise=True)
print("py_compile: OK")

# ── ③b 部署包 gn_deploy/（Blender 侧 GN_DEPLOY_ROOT 载荷）──
# = gn_bridge.py + blender_console 全量（R16：gn_bridge ──import──► blender_console）
deploy = HERE / "gn_deploy"
deploy.mkdir(exist_ok=True)
shutil.copy2(HERE / "gn_bridge.py", deploy / "gn_bridge.py")
bc = HERE.parent / "blender_console"
for f in bc.glob("*.py"):
    if f.name.startswith(("test_", "m7_", "m4_", "m5_", "m6_", "exp1", "probe")):
        continue
    shutil.copy2(f, deploy / f.name)
print("gn_deploy:", len(list(deploy.glob("*.py"))), "modules")

# ── ④ 重打包 whl（全包源码）──
pkg_dir = SRC.parent
with zipfile.ZipFile(OUT_WHL, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(pkg_dir.rglob("*.py")):
        z.write(f, f"brickfly_mcp/{f.relative_to(pkg_dir).as_posix()}")
print("whl repacked:", OUT_WHL.name)

# ── ⑤ 重打包后验证：whl 内含新工具 ──
z = zipfile.ZipFile(OUT_WHL)
srv = z.read("brickfly_mcp/server.py").decode("utf-8")
add = z.read("brickfly_mcp/bundled/addon.py").decode("utf-8")
checks = {
    "server 8 工具声明": all(f"async def {n}(" in srv for n, _, _ in TOOLS),
    "addon 8 个 handler 键": all(f'"{n}": lambda' in add for n, _, _ in TOOLS),
    "whl 可读": len(z.namelist()) >= 11,
}
print("VERIFY:", checks)
assert all(checks.values())
print("M8-R2b PATCH: OK")
