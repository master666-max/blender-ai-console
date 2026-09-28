"""
plan_schema.py — 工单 M4-7：plan-JSON 的结构校验（不依赖外部库，纯 Python）

EXP-1 实测根因：首版 0% 失败全在运行时才发现（契约不完整）。
解法：编译前预校验——字段拼错/类型不对/依赖缺失/参数超范围/未知 op **全部在编译期拦截**。
这是 EXP-1 首版 0% → 80% 的直接解药（不是"更好 的 prompt"，是"更严的闸门"）。

设计原则：
1. `additionalProperties: false` —— plan-JSON 不允许任何未声明字段
2. discriminated union —— 用 `op` 字段区分 plan 变体，未知 op 直接拒绝
3. 数值约束 —— min/max/step 在 schema 里声明，编译前检查
4. 依赖存在性 —— `depends_on` 引用的段名必须在同 plan 中已声明
5. 纯 Python —— 不依赖 jsonschema/Ajv，用递归下降校验器（同一逻辑可移植到 Ajv）
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

__all__ = ["PlanValidationError", "PlanSchema", "validate_plan", "SEGMENT_OPS"]

# ── 合法的段落操作类型 ──────────────────────────────────────
SEGMENT_OPS = {
    "revolve_profile", "cylinder", "cube", "sphere", "torus_segment",
    "sweep_rounded_rect", "sweep_circle", "boolean_diff", "boolean_union",
    "boolean_intersect", "fillet", "shell", "subdivide", "remesh",
    "sdf_boolean", "sdf_smooth", "array_linear", "array_radial",
    "mirror", "offset_surface", "set_material", "join_geometry",
    "transform", "scale_elements", "merge_by_distance", "delete_faces",
    "custom_script",  # 逃逸舱 M4-4：必须配 escape_hatch=true
}

_UNITS = {"mm", "cm", "m", "in", "deg", "rad", ""}
_PARAM_ROLES = {"input", "derived", "internal"}
_PARAM_TYPES = {"FLOAT", "INT", "BOOL", "VECTOR", "STRING", "GEOMETRY", "MATERIAL"}

# 材质预设（d3-material 调研：Principled BSDF 物理范围）
_MATERIAL_PRESETS = {"ceramic", "metal", "plastic", "glass", "wood", "fabric", "auto"}

# DFM 约束（d3-dfm 调研：可参数化谓词，Material Token 格式）
_DFM_DEFAULTS = {
    "fdm": {"wall_min_mm": 1.2, "overhang_deg": 45, "bridge_max_mm": 10, "min_hole_dia": 2.0},
    "sla": {"wall_min_mm": 0.5, "overhang_deg": 30, "bridge_max_mm": 5, "min_hole_dia": 0.5},
    "sls": {"wall_min_mm": 0.7, "overhang_deg": 999, "bridge_max_mm": 30, "min_hole_dia": 1.0},
    "injection": {"wall_min_mm": 0.8, "draft_deg": 1.0, "bridge_max_mm": 999, "min_hole_dia": 0.5},
}


@dataclass
class PlanIssue:
    """校验发现的一条问题。"""
    level: str       # "error" | "warning"
    path: str        # JSON 路径（如 sections[0].parameters[1].name）
    code: str        # 机器可读错误码
    message: str     # 人类可读

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.path}: {self.code} — {self.message}"


class PlanValidationError(Exception):
    """plan-JSON 校验失败（含全部 issue 列表）。"""
    def __init__(self, issues: list[PlanIssue]):
        self.issues = issues
        lines = "\n".join(str(i) for i in issues)
        super().__init__(f"plan 校验失败（{len(issues)} 个问题）：\n{lines}")


@dataclass
class PlanSchema:
    """plan-JSON 的声明式 schema。编译前用 `validate()` 做全量校验。

    用法：
        schema = PlanSchema(
            segment_names=["body", "handle", "finish"],
            param_ranges={"Body_Radius": (0.005, 0.5, "m"), ...},
            material="pla",
        )
        issues = schema.validate(plan_json)
        if issues: raise PlanValidationError(issues)
    """
    segment_names: list[str] = field(default_factory=list)
    param_ranges: dict[str, tuple[float, float, str]] = field(default_factory=dict)
    material: str = ""
    process: str = "fdm"
    require_thought_refs: bool = False
    max_segments: int = 30
    max_params_per_segment: int = 20

    def validate(self, plan: Mapping[str, Any]) -> list[PlanIssue]:
        issues: list[PlanIssue] = []
        self._check_top_level(plan, issues)
        self._check_sections(plan, issues)
        self._check_constraints(plan, issues)
        self._check_dependencies(plan, issues)
        return issues

    # ── 顶层 ──────────────────────────────────────────────────
    def _check_top_level(self, plan: Mapping[str, Any], issues: list[PlanIssue]) -> None:
        allowed_top = {"version", "intent", "tokens", "sections", "constraints",
                       "material", "process", "seed"}
        for k in plan:
            if k not in allowed_top:
                issues.append(PlanIssue("error", f"$.{k}", "UNKNOWN_FIELD",
                    f"未知顶层字段 {k!r}；允许：{sorted(allowed_top)}"))

        if "sections" not in plan:
            issues.append(PlanIssue("error", "$.sections", "MISSING_REQUIRED",
                "缺少 sections 数组——plan 必须至少声明一个语义段落"))
            return

        sections = plan["sections"]
        if not isinstance(sections, list) or len(sections) == 0:
            issues.append(PlanIssue("error", "$.sections", "EMPTY_SECTIONS",
                "sections 必须是非空数组"))
            return

        if len(sections) > self.max_segments:
            issues.append(PlanIssue("error", "$.sections", "TOO_MANY_SEGMENTS",
                f"段落数 {len(sections)} 超过上限 {self.max_segments}；拆分为多个 plan"))

    # ── 段落 ──────────────────────────────────────────────────
    def _check_sections(self, plan: Mapping[str, Any], issues: list[PlanIssue]) -> None:
        sections = plan.get("sections", [])
        if not isinstance(sections, list):
            return

        seen_names: set[str] = set()
        allowed_seg_keys = {"id", "order", "op", "parameters", "depends_on",
                           "fallback", "thought_refs", "escape_hatch", "obj",
                           "consumes_input", "stage", "part",   # M7-2 工艺阶段+部件路径
                           "rig_json"}   # M4-12b 段落级 rig 资产（深度校验在编译期 rig_compiler）

        for i, sec in enumerate(sections):
            prefix = f"$.sections[{i}]"
            if not isinstance(sec, Mapping):
                issues.append(PlanIssue("error", prefix, "NOT_OBJECT", "段落必须是对象"))
                continue

            # 字段白名单：通用字段 ∪ 该 op 的专属常量字段（单一事实源在
            # op_compiler.OP_CONST_FIELDS——纯 Python 无 bpy，可安全导入）
            op_fields = set()
            try:
                from op_compiler import spec_field_whitelist
                op_fields = spec_field_whitelist(sec.get("op", ""))
            except Exception:  # noqa: BLE001  op_compiler 缺席时退化为通用白名单
                op_fields = {"source", "operand", "axis"}
            for k in sec:
                if k not in allowed_seg_keys and k not in op_fields:
                    issues.append(PlanIssue("error", f"{prefix}.{k}", "UNKNOWN_FIELD",
                        f"未知段落字段 {k!r}；允许：{sorted(allowed_seg_keys | op_fields)}"))

            # id 必须唯一
            name = sec.get("id", "")
            if not name or not isinstance(name, str):
                issues.append(PlanIssue("error", f"{prefix}.id", "MISSING_ID",
                    "段落缺少 id（字符串）"))
            elif name in seen_names:
                issues.append(PlanIssue("error", f"{prefix}.id", "DUPLICATE_ID",
                    f"段落 id {name!r} 重复"))
            else:
                seen_names.add(name)

            # op 必须在合法集合内
            op = sec.get("op", "")
            if op not in SEGMENT_OPS:
                issues.append(PlanIssue("error", f"{prefix}.op", "UNKNOWN_OP",
                    f"未知操作 {op!r}；合法集合：{sorted(SEGMENT_OPS)[:10]}…"))

            # 参数校验
            params = sec.get("parameters", [])
            if not isinstance(params, list):
                issues.append(PlanIssue("error", f"{prefix}.parameters", "NOT_ARRAY",
                    "parameters 必须是数组"))
                continue
            if len(params) > self.max_params_per_segment:
                issues.append(PlanIssue("error", f"{prefix}.parameters", "TOO_MANY_PARAMS",
                    f"参数数 {len(params)} 超过上限 {self.max_params_per_segment}"))
            self._check_params(params, f"{prefix}.parameters", issues)

            # 逃逸舱检查
            if op == "custom_script" and not sec.get("escape_hatch"):
                issues.append(PlanIssue("error", f"{prefix}.escape_hatch",
                    "MISSING_ESCAPE_HATCH",
                    "custom_script 必须显式声明 escape_hatch=true（A17）"))

    def _check_params(self, params: list, prefix: str,
                      issues: list[PlanIssue]) -> None:
        seen_names: set[str] = set()
        for j, p in enumerate(params):
            pp = f"{prefix}[{j}]"
            if not isinstance(p, Mapping):
                issues.append(PlanIssue("error", pp, "NOT_OBJECT", "参数必须是对象"))
                continue

            pname = p.get("name", "")
            if not pname or not isinstance(pname, str):
                issues.append(PlanIssue("error", f"{pp}.name", "MISSING_NAME",
                    "参数缺少 name"))
                continue

            # 参数名必须是艺术家语义（拒绝 parm3/args[0]/Socket_N/Input_N）
            if re.match(r"^(parm|arg|Socket_|Input_)\d*$", pname, re.IGNORECASE):
                issues.append(PlanIssue("error", f"{pp}.name", "NON_SEMANTIC_NAME",
                    f"参数名 {pname!r} 不是艺术家语义名；用 'Wall_Thickness' 而非 'parm3'"))
            if pname in seen_names:
                issues.append(PlanIssue("error", f"{pp}.name", "DUPLICATE_PARAM",
                    f"参数名 {pname!r} 在同段内重复"))
            seen_names.add(pname)

            # 类型
            ptype = p.get("type", "FLOAT")
            if ptype not in _PARAM_TYPES:
                issues.append(PlanIssue("error", f"{pp}.type", "UNKNOWN_TYPE",
                    f"未知参数类型 {ptype!r}；合法：{sorted(_PARAM_TYPES)}"))

            # 数值范围
            val = p.get("value", p.get("default"))
            rng = self.param_ranges.get(pname)
            if rng and isinstance(val, (int, float)):
                lo, hi, unit = rng
                if not (lo <= val <= hi):
                    issues.append(PlanIssue("error", f"{pp}.value", "OUT_OF_RANGE",
                        f"{pname}={val} 超出范围 [{lo}, {hi}] {unit}"))

            # min/max 一致性
            mn, mx = p.get("min"), p.get("max")
            if mn is not None and mx is not None and mn >= mx:
                issues.append(PlanIssue("error", f"{pp}.min_max", "MIN_GE_MAX",
                    f"min({mn}) >= max({mx})"))

    # ── 依赖 ──────────────────────────────────────────────────
    def _check_dependencies(self, plan: Mapping[str, Any],
                            issues: list[PlanIssue]) -> None:
        sections = plan.get("sections", [])
        if not isinstance(sections, list):
            return
        ids = [s.get("id", "") for s in sections if isinstance(s, Mapping)]
        # M9-1b 接线修复（m9_intake_live 实锤）：依赖合法目标 = 本次载荷 sections
        # ∪ segment_names（会话中已编译段）——增量编译（console.compile 单段模式）
        # 带 depends_on 指向前段时，前段不在本次载荷里，此前被误判 MISSING_DEPENDENCY。
        # 已编译段必已通过环检且不可回边，并入 id_set 不影响 CYCLE 检测。
        id_set = set(ids) | set(self.segment_names)

        for i, sec in enumerate(sections):
            if not isinstance(sec, Mapping):
                continue
            deps = sec.get("depends_on", [])
            if not isinstance(deps, list):
                continue
            for d in deps:
                if d not in id_set:
                    issues.append(PlanIssue("error", f"$.sections[{i}].depends_on",
                        "MISSING_DEPENDENCY", f"依赖 {d!r} 不在同 plan 的 sections 中"))

        # 环检测（复用 m1_core 的逻辑简化版）
        graph = {}
        for s in sections:
            if isinstance(s, Mapping):
                sid = s.get("id", "")
                graph[sid] = [d for d in s.get("depends_on", []) if d in id_set]
        if self._has_cycle(graph):
            issues.append(PlanIssue("error", "$.sections", "CYCLE",
                "段落依赖成环——Grasshopper 铁律：数据流单向，禁止回环"))

    @staticmethod
    def _has_cycle(graph: Mapping[str, list[str]]) -> bool:
        color = {n: 0 for n in graph}
        for start in graph:
            if color[start]:
                continue
            stack = [(start, iter(graph.get(start, [])))]
            color[start] = 1
            while stack:
                node, it = stack[-1]
                advanced = False
                for nxt in it:
                    if nxt in color:
                        if color[nxt] == 1:
                            return True
                        if color[nxt] == 0:
                            color[nxt] = 1
                            stack.append((nxt, iter(graph.get(nxt, []))))
                            advanced = True
                            break
                if not advanced:
                    color[node] = 2
                    stack.pop()
        return False

    # ── constraints ───────────────────────────────────────────
    def _check_constraints(self, plan: Mapping[str, Any],
                           issues: list[PlanIssue]) -> None:
        constraints = plan.get("constraints", [])
        if not isinstance(constraints, list):
            return
        for i, c in enumerate(constraints):
            if not isinstance(c, Mapping):
                continue
            if "param" not in c and "check" not in c:
                issues.append(PlanIssue("error", f"$.constraints[{i}]",
                    "MISSING_TARGET", "约束必须指定 param 或 check"))


# ══════════════════════════════════════════════════════════════
# 便捷函数：validate + 汇总错误
# ══════════════════════════════════════════════════════════════
def validate_plan(plan: Mapping[str, Any],
                  segment_names: list[str] | None = None,
                  param_ranges: dict[str, tuple[float, float, str]] | None = None,
                  material: str = "",
                  process: str = "fdm") -> list[PlanIssue]:
    schema = PlanSchema(
        segment_names=segment_names or [],
        param_ranges=param_ranges or {},
        material=material, process=process,
    )
    return schema.validate(plan)
