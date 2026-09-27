"""从 brickfly_mcp_src 重打包 whl（2.0.2-gn）+ 同步 site-packages + 验证 10 工具"""
import asyncio
import shutil
import zipfile
from pathlib import Path

BRIDGE = Path(r"D:/WorkBuddy专用！危险！！！！！！！！/2026-09-26-21-02-58/m8_bridge")
SRC_PKG = BRIDGE / "brickfly_mcp_src" / "brickfly_mcp"
OUT_WHL = BRIDGE / "brickfly_mcp-2.0.3-gn-py3-none-any.whl"
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
          "gn_render_diff", "gn_ab_prepare", "gn_ab_commit", "gn_accept", "gn_export_state"}
print("RESULT:", "OK 10/10" if set(gn) == expect else "MISMATCH: " + str(set(gn) ^ expect))
