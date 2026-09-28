"""
gn_ab.py — 路线 AB 对照实验（错误面可检出性基准）
===================================================

⚠️ 方法学声明（先说清楚，免得数字被误读）
------------------------------------------
这不是"模型成功率基准"——我无法在这里采样一个实时模型。
它测的是**错误面的可检出性**：对每一条路线，注入一组「真实世界 LLM 会犯的错」，
看有多少被**响亮拦下**、多少**静默通过**。

为什么这个才是决策相关的：
    ops 路线的失败大多是响亮的（Blender 会抛错），
    GN 路线的失败大多是静默的（跑完不报错，但结果不对）——我在 gn_adapter 里已经踩到 3 个。
    **"改了但没变"比"直接崩了"危险一个数量级**，因为它会一路骗过所有测试。
    所以真正要比较的不是"谁更容易写对"，而是"写错了谁能告诉你"。

每条路线的错误样本来自本次调研实测到的真实坑位，不是凭空编的。

跑法：
    blender --background --factory-startup --python gn_ab.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]  # 仓库根（相对推导，跨机器可移植）
from typing import Any, Callable

import bpy

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from gn_adapter import GNAdapter, ParamSpec  # noqa: E402
from gn_console import GNConsole, SPECS  # noqa: E402
from gn_verify import GeometryVerifier  # noqa: E402

OUT = ROOT / "results" / "gn_ab_result.json"
ROWS: list[dict[str, Any]] = []


def say(m: str) -> None:
    print(m)


def fresh_obj(name: str = "Mug") -> Any:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    o = bpy.context.active_object
    o.name = name
    o.data = bpy.data.meshes.new("Base")      # 清空，让 GN 完全生成
    return o


def stats_of(obj: Any, deps: Any) -> dict[str, float]:
    deps.update()
    ev = obj.evaluated_get(deps)
    m = ev.to_mesh()
    if m is None or len(m.vertices) == 0:
        ev.to_mesh_clear()
        return {"faces": 0.0, "area": 0.0, "bbox_x": 0.0, "bbox_z": 0.0}
    area = 0.0
    for p in m.polygons:
        try:
            area += p.area
        except Exception:  # noqa: BLE001
            pass
    xs = [v.co.x for v in m.vertices]
    zs = [v.co.z for v in m.vertices]
    st = {"faces": float(len(m.polygons)), "area": round(area, 8),
          "bbox_x": round(max(xs) - min(xs), 6) if xs else 0.0,
          "bbox_z": round(max(zs) - min(zs), 6) if zs else 0.0}
    ev.to_mesh_clear()
    return st


def stats_baked(obj: Any) -> dict[str, float]:
    """obj.data 的真实统计 —— 也就是**导出时你会拿到的东西**。

    为什么必须分开测：ops 路线"加 modifier 但不 apply"这个 bug，
    视口（evaluated）看着完全正常，但 obj.data 根本没变。
    只测 evaluated 就会把它判成"通过"。
    """
    m = obj.data
    if m is None or len(getattr(m, "vertices", [])) == 0:
        return {"faces": 0.0, "area": 0.0, "bbox_x": 0.0, "bbox_z": 0.0}
    area = 0.0
    for p in m.polygons:
        try:
            area += p.area
        except Exception:  # noqa: BLE001
            pass
    xs = [v.co.x for v in m.vertices]
    zs = [v.co.z for v in m.vertices]
    return {"faces": float(len(m.polygons)), "area": round(area, 8),
            "bbox_x": round(max(xs) - min(xs), 6) if xs else 0.0,
            "bbox_z": round(max(zs) - min(zs), 6) if zs else 0.0}


def close(a: float, b: float, tol: float = 0.02) -> bool:
    if a == 0 and b == 0:
        return True
    if a == 0 or b == 0:
        return False
    return abs(a - b) / max(abs(a), abs(b)) <= tol


# ══════════════════════════════════════════════════════════════
# Route A：写 SPECS（声明式段落）→ gn_adapter 编译 → 挂层
# ══════════════════════════════════════════════════════════════
def a_baseline(ad: GNAdapter) -> tuple[Any, Any]:
    obj = fresh_obj()
    con = GNConsole(ad, obj)
    for spec in SPECS:
        con.compile_and_mount(spec)
    return obj, con


def a_old_api(ad: GNAdapter) -> tuple[Any, Any]:
    """A2：用 4.x 的旧式 per-instance 写法 —— 5.2 实测会抛错（响亮）。"""
    obj, con = a_baseline(ad)
    rec = con.segments["S3_收尾"]
    rec["mod"][rec["sid"]["Subdiv_Level"]] = 3      # 旧写法
    return obj, con


def a_bad_param_name(ad: GNAdapter) -> tuple[Any, Any]:
    """A3：参数名用 parm3 —— ParamSpec 直接拒。"""
    obj = fresh_obj()
    con = GNConsole(ad, obj)
    tree = ad.new_group("Bad")
    ad.promote_input(tree, ParamSpec("parm3", "FLOAT", 1.0))   # 这里就会抛
    return obj, con


def a_socket_typo(ad: GNAdapter) -> tuple[Any, Any]:
    """A4：socket 名拼错 —— adapter 抛错（响亮）。"""
    obj = fresh_obj()
    con = GNConsole(ad, obj)
    tree = ad.new_group("Typo")
    gi = ad.add_node(tree, "NodeGroupInput", "In")
    cyl = ad.add_node(tree, "GeometryNodeMeshCylinder", "Body")
    ad.promote_input(tree, ParamSpec("Body_Radius", "FLOAT", 0.04))
    ad.link(tree, gi, "Body_Radiuss", cyl, "Radius")   # 拼错
    return obj, con


def a_type_mismatch(ad: GNAdapter) -> tuple[Any, Any]:
    """A5：GEOMETRY → INT 连线 —— Blender 自己的 links.new 不拦，adapter 拦（响亮）。"""
    obj = fresh_obj()
    con = GNConsole(ad, obj)
    tree = ad.new_group("TypeBad")
    sid_g = ad.promote_input(tree, ParamSpec("Incoming_Geometry", "GEOMETRY"))
    ad.promote_output(tree, "Geometry", "GEOMETRY")
    gi = ad.add_node(tree, "NodeGroupInput", "In")
    sub = ad.add_node(tree, "GeometryNodeSubdivisionSurface", "S")
    ad.link(tree, gi, sid_g, sub, "Level")   # GEOMETRY → INT
    return obj, con


def a_no_invalidate(ad: GNAdapter) -> tuple[Any, Any]:
    """A6：改完参数不失效 —— **静默失败**：不报错，但结果还是旧的。"""
    obj, con = a_baseline(ad)
    rec = con.segments["S3_收尾"]
    # 绕过 adapter，直接改 interface default（实测在 headless 下不生效，但也不报错）
    for it in ad._interface_items(rec["tree"]):
        if it.name == "Subdiv_Level":
            it.default_value = 5
    con.deps.update()
    return obj, con


# ══════════════════════════════════════════════════════════════
# Route B：写 bpy.ops 序列
# ══════════════════════════════════════════════════════════════
def b_baseline() -> Any:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.040, depth=0.095)
    body = bpy.context.active_object
    bpy.ops.mesh.primitive_torus_add(
        major_radius=0.032, minor_radius=0.011,
        location=(0.040, 0.0, 0.0), rotation=(0.0, 1.5708, 0.0))
    handle = bpy.context.active_object
    # 必须显式按引用选中两个：第二个 add 之后 cylinder 可能已不在选区里，
    # 只靠 selected_objects 会静默少 join 一个（我第一版就栽在这：只剩 768 面的 torus）
    body.select_set(True)
    handle.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    joined = bpy.context.active_object
    m = joined.modifiers.new("Subdiv", "SUBSURF")
    m.levels = 2
    bpy.ops.object.modifier_apply(modifier="Subdiv")
    bpy.ops.object.shade_smooth()
    return joined


def b_wrong_units() -> Any:
    """B3：把 mm 当 m 写进去 —— 尺寸放大 1000 倍，**静默通过**（不报错，只是巨大）。"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cylinder_add(radius=40.0, depth=95.0)
    return bpy.context.active_object


def b_no_active_for_join() -> Any:
    """B2：join 前没设 active —— Blender 抛错（响亮）。"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=0.095)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.032, minor_radius=0.011)
    bpy.context.view_layer.objects.active = None
    bpy.ops.object.join()
    return bpy.context.active_object


def b_typo_op() -> Any:
    """B5：算子名拼错 —— AttributeError（响亮）。"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cylindr_add(radius=0.04, depth=0.095)
    return bpy.context.active_object


def b_no_apply() -> Any:
    """B6：加细分但不 apply —— **静默**：视口看着对，面数不对，导出/布尔会翻车。"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.040, depth=0.095)
    body = bpy.context.active_object
    handle = bpy.context.active_object
    body.select_set(True)
    handle.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    joined = bpy.context.active_object
    m = joined.modifiers.new("Subdiv", "SUBSURF")
    m.levels = 2     # 故意不 apply
    return joined


def b_active_drift() -> Any:
    """B6：active object 漂移 —— 后续操作加到**错误的物体**上。

    这是 ops 路线最经典的静默 bug：中间任何一个算子都会改 active，
    你以为在改杯身，其实在改把手。不报错，导出才发现。
    """
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.040, depth=0.095)
    body = bpy.context.active_object
    bpy.ops.mesh.primitive_torus_add(major_radius=0.032, minor_radius=0.011,
                                     location=(0.040, 0.0, 0.0))
    # 此时 active 已经漂到 handle 上；下面这句本意是"给杯身加细分"
    m = bpy.context.active_object.modifiers.new("Subdiv", "SUBSURF")
    m.levels = 2
    bpy.ops.object.modifier_apply(modifier="Subdiv")   # 加到了把手上，不是杯身
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    return body


# ══════════════════════════════════════════════════════════════
# 评分
# ══════════════════════════════════════════════════════════════
CASES: list[tuple[str, str, str, Callable[[], Any]]] = [
    ("A1", "GN", "baseline 正确写法", lambda ad: a_baseline(ad)),
    ("A2", "GN", "旧式 modifier[Socket]=v", lambda ad: a_old_api(ad)),
    ("A3", "GN", "参数名 parm3", lambda ad: a_bad_param_name(ad)),
    ("A4", "GN", "socket 名拼错", lambda ad: a_socket_typo(ad)),
    ("A5", "GN", "GEOMETRY→INT 连线", lambda ad: a_type_mismatch(ad)),
    ("A6", "GN", "改完参数不失效", lambda ad: a_no_invalidate(ad)),
    ("B1", "ops", "baseline 正确写法", lambda ad: b_baseline()),
    ("B2", "ops", "join 前没设 active", lambda ad: b_no_active_for_join()),
    ("B3", "ops", "单位写错（mm 当 m）", lambda ad: b_wrong_units()),
    ("B4", "ops", "算子名拼错", lambda ad: b_typo_op()),
    ("B5", "ops", "加 modifier 不 apply", lambda ad: b_no_apply()),
    ("B6", "ops", "active 漂移改错对象", lambda ad: b_active_drift()),
]


def main() -> None:
    say(f"Blender {bpy.app.version_string}")
    ad = GNAdapter(bpy)
    verifier = GeometryVerifier(budget_faces=200_000, ground_z=-1.0)

    # 先取 GN baseline 的几何作为"意图基准"
    base_obj, base_con = a_baseline(ad)
    base_stats = stats_of(base_obj, base_con.deps)
    base_baked = stats_baked(base_obj)   # 必须在 read_factory_settings 之前取
    say(f"\nGN baseline: {base_stats}")
    say(f"GN baseline baked={base_baked}  ← GN 路由下 obj.data 是空的，导出前必须 realize")

    # ops baseline 也测一次（用于 B 路线的对照）
    try:
        bobj = b_baseline()
        bstats = stats_of(bobj, bpy.context.evaluated_depsgraph_get())
        bbaked = stats_baked(bobj)
        say(f"ops baseline: {bstats}  baked={bbaked}")
    except Exception as e:  # noqa: BLE001
        bstats, bbaked = None, None
        say(f"ops baseline 抛错：{e!r}")

    say("\n" + "=" * 78)
    say(f"{'case':<5}{'route':<6}{'注入的错误':<24}{'结果':<10}{'说明'}")
    say("=" * 78)

    for cid, route, note, fn in CASES:
        raised, silent, ok = "", False, False
        detail = ""
        st: dict[str, float] = {}
        try:
            res = fn(ad)
            if isinstance(res, tuple):
                obj, con = res
                deps = con.deps
            else:
                obj, deps = res, bpy.context.evaluated_depsgraph_get()
            deps.update()
            st = stats_of(obj, deps)
            bk = stats_baked(obj)
            # 与同路线的 baseline 比几何（evaluated 与 baked 都要比）
            ref = base_stats if route == "GN" else (bstats or base_stats)
            ref_bk = base_baked if route == "GN" else (bbaked or base_baked)
            if cid in ("A1", "B1"):
                ok = True
                detail = f"eval_faces={st['faces']:.0f} baked_faces={bk['faces']:.0f}"
            else:
                # 判定"未被察觉"：evaluated 看着对 AND baked 也对 → 错误完全没暴露
                hidden = (close(st["area"], ref["area"]) and close(st["bbox_x"], ref["bbox_x"])
                          and close(bk["faces"], ref_bk["faces"], tol=0.02))
                silent = True     # 没抛错，全是静默；差别只在"是否完全没暴露"
                if hidden:
                    detail = "evaluated 与 baked 都与正确版一致 → 错误完全没暴露"
                elif not close(bk["faces"], ref_bk["faces"], tol=0.02):
                    detail = (f"baked 面数异常 {bk['faces']:.0f} vs {ref_bk['faces']:.0f}"
                              f"（视口仍正常 → 会一路骗到导出）")
                else:
                    detail = f"evaluated 偏离正确版 area={st['area']} vs {ref['area']}"
            st["baked_faces"] = bk["faces"]
        except Exception as e:  # noqa: BLE001
            raised = type(e).__name__
            detail = str(e)[:70]
        else:
            if not raised and not silent:
                ok = True

        if raised:
            verdict = "响亮失败"
        elif silent:
            verdict = "静默失败"
        else:
            verdict = "通过"
        say(f"{cid:<5}{route:<6}{note:<24}{verdict:<10}{detail}")
        ROWS.append({"case": cid, "route": route, "injected": note,
                     "raised": raised, "silent": silent, "ok": ok,
                     "stats": st, "detail": detail})

    say("=" * 78)
    for route in ("GN", "ops"):
        rs = [r for r in ROWS if r["route"] == route and r["case"] not in ("A1", "B1")]
        loud = sum(1 for r in rs if r["raised"])
        sil = sum(1 for r in rs if not r["raised"])
        say(f"{route}: 注入 {len(rs)} 个错误 → 响亮拦下 {loud} 个，静默通过 {sil} 个 "
            f"（静默率 {sil/len(rs)*100:.0f}%）")
    DATA = {"rows": ROWS, "gn_baseline": base_stats, "ops_baseline": bstats}
    OUT.write_text(json.dumps(DATA, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    say(f"\nresult -> {OUT}")


if __name__ == "__main__":
    main()
