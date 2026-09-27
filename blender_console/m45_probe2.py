"""m45_probe2.py — SDF 节点 socket 实况探针（R1 实现前置）。
"""
import json
from pathlib import Path
import bpy

OUT = Path(r"D:\WorkBuddy专用！危险！！！！！！！！\2026-09-26-blender")
report = {}
ng = bpy.data.node_groups.new("_probe2", "GeometryNodeTree")
for nid in ("GeometryNodeMeshToSDFGrid", "GeometryNodeSDFGridBoolean",
            "GeometryNodeGridToMesh", "GeometryNodeMeshGrid"):
    try:
        n = ng.nodes.new(nid)
        report[nid] = {
            "inputs": [{"name": s.name, "type": s.type, "id": s.identifier,
                        "default": (list(s.default_value) if hasattr(s.default_value, "__len__")
                                     else s.default_value) if not s.type == "GEOMETRY" else None}
                       for s in n.inputs],
            "outputs": [{"name": s.name, "type": s.type, "id": s.identifier}
                        for s in n.outputs],
        }
        print(nid, "OK")
    except Exception as exc:  # noqa: BLE001
        report[nid] = f"FAIL: {exc!r}"
        print(nid, "FAIL", exc)
(OUT / "m45_probe2.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
print("result ->", OUT / "m45_probe2.json")
