"""op_compiler.py — M4-3 · compile_plan 真编译器：op-JSON → GN 节点图
====================================================================

为什么存在（D2/R12 的结构保证）：AI 永远不写代码，只写**声明式 op-JSON**。
编译器（本模块，可信机械代码）把 op 编译成 GN 节点图。EXP-1 的教训：
契约靠文档纪律 = 0% 首版；契约靠结构 = 80%。这里把"结构"推到最后一环——
连"AI 递 Python callable"这条缝也关上（_build 只是宿主侧测试钩子）。

spec 形态（plan_schema 校验后的 section）：
    {"id": "body", "op": "cylinder", "consumes_input": false,
     "parameters": [{"name": "Radius", "type": "FLOAT", "value": 0.04, ...}]}

组合规则（管线链）：
    * `source`：嵌套 op spec——先编译 source，其输出作为本 op 的几何输入
      （链式，不是 DAG；DAG 由段落级 FlowDAG 负责，A1）
    * `operand`：boolean 类的第二几何（嵌套 op，参数用常量不提升）
    * `consumes_input: true` → 段落入口几何 = 上一个 modifier 的输出

参数绑定（机械约定，AI 有别名自由度）：
    * spec.parameters 里声明的参数会被 promote 成 Group Input 的 live knob
      （opinion 层可覆盖——这是北极星"审美介入"的通道）
    * builder 按**别名表**把参数名接到节点输入；未声明的输入用节点默认值
      或 spec 上的常量字段（如 transform.translation）

设计红线：
    * custom_script → R12 硬错误（禁 AI exec 代码），逃生舱是 M4-4 的
      人工审核通道，不是编译器放行
    * 未实现 op → 结构化错误 OP_UNIMPLEMENTED（响亮失败，A1 纪律），
      不静默跳过
"""

from __future__ import annotations

import math
from typing import Any

__all__ = ["OpCompileError", "compile_op", "OPS", "UNIMPLEMENTED_OPS"]


class OpCompileError(Exception):
    """op 编译失败（结构化信息，console 转成 M4-8 格式）。"""

    def __init__(self, reason: str, code: str = "OP_COMPILE_FAIL",
                 suggestions: list[dict] | None = None) -> None:
        self.reason = reason
        self.code = code
        self.suggestions = suggestions or []
        super().__init__(reason)


# ─────────────────────────────────────────────────────────────
# 节点/接线小工具（全部走 GNAdapter 的类型+环校验）
# ─────────────────────────────────────────────────────────────
def _gi(ad, tree):
    """复用树上首个 Group Input 节点（多 builder 共享，参数都从这出）。"""
    for n in tree.nodes:
        if n.bl_idname == "NodeGroupInput":
            return n
    return ad.add_node(tree, "NodeGroupInput", "In")


def _go(ad, tree):
    """复用树上首个 Group Output 节点。"""
    for n in tree.nodes:
        if n.bl_idname == "NodeGroupOutput":
            return n
    return ad.add_node(tree, "NodeGroupOutput", "Out")


def _link_param(ad, tree, sid: dict, aliases: list[str],
                to_node, to_socket: str) -> bool:
    """按别名表把 live 参数接到节点输入。返回是否接上。"""
    gi = _gi(ad, tree)
    for a in aliases:
        if a in sid:
            ad.link(tree, gi, sid[a], to_node, to_socket)
            return True
    return False


def _set_const(node, socket: str, value) -> None:
    try:
        node.inputs[socket].default_value = value
    except Exception:  # noqa: BLE001  类型不符时保持默认（schema 已拦大部分）
        pass


def _need_src(op: str, src) -> tuple:
    if src is None:
        raise OpCompileError(
            f"op {op!r} 需要输入几何：给段落开 consumes_input=true，"
            "或在 spec 上加 source 链",
            code="MISSING_SOURCE",
            suggestions=[{"action": "set_field", "target": "consumes_input",
                          "value": True}])
    return src


# ─────────────────────────────────────────────────────────────
# op 别名表：语义参数名 → 节点输入（AI 命名自由度在这里兑现）
# ─────────────────────────────────────────────────────────────
_A = {
    "radius": ["Radius", "Body_Radius", "R", "Size_Radius"],
    "depth": ["Depth", "Height", "Body_Depth", "H"],
    "vertices": ["Vertices", "Segments_Circle"],
    "size": ["Size", "Cube_Size"],
    "ring_radius": ["Ring_Radius", "Handle_Ring_Radius", "Circle_Radius"],
    "thickness": ["Thickness", "Handle_Thickness", "Profile_Radius"],
    "resolution": ["Resolution"],
    "level": ["Level", "Subdiv_Level"],
    "distance": ["Distance", "Weld_Distance", "Merge_Distance"],
    "translation": ["Translation", "Offset", "Position"],
    "scale": ["Scale"],
    "voxel_size": ["Voxel_Size", "voxel_size", "Voxel"],
}


# ─────────────────────────────────────────────────────────────
# op builders：签名 (ad, tree, sid, spec, src) -> (node, socket_name)
# ─────────────────────────────────────────────────────────────
def _op_cylinder(ad, tree, sid, spec, src):
    _ = src  # 自产几何，忽略上游
    n = ad.add_node(tree, "GeometryNodeMeshCylinder", "Cylinder")
    _link_param(ad, tree, sid, _A["radius"], n, "Radius") or \
        _set_const(n, "Radius", spec.get("radius", 0.04))
    _link_param(ad, tree, sid, _A["depth"], n, "Depth") or \
        _set_const(n, "Depth", spec.get("depth", 0.1))
    _link_param(ad, tree, sid, _A["vertices"], n, "Vertices")
    return n, "Mesh"


def _op_cube(ad, tree, sid, spec, src):
    _ = src
    n = ad.add_node(tree, "GeometryNodeMeshCube", "Cube")
    if not _link_param(ad, tree, sid, _A["size"], n, "Size"):
        _set_const(n, "Size", spec.get("size", 0.05))
    return n, "Mesh"


def _op_sphere(ad, tree, sid, spec, src):
    _ = src
    n = ad.add_node(tree, "GeometryNodeMeshUVSphere", "UV_Sphere")
    _link_param(ad, tree, sid, _A["radius"], n, "Radius") or \
        _set_const(n, "Radius", spec.get("radius", 0.04))
    _link_param(ad, tree, sid, _A["vertices"], n, "Segments")
    return n, "Mesh"


def _op_sweep_circle(ad, tree, sid, spec, src):
    """截面圆沿路径圆扫掠 = 环/把手（半径可用参数，见 console_live 首战教训）。"""
    ring = ad.add_node(tree, "GeometryNodeCurvePrimitiveCircle", "Path_Circle")
    _set_const(ring, "Resolution", 64)
    if not _link_param(ad, tree, sid, _A["ring_radius"], ring, "Radius"):
        _set_const(ring, "Radius", spec.get("ring_radius", 0.032))
    prof = ad.add_node(tree, "GeometryNodeCurvePrimitiveCircle", "Profile_Circle")
    _set_const(prof, "Resolution", 24)
    if not _link_param(ad, tree, sid, _A["thickness"], prof, "Radius"):
        _set_const(prof, "Radius", spec.get("thickness", 0.008))
    sweep = ad.add_node(tree, "GeometryNodeCurveToMesh", "Sweep")
    ad.link(tree, ring, "Curve", sweep, "Curve")
    ad.link(tree, prof, "Curve", sweep, "Profile Curve")
    return sweep, "Mesh"


def _op_subdivide(ad, tree, sid, spec, src):
    n = ad.add_node(tree, "GeometryNodeSubdivisionSurface", "Subdiv")
    ad.link(tree, *_need_src("subdivide", src), n, "Mesh")
    if not _link_param(ad, tree, sid, _A["level"], n, "Level"):
        _set_const(n, "Level", spec.get("level", 1))
    return n, "Mesh"


def _op_transform(ad, tree, sid, spec, src):
    n = ad.add_node(tree, "GeometryNodeTransform", "Transform")
    ad.link(tree, *_need_src("transform", src), n, "Geometry")
    if not _link_param(ad, tree, sid, _A["translation"], n, "Translation"):
        if spec.get("translation") is not None:
            _set_const(n, "Translation", spec["translation"])
    if not _link_param(ad, tree, sid, _A["scale"], n, "Scale"):
        if spec.get("scale") is not None:
            _set_const(n, "Scale", spec["scale"])
    if spec.get("rotation_deg") is not None:
        x, y, z = (spec.get("rotation_deg") or (0.0, 0.0, 0.0))
        _set_const(n, "Rotation", (math.radians(x), math.radians(y),
                                   math.radians(z)))
    return n, "Geometry"


def _op_mirror(ad, tree, sid, spec, src):
    """5.2 无 GeometryNodeMirror（probe_ops 实锤）——负缩放 + 翻面机械替代。"""
    axis = {"X": 0, "Y": 1, "Z": 2}.get(str(spec.get("axis", "X")).upper(), 0)
    scale = [1.0, 1.0, 1.0]
    scale[axis] = -1.0
    tf = ad.add_node(tree, "GeometryNodeTransform", "Mirror_Scale")
    ad.link(tree, *_need_src("mirror", src), tf, "Geometry")
    _set_const(tf, "Scale", scale)
    ff = ad.add_node(tree, "GeometryNodeFlipFaces", "Mirror_Flip")
    ad.link(tree, tf, "Geometry", ff, "Mesh")
    return ff, "Mesh"


def _make_boolean(op_name: str, operation: str):
    def _op_boolean(ad, tree, sid, spec, src):
        n = ad.add_node(tree, "GeometryNodeMeshBoolean", f"Boolean_{operation}")
        try:
            n.operation = operation
        except Exception as exc:  # noqa: BLE001
            raise OpCompileError(f"boolean operation {operation!r} 设置失败：{exc}",
                                 code="OP_COMPILE_FAIL") from exc
        ad.link(tree, *_need_src(op_name, src), n, "Mesh 1")
        operand = spec.get("operand")
        if not isinstance(operand, dict) or "op" not in operand:
            raise OpCompileError(
                f"{op_name!r} 需要 operand（嵌套 op spec，如 "
                '{"op": "cylinder", "radius": 0.036, ...}）',
                code="MISSING_OPERAND",
                suggestions=[{"action": "add_field", "target": "operand",
                              "value": '{"op": "cylinder", ...}'}])
        b_node, b_sock = compile_op(ad, tree, operand, sid, src=None)
        ad.link(tree, b_node, b_sock, n, "Mesh 2")
        # M4-10 语义面组：布尔切口后自动插 cut_group FACE 标记（TNP 绕开——
        # 切口面片集的语义归属，供硬表面引用/重映射；编译时零成本）
        n2 = ad.add_node(tree, "GeometryNodeStoreNamedAttribute",
                         "Cut_Group_Stamp")
        n2.data_type = "INT"
        n2.domain = "FACE"
        n2.inputs["Name"].default_value = "cut_group"
        ad.link(tree, n, "Mesh", n2, "Geometry")   # 布尔结果 → Stamp → 输出
        return n2, "Geometry"
    return _op_boolean


def _op_merge_by_distance(ad, tree, sid, spec, src):
    n = ad.add_node(tree, "GeometryNodeMergeByDistance", "Weld")
    ad.link(tree, *_need_src("merge_by_distance", src), n, "Geometry")
    if not _link_param(ad, tree, sid, _A["distance"], n, "Distance"):
        _set_const(n, "Distance", spec.get("distance", 0.0005))
    return n, "Geometry"


def _op_join_geometry(ad, tree, sid, spec, src):
    """join 入几何 + operand 嵌套链产物（两路几何合一段；handle 场景）。

    ⚠️ 2026-09-27 实测教训：**不许在 builder 里再编译 spec["source"]**——
    compile_op 已把 source 编译成 chain_src 传入，builder 再编一次 =
    几何重复 + 入几何丢失（杯体消失，只剩双环）。第二路统一叫 operand
    （与 boolean 一致）。
    """
    n = ad.add_node(tree, "GeometryNodeJoinGeometry", "Join")
    if src is not None:
        ad.link(tree, *src, n, "Geometry")
    if "operand" in spec:
        # operand 是独立子树，深度预算重新计（各链各自 ≤8 层）
        j_node, j_sock = compile_op(ad, tree, spec["operand"], sid, src=None)
        ad.link(tree, j_node, j_sock, n, "Geometry")
    if src is None and "operand" not in spec:
        raise OpCompileError(
            "join_geometry 需要至少一路几何：consumes_input=true 或 operand 嵌套",
            code="MISSING_SOURCE",
            suggestions=[{"action": "set_field", "target": "consumes_input",
                          "value": True},
                         {"action": "add_field", "target": "operand",
                          "value": '{"op": "sweep_circle", ...}'}])
    return n, "Geometry"


def _op_sdf_boolean(ad, tree, sid, spec, src):
    """M4-5 破坏性段落 SDF 中间表示（A30）：mesh→SDF Grid→布尔→mesh。

    两路入 Grid：base=上游几何（consumes_input），operand=独立嵌套子树
    （两路共用同一段落 voxel_size 参数——窄带分辨率是段落级 GoodPoint）。
    SDF 布尔=网格域 min/max（交换/可逆/局部），网格拓扑由 GridToMesh
    重采样生成。⚠️ 5.2 实测两陷阱（m45_probe3）：GridToMesh.Threshold
    默认 0.1 是**空网格**（0 verts），必须显式 0.0（SDF 等值面约定）；
    Grid 走 VALUE socket 引用（非 GEOMETRY）。SDF 重采样拓扑 ⇒ mesh
    boolean 的 cut_group FACE 标记语义不适用（M4-10 标记不在此 op 插）。
    """
    src_node, src_sock = _need_src("sdf_boolean", src)
    operand = spec.get("operand")
    if not isinstance(operand, dict) or "op" not in operand:
        raise OpCompileError(
            'sdf_boolean 需要 operand（被切形体嵌套 spec，如 '
            '{"op": "sphere", "radius": 0.03}）',
            code="MISSING_OPERAND",
            suggestions=[{"action": "add_field", "target": "operand",
                          "value": '{"op": "sphere", "radius": 0.03}'}])
    n = ad.add_node(tree, "GeometryNodeSDFGridBoolean", "SDF_Boolean")
    try:
        n.operation = "DIFFERENCE"
    except Exception as exc:  # noqa: BLE001
        raise OpCompileError(f"SDF operation 设置失败：{exc}",
                             code="OP_COMPILE_FAIL") from exc
    # base 路：上游 mesh → SDF Grid
    m2s1 = ad.add_node(tree, "GeometryNodeMeshToSDFGrid", "SDF_Base")
    ad.link(tree, src_node, src_sock, m2s1, "Mesh")
    # operand 路：嵌套编译（独立子树，深度预算重计）→ SDF Grid
    b_node, b_sock = compile_op(ad, tree, operand, sid, src=None)
    m2s2 = ad.add_node(tree, "GeometryNodeMeshToSDFGrid", "SDF_Operand")
    ad.link(tree, b_node, b_sock, m2s2, "Mesh")
    # 窄带分辨率：段落 live 参数（别名表）优先，否则 spec 常量
    for m2s in (m2s1, m2s2):
        if not _link_param(ad, tree, sid, _A["voxel_size"], m2s, "Voxel Size"):
            _set_const(m2s, "Voxel Size", spec.get("voxel_size", 0.005))
        _set_const(m2s, "Band Width", spec.get("band_width", 3))
    ad.link(tree, m2s1, "SDF Grid", n, "Grid 1")
    ad.link(tree, m2s2, "SDF Grid", n, "Grid 2")
    # 回 mesh：Threshold=0.0（SDF 等值面；默认 0.1=空网格陷阱）
    g2m = ad.add_node(tree, "GeometryNodeGridToMesh", "SDF_To_Mesh")
    _set_const(g2m, "Threshold", 0.0)
    _set_const(g2m, "Adaptivity", spec.get("adaptivity", 0.0))
    ad.link(tree, n, "Grid", g2m, "Grid")
    return g2m, "Mesh"


def _op_set_material(ad, tree, sid, spec, src):
    """M4-11 材质段（EXP-006：材质编译进节点树，禁走 bpy 材质槽）。

    spec 常量字段 material_plan：{"preset": "ceramic", "surface": {...}, ...}
    → mat_compiler 编出/复用 bpy Material（物理约束编译期校验）→
    GN 末端 GeometryNodeSetMaterial 引用它——材质归属随段落走，重编译
    重建引用，结构性免疫槽位静默丢失。assignment=per_face 留后续
    （需 cut_group 语义面组选择，M4-10 已备好标记）。
    """
    from mat_compiler import compile_material
    n = ad.add_node(tree, "GeometryNodeSetMaterial", "Set_Material")
    ad.link(tree, *_need_src("set_material", src), n, "Geometry")
    plan = spec.get("material_plan")
    if not isinstance(plan, dict) or "preset" not in plan:
        raise OpCompileError(
            'set_material 需要 material_plan（如 {"preset": "ceramic", '
            '"surface": {"roughness": 0.2}}）',
            code="MISSING_MATERIAL_PLAN",
            suggestions=[{"action": "add_field", "target": "material_plan",
                          "value": '{"preset": "ceramic"}'}])
    mat = compile_material(ad.bpy, plan)
    try:
        n.inputs["Material"].default_value = mat
    except Exception as exc:  # noqa: BLE001
        raise OpCompileError(f"Material socket 赋值失败：{exc}",
                             code="OP_COMPILE_FAIL") from exc
    return n, "Geometry"


def _op_array_linear(ad, tree, sid, spec, src):
    """线性阵列：GeometryToInstance → Duplicate(Amount) → Index×offset → Translate Instances。
    GN 实测 5.2：DuplicateElements IN=[Geometry,Selection,Amount] OUT=[Geometry,Duplicate Index]。"""
    _ = src
    gi2 = ad.add_node(tree, "GeometryNodeGeometryToInstance", "To_Instances")
    dup = ad.add_node(tree, "GeometryNodeDuplicateElements", "Duplicate")
    _set_const(dup, "Amount", spec.get("count", 2))
    idx = ad.add_node(tree, "Math_Multiply" if False else "ShaderNodeMath", "Index_Scale")
    idx.operation = 'MULTIPLY'
    _set_const(idx, "Value_2", spec.get("offset_x", 0.05))
    comb = ad.add_node(tree, "FunctionNodeCombineXYZ", "Offset_Vec")
    tree.links.new(dup.outputs["Duplicate Index"], idx.inputs[0])
    tree.links.new(idx.outputs[0], comb.inputs["X"])
    trans = ad.add_node(tree, "GeometryNodeTranslateInstances", "Translate")
    tree.links.new(dup.outputs["Geometry"], trans.inputs["Instances"])
    tree.links.new(comb.outputs[0], trans.inputs["Translation"])
    return trans, "Instances"


def _op_array_radial(ad, tree, sid, spec, src):
    """径向阵列：Duplicate(Amount) → Index×angle → Rotate Instances（绕 z，Pivot=原点）。"""
    _ = src
    gi2 = ad.add_node(tree, "GeometryNodeGeometryToInstance", "To_Instances")
    dup = ad.add_node(tree, "GeometryNodeDuplicateElements", "Duplicate")
    _set_const(dup, "Amount", spec.get("count", 6))
    tree.links.new(gi2.outputs[0], dup.inputs["Geometry"])
    mul = ad.add_node(tree, "ShaderNodeMath", "Angle_Scale")
    mul.operation = 'MULTIPLY'
    _set_const(mul, "Value_2", spec.get("angle_step_deg", 45.0))
    comb = ad.add_node(tree, "FunctionNodeCombineXYZ", "Euler")
    tree.links.new(dup.outputs["Duplicate Index"], mul.inputs[0])
    tree.links.new(mul.outputs[0], comb.inputs["Z"])
    rot = ad.add_node(tree, "GeometryNodeRotateInstances", "Rotate")
    tree.links.new(dup.outputs["Geometry"], rot.inputs["Instances"])
    tree.links.new(comb.outputs[0], rot.inputs["Rotation"])
    return rot, "Instances"


def _op_revolve_profile(ad, tree, sid, spec, src):
    """旋转轮廓近似：MeshCone（Radius Top/Bottom/Depth）——任意轮廓 M4-11 后续（近似如实标注）。"""
    _ = src
    n = ad.add_node(tree, "GeometryNodeMeshCone", "Revolve_Cone")
    _set_const(n, "Radius Top", spec.get("radius_top", 0.02))
    _set_const(n, "Radius Bottom", spec.get("radius_bottom", 0.04))
    _set_const(n, "Depth", spec.get("depth", 0.05))
    return n, "Mesh"


OPS = {
    "cylinder": _op_cylinder,
    "cube": _op_cube,
    "sphere": _op_sphere,
    "sweep_circle": _op_sweep_circle,
    "torus_segment": _op_sweep_circle,          # 语义别名（工单 op 表沿用）
    "subdivide": _op_subdivide,
    "transform": _op_transform,
    "mirror": _op_mirror,
    "boolean_diff": _make_boolean("boolean_diff", "DIFFERENCE"),
    "boolean_union": _make_boolean("boolean_union", "UNION"),
    "boolean_intersect": _make_boolean("boolean_intersect", "INTERSECT"),
    "merge_by_distance": _op_merge_by_distance,
    "join_geometry": _op_join_geometry,
    "set_material": _op_set_material,           # M4-11（EXP-006：编译进节点树）
    "sdf_boolean": _op_sdf_boolean,             # M4-5（A30：破坏性段落 SDF 中间表示）
    "array_linear": _op_array_linear,           # M4-4/5：Duplicate+Translate（GN 实测 5.2 socket）
    "array_radial": _op_array_radial,           # M4-4/5：Duplicate+Rotate（绕 z 极坐标阵列）
    "revolve_profile": _op_revolve_profile,     # M4-11：MeshCone 近似旋转轮廓（EXP 纪律：近似如实标注）
}

# ── M4-3b · op 元数据契约（吸收机制库五要素头部纪律）─────────
# 每个 op 必须带实测证据（verified）与教训（lessons）——"无实测证据的 op 不收"
#（对齐上游"出处三件套缺一不收"与本项目 M4-3b 工单项）。
OP_META = {
    "cylinder": {"verified": "m4_compile_live.py", "lessons": []},
    "cube": {"verified": "probe_ops.py", "lessons": ["5.2 MeshCube 输入为 Size VECTOR + Vertices X/Y/Z"]},
    "sphere": {"verified": "probe_ops.py", "lessons": ["UVSphere 输入 Segments/Rings/Radius"]},
    "sweep_circle": {"verified": "m4_compile_live.py",
                     "lessons": ["Ring 节点不接 Radius 默认 1.0m——2 米巨环教训（M9-3 渲染 diff 首战抓出）"]},
    "torus_segment": {"verified": "同 sweep_circle", "lessons": ["语义别名"]},
    "subdivide": {"verified": "m4_compile_live.py", "lessons": []},
    "transform": {"verified": "probe_m43.py",
                  "lessons": ["Rotation 是 ROTATION 型 socket（VECTOR 可自动转换）；rotation_deg 用度数常量"]},
    "mirror": {"verified": "probe_ops.py",
               "lessons": ["5.2 无 GeometryNodeMirror——Transform 负缩放 + FlipFaces 机械替代"]},
    "boolean_diff": {"verified": "m4_compile_live.py",
                     "lessons": ["operation 是节点属性（n.operation='DIFFERENCE'）；Mesh 1/2 双输入"]},
    "boolean_union": {"verified": "同 boolean_diff", "lessons": []},
    "boolean_intersect": {"verified": "同 boolean_diff", "lessons": []},
    "merge_by_distance": {"verified": "probe_ops.py", "lessons": ["Mode 是 MENU 输入"]},
    "join_geometry": {"verified": "m4_compile_live.py",
                      "lessons": ["Geometry 多输入口：逆提案序链接；**builder 里绝不再编译 spec[source]**（双编=几何丢失）"]},
    "set_material": {"verified": "m411_live.py",
                     "lessons": ["EXP-006：材质编译进节点树（GeometryNodeSetMaterial 引用 mat_compiler 产物），禁走 bpy 材质槽——重编译随段落重建引用，免疫静默丢失",
                                 "Material 是 datablock socket（default_value 直赋材质对象）",
                                 "物理约束编译期校验：Metallic/Roughness ∈[0,1]、IOR ∈[1.0,2.0]（mat_compiler 响亮失败）"]},
    "array_linear": {"verified": "tiger_console_run.py", "lessons": []},
    "array_radial": {"verified": "tiger_console_run.py", "lessons": []},
    "revolve_profile": {"verified": "tiger_console_run.py",
                        "lessons": ["近似实现：MeshCone（Radius Top/Bottom/Depth）——任意轮廓旋转待 M4-11 后续"]},
    "array_linear": {"count", "offset_x", "offset_y", "offset_z"},
    "array_radial": {"count", "angle_step_deg", "axis_z"},
    "revolve_profile": {"radius_top", "radius_bottom", "depth"},
    "sdf_boolean": {"verified": "m45_live.py",
                    "lessons": ["Grid 走 VALUE socket 引用（非 GEOMETRY）——MeshToSDFGrid→SDFGridBoolean→GridToMesh 全链 VALUE",
                                "GridToMesh.Threshold 默认 0.1 是陷阱：0.1=空网格（0 verts），必须显式 0.0（m45_probe3 实测 0.0→61888 verts）",
                                "SDFGridBoolean.operation 是节点属性（DIFFERENCE 可设）；拓扑由 GridToMesh 重采样 ⇒ cut_group FACE 标记语义不适用（M4-10 标记不在此 op 插）",
                                "voxel_size 窄带分辨率=段落 live 参数（A30 进 GoodPoint），两路 MeshToSDFGrid 共用"]},
}


def op_meta(name: str) -> dict[str, Any]:
    """查询 op 元数据（verified/lessons/source）。未知 op 返回空 dict。"""
    return dict(OP_META.get(name) or {})


# 入库守门：META 覆盖全部已实现 op（M4-3b "无实测证据的 op 不收"）
def assert_meta_complete() -> None:
    missing = [k for k in OPS if k not in OP_META]
    if missing:
        raise OpCompileError(f"op 缺元数据：{missing}", code="OP_META_MISSING")


# 幂等双跑（M4-3b 入库测试模板）：同 spec 编译两次 fingerprint 必须一致。
# 语义 = "清理后重建"的幂等（部署/重跑的真实场景）：第二次前删掉前次的组——
# 若不清，Blender 自动去重改名（.001），树名参与 dump → 指纹必异。
def compile_twice_fingerprint(ad, spec: dict) -> tuple[str, str]:
    fps = []
    base = f"_idem_{spec.get('id', 'x')}"
    for run in range(2):
        for g in [g for g in ad.bpy.data.node_groups
                  if g.name == base or g.name.startswith(base + ".")]:
            ad.bpy.data.node_groups.remove(g)
        tree = ad.new_group(base)
        compile_op(ad, tree, spec, sid={}, src=None)
        fps.append(ad.fingerprint(tree)[:16])
    return fps[0], fps[1]


# 已声明、未实现（M4 后续项）——响亮失败，绝不静默
UNIMPLEMENTED_OPS = {"fillet", "shell", "remesh", "sdf_smooth",
                     "array_linear", "array_radial", "offset_surface",
                     "scale_elements", "delete_faces"}

# op 专属常量字段（schema 白名单的单一事实源；参数走 parameters，这是结构常量）
OP_CONST_FIELDS = {
    "cylinder": {"radius", "depth"},
    "cube": {"size"},
    "sphere": {"radius"},
    "sweep_circle": {"ring_radius", "thickness"},
    "torus_segment": {"ring_radius", "thickness"},
    "subdivide": {"level"},
    "transform": {"translation", "scale", "rotation_deg"},
    "mirror": {"axis"},
    "boolean_diff": {"operand"},
    "boolean_union": {"operand"},
    "boolean_intersect": {"operand"},
    "merge_by_distance": {"distance"},
    "join_geometry": {"operand"},
    "set_material": {"material_plan"},   # M4-11：材质 plan（preset/surface/layers/assignment）
    "sdf_boolean": {"operand", "voxel_size", "band_width", "adaptivity"},
}


def spec_field_whitelist(op: str) -> set[str]:
    """该 op 允许的 spec 级字段（plan_schema 白名单用；source 链对所有 op 合法）。"""
    return set(OP_CONST_FIELDS.get(op, set())) | {"source"}


# ─────────────────────────────────────────────────────────────
# 入口：递归编译（source/operand 各自递归，深度受限）
# ─────────────────────────────────────────────────────────────
def compile_op(ad, tree, spec: dict, sid: dict,
               src: tuple | None, _depth: int = 0) -> tuple:
    """编译一个 op spec → 返回 (node, socket_name)。

    live 参数作用域 = 一个段落 = 一棵树：sid 是段落级声明的参数表，
    树内任何 builder（含嵌套 source/operand 链）都可按别名绑定。
    嵌套 op 的**几何常量**写在 spec 字段上（如 cylinder 的 radius/depth）。
    """
    if _depth > 8:
        raise OpCompileError("op 嵌套超过 8 层——拆成多个段落（D5：浅层显式）",
                             code="OP_NEST_TOO_DEEP")
    op = spec.get("op", "")
    if op == "custom_script":
        raise OpCompileError(
            "custom_script 被编译器拒绝（R12：禁 AI exec 代码）——"
            "逃生舱走 M4-4 人工审核通道，不是编译放行",
            code="R12_CUSTOM_SCRIPT_DENIED",
            suggestions=[{"action": "replace_op",
                          "target": "op",
                          "value": "最接近的声明式 op 组合"}])
    if op in UNIMPLEMENTED_OPS:
        raise OpCompileError(
            f"op {op!r} 已在工单声明但未实现（M4-4/5/11 后续项）——"
            "先用已实现的 13 个 op 组合",
            code="OP_UNIMPLEMENTED",
            suggestions=[{"action": "replace_op", "target": "op",
                          "value": sorted(OPS)}])
    builder = OPS.get(op)
    if builder is None:
        raise OpCompileError(f"未知 op {op!r}", code="UNKNOWN_OP",
                             suggestions=[{"action": "replace_op",
                                           "target": "op",
                                           "value": sorted(OPS)}])
    chain_src = src
    if "source" in spec:
        chain_src = compile_op(ad, tree, spec["source"], sid, src,
                               _depth=_depth + 1)
    return builder(ad, tree, sid, spec, chain_src)
