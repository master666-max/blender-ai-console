"""gn_bridge.py — M8-R2b · blender_console 的 Blender 侧部署桥（薄封装）
================================================================================
依赖方向（R16）：本模块（上游 fork 侧部署件）──import──► blender_console（本项目）。
单向：blender_console 永不 import 本模块或任何上游代码。

职责：把 Console/DirectorSession 暴露成 8 个可被 addon handlers 透传调用的函数。
设计：单例 Console（附着在一个 Blender 物体上）；deploy 根由 addon 的 handlers
在 import 前注入 sys.path（上游 deploy-roots 机制，11 分册）。
契约：所有函数返回 dict（M9-1 tool return / 结构化错误），字符串化由 server 层做。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

DEPLOY_ROOT = None  # 由 addon handlers 注入（blender_console 所在目录）


def _ensure_console_module():
    if "gn_adapter" in sys.modules:
        return
    if DEPLOY_ROOT and str(DEPLOY_ROOT) not in sys.path:
        sys.path.insert(0, str(DEPLOY_ROOT))
    for mod in ("m1_core", "gn_adapter", "gn_verify", "experience", "plan_schema",
                "op_compiler", "render_diff", "gn_session", "console", "director",
                "ui_panel"):
        importlib.import_module(mod)


def _panel_attach() -> str:
    """M9-2：N 面板挂载（注册幂等 + 绑定当前会话）。失败不阻塞工具面
    （热拔插原则：缺省零依赖），但结果**显式返回**不静默。"""
    try:
        ui = importlib.import_module("ui_panel")
        if not ui.is_registered():
            ui.register()
        if _STATE["console"] is not None:
            ui.bind(_STATE["console"])
        return "bound"
    except Exception as exc:  # noqa: BLE001
        return f"unavailable: {exc!r}"[:120]


def _get_console_module():
    _ensure_console_module()
    return importlib.import_module("console")


_STATE: dict[str, Any] = {"console": None, "director": None, "obj": None}


# ── 生命周期 ──────────────────────────────────────────────────
def gn_begin(obj_name: str = "Mug", brief: str = "",
             policy: str = "NORMAL", library_dir: str | None = None) -> dict:
    """导演会话入口：建单例 Console + DirectorSession（附着 obj_name）。"""
    import bpy  # noqa: PLC0415
    _ensure_console_module()
    console_mod = _get_console_module()
    from director import NormalPolicy, StrictPolicy, AutoPilotPolicy  # noqa: PLC0415
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        return {"ok": False, "error": {"error_code": "OBJECT_NOT_FOUND",
                                       "reason": f"物体 {obj_name!r} 不存在"}}
    if _STATE["console"] is None or _STATE["obj"] != obj_name:
        con = console_mod.Console(_console_adapter(), obj,
                                  workdir=Path(library_dir) if library_dir else None)
        _STATE["console"] = con
        _STATE["obj"] = obj_name
        _STATE["director"] = None
    if _STATE["director"] is None:
        pol = {"NORMAL": NormalPolicy(), "STRICT": StrictPolicy(),
               "AUTOPILOT": AutoPilotPolicy()}.get(policy.upper(), NormalPolicy())
        _STATE["director"] = importlib.import_module("director").DirectorSession(
            _STATE["console"], pol)
        _STATE["director"].begin(brief=brief)
    if library_dir:
        _STATE["console"].attach_experience(
            library_dir=Path(library_dir) / "experience_library.jsonl")
    return {"ok": True, "obj": obj_name, "policy": policy,
            "director": _STATE["director"].policy.name,
            "panel": _panel_attach()}


def gn_reset(obj_name: str | None = None) -> dict:
    """重置导演会话（工单 3b）：清单例状态；给 obj_name 时删其全部 GN modifier/节点组。

    语义：附着物体是 GN 会话专用目标（bootstrap 语义）——重开对话前调用，
    避免 FlowDAG"step 重复"与 modifier 堆积。不碰非 NODES modifier。
    """
    import bpy  # noqa: PLC0415
    removed: list[str] = []
    name = obj_name or _STATE.get("obj")
    target = bpy.data.objects.get(name) if name else None
    if target is not None:
        for mod in list(target.modifiers):
            if mod.type == "NODES":
                ng = mod.node_group
                removed.append(mod.name)
                target.modifiers.remove(mod)
                if ng is not None and ng.users == 0:
                    bpy.data.node_groups.remove(ng)
    _STATE["console"] = None
    _STATE["director"] = None
    _STATE["obj"] = None
    try:
        importlib.import_module("ui_panel").unbind()   # 面板不得显示 stale 会话
    except Exception:  # noqa: BLE001  模块未加载过——无可解绑
        pass
    return {"ok": True, "obj": name, "removed_modifiers": removed}


def _console_adapter():
    """GNAdapter 的轻量适配：Console 需要 GNAdapter（版本守卫）。"""
    gn_adapter = importlib.import_module("gn_adapter")
    return gn_adapter.GNAdapter(__import__("bpy"))


def _con() -> Any:
    if _STATE["console"] is None:
        raise RuntimeError("gn_bridge.begin(obj_name) 未调用——先开会话")
    return _STATE["console"]


def gn_compile(spec_json: str | dict, assumption: str = "") -> dict:
    """plan_json: 单段落 spec（JSON 字符串或 dict，plan_schema 契约）。走导演 propose。"""
    import json as _json
    _con()
    ds = _STATE["director"]
    if ds is None:
        return {"ok": False,
                "error": {"error_code": "NO_SESSION",
                          "failed_node": None,
                          "reason": "导演会话未开或刚被 gn_reset——先调用 gn_begin",
                          "suggestions": ["gn_begin(obj_name='Mug', policy='NORMAL')"]}}
    spec = _json.loads(spec_json) if isinstance(spec_json, str) else spec_json
    assum = assumption or (spec.get("assumption") if isinstance(spec, dict) else "") or ""
    return ds.propose(spec, assumption=assum)   # propose 返回 dict（已含三件套字段）


def gn_accept(note: str = "") -> dict:
    """导演通过待决提案（T3 阻塞的解除口——M7 状态机）。"""
    ds = _STATE["director"]
    if ds is None:
        raise RuntimeError("gn_bridge.begin 未调用")
    return ds.accept(note=note)


def gn_verify(label: str = "") -> dict:
    return _con().verify(label).to_tool_return()


def gn_checkpoint(name: str) -> dict:
    return _con().checkpoint(name).to_tool_return()


def gn_revert(target: str) -> dict:
    """target: GoodPoint 名 或 "pop"（删最后一层）。"""
    con = _con()
    if target == "pop":
        return con.pop_layer().to_tool_return()
    return con.revert_to_checkpoint(target).to_tool_return()


def gn_render_diff(label: str = "") -> dict:
    return _con().render_diff(label).to_tool_return()


def gn_ab_prepare(variants_json: str | list[dict], ai_preferred: int = 0,
                  ai_reason: str = "") -> dict:
    import json as _json
    seg = _ab_seg()
    variants = _json.loads(variants_json) if isinstance(variants_json, str) else variants_json
    return _con().ab_prepare(seg, variants,
                             ai_preferred=ai_preferred,
                             ai_reason=ai_reason).to_tool_return()


def gn_ab_commit(choice: str, confidence: int, note: str = "") -> dict:
    return _con().ab_commit(choice, confidence, note=note).to_tool_return()


def gn_export_state() -> dict:
    return _con().export_state().data


def _ab_seg() -> str:
    pending = _STATE["director"].pending if _STATE["director"] else None
    if pending:
        return pending["seg"]
    order = getattr(_con(), "order", [])
    return order[-1] if order else "handle"
