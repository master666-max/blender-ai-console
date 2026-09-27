"""rig_compiler.py — M4-12 角色管线编译器（d4-character · rig-as-data）
=====================================================================

为什么存在（工单 M4-12 口径）：AI 写 plan 里的 rig_json（骨骼位置/模板/IK 配置），
编译器（可信模块）调 Rigify 产出 rig——AI 不碰 bpy 骨骼 API，只写数据。

rig_json schema v1（最小闭环；sample 模板路径留 v2）：
    {"name": "hero_rig",                    # 可选：metarig 名（缺省 RIGPLAN_<fp8>）
     "bones": [                              # 必填，非空
       {"name": "spine",                    # 必填，唯一
        "head": [x,y,z],                    # 必填，3 数
        "tail": [x,y,z],                    # 必填，3 数，且 head!=tail
        "parent": "root",                   # 可选（缺省 None；只要求引用存在，
                                            #   不要求声明顺序——两遍建骨）
        "rigify_type": "basic.raw_copy",    # 可选（缺省 root→"" 其余→basic 系；
                                            #   注册表校验 RIG_TYPE_UNKNOWN）
        "roll": 0.0,                        # 可选（弧度）
        "collection": "Main"}               # 可选（缺省归第一个 collection）
     ],
     "collections": [                       # 可选；缺省自动建 "Main" ui_row=1 全收
       {"name": "Main", "ui_row": 1, "bones": ["root", "spine"]}],
     "deform": true,                        # 可选：骨骼 use_deform（默认 True）
     "expressions": {                       # 可选（R7f）：ARKit-52 表情通道
       "mesh": "AI_Face",                   # 必填：宿主 mesh 对象名（编译期查在场+类型）
       "values": {"jawOpen": 0.4},          # 必填：{ARKit-52 白名单名: 0..1}
       "make_channels": true}               # 可选：建 shape key 通道（默认 true）
    }
# expressions 语义（诚实边界）：v1 交付 = ARKit-52 标准命名 shape key 通道 +
# 数值驱动接口（对齐 ARKit/Mixamo/MetaHuman 生态导入约定）；通道形状偏移为
# 占位（零偏移）——真实表情形状需美术资产或后续生成管线。

5.2 / Rigify 0.6.x 实锤（m412_probe R7-1 沉淀，逐条对应实现）：
  * 生成入口 bpy.ops.pose.rigify_generate（旧 pose API 存活）
  * 0.6.x 前置①：bone collections 必须有 rigify_ui_row 分配——否则
    "No bone collections have UI buttons assigned" 拒绝生成
  * 0.6.x 前置②：rig_lists 注册表懒加载——import 触发构建；不触发则
    generate 报 KeyError 'basic.copy'
  * bpy 坐标 float32——rig_json 坐标 roundtrip 断言须 1e-6 容差
  * bpy.ops getattr 链须 split(".")[2:]（跳 bpy+ops 两级）
  * op() 返回 set——不可 JSON 序列化

幂等语义（与 mat_compiler 同纪律、重建变体）：
  * plan 指纹派生稳定名；同名同指纹 → 复用现产物（rig 对象在场即跳过）
  * 指纹变更 → 删旧 metarig + RIG-* + WGT-* 后重建（rig 结构变更不重放——
    骨骼拓扑无"参数重放"语义，EXP-006 免疫同源：引用重建非槽位保留）
  * v1 诚实边界：假设场景单 rig（WGT- 清理按前缀全局）——多 rig 共存留 v2
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = ["RigConstraintError", "validate_rig_plan", "compile_rig", "rig_fingerprint"]


class RigConstraintError(Exception):
    """rig plan 校验/编译失败（结构化信息，console 转成 M4-8 格式）。"""

    def __init__(self, reason: str, code: str = "RIG_CONSTRAINT",
                 suggestions: list[dict] | None = None) -> None:
        self.reason = reason
        self.code = code
        self.suggestions = suggestions or []
        super().__init__(reason)


# ─────────────────────────────────────────────────────────────
# 纯 Python 校验层（无 bpy——预校验可移植，对齐 mat_compiler 分层）
# ─────────────────────────────────────────────────────────────
ALLOWED_FIELDS = {"name", "bones", "collections", "deform", "expressions"}
BONE_FIELDS = {"name", "head", "tail", "parent", "rigify_type", "roll", "collection"}
COLL_FIELDS = {"name", "ui_row", "bones"}

# Apple ARKit Face Tracking 52 blendshape 标准名（ARBlendShapeLocation 全集）——
# 表情通道命名白名单（对齐 ARKit / Mixamo / MetaHuman 生态导入约定）。
ARKIT_52 = frozenset({
    "browDownLeft", "browDownRight", "browInnerUp",
    "browOuterUpLeft", "browOuterUpRight",
    "cheekPuff", "cheekSquintLeft", "cheekSquintRight",
    "eyeBlinkLeft", "eyeBlinkRight",
    "eyeLookDownLeft", "eyeLookDownRight", "eyeLookInLeft", "eyeLookInRight",
    "eyeLookOutLeft", "eyeLookOutRight", "eyeLookUpLeft", "eyeLookUpRight",
    "eyeSquintLeft", "eyeSquintRight", "eyeWideLeft", "eyeWideRight",
    "jawForward", "jawLeft", "jawOpen", "jawRight",
    "mouthClose", "mouthDimpleLeft", "mouthDimpleRight",
    "mouthFrownLeft", "mouthFrownRight", "mouthFunnel",
    "mouthLeft", "mouthRight",
    "mouthLowerDownLeft", "mouthLowerDownRight",
    "mouthPressLeft", "mouthPressRight",
    "mouthPucker", "mouthRollLower", "mouthRollUpper",
    "mouthShrugLower", "mouthShrugUpper",
    "mouthSmileLeft", "mouthSmileRight",
    "mouthStretchLeft", "mouthStretchRight",
    "mouthUpperUpLeft", "mouthUpperUpRight",
    "noseSneerLeft", "noseSneerRight",
    "tongueOut",
})
EXPR_FIELDS = {"mesh", "values", "make_channels"}


def _validate_expressions(expr: Any) -> dict:
    """expressions 维度校验（纯 Python）：ARKit-52 白名单 + 值域 0..1。"""
    if not isinstance(expr, dict):
        raise RigConstraintError(
            f"expressions 必须是 dict，实得 {type(expr).__name__}", code="RIG_EXPR_TYPE")
    bad = [k for k in expr if k not in EXPR_FIELDS]
    if bad:
        raise RigConstraintError(
            f"expressions 未知字段 {bad}；允许 {sorted(EXPR_FIELDS)}",
            code="RIG_EXPR_FIELD")
    mesh = expr.get("mesh")
    if not isinstance(mesh, str) or not mesh.strip():
        raise RigConstraintError(
            "expressions.mesh 必须是非空字符串（shape key 通道的宿主 mesh 对象名）",
            code="RIG_EXPR_MESH")
    values = expr.get("values")
    if not isinstance(values, dict) or not values:
        raise RigConstraintError(
            "expressions.values 必须是非空 dict（{ARKit-52 名: 0..1}）",
            code="RIG_EXPR_VALUES")
    for k, v in values.items():
        if k not in ARKIT_52:
            raise RigConstraintError(
                f"expressions.values 键 {k!r} 不在 ARKit-52 白名单",
                code="RIG_BSD_NAME_UNKNOWN",
                suggestions=[{"action": "replace_value", "target": f"expressions.values.{k}",
                              "value": sorted(ARKIT_52)[:24]}])
        try:
            fv = float(v)
        except (TypeError, ValueError) as e:
            raise RigConstraintError(
                f"expressions.values[{k!r}] 必须是数值，实得 {v!r}",
                code="RIG_BSD_VALUE_TYPE") from e
        if not 0.0 <= fv <= 1.0:
            raise RigConstraintError(
                f"expressions.values[{k!r}]={fv} 越界（合法 0..1）",
                code="RIG_BSD_VALUE_RANGE")
    make_channels = expr.get("make_channels", True)
    if not isinstance(make_channels, bool):
        raise RigConstraintError(
            "expressions.make_channels 必须是布尔", code="RIG_EXPR_MAKE_TYPE")
    return {"mesh": mesh,
            "values": {k: float(v) for k, v in values.items()},
            "make_channels": make_channels}


def _vec3(v: Any, where: str) -> list[float]:
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise RigConstraintError(
            f"{where} 必须是 [x,y,z] 三数组，实得 {v!r}", code="RIG_VEC3")
    try:
        return [float(x) for x in v]
    except (TypeError, ValueError) as e:
        raise RigConstraintError(f"{where} 含非数值元素：{v!r}", code="RIG_VEC3") from e


def normalize_rig_plan(rig_json: dict) -> dict:
    """schema 校验 + 归一化（缺省填充；纯 Python，不碰 bpy）。

    返回归一化 dict：bones 顺序保持、parent 引用检查（不要求顺序）、
    collection 缺省归 "Main"。
    """
    if not isinstance(rig_json, dict):
        raise RigConstraintError(
            f"rig_json 必须是 dict，实得 {type(rig_json).__name__}", code="RIG_PLAN_TYPE")
    unknown = [k for k in rig_json
               if k not in ALLOWED_FIELDS and not k.startswith("_")]
    # `_` 前缀 = 文档性注记（对 AI 宽容：sample/plan 允许携带 _comment 等元字段）
    if unknown:
        raise RigConstraintError(
            f"rig_json 未知字段 {unknown}；允许 {sorted(ALLOWED_FIELDS)}",
            code="RIG_PLAN_FIELD",
            suggestions=[{"action": "remove_field", "target": str(unknown)}])
    bones = rig_json.get("bones")
    if not isinstance(bones, list) or not bones:
        raise RigConstraintError(
            "rig_json.bones 必须是非空数组", code="RIG_BONES_EMPTY")
    if "name" in rig_json and (not isinstance(rig_json["name"], str)
                               or not rig_json["name"].strip()):
        raise RigConstraintError("rig_json.name 必须是非空字符串", code="RIG_NAME")

    norm_bones: list[dict] = []
    seen: set[str] = set()
    for i, b in enumerate(bones):
        if not isinstance(b, dict):
            raise RigConstraintError(f"bones[{i}] 必须是 dict", code="RIG_BONE_TYPE")
        bad = [k for k in b if k not in BONE_FIELDS]
        if bad:
            raise RigConstraintError(
                f"bones[{i}] 未知字段 {bad}；允许 {sorted(BONE_FIELDS)}",
                code="RIG_BONE_FIELD")
        name = b.get("name")
        if not isinstance(name, str) or not name.strip():
            raise RigConstraintError(f"bones[{i}].name 必须是非空字符串", code="RIG_BONE_NAME")
        if name in seen:
            raise RigConstraintError(
                f"骨骼重名 {name!r}（bones[{i}]）", code="RIG_BONE_DUP")
        seen.add(name)
        head = _vec3(b.get("head"), f"bones[{i}].head")
        tail = _vec3(b.get("tail"), f"bones[{i}].tail")
        if sum((a - c) ** 2 for a, c in zip(head, tail)) < 1e-12:
            raise RigConstraintError(
                f"bones[{i}] ({name}) head==tail 零长度", code="RIG_BONE_ZERO_LENGTH")
        norm_bones.append({
            "name": name, "head": head, "tail": tail,
            "parent": b.get("parent"),            # 引用存在性在 bones 全量后统一查
            "rigify_type": b.get("rigify_type"),
            "roll": float(b.get("roll") or 0.0),
            "collection": b.get("collection"),
        })

    # parent 引用存在性（不要求声明顺序——编译层两遍建骨）
    for b in norm_bones:
        if b["parent"] is not None and b["parent"] not in seen:
            raise RigConstraintError(
                f"骨骼 {b['name']!r} 的 parent {b['parent']!r} 未声明",
                code="RIG_PARENT_UNKNOWN",
                suggestions=[{"action": "fix_reference", "target": "parent",
                              "known": sorted(seen)[:20]}])

    colls = rig_json.get("collections")
    norm_colls: list[dict] = []
    if colls is not None:
        if not isinstance(colls, list) or not colls:
            raise RigConstraintError(
                "collections 若给出必须是非空数组", code="RIG_COLL_TYPE")
        cnames: set[str] = set()
        for i, c in enumerate(colls):
            if not isinstance(c, dict):
                raise RigConstraintError(f"collections[{i}] 必须是 dict", code="RIG_COLL_ITEM")
            bad = [k for k in c if k not in COLL_FIELDS]
            if bad:
                raise RigConstraintError(
                    f"collections[{i}] 未知字段 {bad}；允许 {sorted(COLL_FIELDS)}",
                    code="RIG_COLL_FIELD")
            cn = c.get("name")
            if not isinstance(cn, str) or not cn.strip():
                raise RigConstraintError(
                    f"collections[{i}].name 必须是非空字符串", code="RIG_COLL_NAME")
            if cn in cnames:
                raise RigConstraintError(f"collection 重名 {cn!r}", code="RIG_COLL_DUP")
            cnames.add(cn)
            bones_in = c.get("bones") or []
            if not isinstance(bones_in, list):
                raise RigConstraintError(
                    f"collections[{i}].bones 必须是数组", code="RIG_COLL_BONES")
            for bn in bones_in:
                if bn not in seen:
                    raise RigConstraintError(
                        f"collection {cn!r} 引用未声明骨骼 {bn!r}", code="RIG_COLL_UNKNOWN_BONE")
            norm_colls.append({"name": cn, "ui_row": int(c.get("ui_row") or 1),
                               "bones": list(bones_in)})
        # 骨骼的 collection 字段必须指向已声明 collection
        declared = {c["name"] for c in norm_colls}
        for b in norm_bones:
            if b["collection"] is not None and b["collection"] not in declared:
                raise RigConstraintError(
                    f"骨骼 {b['name']!r} 的 collection {b['collection']!r} 未声明",
                    code="RIG_COLL_UNKNOWN",
                    suggestions=[{"action": "fix_reference", "target": "collection",
                                  "known": sorted(declared)}])
    else:
        norm_colls = [{"name": "Main", "ui_row": 1, "bones": []}]

    deform = rig_json.get("deform", True)
    if not isinstance(deform, bool):
        raise RigConstraintError("deform 必须是布尔", code="RIG_DEFORM_TYPE")
    expressions = None
    if "expressions" in rig_json:
        expressions = _validate_expressions(rig_json["expressions"])
    return {"name": rig_json.get("name"), "bones": norm_bones,
            "collections": norm_colls, "deform": deform,
            "expressions": expressions}


def rig_fingerprint(rig_json: dict) -> str:
    """plan 指纹（幂等对账；归一化后序列化，键序稳定）。"""
    norm = normalize_rig_plan(rig_json)
    payload = json.dumps(norm, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:8]


# ─────────────────────────────────────────────────────────────
# bpy 编译层
# ─────────────────────────────────────────────────────────────
def _resolve_basic_type() -> str:
    """从注册表解析可用的 basic 系类型名（0.6.x 懒加载实锤：import 触发构建）。"""
    from rigify import rig_lists  # noqa: F401  ← import 副作用即注册表构建（G1 实锤）
    rigs = getattr(rig_lists, "rigs", {})
    for cand in ("basic.raw_copy", "basic.copy", "basic.super_copy"):
        if cand in rigs:
            return cand
    raise RigConstraintError(
        f"rig_lists.rigs 无 basic 系候选（raw_copy/copy/super_copy）——"
        f"注册表实得 {sorted(rigs)[:20]}", code="RIG_REGISTRY_EMPTY")


def _enable_rigify(bpy) -> None:
    prefs = bpy.context.preferences
    if "rigify" not in prefs.addons:
        bpy.ops.preferences.addon_enable(module="rigify")
    if "rigify" not in prefs.addons:
        raise RigConstraintError("rigify addon 启用失败", code="RIGIFY_NOT_ENABLED")


def _wipe(bpy, metarig_name: str) -> None:
    """删除旧 metarig + RIG-* + WGT-*（v1 单 rig 假设——见模块头诚实边界）。"""
    for obj in list(bpy.data.objects):
        if obj.name == metarig_name or obj.name.startswith("RIG-") \
                or obj.name.startswith("WGT-"):
            bpy.data.objects.remove(obj, do_unlink=True)
    for coll in list(bpy.data.collections):
        if coll.name.startswith("WGTS_"):
            bpy.data.collections.remove(coll)


def compile_rig(bpy, rig_json: dict, name: str | None = None) -> dict:
    """编译 rig_json → Rigify rig（metarig 建 + 前置两件 + pose.rigify_generate）。

    幂等：name 或指纹派生稳定名；同名同指纹且 RIG-* 在场 → 复用（reused=True）；
    指纹变更 → wipe 重建。返回 detail dict（对账面）。
    """
    norm = normalize_rig_plan(rig_json)
    fp = rig_fingerprint(rig_json)
    if name is None:
        name = norm["name"] or f"RIGPLAN_{fp}"
    rig_name = f"RIG-{name}"

    _enable_rigify(bpy)

    # 幂等快路：metarig 在场、指纹一致、rig 产物在场 → 复用
    old = bpy.data.objects.get(name)
    if old is not None and old.get("rig_plan_fp") == fp \
            and bpy.data.objects.get(rig_name) is not None:
        return {"metarig": name, "rig": rig_name, "reused": True,
                "fingerprint": fp,
                "n_bones": len(old.data.bones),
                "rig_bones": [pb.name for pb in
                              bpy.data.objects[rig_name].pose.bones]}

    _wipe(bpy, name)

    # 注册表先于骨骼标注（前置②：懒加载触发 + rigify_type 白名单校验）
    basic_type = _resolve_basic_type()
    rigs_registry = __import__("rigify").rig_lists.rigs
    for b in norm["bones"]:
        rt = b["rigify_type"]
        if rt is not None and rt != "" and rt not in rigs_registry:
            raise RigConstraintError(
                f"rigify_type {rt!r} 不在注册表（骨骼 {b['name']!r}）",
                code="RIG_TYPE_UNKNOWN",
                suggestions=[{"action": "replace_value", "target": f"bones.{b['name']}.rigify_type",
                              "value": sorted(rigs_registry)[:20]}])

    # 建骨架 + 两遍建骨（第一遍全建、第二遍连 parent——parent 不要求声明顺序）
    arm = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, arm)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    made: dict[str, Any] = {}
    for b in norm["bones"]:
        eb = arm.edit_bones.new(b["name"])
        eb.head, eb.tail = b["head"], b["tail"]
        eb.roll = b["roll"]
        eb.use_deform = norm["deform"]
        made[b["name"]] = eb
    for b in norm["bones"]:
        if b["parent"] is not None:
            made[b["name"]].parent = made[b["parent"]]
    bpy.ops.object.mode_set(mode="OBJECT")

    # collections（前置①）：new + assign + rigify_ui_row
    coll_map: dict[str, Any] = {}
    for c in norm["collections"]:
        col = arm.collections.new(c["name"])
        col.rigify_ui_row = max(1, c["ui_row"])
        coll_map[c["name"]] = col
    first = norm["collections"][0]["name"]
    coll_assign_errs: list[str] = []
    for b in norm["bones"]:
        target = b["collection"] or first
        col = coll_map[target]
        try:
            col.assign(arm.bones[b["name"]])
        except Exception as e:  # noqa: BLE001
            coll_assign_errs.append(f"{b['name']}→{target}: {e}")
    if coll_assign_errs:
        raise RigConstraintError(
            f"bone collection 分配失败：{coll_assign_errs}", code="RIG_COLL_ASSIGN")
    # 缺省 collection 兜底：任何未分配骨骼（bones 字段漏列的）补进第一个
    assigned: set[str] = set()
    for c in norm["collections"]:
        assigned.update(c["bones"])
    fallback = coll_map[first]
    for b in norm["bones"]:
        if b["collection"] is None and b["name"] not in assigned:
            fallback.assign(arm.bones[b["name"]])

    # rigify_type 标注（object mode 经 pose_bones；root 类骨架骨默认 ""）
    for b in norm["bones"]:
        pb = obj.pose.bones[b["name"]]
        if hasattr(pb, "rigify_type"):
            pb.rigify_type = b["rigify_type"] if b["rigify_type"] is not None else (
                "" if b["name"] == norm["bones"][0]["name"] and not b["parent"] else basic_type)

    # 生成（入口实锤：pose.rigify_generate；getattr 链 [2:] 跳 bpy+ops）
    bpy.context.view_layer.objects.active = obj
    try:
        r = bpy.ops.pose.rigify_generate()
    except Exception as e:  # noqa: BLE001
        raise RigConstraintError(
            f"rigify_generate 异常：{type(e).__name__}: {e}", code="RIG_GENERATE_FAILED") from e
    if set(r) != {"FINISHED"}:
        raise RigConstraintError(
            f"rigify_generate 未完成：{sorted(r)}", code="RIG_GENERATE_FAILED")
    rig_obj = bpy.data.objects.get(rig_name)
    if rig_obj is None or rig_obj.type != "ARMATURE":
        raise RigConstraintError(
            f"生成完成但 {rig_name!r} 不在场（Rigify 产物命名漂移？）",
            code="RIG_GENERATE_NO_PRODUCT")

    # 0.6.x raw_copy 实锤（m412_live 首跑）：生成的 rig 保留 metarig 骨骼名
    # 但 use_deform 全 False（DEF-* deform 骨骼仅由复杂 rig 类型生成）——
    # rig-as-data 语义：metarig 骨骼即最终 deform 链，无 deform 骨骼时打补丁
    # （蒙皮绑定依赖 use_deform，否则自动权重空绑定、姿势零形变）。
    deform_patched = False
    if not any(b.use_deform for b in rig_obj.data.bones):
        meta_names = {b["name"] for b in norm["bones"]}
        for b in rig_obj.data.bones:
            if b.name in meta_names:
                b.use_deform = True
        deform_patched = True

    # expressions（ARKit-52 表情通道；R7f）：宿主 mesh 上建 basis + 各声明名
    # shape key，value=声明值；已有同名 SK 只设值（幂等）。诚实边界：v1 通道
    # 形状偏移为占位（相对 basis 零偏移）——真实表情形状需美术资产/生成管线；
    # v1 交付 = ARKit-52 标准命名通道 + 数值驱动接口（对齐生态导入约定）。
    expr_detail = None
    if norm["expressions"] is not None:
        ex = norm["expressions"]
        mesh_obj = bpy.data.objects.get(ex["mesh"])
        if mesh_obj is None:
            raise RigConstraintError(
                f"expressions.mesh {ex['mesh']!r} 不在场景",
                code="RIG_EXPR_MESH_UNKNOWN",
                suggestions=[{"action": "fix_reference", "target": "expressions.mesh",
                              "known": sorted(o.name for o in bpy.data.objects
                                              if o.type == "MESH")[:20]}])
        if mesh_obj.type != "MESH":
            raise RigConstraintError(
                f"expressions.mesh {ex['mesh']!r} 不是 MESH（实得 {mesh_obj.type}）",
                code="RIG_EXPR_MESH_NOT_MESH")
        made_channels: list[list] = []
        if ex["make_channels"]:
            if mesh_obj.data.shape_keys is None:
                mesh_obj.shape_key_add(name="Basis", from_mix=False)
            for k, v in ex["values"].items():
                kb = mesh_obj.data.shape_keys.key_blocks.get(k)
                if kb is None:
                    kb = mesh_obj.shape_key_add(name=k, from_mix=False)
                kb.value = v
                made_channels.append([k, v])
        expr_detail = {"mesh": ex["mesh"], "channels": made_channels,
                       "n_channels": len(made_channels),
                       "make_channels": ex["make_channels"]}

    obj["rig_plan_fp"] = fp
    # float32 容差对账（probe E1 实锤）：读回 head 与 plan 差 ≤1e-6
    drift = []
    for b in norm["bones"]:
        got = obj.pose.bones[b["name"]].bone.head_local
        want = b["head"]
        if any(abs(g - w) > 1e-6 for g, w in zip(got, want)):
            drift.append(b["name"])
    if drift:
        raise RigConstraintError(
            f"骨骼坐标 roundtrip 漂移 >1e-6：{drift}", code="RIG_COORD_DRIFT")

    return {"metarig": name, "rig": rig_name, "reused": False,
            "fingerprint": fp, "n_bones": len(norm["bones"]),
            "rig_bones": [pb.name for pb in rig_obj.pose.bones],
            "deform_patched": deform_patched,
            "deform_bones": [b.name for b in rig_obj.data.bones if b.use_deform],
            "collections": [c.name for c in arm.collections],
            "basic_type_used": basic_type,
            "expressions": expr_detail}
