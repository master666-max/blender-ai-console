"""真实 MCP 客户端联调冒烟（M8-R2 · WorkBuddy 路线预演）

链路：mcp ClientSession(stdio) → server.py(FastMCP) → TCP 9876 →
      addon handlers → gn_bridge → blender_console（导演会话）

验证：initialize → tools/list(11 gn) → gn_begin → gn_compile(T1) → gn_verify →
      gn_render_diff → gn_export_state → gn_accept 状态机（T3 拒绝路径预期）。
"""
import asyncio
import json
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

# 模拟 WorkBuddy 启动形态：mcp.json env 字段会传给 server 进程。
# 注意：StdioServerParameters(env=None) 用白名单环境（不继承父进程全部变量），
# 必须显式合并——否则 SAFE_MODE 在 server 侧是关的（实测踩坑）。
_ENV = get_default_environment()
_ENV["BLENDER_MCP_SAFE_MODE"] = "1"

BRIDGE = ROOT / "m8_bridge"
PYV = str(BRIDGE / ".venv-mcp" / "Scripts" / "python.exe")

PARAMS = StdioServerParameters(
    command=PYV,
    args=["-c", "from brickfly_mcp.server import main; main()"],
    env=_ENV,
)

ROWS = []


def check(name, cond, detail=""):
    ok = bool(cond)
    ROWS.append({"case": name, "ok": ok, "detail": str(detail)[:160]})
    print(("  PASS  " if ok else "  FAIL  ") + name + "  " + str(detail)[:120])


def parse(result):
    """CallToolResult → dict（server 返回 JSON 文本）"""
    return json.loads(result.content[0].text)


SPEC_BODY = {
    "id": "body", "op": "cylinder", "consumes_input": False,
    "parameters": [
        {"name": "Radius", "type": "FLOAT", "value": 0.04},
        {"name": "Depth", "type": "FLOAT", "value": 0.095},
    ],
}


async def main_async():
    async with stdio_client(PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            check("initialize", init.serverInfo.name != "", init.serverInfo.name)

            tools = await session.list_tools()
            gn = sorted(t.name for t in tools.tools if t.name.startswith("gn_"))
            check("tools/list 含 11 个 gn 工具", len(gn) == 11, gn)

            # 导演会话开始
            r = parse(await session.call_tool("gn_begin", {
                "obj_name": "Mug", "brief": "真实 MCP 客户端联调", "policy": "NORMAL"}))
            check("gn_begin ok", r.get("ok") is True, r)

            # T1 自产图元（自动档）
            r = parse(await session.call_tool("gn_compile", {
                "spec_json": json.dumps(SPEC_BODY),
                "assumption": "圆柱杯体比例合理"}))
            check("gn_compile body（T1 自动）", r.get("auto_accepted") is True,
                  f"tier={r.get('tier')}")

            # T3 拒绝路径：不用 accept，直接 verify 前先看提案档位
            # （hollow 属结构 op → T3_DIRECTOR，待决时 verify 行为观察）
            hollow = {"id": "hollow", "op": "boolean_diff", "consumes_input": True,
                      "parameters": [],
                      "operand": {"op": "transform", "translation": [0.0, 0.0, 0.01],
                                  "source": {"op": "cylinder", "radius": 0.036,
                                             "depth": 0.085}}}
            r = parse(await session.call_tool("gn_compile", {
                "spec_json": json.dumps(hollow),
                "assumption": "掏空壁厚 4mm"}))
            t3_pending = (r.get("tier") == "T3_DIRECTOR"
                          and r.get("auto_accepted") is False)
            check("gn_compile hollow（T3 待决）", t3_pending,
                  f"tier={r.get('tier')} accepted={r.get('auto_accepted')}")

            # 导演通过
            r = parse(await session.call_tool("gn_accept", {"note": "掏空壁厚合理"}))
            check("gn_accept 回 IDLE", r.get("state") == "IDLE", r)

            # 机械门禁
            r = parse(await session.call_tool("gn_verify", {"label": "mcp_smoke"}))
            check("gn_verify PASS", r.get("ok") is True, r.get("failures", r))

            # 渲染 diff
            r = parse(await session.call_tool("gn_render_diff", {"label": "mcp_smoke"}))
            img_len = len(r.get("render_diff_b64", "") or "")
            check("gn_render_diff 有图", img_len > 1000, f"b64={img_len}B")

            # 状态导出
            r = parse(await session.call_tool("gn_export_state", {}))
            check("gn_export_state schema /1.1",
                  r.get("schema") == "mug-console-state/1.1",
                  r.get("schema"))
            check("gn_export_state kpis 在场（M10-4）",
                  "kpis" in r, True)
            check("段落数=2", len(r.get("steps", [])) == 2, len(r.get("steps", [])))

            # R12 反例：SAFE_MODE=1 下 execute_blender_code 跑白名单外 import 必须被拦
            # （原版工具返回纯文本而非 JSON——不能走 parse）
            raw = (await session.call_tool("execute_blender_code", {
                "code": "import os"})).content[0].text
            blocked = ("Sandbox" in raw or "violation" in raw.lower()
                       or "safe mode" in raw.lower()
                       or "not allowed" in raw.lower()
                       or raw.strip().startswith("Error"))
            check("R12 反例：SAFE_MODE 拦截 import os", blocked, raw[:120])

            # 工单 3a 反例：重复 gn_compile 同名段 → 结构化 ok=false（不再非 JSON 裸异常）
            r = parse(await session.call_tool("gn_compile", {
                "spec_json": json.dumps(SPEC_BODY),
                "assumption": "圆柱杯体比例合理"}))
            dup = (r.get("ok") is False
                   and (r.get("error", {}).get("error_code") is not None
                        or r.get("error_code") is not None))
            check("重复段 → 结构化 ok=false（3a 修复）", dup,
                  str(r)[:140])

            # 工单 3b：gn_reset → 清段 + 删 modifier → begin 后同名段可重编译
            r = parse(await session.call_tool("gn_reset", {}))
            check("gn_reset ok", r.get("ok") is True,
                  f"removed={len(r.get('removed_modifiers', []))}")
            r = parse(await session.call_tool("gn_begin", {
                "obj_name": "Mug", "brief": "reset 后重开", "policy": "NORMAL"}))
            check("reset 后 gn_begin ok", r.get("ok") is True, r)
            r = parse(await session.call_tool("gn_compile", {
                "spec_json": json.dumps(SPEC_BODY),
                "assumption": "重置后重建 body"}))
            check("reset 后同名段可重编译", r.get("tier") is not None,
                  f"tier={r.get('tier')}")

    failed = [x for x in ROWS if not x["ok"]]
    print(f"\nMCP SMOKE: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
    out = BRIDGE / "mcp_smoke_result.json"
    out.write_text(json.dumps(ROWS, ensure_ascii=False, indent=1), encoding="utf-8")
    print("result ->", out)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main_async())
