"""client_e2e.py — M8-R2 端到端全链验证 · 客户端（TCP 直连，FastMCP 层已静态验证）

链路：本脚本（stub mcp 后 import 真实 BlenderConnection）──TCP 9876──►
fork 插件 handlers dict ──import──► gn_bridge ──► blender_console（M1-M7 全家）

场景：NORMAL 策略导演会话——body(T1 自动) / hollow(T3+accept) / handle(T3+accept) /
finish(T3+accept) → verify → render_diff ×2（diff 出图）→ A/B 一轮 → export_state。
"""
import json
import sys
import time
import types
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "brickfly_mcp_src"))

# ── stub mcp（FastMCP 层静态已验；TCP 层走真实 BlenderConnection）──
import importlib.util as _ilu
if _ilu.find_spec("mcp") is None:          # 真实 mcp 已装（venv）则用真 FastMCP
    mcp = types.ModuleType("mcp")
    ms = types.ModuleType("mcp.server")
    mf = types.ModuleType("mcp.server.fastmcp")

    class FastMCP:
        def __init__(self, *a, **k):
            pass

        def tool(self, *a, **k):
            def deco(f):
                return f
            return deco

    mf.FastMCP = FastMCP
    mf.Context = object
    mf.Image = object
    sys.modules.update({"mcp": mcp, "mcp.server": ms, "mcp.server.fastmcp": mf})

from brickfly_mcp import server as gn_server  # noqa: E402  真实模块（含 BlenderConnection）

ROWS: list[dict] = []


def check(name, fn, expect=True):
    try:
        val = fn()
        if val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True, "detail": str(val)[:120]})
        print(f"  PASS  {name}  {str(val)[:100]}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:200]})
        print(f"  FAIL  {name}  {exc!r}")


# ── 连接（重试等 Blender 起服务）────────────────────────────
conn = gn_server.BlenderConnection("localhost", 9876)
ok = False
for i in range(45):
    if conn.connect():              # connect() 失败返回 False 不抛——必须查返回值
        ok = True
        print(f"connected (attempt {i + 1})")
        break
    time.sleep(1)
assert ok, "9876 连接失败——Blender 侧未起"


def cmd(t, p=None):
    r = conn.send_command(t, p or {})
    if isinstance(r, dict) and r.get("status") == "error":
        raise RuntimeError(f"{t}: {r.get('message', r)}")
    if isinstance(r, dict) and "result" in r and "status" in r:
        r = r["result"]                                # 兼容两种响应形态
    return r


print("== M8-R2 端到端全链 ==")
# 0. 传输层
pong = cmd("ping")
check("TCP ping/pong", lambda: pong.get("pong"), True)

# 1. F-148 能力自报
info = cmd("get_addon_info")
gn_caps = [c for c in info["capabilities"] if c.startswith("gn_")]
check("F-148 能力自报含 11 个 gn 工具", lambda: len(gn_caps), 11)

# 2. 导演会话
beg = cmd("gn_begin", {"obj_name": "Mug", "brief": "e2e 马克杯", "policy": "NORMAL"})
check("gn_begin", lambda: beg["ok"], True)

# 3. 四段纯 op 编译（T1/T3 混合）
SPECS = [
    {"id": "body", "op": "cylinder", "consumes_input": False,
     "parameters": [{"name": "Radius", "type": "FLOAT", "value": 0.04},
                    {"name": "Depth", "type": "FLOAT", "value": 0.095}],
     "assumption": "圆柱杯体比例合理"},
    {"id": "hollow", "op": "boolean_diff", "consumes_input": True, "parameters": [],
     "operand": {"op": "transform", "translation": [0.0, 0.0, 0.01],
                 "source": {"op": "cylinder", "radius": 0.036, "depth": 0.085}},
     "assumption": "掏空壁厚 4mm"},
    {"id": "handle", "op": "join_geometry", "consumes_input": True,
     "parameters": [{"name": "Handle_Thickness", "type": "FLOAT", "value": 0.008}],
     "operand": {"op": "transform", "translation": [0.062, 0.0, 0.045],
                 "source": {"op": "transform", "rotation_deg": [90.0, 0.0, 0.0],
                            "source": {"op": "sweep_circle", "ring_radius": 0.032}}},
     "assumption": "8mm 把手"},
    {"id": "finish", "op": "subdivide", "consumes_input": True,
     "parameters": [{"name": "Level", "type": "INT", "value": 1}],
     "assumption": "1 级细分够圆滑"},
]
tiers = []
for sp in SPECS:
    sp_clean = {k: v for k, v in sp.items() if k != "assumption"}   # 假设是提案元数据，不进 plan
    r = cmd("gn_compile", {"spec_json": json.dumps(sp_clean, ensure_ascii=False),
                                      "assumption": sp["assumption"]})
    if not r.get("auto_accepted", False) and "compile_error" in r:
        print(f"  COMPILE-ERROR {sp['id']}:", r["compile_error"])
    tiers.append((sp["id"], r.get("tier"), r.get("auto_accepted")))
    if r.get("auto_accepted") is False and "compile_error" not in r:
        a = cmd("gn_accept", {"note": f"{sp['id']} 通过"})
        assert a["state"] == "IDLE"
print("  tiers:", tiers)
check("四段全编译通过", lambda: all(t is not None for _, t, _ in tiers), True)
check("分档正确（hollow/handle/finish 为 T3）",
      lambda: [t for i, t, _ in tiers if i in ("hollow", "handle", "finish")],
      ["T3_DIRECTOR"] * 3)

# 4. 机械门禁
v = cmd("gn_verify", {"label": "e2e"})
check("verifier PASS", lambda: v["ok"], True)

# 5. 渲染 diff（两次：首帧基线 + 二帧 diff）
r1 = cmd("gn_render_diff", {"label": "e2e_a"})
r2 = cmd("gn_render_diff", {"label": "e2e_b"})
check("首帧有渲染图（ directors 会话不裸奔）", lambda: len(r1["render_diff_b64"]) > 1000, True)
check("二帧确定性（changed_px=0）", lambda: r2["data"].get("changed_px"), 0)

# 6. A/B 一轮（finish 段细分 1 vs 2）
ab = cmd("gn_ab_prepare", {
    "variants_json": json.dumps([{"Level": 1}, {"Level": 2}]),
    "ai_preferred": 1, "ai_reason": "2 级更圆滑"})
check("ab_prepare ok", lambda: ab["ok"], True)
check("甲乙两图在场", lambda: set(ab["data"]["variants"]), {"甲", "乙"})
com = cmd("gn_ab_commit", {"choice": "乙", "confidence": 80,
                                      "note": "选细分 2"})
check("ab_commit ok", lambda: com["ok"], True)
check("偏好模型收到决定（=乙变体，洗牌随机）",
      lambda: com["data"]["applied"],
      com["data"]["reveal"]["mapping"]["乙"])

# 7. 状态导出
st = cmd("gn_export_state", {})
check("schema=mug-console-state/1.1", lambda: st["schema"], "mug-console-state/1.1")
check("kpis 在场（M10-4）", lambda: "kpis" in st, True)
check("段落数=4", lambda: len(st["steps"]), 4)
check("override 率在场", lambda: "overrides" in st, True)

failed = [r for r in ROWS if not r["ok"]]
print(f"\nM8-R2 E2E: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
for f in failed:
    print("  FAILED:", f["case"], "->", f.get("detail"))
out = ROOT / "m8_bridge" / "e2e_result.json"
out.write_text(json.dumps(ROWS, ensure_ascii=False, indent=1), encoding="utf-8")
print("result ->", out)
sys.exit(1 if failed else 0)
