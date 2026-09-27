"""m42_live.py — M4-2 GNArtifact 可寻址产物单元真机验收（Blender 5.2.1）。

跑法：blender --background --factory-startup --python m42_live.py

A11 裁决：GN 路线的可寻址单元 = GNArtifact（node group 引用 +
socket_map 语义名→identifier + param_values）。AI/导演/经验库只面对
这个单元说话，不摸树。

验收项（全机械，B1 纪律）：
  1. 编译产物即 artifact：console.compile 后 rec["artifact"] 在场，
     socket_map 语义可寻址，fingerprint 与 adapter 同口径
  2. dump 打通：树 dump 确定性 + artifact 级元数据完整
  3. set_param 实例路（backdating）：不动树、写 instance 输入、param_values 记录
  4. set_param 组默认路：interface default_value 读回机验
  5. diff：同 spec 结构全同/参数差显示、别名视图判同、结构差异检出
  6. 反例：未知语义名 / 非 artifact diff —— 响亮失败
  7. 渲染：instance 写入真实生效（改动帧 diff 出图）
"""
import base64
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy

from gn_adapter import GNAdapter
from console import Console
from gn_artifact import GNArtifact

OUT = Path(r"D:\WorkBuddy专用！危险！！！！！！！！\2026-09-26-blender")
ROWS: list[dict] = []


def check(name, fn, expect=None):
    try:
        val = fn()
        if expect is not None and val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True, "detail": str(val)[:140]})
        print(f"  PASS  {name}  {val}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:200]})
        print(f"  FAIL  {name}  {exc!r}")


print(f"Blender {bpy.app.version_string}")
ad = GNAdapter(bpy)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.active_object
obj.name = "Mug"
obj.data = bpy.data.meshes.new("Base")

shutil.rmtree(HERE / "_m42_wal", ignore_errors=True)
con = Console(ad, obj, workdir=HERE / "_m42_wal")

BODY = {"id": "body", "op": "cylinder", "consumes_input": False,
        "parameters": [
            {"name": "Radius", "type": "FLOAT", "value": 0.04, "min": 0.02, "max": 0.12},
            {"name": "Depth", "type": "FLOAT", "value": 0.095, "min": 0.05, "max": 0.3},
        ]}
SPHERE = {"id": "body3", "op": "sphere", "consumes_input": False,
          "parameters": [
              {"name": "Radius", "type": "FLOAT", "value": 0.05, "min": 0.02, "max": 0.12},
          ]}

print("\n[1] 编译产物即 artifact（console 集成）")
for sid_ in ("body", "body2", "body3"):
    spec = dict(BODY, id=sid_) if sid_ != "body3" else SPHERE
    t0 = time.perf_counter()
    r = con.compile(spec)
    print(f"  compile {sid_:<6} {(time.perf_counter()-t0)*1000:6.1f} ms  "
          f"{'ok' if r.ok else f'FAIL {r.error}'}")
    check(f"编译 {sid_}", lambda r=r: r.ok, True)

recA = con.segments["body"]
recB = con.segments["body2"]
rec3 = con.segments["body3"]
artA = recA["artifact"]
artB = recB["artifact"]
art3 = rec3["artifact"]
check("rec 带 GNArtifact（body）", lambda: isinstance(artA, GNArtifact), True)
check("rec 带 GNArtifact（body2）", lambda: isinstance(artB, GNArtifact), True)
check("socket_map 语义可寻址（Radius/Depth）",
      lambda: sorted(artA.socket_map), ["Depth", "Radius"])
check("identifier 非空字符串",
      lambda: all(isinstance(v, str) and v for v in artA.socket_map.values()), True)
check("fingerprint 同口径（== rec.fingerprint）",
      lambda: artA.fingerprint()[:16], recA["fingerprint"])
check("spec 溯源在场", lambda: artA.spec["id"], "body")

print("\n[2] dump 打通（委托 adapter，确定性）")
d1, d2 = artA.dump(), artA.dump()
check("dump 树节点数 == 实际", lambda: len(d1["tree"]["nodes"]),
      len(recA["tree"].nodes))
check("dump 两次完全一致（确定性）", lambda: d1 == d2, True)
check("dump 带 socket_map", lambda: d1["socket_map"], artA.socket_map)
check("dump 带 param_values（初始空）", lambda: d1["param_values"], {})

print("\n[3] set_param 实例路（backdating：不动树，写 instance 输入）")
rep = artA.set_param("Radius", 0.045, mod=recA["mod"])
check("path=instance", lambda: rep["path"], "instance")
check("param_values 记录", lambda: artA.param_values.get("Radius"), 0.045)
check("树指纹不变（树没动）", lambda: artA.fingerprint()[:16], recA["fingerprint"])
_ident = artA.socket_map["Radius"]
check("instance 输入真实写上（5.2 properties.inputs 读回）",
      lambda: round(float(recA["mod"].properties.inputs[_ident]["value"]), 4), 0.045)

print("\n[4] set_param 组默认路（写进树 interface default）")
rep2 = artB.set_param("Radius", 0.05)
check("path=group_default", lambda: rep2["path"], "group_default")
_gv = next(i.default_value for i in recB["tree"].interface.items_tree
           if i.item_type == "SOCKET" and i.in_out == "INPUT"
           and i.name == "Radius")
check("interface default_value 读回 0.05（机验写上）",
      lambda: round(float(_gv), 4), 0.05)
check("param_values 记录", lambda: artB.param_values.get("Radius"), 0.05)

print("\n[5] diff（两个 GNArtifact 能 diff——工单验收项）")
dAB = artA.diff(artB)
check("同 spec 两段：树结构 diff 全空",
      lambda: any(dAB["tree_diff"].values()), False)
check("同 spec 两段：socket_diff 空", lambda: dAB["socket_diff"], {})
check("同 spec 两段：param_diff 显示双写值",
      lambda: dAB["param_diff"], {"Radius": [0.045, 0.05]})
alias = GNArtifact(ad, recA["tree"], recA["sid"], "body_alias")
d_alias = alias.diff(artA)
check("别名视图（同一棵树）判同", lambda: d_alias["same_fingerprint"], True)
dA3 = artA.diff(art3)
check("不同 op（cylinder vs sphere）：结构差异检出",
      lambda: bool(dA3["tree_diff"]["nodes_added"]) and bool(dA3["tree_diff"]["nodes_removed"]),
      True)
check("不同 op：same_fingerprint=False", lambda: dA3["same_fingerprint"], False)

print("\n[6] 反例（响亮失败）")
def _unknown_param():
    try:
        artA.set_param("Nope", 1.0, mod=recA["mod"])
        return "未被拒绝"
    except KeyError as e:
        return "KeyError"
check("未知语义名 → KeyError", _unknown_param, "KeyError")
def _bad_diff():
    try:
        artA.diff("not an artifact")
        return "未被拒绝"
    except TypeError:
        return "TypeError"
check("diff 非 artifact → TypeError", _bad_diff, "TypeError")
check("反例零残迹（param_values 未污染）",
      lambda: "Nope" in artA.param_values, False)

print("\n[7] 渲染：instance 写入真实生效（基线/改动两帧）")
rd0 = con.render_diff("m42_base")
check("首帧=基线：无 diff 图", lambda: rd0.render_diff_b64, "")
artA.set_param("Radius", 0.06, mod=recA["mod"])   # 0.04→0.06，域内明显变化
rd1 = con.render_diff("m42_changed")
check("改动帧 diff 出图 >2KB", lambda: len(rd1.render_diff_b64) > 2000, True)
check("diff 图是 PNG", lambda: base64.b64decode(rd1.render_diff_b64)[:4],
      b"\x89PNG")

failed = [r for r in ROWS if not r["ok"]]
print(f"\nM4-2 LIVE: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
out = OUT / "m42_result.json"
out.write_text(json.dumps(ROWS, ensure_ascii=False, indent=1), encoding="utf-8")
print("result ->", out)
sys.exit(1 if failed else 0)
