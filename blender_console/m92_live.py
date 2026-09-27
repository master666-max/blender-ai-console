"""m92_live.py — M9-2 N 面板最小控制台真机验收（Blender 5.2.1）。

跑法：blender --background --factory-startup --python m92_live.py

验收面（panel_data 是唯一逻辑面，draw 只是格式化——背景模式无 GUI 上下文，
视觉布局不做机验，诚实边界登记于模块 docstring）：
  [1] 未绑定态降级   [2] 绑定后数据面（段落/obj/kpis/ab_pending）
  [3] 注册幂等 + poll 负例   [4] A/B 卡经操作符提交（甲）→ 落账生效
  [5] reroll 出口   [6] 无卡时 poll 拒绝（RuntimeError）   [7] 坏 console 降级
  [8] 注册/卸载循环
"""
import json
import shutil
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy  # noqa: E402

import ui_panel  # noqa: E402
from gn_adapter import GNAdapter  # noqa: E402
from console import Console  # noqa: E402

OUT = ROOT.parent / "2026-09-26-blender"
ROWS: list[dict] = []


def check(name, fn, expect=True):
    try:
        val = fn()
        if val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True, "detail": str(val)[:140]})
        print(f"  PASS  {name}  {str(val)[:100]}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:200]})
        print(f"  FAIL  {name}  {exc!r}")


print(f"Blender {bpy.app.version_string}")
bpy.ops.wm.read_factory_settings(use_empty=True)

shutil.rmtree(HERE / "_m92_wal", ignore_errors=True)
WALDIR = HERE / "_m92_wal"

print("\n[1] 未绑定态降级")
ui_panel.unbind()
d = ui_panel.panel_data()
check("未绑定：bound=False", lambda: d["bound"], False)
check("未绑定：ab_pending 永不卡死", lambda: ui_panel.ab_pending(), False)

print("\n[2] 绑定真实 Console")
ad = GNAdapter(bpy)
bpy.ops.mesh.primitive_cylinder_add()
obj = bpy.context.active_object
obj.name = "MugPanel"
obj.data = bpy.data.meshes.new("Base_Panel")
con = Console(ad, obj, workdir=WALDIR)
check("S1 cylinder 编译", lambda: con.compile(
    {"id": "S1", "op": "cylinder",
     "parameters": [{"name": "radius", "value": 0.04},
                    {"name": "depth", "value": 0.09}]}).ok, True)
check("S2 subdivide 编译", lambda: con.compile(
    {"id": "S2", "op": "subdivide", "consumes_input": True,
     "parameters": [{"name": "level", "value": 1}]}).ok, True)
ui_panel.bind(con)
d = ui_panel.panel_data()
check("绑定：bound=True + obj 名", lambda: (d["bound"], d["obj"]), (True, "MugPanel"))
check("绑定：两段在面板数据面",
      lambda: tuple(s["name"] for s in d["segments"]), ("S1", "S2"))
check("段落字段齐全且 dirty 为 bool",
      lambda: all(set(s) >= {"name", "revision", "dirty", "n_steps"}
                  and isinstance(s["dirty"], bool) for s in d["segments"]), True)
check("kpis 含 override_rate（无决策 → None）",
      lambda: "override_rate" in d["kpis"] and d["kpis"]["override_rate"] is None, True)
check("无卡：ab_pending=False", lambda: d["ab_pending"], False)

print("\n[3] 注册幂等 + poll 负例")
ui_panel.register()
check("注册成功（类在 bpy.types）",
      lambda: "VIEW3D_PT_mug_console" in dir(bpy.types)
      and "MUGCONSOLE_OT_ab_commit" in dir(bpy.types), True)
ui_panel.register()  # 幂等：不抛即过
check("重复注册幂等", lambda: ui_panel.is_registered(), True)
op_cls = getattr(bpy.types, "MUGCONSOLE_OT_ab_commit")
check("无卡 poll=False", lambda: op_cls.poll(None), False)

print("\n[4] A/B 卡提交（先直调协议 bisect，再走操作符）")
r = con.ab_prepare("S1", [{"radius": 0.035}, {"radius": 0.045}],
                   ai_preferred=0, ai_reason="变细更轻盈")
check("ab_prepare 出卡", lambda: r.ok, True)
check("出卡后 poll=True + ab_seg",
      lambda: (op_cls.poll(None), ui_panel.panel_data()["ab_seg"]), (True, "S1"))
print("  BISECT: 直调 ab_commit ...", flush=True)
direct = con.ab_commit("甲", 80, "直调 bisect")
print(f"  BISECT: direct.ok={direct.ok} err={getattr(direct, 'error', None)}", flush=True)
check("直调 ab_commit 成功", lambda: direct.ok, True)
check("直调后卡清空", lambda: op_cls.poll(None), False)

r = con.ab_prepare("S1", [{"radius": 0.035}, {"radius": 0.045}],
                   ai_preferred=0, ai_reason="第二轮")
check("二次出卡", lambda: r.ok, True)
print("  BISECT: bpy.ops 调用 ...", flush=True)
res = bpy.ops.mugconsole.ab_commit(choice="甲", confidence=80, note="面板提交")
print(f"  BISECT: ops 返回 {res}", flush=True)
check("操作符提交返回 FINISHED", lambda: set(res) == {"FINISHED"}, True)
d = ui_panel.panel_data()
check("提交后卡清空（poll False）", lambda: op_cls.poll(None), False)
vp = con.vparams.get()
_rad = {k: v for k, v in vp.items() if "radius" in k.lower()}
check("决策落账：radius 已生效（∈变体值域）",
      lambda: bool(_rad) and any(v in (0.035, 0.045) for v in _rad.values()), True)
check("决策落账：override_rate 变数值",
      lambda: isinstance(d["kpis"]["override_rate"], float), True)

print("\n[5] reroll 出口")
check("再出卡", lambda: con.ab_prepare(
    "S1", [{"radius": 0.03}, {"radius": 0.05}], ai_preferred=1).ok, True)
res = bpy.ops.mugconsole.ab_commit(choice="reroll", confidence=80)
check("reroll FINISHED + 卡清空",
      lambda: set(res) == {"FINISHED"} and not op_cls.poll(None), True)

print("\n[6] 无卡时操作符拒绝（poll 闸生效）")
def _expect_runtime_error():
    try:
        bpy.ops.mugconsole.ab_commit(choice="甲", confidence=80)
    except RuntimeError:
        return True
    return False
check("无卡 bpy.ops 调用被 poll 拒绝（RuntimeError）",
      _expect_runtime_error, True)

print("\n[7] 坏 console 降级（draw 每帧调用永不炸）")
class _Bad:
    def export_state(self):
        raise ValueError("boom")
ui_panel.bind(_Bad())
d = ui_panel.panel_data()
check("坏 console：error 降级非空", lambda: bool(d.get("error")), True)
check("坏 console：ab_pending False（不误报）", lambda: d["ab_pending"], False)

print("\n[8] 绑定切换 + 注册/卸载循环")
ui_panel.bind(con)
check("重绑真 console 恢复", lambda: ui_panel.panel_data()["bound"], True)
ui_panel.unregister()
check("卸载后 is_registered=False",
      lambda: "VIEW3D_PT_mug_console" in dir(bpy.types), False)
ui_panel.register()
check("再注册恢复（GUI 用户可继续用）", lambda: ui_panel.is_registered(), True)
ui_panel.unbind()
check("收尾解绑", lambda: ui_panel.is_bound(), False)

failed = [r_ for r_ in ROWS if not r_["ok"]]
print(f"\nM9-2 PANEL LIVE: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
out = OUT / "m92_result.json"
out.write_text(json.dumps({"rows": ROWS}, ensure_ascii=False, indent=1),
               encoding="utf-8")
print("result ->", out)
sys.exit(1 if failed else 0)
