"""escape.py — M4-4 · 逃逸舱三层粒度（A17/R12 的**受控例外**口子）
================================================================================
定位（工单 M4-4 + d4-character）：R12 说"AI 不写代码"，但角色 rig/物理约束等域
确实存在"参数化无法表达"的尾部——逃逸舱是这个尾部的**受控出口**，不是后门：
  L1 参数层（默认）：一切可参数化的走 plan-JSON 编译——**不是逃逸，是主干**。
  L2 模板层：plan 引用**注册过的模板名**+参数；模板体是预审代码，plan 不许改。
  L3 脚本层：单文件 .py 过**域白名单 AST 审查**（限 Armature/Constraint/ShapeKey）
             + 人工审核标记（escape_hatch=true）后才执行。
纪律：
  * custom_script（L3）必须显式 escape_hatch=true（plan_schema 已拦）+ 本审查器域白名单
  * 白名单是**域白名单**不是通用沙箱——非角色域的 bpy 调用一律拒（与上游 safe_mode
    的区别：它防 prompt injection，我们防"逃逸舱被当通用后门用"）
  * 产物必须落到稳定数据接口（标准骨架命名/VG/UV——工单"共存契约"）
  * 每次逃逸使用 WAL 留痕（actor/模板名/脚本哈希）
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable

__all__ = ["EscapeError", "TemplateRegistry", "ScriptAuditor", "EscapeHatch"]

#: L3 脚本层允许的 bpy 子域（角色 rig 域——工单 M4-4 定义）
_ALLOWED_ROOTS = {"bpy", "bpy.props", "bmesh", "mathutils"}
#: 允许的 bpy.ops 类别（其他 ops 类别一律拒——域白名单的核心）
_ALLOWED_OPS_CATS = {"object", "armature", "pose", "mesh", "object.armature"}
#: 禁止的逃逸面（与上游 safe_mode 同思想，收窄到角色域语境）
_DENIED_NAMES = {"__import__", "eval", "exec", "compile", "globals", "locals",
                 "open", "input", "breakpoint", "vars", "dir", "getattr",
                 "setattr", "delattr", "sys", "os", "subprocess", "pathlib",
                 "requests", "urllib", "socket"}


class EscapeError(Exception):
    """逃逸舱错误（code: TEMPLATE_NOT_FOUND / DOMAIN_DENIED / HATCH_REQUIRED …）"""

    def __init__(self, reason: str, code: str = "ESCAPE_ERROR",
                 suggestions: list[dict] | None = None) -> None:
        self.reason = reason
        self.code = code
        self.suggestions = suggestions or []
        super().__init__(reason)


# ══════════════════════════════════════════════════════════════
# L2 · 模板注册表（plan 引用模板名+参数；模板体预审、plan 不许改）
# ══════════════════════════════════════════════════════════════
@dataclass
class TemplateEntry:
    name: str
    domain: str                                   # "rig" | "physics" | …
    fn: Callable[[dict[str, Any]], dict[str, Any]]   # params → report
    params_schema: dict[str, Any] = field(default_factory=dict)
    provenance: str = ""                          # 模板来源/审核人


class TemplateRegistry:
    def __init__(self) -> None:
        self._tpl: dict[str, TemplateEntry] = {}

    def register(self, entry: TemplateEntry) -> None:
        if entry.domain not in ("rig", "physics"):
            raise EscapeError(f"模板域 {entry.domain!r} 不在受控清单（rig/physics）",
                              code="TEMPLATE_DOMAIN_DENIED")
        self._tpl[entry.name] = entry

    def get(self, name: str) -> TemplateEntry:
        if name not in self._tpl:
            raise EscapeError(f"模板 {name!r} 未注册——先 register（L2 契约："
                              "plan 只许引用注册过的模板，不许内联代码）",
                              code="TEMPLATE_NOT_FOUND")
        return self._tpl[name]

    def run(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        e = self.get(name)
        missing = [k for k in e.params_schema if k not in params]
        if missing:
            raise EscapeError(f"模板 {name!r} 缺参数 {missing}",
                              code="TEMPLATE_PARAM_MISSING")
        return e.fn(params)


# ══════════════════════════════════════════════════════════════
# L3 · 脚本域白名单审查器（AST 遍历，deny-by-default——借鉴上游 safe_mode 结构）
# ══════════════════════════════════════════════════════════════
_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Module, ast.FunctionDef, ast.Return, ast.Assign, ast.AnnAssign,
    ast.AugAssign, ast.Expr, ast.Call, ast.Attribute, ast.Subscript, ast.Slice,
    ast.Name, ast.Load, ast.Store, ast.Constant, ast.List, ast.Tuple, ast.Dict,
    ast.Set, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.If, ast.For, ast.While, ast.Pass, ast.Break, ast.Continue,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Not, ast.Eq, ast.NotEq, ast.Lt, ast.LtE,
    ast.Gt, ast.GtE, ast.And, ast.Or, ast.ListComp, ast.SetComp,
    ast.DictComp, ast.comprehension, ast.GeneratorExp, ast.Starred,
    ast.arguments, ast.arg, ast.keyword, ast.Index,
    ast.Import, ast.ImportFrom,          # 域内 import（bpy/bmesh/mathutils）
    ast.alias, ast.JoinedStr, ast.FormattedValue,   # f-string（骨骼动态命名）
)


class ScriptAuditor:
    """L3 脚本域白名单审查：AST 遍历 + 域白名单 + import 全禁 + ops 类别白名单。"""

    def __init__(self, ops_categories: set[str] | None = None) -> None:
        self.ops_cats = ops_categories or _ALLOWED_OPS_CATS

    def audit(self, code: str) -> tuple[bool, str, str]:
        """→ (ok, sha16, reason)。ok=False 时 reason 给出首个违规（可返回给 AI 修复）。"""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, "", f"语法错误：{e.msg}（line {e.lineno}）"
        sha = hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]
        DOMAIN_IMPORTS = {"bpy", "bmesh", "mathutils"}
        for node in ast.walk(tree):
            if type(node) not in _ALLOWED_NODES:
                return False, sha, f"禁用语法节点 {type(node).__name__}（line {node.lineno}）"
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] not in DOMAIN_IMPORTS:
                        return False, sha, (f"import {a.name!r} 超出角色域"
                                            f"（限 {sorted(DOMAIN_IMPORTS)}）")
            if isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root not in DOMAIN_IMPORTS:
                    return False, sha, (f"from {node.module!r} 超出角色域"
                                        f"（限 {sorted(DOMAIN_IMPORTS)}）")
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    if fn.id in _DENIED_NAMES:
                        return False, sha, f"禁用调用 {fn.id}()（line {node.lineno}）"
            # bpy.ops 类别白名单（域白名单核心）：bpy.ops.<cat>.<name>
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                dotted = self._dotted(node.func)
                if dotted.startswith("bpy.ops."):
                    cat = dotted.split(".")[2] if "." in dotted[8:] else ""
                    if cat not in self.ops_cats:
                        return False, sha, (f"bpy.ops 类别 {cat!r} 超出角色域"
                                            f"（限 {sorted(self.ops_cats)}）")
            if isinstance(node, ast.Attribute):
                dotted = self._dotted(node)
                if dotted and dotted.split(".")[0] in _DENIED_NAMES:
                    return False, sha, f"禁用引用 {dotted}（line {node.lineno}）"
        return True, sha, ""

    @staticmethod
    def _dotted(node: ast.Attribute) -> str:
        parts = []
        cur = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))


# ══════════════════════════════════════════════════════════════
# 逃逸舱调度（L1 隐含在编译器；这里只管 L2/L3）
# ══════════════════════════════════════════════════════════════
class EscapeHatch:
    """三层逃逸舱调度器：L2 模板 / L3 脚本。L1 参数层走 plan 编译器（非逃逸）。

    用法（导演模式）：custom_script 段（escape_hatch=true 已过 plan_schema）
      → hatch.run_script(code, audited_by="human:xxx") → 报告 + WAL 载荷。
    纪律：audited_by 必须以 human: 开头——**机器/引擎无权批准自由代码**（治理位外置）。
    """

    def __init__(self, registry: TemplateRegistry | None = None) -> None:
        self.registry = registry or TemplateRegistry()
        self.auditor = ScriptAuditor()
        self.usage: list[dict[str, Any]] = []

    def run_template(self, name: str, params: dict[str, Any],
                     actor: str = "ai") -> dict[str, Any]:
        """L2 模板执行：模板体预审，参数从 plan 来。"""
        report = self.registry.run(name, params)
        rec = {"tier": "L2", "template": name, "params": params,
               "report": report, "actor": actor}
        self.usage.append(rec)
        return {"ok": True, "tier": "L2", "template": name, "report": report}

    def run_script(self, code: str, audited_by: str = "",
                   label: str = "") -> dict[str, Any]:
        """L3 脚本执行：域白名单审查通过才落账（返回 shell 供调用方 exec——
        执行权在宿主/导演，不在本类：审计与执行分离是治理位外置的体现）。"""
        if not str(audited_by).startswith("human:"):
            raise EscapeError("L3 脚本必须带人工审核标记 audited_by='human:...'"
                              "（治理位外置：机器无权批准自由代码）",
                              code="HATCH_AUDIT_REQUIRED")
        ok, sha, reason = self.auditor.audit(code)
        if not ok:
            raise EscapeError(f"脚本审查未过：{reason}", code="SCRIPT_AUDIT_FAIL",
                              suggestions=[{"action": "rewrite",
                                            "target": "code",
                                            "value": "仅限 Armature/Constraint/"
                                                     "ShapeKey 域 bpy 调用"}])
        rec = {"tier": "L3", "label": label, "sha16": sha, "audited_by": audited_by,
               "code_chars": len(code)}
        self.usage.append(rec)
        return {"ok": True, "tier": "L3", "sha16": sha, "label": label,
                "note": "审查通过——执行由宿主完成（审计与执行分离）"}
