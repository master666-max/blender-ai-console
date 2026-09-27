"""m412g_live.py — M4-12 收官真机验收（R7g · 多 rig 共存 v2 架构）
======================================================================

跑法：blender.exe -b --factory-startup -P m412g_live.py
产出：result JSON -> results/m412g_live_result.json

背景（工单 v2.19⑥ 登记的 M4-12 最后一块）：v1 的 wipe 按全局前缀扫
RIG-*/WGT-*/WGTS_*——第二个 rig 一编译就把第一个的产物全删（多 rig 共存雷）。
v2 归属隔离：生成后 diff 场景快照沉淀 widget 产物名单进 metarig
rig_widgets 属性；wipe 只清 metarig/RIG-<name> 精确名 + 名单内产物。

验收矩阵：
  [1] rig A 编译 → 产物集对账（metarig + RIG-<name> + 名单沉淀 + WGTS 集合）
  [2] rig B 编译 → A 产物全数在场（共存核心断言）+ B 产物在场 + 名单互斥
  [3] B 指纹变更 wipe 重建 → A 产物仍全数在场（wipe 隔离核心断言）
  [4] A 指纹变更 wipe 重建 → B 产物仍全数在场（对称验证）
  [5] 复用路径：A 同指纹二次 compile → reused=True + 名单不重复沉淀
  [6] 外部造的 metarig（无 rig_widgets 属性）→ 兜底精确删 RIG-<name> + 新 rig 在场
  [7] 孤儿不碰：预置 WGT-unrelated / WGTS_unrelated → 全流程后仍在场
  [8] 表情通道共存：A/B 往同一 mesh 建不同 ARKit 通道 → 值独立对账互不覆盖

诚实边界：basic.raw_copy 类骨骼可能不生成 WGT 对象（widget 归控制骨骼）——
断言不依赖 WGT 对象数，用名单机制与 WGTS 集合归属对账。
"""

import json
import sys
import traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

import bpy

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from rig_compiler import RigConstraintError, compile_rig, rig_fingerprint

RESULTS = ROOT / "results"
checks: list[dict] = []


def check(name: str, fn) -> None:
    rec: dict = {"name": name}
    try:
        rec["ok"] = True
        rec["detail"] = fn()
        print(f"  PASS  {name}  {str(rec['detail'])[:150]}")
    except Exception as e:  # noqa: BLE001
        rec["ok"] = False
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["trace"] = traceback.format_exc(limit=3)
        print(f"  FAIL  {name}  {type(e).__name__}: {str(e)[:150]}")
    checks.append(rec)


def clear_scene() -> None:
    for obj in list(bpy.data.objects):
        if obj.name.startswith(("RIG-", "RIGPLAN_", "WGT-", "AI_")):
            bpy.data.objects.remove(obj, do_unlink=True)
    for coll in list(bpy.data.collections):
        if coll.name.startswith("WGTS_"):
            bpy.data.collections.remove(coll)


def rig_plan(name: str, x: float = 0.0, z_shift: float = 0.0) -> dict:
    """最简 rig plan：root + spine + head，x 参数供指纹变更。"""
    return {"name": name,
            "bones": [
                {"name": "root", "head": [x, 0.0, 0.0], "tail": [x, 0.0, 0.1]},
                {"name": "spine", "head": [x, 0.0, 0.1], "tail": [x, 0.0, 0.5],
                 "parent": "root"},
                {"name": "head", "head": [x, 0.0, 0.5], "tail": [x, 0.05, 0.8 + z_shift],
                 "parent": "spine"}]}


def product_assets(bpy, detail: dict) -> dict:
    """detail → 本 rig 应在场的产物资产（对象名集合 / 集合名集合）。"""
    meta = bpy.data.objects[detail["metarig"]]
    rec = json.loads(meta["rig_widgets"])
    return {"objects": {detail["metarig"], detail["rig"]} | set(rec["objects"]),
            "collections": set(rec["collections"])}


def assert_present(bpy, prod: dict, who: str) -> None:
    missing = [n for n in prod["objects"] if bpy.data.objects.get(n) is None]
    assert not missing, f"{who} 产物对象缺失：{missing}"
    cn_all = {c.name for c in bpy.data.collections}
    missing_c = [n for n in prod["collections"]
                 if n not in cn_all and not any(k.startswith(n + ".") for k in cn_all)]
    assert not missing_c, f"{who} 产物集合缺失：{missing_c}"


# ── 准备：清场 + 预置孤儿（[7] 全程断言不碰他者）────────────────
clear_scene()
bpy.data.objects.new("WGT-unrelated", None)
bpy.data.objects["WGT-unrelated"].name = "WGT-unrelated"  # 确保 exact 名
for o in list(bpy.data.objects):
    if o.name == "WGT-unrelated":
        bpy.context.scene.collection.objects.link(o)
bpy.data.collections.new("WGTS_unrelated")

# [1] rig A 编译
def t1():
    detail = compile_rig(bpy, rig_plan("RigA"), name="RigA")
    assert detail["reused"] is False and detail["rig"] == "RIG-RigA"
    assert "widgets" in detail, "detail 缺 widgets 对账面"
    meta = bpy.data.objects["RigA"]
    rec = json.loads(meta["rig_widgets"])
    assert isinstance(rec["objects"], list) and isinstance(rec["collections"], list)
    # Rigify 生成流程固定建 WGTS 集合——名单至少应有集合条目
    assert rec["collections"], f"WGTS 集合名单为空：{rec}"
    prod = product_assets(bpy, detail)
    assert_present(bpy, prod, "RigA")
    return (f"RigA 编译 · rig={detail['rig']} · 名单 obj={rec['objects']} "
            f"coll={rec['collections']}")

RIG_A_DETAIL = {"metarig": "RigA", "rig": "RIG-RigA"}
check("[1] rig A 编译 → 产物集 + 名单沉淀对账", t1)

# 供后续各断言使用的 A 产物快照（t1 后立即固化）
def a_products():
    meta = bpy.data.objects["RigA"]
    rec = json.loads(meta["rig_widgets"])
    return {"objects": {"RigA", "RIG-RigA"} | set(rec["objects"]),
            "collections": set(rec["collections"])}

# [2] rig B 编译 → A 共存
def t2():
    before = a_products()
    detail = compile_rig(bpy, rig_plan("RigB", x=2.0), name="RigB")
    assert detail["reused"] is False and detail["rig"] == "RIG-RigB"
    assert_present(bpy, before, "RigA(编译B后)")
    b_prod = product_assets(bpy, detail)
    assert_present(bpy, b_prod, "RigB")
    # 名单互斥：A/B 的名单对象不交叠
    assert not (before["objects"] & (b_prod["objects"] - {"RIG-RigB", "RigB"})), \
        "A/B widget 名单交叠"
    assert not (before["collections"] & b_prod["collections"]), "A/B WGTS 集合交叠"
    return "B 编译后 A 产物全数在场 · B 产物在场 · 名单互斥"

check("[2] rig B 编译 → A 共存 + 名单互斥", t2)

# [3] B 指纹变更 wipe 重建 → A 不受伤
def t3():
    before = a_products()
    b_changed = rig_plan("RigB", x=2.0, z_shift=0.15)
    fp_old = rig_fingerprint(rig_plan("RigB", x=2.0))
    fp_new = rig_fingerprint(b_changed)
    assert fp_old != fp_new, "指纹变更构造失败"
    detail = compile_rig(bpy, b_changed, name="RigB")
    assert detail["reused"] is False, "指纹变更应当重建"
    assert detail["rig"] == "RIG-RigB"
    assert_present(bpy, before, "RigA(B重建后)")
    # 旧 B 的 WGTS 集合应被名单清掉（不残留）
    b_meta = bpy.data.objects["RigB"]
    b_rec = json.loads(b_meta["rig_widgets"])
    for cn in b_rec["collections"]:
        alive = [c.name for c in bpy.data.collections
                 if c.name == cn or c.name.startswith(cn + ".")]
        assert len(alive) <= 1, f"B 重建后旧 WGTS 集合残留：{alive}"
    return "B wipe 重建 · A 产物全数在场 · B 旧集合无残留"

check("[3] B 指纹变更 wipe → A 隔离不受伤", t3)

# [4] A 指纹变更 wipe 重建 → B 不受伤（对称验证）
def t4():
    b_meta = bpy.data.objects["RigB"]
    b_rec = json.loads(b_meta["rig_widgets"])
    b_prod = {"objects": {"RigB", "RIG-RigB"} | set(b_rec["objects"]),
              "collections": set(b_rec["collections"])}
    detail = compile_rig(bpy, rig_plan("RigA", x=0.1), name="RigA")
    assert detail["reused"] is False, "指纹变更应当重建"
    assert_present(bpy, b_prod, "RigB(A重建后)")
    return "A wipe 重建 · B 产物全数在场（对称）"

check("[4] A 指纹变更 wipe → B 隔离不受伤", t4)

# [5] 复用路径：名单不重复沉淀
def t5():
    d1 = compile_rig(bpy, rig_plan("RigA", x=0.1), name="RigA")
    assert d1["reused"] is True, "同指纹应当复用"
    rec1 = json.loads(bpy.data.objects["RigA"]["rig_widgets"])
    d2 = compile_rig(bpy, rig_plan("RigA", x=0.1), name="RigA")
    assert d2["reused"] is True
    rec2 = json.loads(bpy.data.objects["RigA"]["rig_widgets"])
    assert rec1 == rec2, "复用不应改写名单"
    # WGTS 集合无重复（.001 漂移检测）
    for cn in rec2["collections"]:
        alive = [c.name for c in bpy.data.collections
                 if c.name == cn or c.name.startswith(cn + ".")]
        assert len(alive) == 1, f"WGTS 集合重复：{alive}"
    return "reused=True ×2 · 名单稳定 · 集合无重复"

check("[5] 复用路径 → 名单稳定无重复", t5)

# [6] 外部造的 metarig（无 rig_widgets 属性）→ 兜底精确删
def t6():
    arm = bpy.data.armatures.new("ExtRig")
    ext = bpy.data.objects.new("ExtRig", arm)
    bpy.context.scene.collection.objects.link(ext)
    dummy = bpy.data.objects.new("RIG-ExtRig", None)
    bpy.context.scene.collection.objects.link(dummy)
    detail = compile_rig(bpy, rig_plan("ExtRig", x=4.0), name="ExtRig")
    assert detail["reused"] is False and detail["rig"] == "RIG-ExtRig"
    # 旧占位 RIG-ExtRig（空对象）已被精确清除——现名下是新生成的 ARMATURE
    new_rig = bpy.data.objects["RIG-ExtRig"]
    assert new_rig.type == "ARMATURE", f"旧占位未被清换：{new_rig.type}"
    # A/B 仍在场
    assert bpy.data.objects.get("RigA") and bpy.data.objects.get("RigB")
    return "无名单 metarig → 兜底精确删 + 新 rig 在场 + A/B 不受伤"

check("[6] 外部 metarig 兜底路径", t6)

# [7] 孤儿不碰（全流程收尾断言）
def t7():
    assert bpy.data.objects.get("WGT-unrelated") is not None, "孤儿 WGT 被误删"
    cn_all = {c.name for c in bpy.data.collections}
    assert "WGTS_unrelated" in cn_all, f"孤儿集合被误删：{cn_all}"
    return "WGT-unrelated / WGTS_unrelated 全流程后仍在场（不碰他者）"

check("[7] 孤儿 WGT/集合不被误删", t7)

# [8] 表情通道共存（同一 mesh 双 rig 各建各的通道）
def t8():
    bpy.ops.mesh.primitive_cube_add(size=0.2, location=(0, -0.05, 0.8))
    face = bpy.context.active_object
    face.name = "AI_SharedFace"
    plan_a = rig_plan("RigA", x=0.1)
    plan_a["expressions"] = {"mesh": "AI_SharedFace",
                             "values": {"jawOpen": 0.4}}
    plan_b = rig_plan("RigB", x=2.0, z_shift=0.15)
    plan_b["expressions"] = {"mesh": "AI_SharedFace",
                             "values": {"eyeBlinkLeft": 0.9, "browInnerUp": 0.5}}
    da = compile_rig(bpy, plan_a, name="RigA")
    db = compile_rig(bpy, plan_b, name="RigB")
    # A 重建（指纹变）→ B 的通道值不受影响
    assert da["expressions"]["n_channels"] == 1
    assert db["expressions"]["n_channels"] == 2
    sks = face.data.shape_keys
    names = [kb.name for kb in sks.key_blocks]
    for want in ("Basis", "jawOpen", "eyeBlinkLeft", "browInnerUp"):
        assert want in names, f"{want} 缺失：{names}"
    assert abs(sks.key_blocks["jawOpen"].value - 0.4) < 1e-6
    assert abs(sks.key_blocks["eyeBlinkLeft"].value - 0.9) < 1e-6
    assert abs(sks.key_blocks["browInnerUp"].value - 0.5) < 1e-6
    assert len(names) == 4, f"通道重复：{names}"
    return f"双 rig 通道共存 · SK={names} · 值独立对账 0.4/0.9/0.5"

check("[8] 同一 mesh 双 rig 表情通道共存", t8)

# ── 落盘 ────────────────────────────────────────────────────
ok = all(c["ok"] for c in checks)
RESULTS.mkdir(parents=True, exist_ok=True)
out = {"suite": "m412g_live", "ok": ok,
       "passed": sum(1 for c in checks if c["ok"]), "total": len(checks),
       "checks": checks}
(RESULTS / "m412g_live_result.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nm412g_live: {out['passed']}/{out['total']} {'ALL GREEN' if ok else 'HAS FAILURES'}")
assert ok, "存在失败断言"
