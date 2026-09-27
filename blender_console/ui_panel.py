"""ui_panel.py — M9-2 Blender N 面板最小控制台（可信模块侧）。

定位（不变量）：**前端是状态视图，不是新真源**——面板只读 export_state 语义的
快照数据 + 提交 A/B 决策（决策协议本体在 console.ab_commit，M5 已落地）。
A/B 的**发起**是 AI 的活（对话/MCP 工具），面板不提供 prepare 按钮。

数据通路：gn_bridge（部署侧，R16 允许的方向）在 gn_begin 后调用
``ui_panel.bind(console)``；面板 draw 每帧调用 ``panel_data()`` 取数——
panel_data 是本模块唯一有逻辑的函数，headless 可测（m92_live.py）；
draw 方法只做格式化，视觉布局不做机验（背景模式无 GUI 上下文，诚实边界）。

可信模块注册 UI 不受 exec 沙箱限制（M9-2 设计前提：AI 写数据，可信代码写 UI）。

跑法（真机验收）：blender --background --factory-startup --python m92_live.py

⚠ 注：本模块**禁用** `from __future__ import annotations`——Blender 靠
`__annotations__` 里的真实 Property 对象发现 Operator 属性，postponed
evaluation 会把注解变字符串 → 属性静默丢失 → bpy.ops 报
"keyword unrecognized"（m92_live 首跑实测抓出）。
"""
from typing import Any

# ── 绑定钩子（gn_bridge 注入；面板无权创建会话） ──────────────
_BOUND: Any = None


def bind(console: Any) -> None:
    global _BOUND
    _BOUND = console


def unbind() -> None:
    global _BOUND
    _BOUND = None


def is_bound() -> bool:
    return _BOUND is not None


# ── 数据面（headless 可测——draw 只消费这里） ─────────────────
def panel_data() -> dict[str, Any]:
    """面板状态快照。永不抛异常（draw 每帧调用，坏数据降级显示）。"""
    if _BOUND is None:
        return {"bound": False, "ab_pending": False, "segments": [],
                "mode": "—", "schema": "—", "kpis": {}, "obj": None}
    try:
        st = _BOUND.export_state().data
    except Exception as exc:  # noqa: BLE001  降级显示，不炸 UI
        return {"bound": True, "error": repr(exc)[:120], "ab_pending": False,
                "segments": [], "mode": "—", "schema": "—", "kpis": {},
                "obj": None}
    ab = getattr(_BOUND, "_ab", None)
    segments = [
        {"name": name,
         "revision": (v or {}).get("revision", 0),
         "dirty": bool((v or {}).get("dirty")),
         "n_steps": len((v or {}).get("steps", []))}
        for name, v in (st.get("segments") or {}).items()
    ]
    return {"bound": True, "error": None,
            "obj": getattr(_BOUND, "obj", None) and _BOUND.obj.name,
            "schema": st.get("schema", "—"), "mode": st.get("mode", "—"),
            "segments": segments,
            "kpis": st.get("kpis") or {},
            "ab_pending": ab is not None,
            "ab_seg": ab.get("seg") if isinstance(ab, dict) else None}


def ab_pending() -> bool:
    return panel_data()["ab_pending"]


# ── Blender UI（import 时才需要 bpy；纯函数部分无 bpy 可无头测） ──
CLASSES: list = []


def register() -> None:
    """注册 Operator + Panel（幂等：已注册则跳过）。"""
    import bpy  # noqa: PLC0415

    if is_registered():
        return

    class MUGCONSOLE_OT_ab_commit(bpy.types.Operator):
        """提交当前 A/B 决策（甲/乙/reroll）——落账走 console.ab_commit 真写链"""
        bl_idname = "mugconsole.ab_commit"
        bl_label = "A/B 提交"
        bl_options = {"REGISTER"}

        choice: bpy.props.StringProperty(default="甲")  # noqa: N815
        confidence: bpy.props.IntProperty(default=80, min=5, max=95)  # noqa: N815
        note: bpy.props.StringProperty(default="")  # noqa: N815

        @classmethod
        def poll(cls, _context) -> bool:
            return is_bound() and ab_pending()

        def execute(self, _context) -> set:
            r = _BOUND.ab_commit(self.choice, self.confidence, self.note)
            if r.ok:
                self.report({"INFO"}, f"A/B 已提交：{self.choice}")
                return {"FINISHED"}
            err = (r.error or {}).get("error_code", "?")
            self.report({"ERROR"}, f"ab_commit 拒绝：{err}")
            return {"CANCELLED"}

    class VIEW3D_PT_mug_console(bpy.types.Panel):
        """Mug 控制台（View3D N 面板）：段落状态 × verifier × override 率 × A/B 提交"""
        bl_label = "Mug 控制台"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "Mug"

        def draw(self, context) -> None:  # noqa: ARG002
            l = self.layout
            d = panel_data()
            if not d["bound"]:
                l.label(text="未绑定会话（gn_begin 后出现）", icon="INFO")
                return
            if d.get("error"):
                l.label(text="状态读取失败（见系统控制台）", icon="ERROR")
                return
            box = l.box()
            box.label(text=f"对象：{d['obj'] or '—'}｜mode {d['mode']}")
            box.label(text=f"schema {d['schema']}")
            segbox = l.box()
            segbox.label(text=f"段落 ×{len(d['segments'])}")
            for s in d["segments"][:8]:          # 上限 8 行防长列表糊屏
                mark = "●" if s["dirty"] else "✓"
                segbox.label(text=f"{mark} {s['name']}  rev{s['revision']}"
                                  f"  {s['n_steps']}步")
            if len(d["segments"]) > 8:
                segbox.label(text=f"…共 {len(d['segments'])} 段")
            k = d["kpis"] or {}
            if "override_rate" in k:
                rate = k["override_rate"]
                rate_s = "—" if rate is None else f"{rate * 100:.1f}%"
                l.label(text=f"override 率 {rate_s}"
                             f"（{k.get('overrides', '—')}/{k.get('ab_decisions', '—')}）")
            abox = l.box()
            if d["ab_pending"]:
                abox.label(text=f"A/B 待决：{d['ab_seg']}", icon="QUESTION")
                row = abox.row(align=True)
                for ch in ("甲", "乙", "reroll"):
                    op = row.operator("mugconsole.ab_commit", text=ch)
                    op.choice = ch
            else:
                abox.label(text="无待决 A/B 卡（由 AI 在对话中发起）")

    CLASSES[:] = [MUGCONSOLE_OT_ab_commit, VIEW3D_PT_mug_console]
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister() -> None:
    import bpy  # noqa: PLC0415

    for c in reversed(CLASSES):
        if c is not None and hasattr(bpy.types, c.__name__):
            try:
                bpy.utils.unregister_class(c)
            except Exception:  # noqa: BLE001  已被外部注销等场景
                pass
    CLASSES[:] = []


def is_registered() -> bool:
    import bpy  # noqa: PLC0415

    return bool(CLASSES) and "VIEW3D_PT_mug_console" in dir(bpy.types)
