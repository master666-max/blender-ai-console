"""gn_artifact.py — M4-2 GNArtifact 可寻址产物单元（A11）
====================================================================

为什么存在：编译产物目前散在 console.segments 的 dict 里（tree/sid/mod/
fingerprint 各一把钥匙），没有统一的"产品"边界。A11 裁决：GN 路线的
可寻址单元是 **GNArtifact**——持有 node group 引用 + socket_map
（语义名 → interface identifier）+ param_values。AI/导演/经验库都
只面对这个单元说话，不摸树。

与既有层的打通（工单验收口径）：
  * dump()/fingerprint() 委托 GNAdapter（确定性序列化，实测 SHA-256 相同）
  * 两个 GNArtifact 能 diff（树结构 diff 委托 + socket_map/param 值差）

R16 单向依赖：gn_artifact → GNAdapter（引用传入，不反向）。
自身不 import bpy——纯 Python，可脱离 Blender 单测。

两处参数写入口（值域纪律与 console.set_param 一致——参数是语义名的，
不是 identifier 的）：
  * set_param(semantic, value, mod=None)：mod 在场 → 实例输入（backdating
    快路径，不动树）；mod=None → 组默认（写进树，fingerprint 随之变）
"""

from __future__ import annotations

from typing import Any

__all__ = ["GNArtifact"]


class GNArtifact:
    """GN 编译产物的可寻址单元（A11）。

    字段：
      tree          node group 引用（bpy NodeTree，本体不序列化）
      socket_map    语义参数名 → interface identifier（promote_input 产物）
      param_values  语义参数名 → 当前实例值（显式写入过的才记录）
      spec          编译来源 spec（溯源用，可 None）
    """

    def __init__(self, ad: Any, tree: Any, sid: dict[str, str], name: str,
                 spec: dict | None = None) -> None:
        self.ad = ad
        self.tree = tree
        self.socket_map: dict[str, str] = dict(sid)
        self.name = name
        self.param_values: dict[str, Any] = {}
        self.spec = spec

    # ── 打通既有机制（委托 adapter，绝不自造指纹口径）──────────
    def fingerprint(self) -> str:
        """与 GNAdapter.fingerprint 同一口径（树级确定性指纹）。"""
        return self.ad.fingerprint(self.tree)

    def dump(self) -> dict[str, Any]:
        """树 dump + artifact 级元数据（socket_map / param_values）。"""
        return {
            "artifact": self.name,
            "tree": self.ad.dump(self.tree),
            "socket_map": dict(self.socket_map),
            "param_values": dict(self.param_values),
        }

    # ── 参数写入（语义名寻址；两路分治）────────────────────────
    def set_param(self, semantic: str, value: Any, mod: Any = None) -> dict:
        """按语义名写参数。mod 在场 → 实例输入（backdating，树不变）；
        否则 → 组默认（树变，fingerprint 变）。返回执行报告 dict。"""
        if semantic not in self.socket_map:
            raise KeyError(
                f"{self.name} 无语义参数 {semantic!r}；可寻址：{sorted(self.socket_map)}")
        ident = self.socket_map[semantic]
        if mod is not None:
            self.ad.set_instance_input(mod, ident, value)
            path = "instance"
        else:
            self.ad.set_group_default(self.tree, semantic, value)
            path = "group_default"
        self.param_values[semantic] = value
        return {"artifact": self.name, "param": semantic,
                "value": value, "path": path,
                "fingerprint": self.fingerprint()}

    # ── diff（两个 GNArtifact 能 diff——工单验收项）───────────
    def diff(self, other: "GNArtifact") -> dict[str, Any]:
        """树结构 diff（委托）+ 接口/参数值差。指纹相同 → same=True。"""
        if not isinstance(other, GNArtifact):
            raise TypeError(f"diff 对象必须是 GNArtifact，实得 {type(other).__name__}")
        fd = self.ad.diff(self.tree, other.tree)
        socket_diff = {k: [self.socket_map.get(k), other.socket_map.get(k)]
                       for k in set(self.socket_map) | set(other.socket_map)
                       if self.socket_map.get(k) != other.socket_map.get(k)}
        keys = set(self.param_values) | set(other.param_values)
        param_diff = {k: [self.param_values.get(k), other.param_values.get(k)]
                      for k in keys
                      if self.param_values.get(k) != other.param_values.get(k)}
        fa, fb = self.fingerprint(), other.fingerprint()
        structure_changed = any(fd.values())
        return {
            "same_fingerprint": fa == fb and not structure_changed,
            "fingerprint_a": fa, "fingerprint_b": fb,
            "tree_diff": fd,
            "socket_diff": socket_diff,
            "param_diff": param_diff,
        }

    def __repr__(self) -> str:  # 调试友好
        return (f"GNArtifact({self.name!r}, params={sorted(self.socket_map)}, "
                f"fp={self.fingerprint()[:8]})")
