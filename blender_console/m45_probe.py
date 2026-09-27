"""m45_probe.py — M4-5 SDF 中间表示前置 API 探针（Blender 5.2.1）。

A30 裁决引用"Blender GN 已原生内置 sdf_grid_boolean"——该调研早于 5.2，
本探针核实 5.2.1 里 SDF 节点的真实存在形态与 bl_idname，给 M4-5 定范围。
"""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

import bpy

OUT = ROOT / "results"

all_geo = sorted(n for n in dir(bpy.types) if n.startswith("GeometryNode"))
sdf_like = [n for n in all_geo if "sdf" in n.lower()]
grid_like = [n for n in all_geo if "grid" in n.lower()]
volume_like = [n for n in all_geo if "volume" in n.lower()]

print(f"GeometryNode* 总数: {len(all_geo)}")
print(f"含 'sdf': {sdf_like or '无'}")
print(f"含 'grid': {grid_like or '无'}")
print(f"含 'volume': {volume_like}")

# 候选 bl_idname 直查 + 实建节点尝试（存在性硬证据）
CANDIDATES = ["GeometryNodeSDFGridBoolean", "GeometryNodeSDFGridSphere",
              "GeometryNodeSDFGridBox", "GeometryNodeSDFGridVDB",
              "GeometryNodeGridBoolean", "GeometryNodeVolumeBoolean"]
probe = {}
for c in CANDIDATES:
    exists = hasattr(bpy.types, c)
    made = None
    if exists:
        try:
            ng = bpy.data.node_groups.new("_probe", "GeometryNodeTree")
            node = ng.nodes.new(c)
            made = {"inputs": [s.name for s in node.inputs],
                    "outputs": [s.name for s in node.outputs]}
            bpy.data.node_groups.remove(ng)
        except Exception as exc:  # noqa: BLE001
            made = f"add_node 失败: {exc!r}"
    probe[c] = {"registered": exists, "add_node": made}
    print(f"  {c}: registered={exists} add_node={made}")

out = {"geo_node_total": len(all_geo), "sdf_like": sdf_like,
       "grid_like": grid_like, "volume_like": volume_like,
       "candidates": probe, "blender": bpy.app.version_string}
(OUT / "m45_probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
print("result ->", OUT / "m45_probe.json")
