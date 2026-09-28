"""从 brickfly_mcp_src 重打包 whl（M8-R6 发布定版 2.1.0-gn）+ 同步 site-packages + 验证 11 工具

R6 定版说明：工具面 11 个（v2.3 加 gn_reset 起），本脚本自 2.0.3 起未随 expect 同步——
历史脚本 expect 只有 10 个是**过时断言**（2.0.3 实际打包时手工核过 11 工具），
本次修正为 11 工具单一定版事实源。
"""
import asyncio
import shutil
import zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

BRIDGE = ROOT / "m8_bridge"
SRC_PKG = BRIDGE / "brickfly_mcp_src" / "brickfly_mcp"
OUT_WHL = BRIDGE / "brickfly_mcp-2.1.0-gn-py3-none-any.whl"
SP = BRIDGE / ".venv-mcp" / "Lib" / "site-packages"

# 1. 重打包（whl=zip，包根 brickfly_mcp/）
if OUT_WHL.exists():
    OUT_WHL.unlink()
with zipfile.ZipFile(OUT_WHL, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(SRC_PKG.rglob("*")):
        if "__pycache__" in p.parts:
            continue
        z.write(p, p.relative_to(SRC_PKG.parent).as_posix())
print("whl ->", OUT_WHL.name, OUT_WHL.stat().st_size, "bytes")

# 2. 同步 site-packages（先清旧包目录避免残留 .pyc 混淆）
sp_pkg = SP / "brickfly_mcp"
if sp_pkg.exists():
    shutil.rmtree(sp_pkg)
shutil.copytree(SRC_PKG, sp_pkg, ignore=shutil.ignore_patterns("__pycache__"))
print("site-packages synced")

# 3. 验证工具注册
import sys
sys.path.insert(0, str(SP))
from brickfly_mcp.server import main, mcp  # noqa: E402, F401

tools = asyncio.new_event_loop().run_until_complete(mcp.list_tools())
names = sorted(t.name for t in tools)
gn = sorted(n for n in names if n.startswith("gn_"))
print("total tools:", len(names))
print("gn tools (%d):" % len(gn), gn)
expect = {"gn_begin", "gn_compile", "gn_verify", "gn_checkpoint", "gn_revert",
          "gn_render_diff", "gn_ab_prepare", "gn_ab_commit", "gn_accept", "gn_export_state",
          "gn_reset"}
print("RESULT:", "OK 11/11" if set(gn) == expect else "MISMATCH: " + str(set(gn) ^ expect))
