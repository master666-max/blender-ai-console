"""
gn_adapter.py — Blender Geometry Nodes 适配层 + 链接校验器
=========================================================

存在的唯一理由（实测依据，见 GN岔路调研_编译到GN还是执行bpy.ops.md）：

1. **Blender 的 GN Python API 在漂移，而且已经漂过。**
   5.2.1 LTS 实测踩到两处：
     · `node_tree.interface.items_ui`  →  改名为 `items_tree`
     · `modifier["Socket_N"] = v`      →  失效（报 no __getitem__ support）
                                          正确路径 `modifier.properties.inputs["Socket_N"] = v`
   LLM 一定会写错，而且会自信地写错。所以这些差异必须封在一层里，对上层隐藏。

2. **Grasshopper 的教训：显式 DAG + 禁止回环 = 可预测重算的前提。**
   所以 `link()` 默认强制校验：链接类型 + 环检测。回环直接拒绝，不静默通过。

3. **节点树是可 diff、可寻址、可版本化的资产。**
   实测：同一棵树两次 dump 的 SHA-256 一致；`NodesModifier.persistent_uid` 跨编辑稳定。

设计约束
--------
- **纯 Python 可测**：校验核心（`socket_compatible` / `find_cycles`）不依赖 bpy，
  `python gn_adapter.py` 即可跑通全部单元测试。
- **bpy 延迟导入**：只有真正要用 Blender 时才 import，所以 CI 里没装 Blender 也能测核心。
- **版本硬守卫**：只放行 5.2.x，其他版本直接 `UnsupportedBlender`，不做"尽力而为"。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "UnsupportedBlender",
    "GNValidationError",
    "ParamSpec",
    "GNAdapter",
    "socket_compatible",
    "find_cycles",
    "SOCKET_ALIAS",
    "ZONE_INPUT_TO_OUTPUT",
]


# ─────────────────────────────────────────────────────────────
# 异常
# ─────────────────────────────────────────────────────────────
class GNAdapterError(Exception):
    """适配层基础异常。"""


class UnsupportedBlender(GNAdapterError):
    """Blender 版本不在支持列表内。"""


class GNValidationError(GNAdapterError):
    """节点树结构校验失败（类型不匹配 / 出现回环 / 节点不存在）。"""


# ─────────────────────────────────────────────────────────────
# 版本守卫
# ─────────────────────────────────────────────────────────────
SUPPORTED_MINOR = {(5, 2)}


def parse_version(version: Sequence[int]) -> tuple[int, int, int]:
    v = tuple(int(x) for x in version)
    while len(v) < 3:
        v = (*v, 0)
    return v[0], v[1], v[2]


def version_supported(version: Sequence[int]) -> bool:
    major, minor, _ = parse_version(version)
    return (major, minor) in SUPPORTED_MINOR


# ─────────────────────────────────────────────────────────────
# 友好类型名 → Blender socket 类型
# ─────────────────────────────────────────────────────────────
SOCKET_ALIAS: dict[str, str] = {
    "FLOAT": "NodeSocketFloat",
    "INT": "NodeSocketInt",
    "BOOL": "NodeSocketBool",
    "BOOLEAN": "NodeSocketBool",
    "VECTOR": "NodeSocketVector",
    "COLOR": "NodeSocketColor",
    "RGBA": "NodeSocketColor",
    "STRING": "NodeSocketString",
    "GEOMETRY": "NodeSocketGeometry",
    "OBJECT": "NodeSocketObject",
    "COLLECTION": "NodeSocketCollection",
    "MATERIAL": "NodeSocketMaterial",
    "IMAGE": "NodeSocketImage",
    "ROTATION": "NodeSocketRotation",
    "MATRIX": "NodeSocketMatrix",
    "MENU": "NodeSocketMenu",
    "BUNDLE": "NodeSocketBundle",
    "CLOSURE": "NodeSocketClosure",
}


def resolve_socket_type(name: str) -> str:
    """接受 'FLOAT' / 'NodeSocketFloat' 两种写法，统一成 Blender 的写法。"""
    if name.startswith("NodeSocket"):
        return name
    key = name.strip().upper()
    if key not in SOCKET_ALIAS:
        raise GNValidationError(
            f"未知 socket 类型 {name!r}；可用：{sorted(SOCKET_ALIAS)}"
        )
    return SOCKET_ALIAS[key]


# ─────────────────────────────────────────────────────────────
# 纯函数 1：socket 类型兼容判定（不依赖 bpy，可单测）
# ─────────────────────────────────────────────────────────────
# Blender 会做部分隐式转换（int↔float、bool→float 等）；
# 但 GEOMETRY 与标量之间、STRING 与数值之间绝不允许。
# 我们把"允许但会隐式转换"标为 lossy=True，让上层能决定是否 warning。
_IMPLICIT_OK: dict[str, set[str]] = {
    "VALUE": {"VALUE", "INT", "BOOLEAN", "VECTOR", "RGBA", "ROTATION"},
    "INT": {"INT", "VALUE", "BOOLEAN"},
    "BOOLEAN": {"BOOLEAN", "VALUE", "INT"},
    "VECTOR": {"VECTOR", "VALUE", "INT", "RGBA", "ROTATION"},
    "RGBA": {"RGBA", "VECTOR", "VALUE"},
    "ROTATION": {"ROTATION", "VECTOR"},
    "STRING": {"STRING"},
    "GEOMETRY": {"GEOMETRY"},
    "OBJECT": {"OBJECT"},
    "COLLECTION": {"COLLECTION"},
    "MATERIAL": {"MATERIAL"},
    "IMAGE": {"IMAGE"},
    "TEXTURE": {"TEXTURE"},
    "MENU": {"MENU"},
    "BUNDLE": {"BUNDLE"},
    "CLOSURE": {"CLOSURE"},
    "MATRIX": {"MATRIX"},
}


def socket_compatible(
    from_type: str | None,
    to_type: str | None,
    from_structure: str = "SINGLE",
    to_structure: str = "SINGLE",
) -> tuple[bool, bool, str]:
    """判定两个 socket 能否相连。

    返回 `(ok, lossy, reason)`：
      · ok=False → 必须拒绝
      · lossy=True → 可连但会发生隐式转换，建议在段落计划里给个提示
    """
    if not from_type or not to_type:
        return False, False, "socket 类型缺失（可能是旧版 Blender 或 zone 虚拟 socket）"
    f, t = str(from_type).upper(), str(to_type).upper()
    if f == t:
        if from_structure != to_structure:
            return (True, True,
                    f"structure 不一致：{from_structure} → {to_structure}（Blender 会做隐式 field 化）")
        return True, False, ""
    allowed = _IMPLICIT_OK.get(f)
    if allowed is None:
        # 未知类型：不猜，放行但标记为 lossy，交给运行时裁决
        return True, True, f"未知 socket 类型 {f}，未做静态校验"
    if t not in allowed:
        return False, False, f"类型不兼容：{f} → {t}"
    return True, True, f"隐式转换 {f} → {t}"


# ─────────────────────────────────────────────────────────────
# 纯函数 2：环检测（不依赖 bpy，可单测）
# ─────────────────────────────────────────────────────────────
# Repeat / Simulation / Foreach 这类 zone 在链接图上天然成环，是合法的。
# 遇到 zone 内部回边时跳过，其余一律不允许有环。
ZONE_INPUT_TO_OUTPUT: dict[str, str] = {
    "GeometryNodeRepeatInput": "GeometryNodeRepeatOutput",
    "GeometryNodeSimulationInput": "GeometryNodeSimulationOutput",
    "GeometryNodeForeachGeometryElementInput": "GeometryNodeForeachGeometryElementOutput",
    "GeometryNodeClosureInput": "GeometryNodeClosureOutput",
}
_ZONE_OUTPUTS = set(ZONE_INPUT_TO_OUTPUT.values())
_ZONE_INPUTS = set(ZONE_INPUT_TO_OUTPUT)


def find_cycles(
    nodes: Iterable[str],
    edges: Iterable[tuple[str, str]],
    node_kind: Mapping[str, str] | None = None,
    allow_zones: bool = True,
) -> list[list[str]]:
    """找出链接图中的所有环。返回环的节点名列表（每个环以最小节点名起头，已去重）。"""
    node_kind = dict(node_kind or {})
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for a, b in edges:
        if a == b:
            continue
        if allow_zones:
            ka, kb = node_kind.get(a, ""), node_kind.get(b, "")
            # zone 输出 → 同 zone 输入 的回边是合法的，跳过
            if ka in _ZONE_OUTPUTS and ZONE_INPUT_TO_OUTPUT.get(kb) == ka:
                continue
        if a in adj and b in adj:
            adj[a].append(b)

    cycles: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    state: dict[str, int] = {n: 0 for n in adj}  # 0 未访问 1 在栈上 2 已完成
    stack: list[str] = []

    def dfs(u: str) -> None:
        state[u] = 1
        stack.append(u)
        for v in adj[u]:
            if state.get(v, 0) == 0:
                dfs(v)
            elif state.get(v) == 1:
                i = stack.index(v)
                cyc = stack[i:]
                key = tuple(sorted(cyc))
                if key not in seen:
                    seen.add(key)
                    m = cyc.index(min(cyc))
                    cycles.append(cyc[m:] + cyc[:m])
        stack.pop()
        state[u] = 2

    for n in sorted(adj):
        if state[n] == 0:
            dfs(n)
    return cycles


# ─────────────────────────────────────────────────────────────
# 参数规格：HDA 契约的代码化
# ─────────────────────────────────────────────────────────────
def _get_socket(collection: Any, key: Any, where: str) -> Any:
    """按名字或下标取 socket。

    为什么需要下标：zone（Repeat / Simulation / Foreach）的几何入口是**无名 CUSTOM socket**
    （5.2 实测：RepeatInput.inputs == [('Iterations','INT'), ('','CUSTOM')]），
    按名字取必然 KeyError，只能按下标取。
    """
    if isinstance(key, int):
        return collection[key]
    try:
        return collection[key]
    except Exception:  # noqa: BLE001  Blender 的 socket 集合只支持名字索引
        pass
    for sock in collection:
        if str(getattr(sock, "identifier", "")) == str(key):
            return sock
    raise KeyError(f"{where} 里找不到 socket {key!r}")


@dataclass(frozen=True)
class ParamSpec:
    """一个被 promote 出来的具名参数。

    三条硬性理由（不是美学偏好）：
      · `name` 必须是**艺术家语义**——实测确认 LLM 也靠名字理解参数（第 1 组 HDA 契约）
      · 只有 promote 出来的东西才能被 opinion 层覆盖（第 5 节实测）
      · 带 `min/max/unit` 后，"参数反查"可退化为结构化过滤，不必依赖 embedding（第 5 组）
    """

    name: str
    type: str = "FLOAT"
    default: Any = 0.0
    min: float | None = None
    max: float | None = None
    unit: str | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise GNValidationError("ParamSpec.name 不能为空")
        # 拒绝 args[0] / parm3 这类非语义命名——这正是我们要消灭的东西
        if self.name.lower().startswith(("arg", "parm", "input_")) or self.name.startswith("Socket_"):
            raise GNValidationError(
                f"参数名 {self.name!r} 不是艺术家语义名；请用 'Wall_Height' 而不是 'parm3'"
            )
        resolve_socket_type(self.type)

    @property
    def socket_type(self) -> str:
        return resolve_socket_type(self.type)


# ─────────────────────────────────────────────────────────────
# 适配层本体
# ─────────────────────────────────────────────────────────────
class GNAdapter:
    """Blender GN 的版本隔离层。所有版本差异只允许出现在这个类里。"""

    def __init__(self, bpy: Any = None, strict: bool = True) -> None:
        if bpy is None:
            import bpy as _bpy  # noqa: PLC0415  延迟导入：核心校验不需要 Blender
            bpy = _bpy
        self.bpy = bpy
        self.version = parse_version(bpy.app.version)
        self.strict = strict
        if strict and not version_supported(self.version):
            raise UnsupportedBlender(
                f"只支持 Blender {sorted(SUPPORTED_MINOR)}；"
                f"当前 {'.'.join(map(str, self.version))}。"
                f"要支持新版本请先补 gn_adapter 的差异分支，不要绕过守卫。"
            )

    # ── interface API（版本差异集中处）─────────────────────────
    @staticmethod
    def _interface_items(tree: Any) -> list[Any]:
        itf = tree.interface
        for attr in ("items_tree", "items_ui"):
            if hasattr(itf, attr):
                return list(getattr(itf, attr))
        raise UnsupportedBlender("node_tree.interface 既没有 items_tree 也没有 items_ui")

    @staticmethod
    def _new_socket(tree: Any, name: str, in_out: str, socket_type: str) -> Any:
        try:
            return tree.interface.new_socket(
                name=name, in_out=in_out, socket_type=socket_type
            )
        except TypeError:
            return tree.interface.new_socket(name=name, in_out=in_out, type=socket_type)

    # ── group 与参数 ──────────────────────────────────────────
    def new_group(self, name: str) -> Any:
        return self.bpy.data.node_groups.new(name, "GeometryNodeTree")

    def promote_input(self, tree: Any, spec: ParamSpec) -> str:
        """提升一个输入参数，返回它的 socket identifier（不是名字）。"""
        sock = self._new_socket(
            tree, spec.name, "INPUT", resolve_socket_type(spec.type)
        )
        try:
            sock.default_value = spec.default
        except Exception:  # noqa: BLE001  部分类型（Geometry/Object）没有默认值
            pass
        for attr, val in (("min_value", spec.min), ("max_value", spec.max)):
            if val is not None:
                try:
                    setattr(sock, attr, val)
                except Exception:  # noqa: BLE001
                    pass
        if spec.description:
            try:
                sock.description = spec.description
            except Exception:  # noqa: BLE001
                pass
        return str(sock.identifier)

    def promote_output(self, tree: Any, name: str, type_: str = "GEOMETRY") -> str:
        sock = self._new_socket(tree, name, "OUTPUT", resolve_socket_type(type_))
        return str(sock.identifier)

    def socket_id(self, tree: Any, name: str) -> str:
        for item in self._interface_items(tree):
            if item.name == name:
                return str(item.identifier)
        raise GNValidationError(f"节点组 {tree.name!r} 没有名为 {name!r} 的接口项")

    def set_group_default(self, tree: Any, name: str, value: Any) -> None:
        """改节点组自己的默认值。

        ⚠️ 实测警告（Blender 5.2.1 headless）：**这条路不可靠。**
        改 `interface` 的 default_value 之后，即使调 `tree.update_tag()`、
        新建 depsgraph、重赋 `modifier.node_group`，求值结果**都不会变**。
        （s0/s1/s4 三条策略实测全部失败，输出仍是旧值。）

        唯一可靠的改参方式是 per-instance 覆盖 —— 见 `set_instance_input`。
        保留本方法只为"预设初始值"，且**必须在首次求值之前调用**。
        """
        for item in self._interface_items(tree):
            if item.name == name:
                item.default_value = value
                return
        raise GNValidationError(f"节点组 {tree.name!r} 没有名为 {name!r} 的接口项")

    def socket_map(self, tree: Any) -> dict[str, str]:
        return {i.name: str(i.identifier) for i in self._interface_items(tree)}

    # ── 节点与链接 ────────────────────────────────────────────
    def add_node(self, tree: Any, bl_idname: str, label: str | None = None) -> Any:
        if not bl_idname or not hasattr(self.bpy.types, bl_idname):
            raise GNValidationError(f"Blender 里不存在节点类型 {bl_idname!r}")
        node = tree.nodes.new(bl_idname)
        if label:
            node.name = label
        return node

    def link(
        self,
        tree: Any,
        from_node: Any,
        from_socket: str,
        to_node: Any,
        to_socket: str,
        check_cycle: bool = True,
    ) -> Any:
        """连一条边，连之前做类型校验与环检测。回环直接拒绝。"""
        try:
            fs = _get_socket(from_node.outputs, from_socket, f"{from_node.name}.outputs")
        except (KeyError, IndexError, TypeError) as exc:
            raise GNValidationError(
                f"{from_node.name}.outputs 里没有 {from_socket!r}"
            ) from exc
        try:
            ts = _get_socket(to_node.inputs, to_socket, f"{to_node.name}.inputs")
        except (KeyError, IndexError, TypeError) as exc:
            raise GNValidationError(
                f"{to_node.name}.inputs 里没有 {to_socket!r}"
            ) from exc

        ok, lossy, reason = socket_compatible(
            getattr(fs, "type", None),
            getattr(ts, "type", None),
            getattr(fs, "structure_type", "SINGLE"),
            getattr(ts, "structure_type", "SINGLE"),
        )
        if not ok:
            raise GNValidationError(
                f"拒绝连接 {from_node.name}:{from_socket} → "
                f"{to_node.name}:{to_socket} —— {reason}"
            )
        self.warnings: list[str] = getattr(self, "warnings", [])
        if lossy and reason:
            self.warnings.append(f"{from_node.name}:{from_socket} → {to_node.name}:{to_socket}｜{reason}")

        link = tree.links.new(fs, ts)
        if check_cycle and not ts.is_multi_input:
            cyc = self.find_tree_cycles(tree)
            if cyc:
                try:
                    tree.links.remove(link)
                except Exception:  # noqa: BLE001  尽力回滚，别把脏树留给上层
                    pass
                raise GNValidationError(f"回环被拒绝：{' → '.join(cyc[0])} → {cyc[0][0]}")
        return link

    def find_tree_cycles(self, tree: Any) -> list[list[str]]:
        names = [n.name for n in tree.nodes]
        kind = {n.name: n.bl_idname for n in tree.nodes}
        edges = [(l.from_node.name, l.to_node.name) for l in tree.links]
        return find_cycles(names, edges, kind)

    # ── modifier / opinion 层 ─────────────────────────────────
    def attach(self, obj: Any, tree: Any, name: str | None = None) -> Any:
        mod = obj.modifiers.new(name or tree.name, "NODES")
        mod.node_group = tree
        return mod

    def invalidate(self, obj: Any = None, tree: Any = None) -> None:
        """让改动真正生效 —— 这一步漏掉，GN 就是"改了但没变"。

        实测（5.2.1 headless）五条策略：
          · 什么都不做                    → 无效
          · `tree.update_tag()`           → 无效
          · 新建 depsgraph                → 无效
          · `obj.update_tag()`            → ✅ 有效
          · `tree.interface_update(ctx)`  → ✅ 有效
        所以优先 `obj.update_tag()`（不需要 context，headless 更稳）。
        """
        if obj is not None:
            try:
                obj.update_tag()
                return
            except Exception:  # noqa: BLE001
                pass
        if tree is not None:
            try:
                tree.interface_update(self.bpy.context)
                return
            except Exception:  # noqa: BLE001
                pass

    def set_instance_input(
        self,
        modifier: Any,
        socket_identifier: str,
        value: Any,
        invalidate: bool = True,
    ) -> None:
        """写 per-instance 输入（= opinion 覆盖）。**这是唯一可靠的改参方式。**

        5.2 实测三步都要对：
          1. 容器是 `modifier.properties.inputs[id]`，它是一个 IDPropertyGroup
          2. 真正的值在 **`["value"]`** 这个字段里（同组还有 `type` / `attribute_name`）
             —— 直接 `properties.inputs[id] = v` 会把整个 group 替换成标量，静默无效
          3. 写完必须 `invalidate()`，否则求值仍是旧结果

        4.x 的 `modifier[id] = v` 在 5.2 已彻底失效（no __getitem__ support）。
        """
        errors: list[str] = []
        try:
            grp = modifier.properties.inputs[socket_identifier]
            try:
                grp["value"] = value
            except Exception:  # noqa: BLE001  某些类型没有现成 key
                grp.update({"value": value})
        except Exception as exc:  # noqa: BLE001
            errors.append(f"properties.inputs[{socket_identifier!r}]['value']: {exc!r}")
        else:
            if invalidate:
                self.invalidate(obj=getattr(modifier, "id_data", None),
                                tree=getattr(modifier, "node_group", None))
            return

        try:
            modifier[socket_identifier] = value
        except Exception as exc:  # noqa: BLE001
            errors.append(f"modifier[{socket_identifier!r}]: {exc!r}")
        else:
            if invalidate:
                self.invalidate(obj=getattr(modifier, "id_data", None),
                                tree=getattr(modifier, "node_group", None))
            return

        raise GNAdapterError(
            f"无法写入 per-instance 输入 {socket_identifier!r}（Blender "
            f"{'.'.join(map(str, self.version))}）：" + " | ".join(errors)
        )

    def snapshot_instance_inputs(self, modifier: Any) -> dict[str, Any]:
        """快照 modifier 当前全部 per-instance 输入值（键 = socket identifier）。

        R3 实测教训（m5_spec_live）：**node_group 赋值时 Blender 会按
        identifier 迁移旧树的存储值**——跨树 Socket_N 索引撞车会串门：
        cube.Size(Socket_2) 吃到 cylinder.Radius(Socket_2) 的 0.045，
        还原原树后 cylinder.Depth(Socket_3) 又被变体默认 0.12 覆盖。
        换树前 snapshot、还原树后 restore，才能保证预览零残留。
        """
        snap: dict[str, Any] = {}
        tree = getattr(modifier, "node_group", None)
        if tree is None:
            return snap
        for item in self._interface_items(tree):
            try:
                if item.item_type != 'SOCKET' or item.in_out != 'INPUT':
                    continue
            except Exception:  # noqa: BLE001  非 socket 项（panel 等）
                continue
            ident = str(item.identifier)
            try:
                snap[ident] = modifier.properties.inputs[ident]["value"]
            except Exception:  # noqa: BLE001  无 value 键的 socket 跳过
                pass
        return snap

    def restore_instance_inputs(self, modifier: Any, snap: dict[str, Any],
                                invalidate: bool = True) -> int:
        """按 identifier 重放快照值（只写当前 interface 里实际存在的键）。

        返回成功重放的条数。写完全部再一次 invalidate（批量重放只刷一次）。
        """
        n = 0
        for ident, val in snap.items():
            try:
                grp = modifier.properties.inputs[ident]
                try:
                    grp["value"] = val
                except Exception:  # noqa: BLE001
                    grp.update({"value": val})
                n += 1
            except Exception:  # noqa: BLE001  键已随换树消失 → 跳过
                pass
        if invalidate:
            self.invalidate(obj=getattr(modifier, "id_data", None),
                            tree=getattr(modifier, "node_group", None))
        return n

    def realize(self, obj: Any, modifier: Any | None = None) -> Any:
        """把 GN 求值结果实例化为真实网格（GoodPoint 的 bake 边界）。

        实测：`bpy.ops.object.geometry_nodes_apply` 在 headless 下调不动
        （dir 里存在但报 could not be found），改用 meshes.new_from_object，0.19 ms。
        """
        deps = self.bpy.context.evaluated_depsgraph_get()
        deps.update()
        evaluated = obj.evaluated_get(deps)
        new_mesh = self.bpy.data.meshes.new_from_object(evaluated)
        if modifier is not None:
            obj.modifiers.remove(modifier)
        obj.data = new_mesh
        return new_mesh

    # ── 序列化 / 寻址 ─────────────────────────────────────────
    def dump(self, tree: Any) -> dict[str, Any]:
        """确定性序列化：同一棵树两次 dump 结果完全一致（实测 SHA-256 相同）。"""
        iface = []
        for i in self._interface_items(tree):
            iface.append({
                "name": i.name,
                "id": str(i.identifier),
                "in_out": str(i.in_out),
                "type": str(i.socket_type),
            })
        nodes = sorted(
            ({"name": n.name, "bl_idname": n.bl_idname, "loc": tuple(n.location)}
             for n in tree.nodes),
            key=lambda d: d["name"],
        )
        links = sorted(
            ({"from": l.from_node.name, "fs": str(l.from_socket.identifier),
              "to": l.to_node.name, "ts": str(l.to_socket.identifier)}
             for l in tree.links),
            key=lambda d: (d["from"], d["fs"], d["to"], d["ts"]),
        )
        return {"name": tree.name, "interface": iface, "nodes": nodes, "links": links}

    def fingerprint(self, tree: Any) -> str:
        blob = json.dumps(self.dump(tree), sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def diff(self, a: Any, b: Any) -> dict[str, list[Any]]:
        """两棵树的结构 diff —— 节点树是 JSON 化的，所以 .blend 那套二进制无解的问题绕过去了。"""
        da, db = self.dump(a), self.dump(b)
        ka = {(n["name"], n["bl_idname"]) for n in da["nodes"]}
        kb = {(n["name"], n["bl_idname"]) for n in db["nodes"]}
        la = {(l["from"], l["fs"], l["to"], l["ts"]) for l in da["links"]}
        lb = {(l["from"], l["fs"], l["to"], l["ts"]) for l in db["links"]}
        pa = {i["name"]: i["id"] for i in da["interface"]}
        pb = {i["name"]: i["id"] for i in db["interface"]}
        return {
            "nodes_added": sorted(kb - ka),
            "nodes_removed": sorted(ka - kb),
            "links_added": sorted(lb - la),
            "links_removed": sorted(la - lb),
            "params_added": sorted(set(pb) - set(pa)),
            "params_removed": sorted(set(pa) - set(pb)),
        }


# ─────────────────────────────────────────────────────────────
# 纯 Python 单元测试（不需要 Blender）
# ─────────────────────────────────────────────────────────────
def _run_tests() -> None:
    ok = lambda c, m: (_ for _ in ()).throw(AssertionError(m)) if not c else None

    # 1. socket 兼容
    ok(socket_compatible("VALUE", "VALUE")[0], "同类型应可连")
    ok(socket_compatible("INT", "VALUE")[0], "int→float 隐式转换应放行")
    ok(socket_compatible("INT", "VALUE")[1], "隐式转换应标记 lossy")
    ok(not socket_compatible("GEOMETRY", "VALUE")[0], "geometry→value 必须拒绝")
    ok(not socket_compatible("STRING", "INT")[0], "string→int 必须拒绝")
    ok(socket_compatible("GEOMETRY", "GEOMETRY") == (True, False, ""), "geometry 直连应无损")

    # 2. 环检测
    nodes = ["a", "b", "c"]
    ok(find_cycles(nodes, [("a", "b"), ("b", "c")]) == [], "链状不应有环")
    cyc = find_cycles(nodes, [("a", "b"), ("b", "c"), ("c", "a")])
    ok(len(cyc) == 1 and set(cyc[0]) == {"a", "b", "c"}, "三角环应被检出")

    # 3. zone 回边必须放行
    #    实测：Blender 并**不**把 zone 的反馈表示为普通 link（links 里查无此边），
    #    zone 内部环由 paired_output 承载。但为防御未来版本/手工连线，仍放行双向 zone 边。
    kind = {"zi": "GeometryNodeRepeatInput", "zo": "GeometryNodeRepeatOutput"}
    zcyc = find_cycles(["zi", "zo"], [("zi", "zo"), ("zo", "zi")], kind)
    ok(zcyc == [], "zone 双向边不应被判为环")
    ok(not version_supported((4, 5, 0)), "4.5 不受支持（重复断言守卫稳定）")

    # 4. 自环
    ok(find_cycles(["a"], [("a", "a")]) == [], "自边应被忽略")

    # 5. 类型别名
    ok(resolve_socket_type("FLOAT") == "NodeSocketFloat", "FLOAT 别名")
    ok(resolve_socket_type("NodeSocketFloat") == "NodeSocketFloat", "原名透传")
    try:
        resolve_socket_type("NOPE")
        ok(False, "未知类型应抛错")
    except GNValidationError:
        pass

    # 6. ParamSpec 拒绝非语义命名
    p = ParamSpec(name="Wall_Height", type="FLOAT", default=2.4, min=0.1, max=10.0, unit="m")
    ok(p.socket_type == "NodeSocketFloat", "ParamSpec 应解析出 socket 类型")
    for bad in ("parm3", "args[0]", "Socket_2", "Input_1"):
        try:
            ParamSpec(name=bad)
            ok(False, f"{bad} 应被拒绝")
        except GNValidationError:
            pass

    # 7. 版本守卫
    ok(version_supported((5, 2, 1)), "5.2.1 应受支持")
    ok(not version_supported((4, 5, 0)), "4.5 不应受支持")
    ok(parse_version((5, 2)) == (5, 2, 0), "版本号补齐")

    print("gn_adapter core tests: PASS")


if __name__ == "__main__":
    _run_tests()
