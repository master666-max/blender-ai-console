"""m412_probe.py — M4-12 Rigify 5.2 API 漂移探针（R7-1 · go/no-go 依据）

跑法：blender.exe -b --factory-startup -P m412_probe.py
产出：result JSON -> results/m412_probe_result.json

M4-12 需要的四件能力（工单口径）：
  A. rigify addon 可启用（版本/结构）
  B. metarig 创建（sample API 候选逐一试 + rig_templates 清点）
  C. rigify_generate（老 API pose.rigify_generate 是否存活）
  D. Delta Mush modifier 在 5.2 的参数面（形变质量验收的后处理节点）

探针纪律：每步独立 try/except，失败记 reason 不中断——probe 的价值
就是把所有漂移点一次抓全，而不是第一个坑就停。
"""
import json
import sys
import traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]  # 仓库根（相对推导，跨机器可移植）

import bpy

RESULTS = ROOT / "results"

checks: list[dict] = []


def check(name: str, fn) -> None:
    rec: dict = {"name": name}
    try:
        detail = fn()
        rec["ok"] = True
        rec["detail"] = detail
        print(f"  PASS  {name}  {str(detail)[:160]}")
    except Exception as e:  # noqa: BLE001
        rec["ok"] = False
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["trace"] = traceback.format_exc(limit=3)
        print(f"  FAIL  {name}  {type(e).__name__}: {str(e)[:160]}")
    checks.append(rec)


def _enable_rigify():
    prefs = bpy.context.preferences
    was = "rigify" in prefs.addons
    if not was:
        bpy.ops.preferences.addon_enable(module="rigify")
    if "rigify" not in prefs.addons:
        raise RuntimeError("addon_enable 后 rigify 不在 preferences.addons")
    import rigify
    info = getattr(rigify, "bl_info", {}) or {}
    return {"blender": list(bpy.app.version), "rigify_version": info.get("version"),
            "rigify_file": rigify.__file__, "was_enabled": was}


def _rigify_structure():
    import rigify
    keys = [k for k in dir(rigify) if not k.startswith("_")]
    templates = getattr(rigify, "rig_templates", None)
    tnames = [t.name for t in templates] if templates else None
    # metarig 生成相关子模块
    sub = {}
    for mod in ("rigify.metarig", "rigify.rig_templates", "rigify.utils.bones",
                "rigify.utils.naming", "rigify.operators"):
        try:
            __import__(mod)
            sub[mod] = "OK"
        except Exception as e:  # noqa: BLE001
            sub[mod] = f"{type(e).__name__}: {e}"
    return {"dir": keys[:24], "templates": tnames, "submodules": sub}


def _metarig_candidates():
    """逐一试 metarig sample 的 op 候选名（rigify 3.x→4.x API 漂移主嫌疑）。"""
    cands = [
        ("bpy.ops.armature.metarig_sample_add", dict(metarig_type="bird")),
        ("bpy.ops.object.metarig_sample_add", dict(metarig_type="bird")),
        ("bpy.ops.pose.metarig_sample_add", dict(metarig_type="bird")),
        ("bpy.ops.armature.metarig_sample_add", dict(metarig_type="human")),
        ("bpy.ops.object.metarig_sample_add", dict(metarig_type="human")),
    ]
    out = []
    for opname, kwargs in cands:
        try:
            op = bpy.ops
            # ⚠ getattr 链须跳过 "bpy" "ops" 两级（split(".")[2:]）——首版 [1:] 多取一级
            # 'ops' 导致 exists 全误判 False（F1 清点抓出本 bug）。
            for part in opname.split(".")[2:]:
                op = getattr(op, part)
            out.append({"op": opname, "kwargs": kwargs, "exists": True,
                        "poll": bool(op.poll()) if op.poll else "no-poll"})
        except AttributeError:
            out.append({"op": opname, "exists": False})
    return out


def _rig_registry_names() -> set:
    """0.6.x rig 类型注册表名集（多路径探测，尽力而为）。"""
    names: set = set()
    try:
        from rigify import rig_lists
        rigs = getattr(rig_lists, "rigs", None)
        if isinstance(rigs, dict):
            names |= set(rigs.keys())
    except Exception:  # noqa: BLE001
        pass
    try:
        import rigify.rigs as pkg
        import pkgutil
        for m in pkgutil.iter_modules(pkg.__path__):
            names.add(f"basic.{m.name}") if m.name in ("copy", "raw_copy", "super_copy") else None
            names.add(m.name)
    except Exception:  # noqa: BLE001
        pass
    return names


def _rig_types_inventory():
    """G1：rig 类型注册表全量清点（0.6.x 'basic.copy' KeyError 的根因定位）。"""
    out: dict = {}
    try:
        from rigify import rig_lists
        out["rig_lists_dir"] = [s for s in dir(rig_lists) if not s.startswith("_")][:16]
        rigs = getattr(rig_lists, "rigs", None)
        out["rigs_keys"] = sorted(rigs.keys()) if isinstance(rigs, dict) else f"type={type(rigs).__name__}"
        metas = getattr(rig_lists, "metarigs", None)
        out["metarigs_keys"] = sorted(metas.keys())[:10] if isinstance(metas, dict) else f"type={type(metas).__name__}"
        samples = getattr(rig_lists, "metarig_samples", None)
        out["sample_keys_n"] = len(samples) if isinstance(samples, dict) else f"type={type(samples).__name__}"
    except Exception as e:  # noqa: BLE001
        out["rig_lists"] = f"{type(e).__name__}: {e}"
    return out


def _metarig_manual_v2():
    """手工 metarig：两节链 + rigify_type 标注 → 可被 generate 消费。"""
    arm = bpy.data.armatures.new("M412_Meta")
    obj = bpy.data.objects.new("M412_Meta", arm)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.edit_bones
    b0 = eb.new("root"); b0.head, b0.tail = (0, 0, 0), (0, 0, 0.1)
    b1 = eb.new("bone.L"); b1.head, b1.tail = (0, 0, 0.1), (0, 0, 0.5)
    b1.parent = b0
    b2 = eb.new("bone.R"); b2.head, b2.tail = (0.2, 0, 0.1), (0.2, 0, 0.5)
    b2.parent = b0
    bpy.ops.object.mode_set(mode="OBJECT")
    # rigify 骨骼类型标注（Object mode 下通过 pose_bones）
    # 0.6.x 注册表动态探测：'basic.copy' 已 KeyError（C1 首跑实锤），从注册表取真实类型名
    basic_type = "basic.copy"
    registry = _rig_registry_names()
    for cand in ("basic.raw_copy", "basic.copy", "basic.super_copy"):
        if cand in registry:
            basic_type = cand
            break
    types = {}
    for pb in obj.pose.bones:
        if hasattr(pb, "rigify_type"):
            pb.rigify_type = basic_type if pb.name != "root" else ""
            types[pb.name] = pb.rigify_type
        else:
            types[pb.name] = "NO-rigify_type-ATTR"
    types["_registry_used"] = basic_type
    # 0.6.x 新前置：bone collections + UI row 分配（C1 首跑被 "No bone collections
    # have UI buttons assigned" 拒——这里配置并记录属性面）
    col = arm.collections.new("Main")
    assign_errs = []
    for b in arm.bones:
        try:
            col.assign(b)
        except Exception as e:  # noqa: BLE001
            assign_errs.append(f"{b.name}: {e}")
    col_props = sorted(p.identifier for p in col.bl_rna.properties
                       if "rigify" in p.identifier.lower() or "ui" in p.identifier.lower())
    ui_vals = {}
    for pid in col_props:
        try:
            cur = getattr(col, pid)
            if pid.endswith("row") and isinstance(cur, int):
                setattr(col, pid, 1)
                ui_vals[pid] = 1
            else:
                ui_vals[pid] = str(cur)
        except Exception as e:  # noqa: BLE001
            ui_vals[pid] = f"ERR {e}"
    return {"bones": list(obj.pose.bones.keys()), "rigify_type_set": types,
            "collection": col.name, "assign_errors": assign_errs,
            "collection_props": col_props, "ui_assigned": ui_vals}


def _generate():
    obj = bpy.data.objects.get("M412_Meta")
    if obj is None:
        raise RuntimeError("metarig 不在场（前步失败）")
    bpy.context.view_layer.objects.active = obj
    cands = ["bpy.ops.pose.rigify_generate", "bpy.ops.object.rigify_generate",
             "bpy.ops.armature.rigify_generate"]
    tried = []
    for opname in cands:
        try:
            op = bpy.ops
            # 同 B1：[2:] 跳过 bpy.ops 两级（首版 bug 见 _metarig_candidates）
            for part in opname.split(".")[2:]:
                op = getattr(op, part)
        except AttributeError:
            tried.append({"op": opname, "exists": False})
            continue
        try:
            r = op()
            # op() 返回 set（{'FINISHED'}）——set 不可 JSON 序列化（曾致 result 写盘全灭），转 sorted list
            tried.append({"op": opname, "exists": True, "ran": sorted(r),
                          "poll": bool(op.poll()) if op.poll else "no-poll"})
            if r == {"FINISHED"}:
                gen = [o.name for o in bpy.data.objects if o.type == "ARMATURE"]
                return {"tried": tried, "generated_objects": gen}
        except Exception as e:  # noqa: BLE001
            tried.append({"op": opname, "exists": True, "error": f"{type(e).__name__}: {e}"})
    return {"tried": tried, "note": "无一生成成功" if all(not t.get("ran") for t in tried) else ""}


def _delta_mush():
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.3)
    ob = bpy.context.active_object
    sub = ob.modifiers.new("sub", 'SUBSURF'); sub.levels = 1
    # 漂移主探针：modifier type enum 全集（DELTA_MUSH 缺席？→ 找替代/确认移除）
    new_fn = bpy.types.ObjectModifiers.bl_rna.functions["new"]
    enum_items = [i.identifier for i in new_fn.parameters["type"].enum_items]
    detail = {"delta_mush_in_enum": "DELTA_MUSH" in enum_items,
              "n_types": len(enum_items),
              "mush_like": [t for t in enum_items if "MUSH" in t],
              "smooth_like": [t for t in enum_items if "SMOOTH" in t or "CORRECT" in t]}
    if detail["delta_mush_in_enum"]:
        dm = ob.modifiers.new("dm", 'DELTA_MUSH')
        detail["props"] = {p.identifier: getattr(dm, p.identifier)
                           for p in dm.bl_rna.properties if not p.is_readonly}
        dm.repeat = 3
        bpy.context.view_layer.update()
        detail["mesh_verts_after"] = len(ob.data.vertices)
    # GN 节点侧：Delta Mush 是否被整进 Geometry Nodes（5.x 重构的常见去向）
    detail["gn_mush_like"] = [n for n in dir(bpy.types)
                              if n.startswith("GeometryNode") and ("MUSH" in n.upper())]
    detail["gn_smooth_like"] = [n for n in dir(bpy.types)
                                if n.startswith("GeometryNode") and "SMOOTH" in n.upper()][:8]
    return detail


def _rig_json_roundtrip():
    """rig-as-data 最小闭环预演：JSON 描述 → 骨骼重建，坐标零漂。"""
    rig_json = {"bones": [
        {"name": "root", "head": [0, 0, 0], "tail": [0, 0, 0.1], "parent": None},
        {"name": "spine", "head": [0, 0, 0.1], "tail": [0, 0, 0.5], "parent": "root"},
    ]}
    arm = bpy.data.armatures.new("RigJsonRT")
    obj = bpy.data.objects.new("RigJsonRT", arm)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    made = {}
    for b in rig_json["bones"]:
        eb = arm.edit_bones.new(b["name"])
        eb.head, eb.tail = b["head"], b["tail"]
        made[b["name"]] = eb
    for b in rig_json["bones"]:
        if b["parent"]:
            made[b["name"]].parent = made[b["parent"]]
    bpy.ops.object.mode_set(mode="OBJECT")
    pb = obj.pose.bones["spine"]
    # bpy 坐标是 float32——0.1 的 float32 表示 ≈ 0.10000000149，与 float64 字面量 != 是精度事实非 API 漂移；
    # 对 M4-12 的直接影响：rig_json schema 的坐标断言/回写必须用 float32 容差（1e-6）。
    dl = pb.bone.head_local
    tol_ok = all(abs(a - b) < 1e-6 for a, b in zip(dl, (0.0, 0.0, 0.1)))
    return {"head_roundtrip_tol1e6": tol_ok,
            "head_local_repr": [float(x) for x in dl],
            "parent_ok": pb.bone.parent.name == "root"}


def _rigify_ops_inventory():
    """0.6.x 生成入口清点：pose/object 两个 op 分类下全部 rigify 开头的 op id。"""
    inv = {}
    for cat in ("pose", "object", "armature"):
        cat_ops = dir(getattr(bpy.ops, cat))
        inv[cat] = sorted(o for o in cat_ops if "rigify" in o.lower())
    # 生成引擎模块结构（0.6.x：函数式 API 嫌疑）
    import rigify
    gen_probe = {}
    for mod in ("rigify.base_generate", "rigify.generate", "rigify.rig_generation",
                "rigify.operators.generate"):
        try:
            __import__(mod)
            gen_probe[mod] = "OK"
        except Exception as e:  # noqa: BLE001
            gen_probe[mod] = f"{type(e).__name__}"
    # operators 模块里搜 generate 相关符号
    try:
        from rigify import operators  # noqa: F401
        import inspect
        gen_probe["operators_symbols"] = [s for s in dir(operators) if "generat" in s.lower()][:10]
    except Exception as e:  # noqa: BLE001
        gen_probe["operators_symbols"] = f"{type(e).__name__}"
    # base_generate 顶层符号（引擎函数）
    try:
        from rigify import base_generate
        gen_probe["base_generate_symbols"] = [s for s in dir(base_generate) if not s.startswith("_")][:20]
    except Exception as e:  # noqa: BLE001
        gen_probe["base_generate_symbols"] = f"{type(e).__name__}"
    return {"ops": inv, "modules": gen_probe}


check("A1 rigify 启用 + 版本", _enable_rigify)
check("A2 rigify 模块结构/模板清点", _rigify_structure)
check("B1 metarig sample op 候选探测", _metarig_candidates)
check("B2 手工 metarig（rig-as-data 路径）", _metarig_manual_v2)
check("C1 rigify_generate", _generate)
check("F1 rigify op 全量清点（0.6.x 生成入口）", _rigify_ops_inventory)
check("G1 rig 类型注册表清点", _rig_types_inventory)
check("D1 Delta Mush 参数面 + 应用", _delta_mush)
check("E1 rig_json → 骨骼 roundtrip", _rig_json_roundtrip)

n_ok = sum(1 for c in checks if c["ok"])
print(f"\nM4-12 PROBE: {n_ok}/{len(checks)} passed")

out = {
    "suite": "M4-12 rigify 5.2 API probe",
    "passed": n_ok, "total": len(checks),
    "blender_version": list(bpy.app.version),
    "checks": checks,
    "verdict_hint": (
        "GO 路径判读：A 全过 + B2 过 + E1 过 = rig-as-data 手工建骨可用（sample 只是便利品）；"
        "C1 过 = 生成链通；D1 过 = 后处理节点在。缺哪件，M4-12 实施就以哪件为第一工单。"),
}
RESULTS.mkdir(exist_ok=True)
(RESULTS / "m412_probe_result.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("result ->", RESULTS / "m412_probe_result.json")
