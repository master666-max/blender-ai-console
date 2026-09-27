"""m412f_live.py — M4-12 余项真机验收（R7f · ARKit-52 表情 schema + sample 模板路径）
==========================================================================

跑法：blender.exe -b --factory-startup -P m412f_live.py
产出：result JSON -> results/m412f_live_result.json

验收矩阵（工单 v2.15⑥/v2.16⑤ 登记的 M4-12 余项前两件）：
  [1] sample 模板路径：rig_samples/human_min.json 加载 → 校验归一化通过 + 指纹稳定
  [2] ARKit-52 白名单反例：未知名 → RIG_BSD_NAME_UNKNOWN（带 replace_value 建议）
  [3] 值域/字段反例：值越界 → RIG_BSD_VALUE_RANGE；expressions 未知字段 → RIG_EXPR_FIELD
  [4] 真机 compile：程序化宿主 mesh → compile_rig(human_min) → rig 生成 + ARKit-52
      shape key 通道建立（Basis + 3 声明）+ value 对账（0.4/0.6/0.6）
  [5] 幂等：同 plan 二次 compile → reused=True + SK 数量不变
  [6] 表情值变更：jawOpen 0.4→0.8 → 指纹变 → wipe 重建 → value=0.8 对账 + SK 不重复
  [7] mesh 反例：对象不存在 → RIG_EXPR_MESH_UNKNOWN；宿主非 MESH → RIG_EXPR_MESH_NOT_MESH
  [8] 向后兼容：无 expressions 的 rig_json 正常编译（detail.expressions=None）

诚实边界（v1 登记）：shape key 通道形状偏移为占位（零偏移）——真实表情形状
需美术资产/生成管线；v1 交付 = ARKit-52 标准命名通道 + 数值驱动接口。
"""

import json
import sys
import traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

import bpy

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import rig_compiler
from rig_compiler import RigConstraintError, normalize_rig_plan, compile_rig, rig_fingerprint

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


def expect_code(fn, code: str) -> str:
    try:
        fn()
    except RigConstraintError as e:
        assert e.code == code, f"错误码不符：期望 {code}，实得 {e.code}（{e.reason}）"
        return f"code={e.code} ✓"
    raise AssertionError(f"应当抛出 {code}，实际未抛")


def clear_scene() -> None:
    for obj in list(bpy.data.objects):
        if obj.name.startswith(("RIG-", "RIGPLAN_", "WGT-", "AI_")):
            bpy.data.objects.remove(obj, do_unlink=True)
    for coll in list(bpy.data.collections):
        if coll.name.startswith("WGTS_"):
            bpy.data.collections.remove(coll)


def make_host_mesh(name: str = "AI_HumanFace") -> "bpy.types.Object":
    bpy.ops.mesh.primitive_cube_add(size=0.2, location=(0, -0.05, 0.8))
    obj = bpy.context.active_object
    obj.name = name
    return obj


def load_sample() -> dict:
    return json.loads((HERE / "rig_samples" / "human_min.json").read_text(encoding="utf-8"))


# ── 准备：清场 + sample ─────────────────────────────────────
clear_scene()
sample = load_sample()

# [1] sample 模板路径
def t1():
    norm = normalize_rig_plan(sample)
    fp1 = rig_fingerprint(sample)
    fp2 = rig_fingerprint(sample)
    assert fp1 == fp2, "sample 指纹不稳定"
    assert norm["expressions"] is not None, "sample 的 expressions 未被解析"
    assert len(norm["bones"]) == 7, f"sample 骨骼数不符：{len(norm['bones'])}"
    assert norm["expressions"]["values"]["jawOpen"] == 0.4
    return f"human_min 归一化通过 · 7 骨骼 · fp={fp1} · 3 表情值"

check("[1] sample 模板加载 → 归一化 + 指纹稳定", t1)

# [2] ARKit-52 白名单反例
def t2():
    bad = json.loads(json.dumps(sample))
    bad["expressions"]["values"]["jawOpenX"] = 0.5
    def call():
        return normalize_rig_plan(bad)
    return expect_code(call, "RIG_BSD_NAME_UNKNOWN")

check("[2] expressions 未知名 → RIG_BSD_NAME_UNKNOWN", t2)

# [3] 值域 / 字段反例
def t3():
    over = json.loads(json.dumps(sample))
    over["expressions"]["values"]["jawOpen"] = 1.5
    expect_code(lambda: normalize_rig_plan(over), "RIG_BSD_VALUE_RANGE")
    badfield = json.loads(json.dumps(sample))
    badfield["expressions"]["host"] = "x"
    expect_code(lambda: normalize_rig_plan(badfield), "RIG_EXPR_FIELD")
    return "值越界 RIG_BSD_VALUE_RANGE ✓ · 未知字段 RIG_EXPR_FIELD ✓"

check("[3] 值域越界 + expressions 未知字段 → 结构化拒绝", t3)

# [4] 真机 compile + 表情通道建立
def t4():
    make_host_mesh()
    detail = compile_rig(bpy, sample, name="human_min")
    assert detail["reused"] is False
    assert detail["rig"] == "RIG-human_min", f"rig 名不符：{detail['rig']}"
    ex = detail["expressions"]
    assert ex is not None and ex["n_channels"] == 3, f"通道数不符：{ex}"
    sks = bpy.data.objects["AI_HumanFace"].data.shape_keys
    assert sks is not None, "宿主 mesh 无 shape_keys"
    names = [kb.name for kb in sks.key_blocks]
    assert names[0] == "Basis", f"Basis 缺失：{names}"
    for want_name, want_v in ex["channels"]:
        assert want_name in names, f"{want_name} 未建立"
        got = sks.key_blocks[want_name].value
        assert abs(got - want_v) < 1e-6, f"{want_name} 值不符：{got} != {want_v}"
    assert "jawOpen" in names and "mouthSmileLeft" in names
    return f"rig 生成 {detail['rig']} · SK={names} · jawOpen=0.4 对账"

check("[4] compile(human_min) → rig + ARKit-52 通道 + value 对账", t4)

# [5] 幂等
def t5():
    detail = compile_rig(bpy, sample, name="human_min")
    assert detail["reused"] is True, "同指纹应当复用"
    n = len(bpy.data.objects["AI_HumanFace"].data.shape_keys.key_blocks)
    assert n == 4, f"SK 数量应保持 4，实得 {n}"
    return f"reused=True · SK 数量不变（4）"

check("[5] 同 plan 二次 compile → 复用 + SK 不重复", t5)

# [6] 表情值变更 → 重建
def t6():
    changed = json.loads(json.dumps(sample))
    changed["expressions"]["values"]["jawOpen"] = 0.8
    detail = compile_rig(bpy, changed, name="human_min")
    assert detail["reused"] is False, "指纹变更应当重建"
    kb = bpy.data.objects["AI_HumanFace"].data.shape_keys.key_blocks["jawOpen"]
    assert abs(kb.value - 0.8) < 1e-6, f"jawOpen 应为 0.8，实得 {kb.value}"
    n = len(bpy.data.objects["AI_HumanFace"].data.shape_keys.key_blocks)
    assert n == 4, f"重建后 SK 不应重复，实得 {n}"
    return "指纹变 → wipe 重建 · jawOpen=0.8 对账 · SK 无重复"

check("[6] 表情值变更 → 重建 + 新值对账", t6)

# [7] mesh 反例
def t7():
    nomesh = json.loads(json.dumps(sample))
    nomesh["expressions"]["mesh"] = "AI_NoSuchMesh"
    expect_code(lambda: compile_rig(bpy, nomesh, name="human_min2"), "RIG_EXPR_MESH_UNKNOWN")
    notmesh = json.loads(json.dumps(sample))
    notmesh["expressions"]["mesh"] = "human_min"  # metarig 是 ARMATURE
    expect_code(lambda: compile_rig(bpy, notmesh, name="human_min3"), "RIG_EXPR_MESH_NOT_MESH")
    return "RIG_EXPR_MESH_UNKNOWN ✓ · RIG_EXPR_MESH_NOT_MESH ✓"

check("[7] 宿主 mesh 不在场 / 非 MESH → 结构化拒绝", t7)

# [8] 向后兼容回归
def t8():
    plain = {"name": "plain_rig",
             "bones": [
                 {"name": "root", "head": [0, 0, 0], "tail": [0, 0, 0.1]},
                 {"name": "spine", "head": [0, 0, 0.1], "tail": [0, 0, 0.5], "parent": "root"}]}
    detail = compile_rig(bpy, plain, name="plain_rig")
    assert detail["expressions"] is None, "无 expressions 时 detail 应为 None"
    assert detail["rig"] == "RIG-plain_rig" and not detail["reused"]
    return f"无 expressions 编译通过 · {detail['rig']} · expressions=None"

check("[8] 向后兼容：无 expressions 正常编译", t8)

# ── 落盘 ────────────────────────────────────────────────────
ok = all(c["ok"] for c in checks)
RESULTS.mkdir(parents=True, exist_ok=True)
out = {"suite": "m412f_live", "ok": ok,
       "passed": sum(1 for c in checks if c["ok"]), "total": len(checks),
       "checks": checks}
(RESULTS / "m412f_live_result.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nm412f_live: {out['passed']}/{out['total']} {'ALL GREEN' if ok else 'HAS FAILURES'}")
assert ok, "存在失败断言"
