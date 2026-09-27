"""exp3_live.py — EXP-3 depsgraph 脏标记可利用性实验（R7g）
=============================================================

跑法：blender.exe -b --factory-startup -P exp3_live.py
产出：result JSON -> results/exp3_depsgraph_result.json

问题（工单实验清单 EXP-3 · 待做）：depsgraph.updates 能否做增量指纹的
前置过滤器——改 A 只重算 A 的指纹，未脏对象直接复用缓存？
（EXP-5 实锤：全量重算 ≈1600ms 是 diff 管线最大单项成本）

API 实锤（探针四跑沉淀，5.2.1 后台模式）：
  ① **updates 仅在 depsgraph_update_post handler 内可读**——主流程
     （含 dg.update() 后立即读）恒空；evaluated_depsgraph_get() 不填充。
  ② **后台模式 RNA 直接写不自动触发 depsgraph 更新**——须显式
     view_layer.update()（UI 模式由事件循环代劳）。
  ③ updates 按 **ID 数据块**报：改 mesh 顶点 → 对象 ID + mesh ID 两条
     （对象名 ≠ mesh 名，消费侧须做归属映射）；建对象时同 ID 可重复。
  ④ is_updated_geometry / is_updated_transform 区分有效；噪声面 =
     Scene / Collection 级条目（消费侧过滤）。

实验矩阵：
  [E1] 建对象 → handler 自动触发 + 噪声清单（Scene/Collection/重复条目）
  [E2] 改 A 顶点 + 显式 update → A 对象+mesh 双条目 geometry 置位、B 无假阳
  [E3] 改 A 位置 + 显式 update → 仅对象条目 transform 置位
  [E4] 主流程直接读 updates → 恒空（实锤①的反向断言）
  [E5] RNA 写不显式 update → handler 不触发（实锤②的反向断言）
  [E6] 裁决：有条件 GO——handler 收集架构 + ID 归属映射 + 噪声过滤三前提
"""

import json
import sys
import traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

import bpy

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


bpy.ops.wm.read_factory_settings(use_empty=True)

# handler 收集器（实锤①：updates 只能在这里读）
CAUGHT: list[list[tuple]] = []


def _on_update(scene, depsgraph) -> None:
    CAUGHT.append([(u.id.name,
                    u.id.__class__.__name__,
                    bool(u.is_updated_geometry),
                    bool(u.is_updated_transform))
                   for u in depsgraph.updates])


bpy.app.handlers.depsgraph_update_post.append(_on_update)


def flush() -> list[tuple]:
    """显式触发更新 → 返回并清空 handler 收集（一条聚合账）。"""
    bpy.context.view_layer.update()
    got = [x for batch in CAUGHT for x in batch]
    CAUGHT.clear()
    return got


# 建三对象（在 handler 注册后——建对象即产生第一批账）
bpy.ops.mesh.primitive_cube_add(size=0.1, location=(0, 0, 0))
A = bpy.context.active_object
A.name = "Exp3_Cube"          # 注意：mesh 数据名仍是 'Cube'（实锤③素材）
bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.04, depth=0.095,
                                    location=(0.3, 0, 0))
B = bpy.context.active_object
B.name = "Exp3_Cyl"
bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8,
                                     radius=0.04, location=(-0.3, 0, 0))
C = bpy.context.active_object
C.name = "Exp3_Sphere"
flush()  # 清账（建对象基线）

# [E1] 建对象账面噪声清单
def e1():
    bpy.ops.mesh.primitive_torus_add(major_radius=0.05, location=(0.6, 0, 0))
    D = bpy.context.active_object
    D.name = "Exp3_Torus"
    got = flush()
    names = {x[0] for x in got}
    assert "Exp3_Torus" in names, f"新对象未入账：{names}"
    noise = [x for x in got if x[0] in ("Scene",) or "Collection" in x[0]]
    dup = len(got) - len(names)
    return (f"建对象入账 ✓ · 噪声条目 {len(noise)}（Scene/Collection）"
            f"· 重复/多 ID 条目 {dup}")

check("[E1] 建对象 → handler 触发 + 噪声清单", e1)

# [E2] 改 A 顶点 → 对象+mesh 双条目 geometry 置位、B/C 无假阳
def e2():
    A.data.vertices[0].co.x += 0.01
    got = flush()
    by_name = {}
    for name, cls, geo, tr in got:
        by_name.setdefault(name, []).append((cls, geo, tr))
    assert "Exp3_Cube" in by_name, f"对象条目缺失：{sorted(by_name)}"
    assert any(g for _, g, _ in by_name["Exp3_Cube"]), "对象 geometry 未置位"
    mesh_entries = by_name.get(A.data.name, [])
    assert mesh_entries and any(g for _, g, _ in mesh_entries), \
        f"mesh 条目（{A.data.name}）缺失——对象名≠mesh 名，归属映射必需（实锤③）"
    assert "Exp3_Cyl" not in by_name and "Exp3_Sphere" not in by_name, \
        f"未动对象假阳：{sorted(by_name)}"
    return (f"对象 {A.name} + mesh {A.data.name} 双条目 geometry ✓ "
            f"· 未动对象零假阳")

check("[E2] 顶点变更精确性 + 双 ID 条目实锤", e2)

# [E3] 改 A 位置 → 仅对象条目 transform 置位（mesh 不动）
def e3():
    A.location.x += 0.05
    got = flush()
    obj_geo = [x for x in got if x[0] == "Exp3_Cube"]
    assert obj_geo, f"对象条目缺失：{got}"
    assert any(tr for _, _, _, tr in obj_geo), "transform 未置位"
    assert not any(geo for _, _, geo, _ in obj_geo), "改位置不应置 geometry"
    assert A.data.name not in {x[0] for x in got}, "改位置不应牵连 mesh 条目"
    return "改位置 → 仅对象 transform flag（geometry/mesh 不牵连）"

check("[E3] transform 变更 flag 区分度", e3)

# [E4] 主流程直接读 depsgraph.updates → 恒空（实锤①反向断言）
def e4():
    A.data.vertices[1].co.y += 0.01
    bpy.context.view_layer.update()
    n_main = len(bpy.context.view_layer.depsgraph.updates)
    got = flush()
    assert n_main == 0, f"主流程读到 {n_main} 条？实锤①翻案"
    assert got, "handler 侧也空了"
    return f"主流程 updates={n_main} vs handler 收集 {len(got)} 条 → 只能经 handler"

check("[E4] 主流程恒空 → handler 是唯一读取窗口", e4)

# [E5] RNA 写不显式 update → handler 不触发（实锤②反向断言）
def e5():
    CAUGHT.clear()
    A.data.vertices[2].co.z += 0.01
    n_caught = len(CAUGHT)
    got = flush()  # 此时才触发
    assert n_caught == 0, f"RNA 写自动触发了 {n_caught} 次？实锤②翻案"
    assert got, "flush 后应补账"
    return "RNA 写零自动触发 → 显式 view_layer.update() 必需（增量闸门可同步）"

check("[E5] RNA 写不自动触发（后台）", e5)

# [E6] 裁决
def e6():
    return ("有条件 GO：脏标记可做增量指纹前置过滤，三前提——"
            "(a) handler 收集架构（depsgraph_update_post 挂收集器，主流程 "
            "update() 后读聚合账；主流程直接读恒空实锤①）；(b) ID 归属映射"
            "（对象+mesh 双条目、对象名≠mesh 名，须 obj.data 反查归组）；"
            "(c) 噪声过滤（Scene/Collection 条目 + 同 ID 重复去重）。"
            "语义本身零噪声零假阳（E2/E3）+ flag 区分 geometry/transform。"
            "收益边界：单对象无收益，多对象 diff 管线（EXP-5 全量重算 "
            "1600ms）按脏集裁剪重算对象才是真实场景。")

check("[E6] 可利用性裁决", e6)

# ── 落盘 ────────────────────────────────────────────────────
ok = all(c["ok"] for c in checks)
RESULTS.mkdir(parents=True, exist_ok=True)
out = {"suite": "exp3_live", "ok": ok,
       "passed": sum(1 for c in checks if c["ok"]), "total": len(checks),
       "checks": checks}
(RESULTS / "exp3_depsgraph_result.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nexp3_live: {out['passed']}/{out['total']} {'ALL GREEN' if ok else 'HAS FAILURES'}")
assert ok, "存在失败断言"
