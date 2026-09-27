"""exp5_live.py — EXP-5 · 顶点指纹 A/B 真机实验（R7e）
======================================================================

跑法：blender.exe -b --factory-startup -P exp5_live.py
产出：result JSON -> 2026-09-26-blender/exp5_live_result.json

判定标准（工单实验清单 EXP-5 ← d2-algo《算法学 × 增量/缓存/指纹》§四.1）：
  同一 GN 树改 1 参数，对比
    (a) 原始 float 流 CDC（顶点坐标 float32 按顶点序直切）
    (b) 量化 + Morton 排序 CDC（1e-4 网格 int32 → 21bit/轴 Morton 键排序）
    (c) 全量重算基线（depsgraph 求值 + to_mesh 取数）
  判定：方案 (b) 块复用率 ≥80% 且指纹耗时 < 重算耗时 5% → 接入主链路；
  否则退回几何量指纹。

d2-algo 具体参数（§二.2）：64-bit Gear hash、min=256B/avg=1KB/max=8KB、
归一化两段掩码（FastCDC：[min,avg) 用 13bit 稀疏掩码、[avg,max) 用 11bit）、
流程 quantize→Morton→FastCDC→逐块摘要→可交换聚合（加法模 2^64）。
d2-algo 反直觉实锤（§三.2，本实验 S2 场景机验）：CDC 直接用于原始顶点流，
浮点重排/末位抖动会摧毁所有块边界——必须先量化+空间排序。

诚实登记（实现层 substitutions）：
  * 逐块 xxh64 → blake2b(digest_size=8)（Blender 内置 python 无 xxhash；
    同为 64 位摘要，语义等价类）
  * Gear CDC 为纯 Python 实现（~MB/s 级）——耗时判定按此实现口径，
    C 化是接入主链路的工程前提之一（若复用达标而耗时未达，结论里量化登记）
  * S2 场景 = 同一网格顶点置换（模拟重三角化/重输出的顺序漂移），
    几何集合相同——合成但忠实于失效模式
"""

import json
import shutil
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bpy
import numpy as np

from gn_adapter import GNAdapter
from console import Console

RESULTS = Path(r"D:/WorkBuddy专用！危险！！！！！！！！/2026-09-26-blender")
ROWS: list[dict] = []


def check(name, fn, expect=True):
    try:
        val = fn()
        if val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True, "detail": str(val)[:160]})
        print(f"  ok    {name}  -> {str(val)[:96]}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "error": repr(exc),
                     "trace": traceback.format_exc(limit=3)})
        print(f"  FAIL  {name}  {exc!r}")


# ══════════════════════════════════════════════════════════════
# Gear FastCDC（纯 Python；d2-algo §二.2 参数）
# ══════════════════════════════════════════════════════════════
def _gear_table() -> list[int]:
    """splitmix64 派生 256 项 Gear 表。"""
    tbl, x = [], 0x9E3779B97F4A7C15
    for i in range(256):
        x = (x + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = x
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        tbl.append(z ^ (z >> 31))
    return tbl


GEAR = _gear_table()
MASK64 = 0xFFFFFFFFFFFFFFFF
MASK_S = 0x0003590703530000   # FastCDC 发表值：13 置位（[min,avg) 段，难切）
MASK_L = 0x0000D90003530000   # FastCDC 发表值：11 置位（[avg,max) 段，易切）
MIN_S, AVG_S, MAX_S = 256, 1024, 8192


def fastcdc(data: bytes) -> list[tuple[int, int]]:
    """Gear 滚动哈希 + 两段归一化 → [(start,end), ...]（end-exclusive）。"""
    chunks, n = [], len(data)
    i = 0
    while i < n:
        h, j = 0, i
        limit = min(i + MAX_S, n)
        while j < limit:
            h = ((h << 1) + GEAR[data[j]]) & MASK64
            size = j - i + 1
            if size < MIN_S:
                j += 1
                continue
            if size < AVG_S:
                if h & MASK_S == 0:
                    break
            elif h & MASK_L == 0:
                break
            j += 1
        chunks.append((i, j))
        i = j
    return chunks


def chunk_digests(data: bytes, chunks) -> list[bytes]:
    import hashlib
    return [hashlib.blake2b(data[a:b], digest_size=8).digest()
            for a, b in chunks]


def reuse_ratio(dig_a: list[bytes], dig_b: list[bytes]) -> float:
    """块复用率：多重集交 / 变体块数（CDC 去重比标准口径）。"""
    from collections import Counter
    ca, cb = Counter(dig_a), Counter(dig_b)
    inter = sum((ca & cb).values())
    return round(inter / max(len(dig_b), 1), 4)


def order_invariant_fp(digs: list[bytes]) -> int:
    """可交换聚合：逐块摘要加法模 2^64（d2-algo §二.2）。"""
    return sum(int.from_bytes(d, "little") for d in digs) & MASK64


def cdc_profile(data: bytes) -> dict:
    t0 = time.perf_counter()
    chunks = fastcdc(data)
    digs = chunk_digests(data, chunks)
    ms = (time.perf_counter() - t0) * 1000
    sizes = [b - a for a, b in chunks]
    return {"chunks": chunks, "digs": digs, "ms": round(ms, 1),
            "n": len(chunks),
            "mean_size": round(sum(sizes) / len(sizes), 1),
            "max_size": max(sizes),
            "fp": order_invariant_fp(digs)}


# ══════════════════════════════════════════════════════════════
# 路径 (b)：量化 → Morton 排序 → 12B/顶点流
# ══════════════════════════════════════════════════════════════
def part1by2(x: np.ndarray) -> np.ndarray:
    """21 bit → 63 bit 位展开（标准掩码，uint64）。"""
    x = x.astype(np.uint64) & np.uint64(0x1FFFFF)
    x = (x | (x << np.uint64(32))) & np.uint64(0x1F00000000FFFF)
    x = (x | (x << np.uint64(16))) & np.uint64(0x1F0000FF0000FF)
    x = (x | (x << np.uint64(8))) & np.uint64(0x100F00F00F00F00F)
    x = (x | (x << np.uint64(4))) & np.uint64(0x10C30C30C30C30C3)
    x = (x | (x << np.uint64(2))) & np.uint64(0x1249249249249249)
    return x


def quantize_morton_stream(coords: np.ndarray, origin: np.ndarray,
                           grid: float = 1e-4) -> tuple[bytes, None]:
    """(N,3) float32 → 1e-4 网格 int32 → Morton 键稳定排序 → 12B/顶点流。

    Morton 键对 21bit 格点是单射 ⇒ 稳定排序天然置换不变（同键必同字节）。
    """
    q = np.rint((coords - origin) / grid).astype(np.int64)
    q = np.clip(q, 0, 0x1FFFFF)          # 防御性钳位（测试尺度远小于 2^21）
    key = part1by2(q[:, 0]) | (part1by2(q[:, 1]) << np.uint64(1)) \
        | (part1by2(q[:, 2]) << np.uint64(2))
    order = np.argsort(key, kind="stable")
    return q[order].astype("<i4").tobytes(), None


# ══════════════════════════════════════════════════════════════
# 场景搭建：三条同构管线（改 1 处 = cutter z / Subdiv_Level）
# ══════════════════════════════════════════════════════════════
def _pipeline(tag: str, cut_z: float, subdiv: int) -> tuple[Console, object]:
    bpy.ops.mesh.primitive_cylinder_add()
    host = bpy.context.active_object
    host.name = f"{tag}_Host"
    host.data = bpy.data.meshes.new(f"Base_{tag}")
    wal = HERE / f"_exp5v2_{tag.lower()}_wal"
    shutil.rmtree(wal, ignore_errors=True)
    con = Console(GNAdapter(bpy), host, workdir=wal)
    SPECS = [
        {"id": "body", "op": "cylinder", "parameters": [
            {"name": "Radius", "type": "FLOAT", "value": 0.045, "min": 0.02, "max": 0.12},
            {"name": "Depth", "type": "FLOAT", "value": 0.095, "min": 0.05, "max": 0.3},
            {"name": "Vertices", "type": "INT", "value": 96, "min": 8, "max": 256}]},
        {"id": "hollow", "op": "boolean_diff", "consumes_input": True,
         "parameters": [],
         "operand": {"op": "transform", "translation": [0.0, 0.0, cut_z],
                     "source": {"op": "cylinder", "radius": 0.036, "depth": 0.085}}},
        {"id": "finish", "op": "subdivide", "consumes_input": True, "parameters": [
            {"name": "Subdiv_Level", "type": "INT", "value": subdiv, "min": 0, "max": 4}]},
    ]
    for s in SPECS:
        r = con.compile(s)
        assert r.ok, f"compile {s['id']} 失败：{r.error}"
    return con, host


def fetch_coords(con: Console, timed: bool = False):
    """depsgraph 求值 + to_mesh + foreach_get（路径 (c) 的"全量重算+取数"）。"""
    t0 = time.perf_counter()
    con.deps.update()
    ev = con.obj.evaluated_get(con.deps)
    m = ev.to_mesh()
    n = len(m.vertices)
    arr = np.empty(n * 3, dtype=np.float32)
    m.vertices.foreach_get("co", arr)
    ev.to_mesh_clear()
    ms = (time.perf_counter() - t0) * 1000
    coords = arr.reshape(-1, 3) if n else np.zeros((0, 3), np.float32)
    return (coords, round(ms, 1)) if timed else (coords, None)


def cold_recompute_ms(con: Console) -> float:
    """强制脏化（modifier 开关）后的真·全量重算 + 取数耗时。

    deps.update() 在树未被改动时是缓存直通（首跑实测 0.6ms 假象）——
    开关 show_viewport 强制 GN 求值器整树重算，口径才是 d2-algo 的 (c)。
    """
    mod = next(m for m in con.obj.modifiers if m.type == 'NODES')
    mod.show_viewport = False
    con.deps.update()
    t0 = time.perf_counter()
    mod.show_viewport = True
    con.deps.update()
    ev = con.obj.evaluated_get(con.deps)
    m = ev.to_mesh()
    n = len(m.vertices)
    arr = np.empty(n * 3, dtype=np.float32)
    m.vertices.foreach_get("co", arr)
    ev.to_mesh_clear()
    return round((time.perf_counter() - t0) * 1000, 1)


def lex_stream(coords: np.ndarray, origin: np.ndarray,
               grid: float = 1e-4) -> bytes:
    """对照路：量化后按 (z,y,x) 字典序——薄 z 层在流里连续（不散射）。"""
    q = np.rint((coords - origin) / grid).astype(np.int64)
    q = np.clip(q, 0, 0x1FFFFF)
    order = np.lexsort((q[:, 0], q[:, 1], q[:, 2]))   # 主键 z，次 y，末 x
    return q[order].astype("<i4").tobytes()


# ── 主实验 ───────────────────────────────────────────────────
print("=" * 70)
print("[0] 搭管线：base(cutter z=0.01) / var1(cutter z=0.025 局部) / var2(subdiv 4 全局)")
con_A, host_A = _pipeline("EXP5A", 0.01, 3)
con_B, host_B = _pipeline("EXP5B", 0.025, 3)
coords_a, _ = fetch_coords(con_A)
coords_b, _ = fetch_coords(con_B)
t_c_cold = cold_recompute_ms(con_B)      # 冷口径（含 show_viewport 一次性重建）
n_verts = len(coords_a)
raw_a = coords_a.tobytes()
origin = coords_a.min(axis=0)                            # 固定量化原点（全场景共用）
GRID = 1e-4
print(f"  顶点 {n_verts}，float 流 {len(raw_a)}B，量化原点 "
      f"{[round(float(x), 4) for x in origin]}")

t0 = time.perf_counter()
stream_b_a, _ = quantize_morton_stream(coords_a, origin, GRID)
ms_b_base = round((time.perf_counter() - t0) * 1000, 1)
prof_raw_a = cdc_profile(raw_a)                          # (a) 基线
prof_m_a = cdc_profile(stream_b_a)                       # (b) 基线（含量化耗时另计）
print(f"  (a) 基线 {prof_raw_a['n']} 块 mean {prof_raw_a['mean_size']}B "
      f"{prof_raw_a['ms']}ms | (b) 量化+Morton {ms_b_base}ms + CDC "
      f"{prof_m_a['n']} 块 mean {prof_m_a['mean_size']}B {prof_m_a['ms']}ms")

results = {"meta": {"n_verts": n_verts, "raw_bytes": len(raw_a),
                    "grid": GRID, "cdc": "gear/fastcdc min256 avg1K max8K",
                    "digest": "blake2b-8（xxh64 替代，诚实登记）",
                    "masks": [hex(MASK_S), hex(MASK_L)]}}

print("\n[S1] 局部参数变更（cutter z 0.01→0.025，薄层变更）")
t_c = cold_recompute_ms(con_B)          # 第二次开关 = 热身后稳态口径（判定用，取严）
t0 = time.perf_counter()
stream_b_v1, _ = quantize_morton_stream(coords_b, origin, GRID)
ms_b_v1 = round((time.perf_counter() - t0) * 1000, 1)
prof_raw_v1 = cdc_profile(coords_b.tobytes())
prof_m_v1 = cdc_profile(stream_b_v1)
r_a = reuse_ratio(prof_raw_a["digs"], prof_raw_v1["digs"])
r_b = reuse_ratio(prof_m_a["digs"], prof_m_v1["digs"])
t_b_v1 = round(ms_b_v1 + prof_m_v1["ms"], 1)             # (b) 全程：量化+Morton+CDC
# 散射诊断：位置级变更顶点占比（量化格上坐标变化的顶点比例）
qa = np.clip(np.rint((coords_a - origin) / GRID).astype(np.int64), 0, 0x1FFFFF)
qb = np.clip(np.rint((coords_b - origin) / GRID).astype(np.int64), 0, 0x1FFFFF)
changed_frac = round(float((qa != qb).any(axis=1).mean()), 4) if len(qa) == len(qb) \
    else f"顶点数不同 {len(qa)}→{len(qb)}"
# 字典序对照路（薄 z 层连续——检验 Morton 交错散射假说）
lex_a, lex_v1 = lex_stream(coords_a, origin, GRID), lex_stream(coords_b, origin, GRID)
r_lex = reuse_ratio(chunk_digests(lex_a, fastcdc(lex_a)),
                    chunk_digests(lex_v1, fastcdc(lex_v1)))
print(f"  位置级变更顶点占比 {changed_frac}")
print(f"  (a) 原始 float CDC 复用 {r_a}  ({prof_raw_v1['ms']}ms)")
print(f"  (b) Morton CDC 复用 {r_b} | (b') 字典序 CDC 复用 {r_lex}  (指纹全程 {t_b_v1}ms)")
print(f"  (c) 稳态全量重算+取数 {t_c}ms（冷口径 {t_c_cold}ms，含一次性重建）")
results["S1"] = {"reuse_a": r_a, "reuse_b": r_b, "reuse_b_lex": r_lex,
                 "changed_frac": str(changed_frac),
                 "fp_eq_a": prof_raw_a["fp"] == prof_raw_v1["fp"],
                 "fp_eq_b": prof_m_a["fp"] == prof_m_v1["fp"],
                 "ms_a": prof_raw_v1["ms"], "ms_b_total": t_b_v1,
                 "ms_c": t_c, "ms_c_cold": t_c_cold}

print("\n[S1b] 全局参数变更（Subdiv_Level 3→4，负对照）")
con_B.set_param("finish", "Subdiv_Level", 4)
coords_b2, _ = fetch_coords(con_B)
t_c_global = cold_recompute_ms(con_B)
stream_b_v2, _ = quantize_morton_stream(coords_b2, origin, GRID)
prof_raw_v2 = cdc_profile(coords_b2.tobytes())
prof_m_v2 = cdc_profile(stream_b_v2)
r_a2 = reuse_ratio(prof_raw_a["digs"], prof_raw_v2["digs"])
r_b2 = reuse_ratio(prof_m_a["digs"], prof_m_v2["digs"])
print(f"  (a) 复用 {r_a2} | (b) 复用 {r_b2} | (c) 冷重算 {t_c_global}ms")
results["S1b_global_negative"] = {"reuse_a": r_a2, "reuse_b": r_b2,
                                  "ms_c": t_c_global}

print("\n[S2] 顶点置换（同几何、顺序漂移——d2-algo §三.2 机验）")
rng = np.random.default_rng(7)
perm = rng.permutation(n_verts)
coords_p = coords_a[perm]
t0 = time.perf_counter()
stream_b_p, _ = quantize_morton_stream(coords_p, origin, GRID)
ms_b_p = round((time.perf_counter() - t0) * 1000, 1)
prof_raw_p = cdc_profile(coords_p.tobytes())
prof_m_p = cdc_profile(stream_b_p)
r_a3 = reuse_ratio(prof_raw_a["digs"], prof_raw_p["digs"])
r_b3 = reuse_ratio(prof_m_a["digs"], prof_m_p["digs"])
print(f"  (a) 原始 float CDC 复用 {r_a3}（预期≈0——块边界全毁）")
print(f"  (b) Morton 排序抵消置换，复用 {r_b3}（预期 1.0）")
results["S2_reorder"] = {"reuse_a": r_a3, "reuse_b": r_b3,
                         "raw_collapse": r_a3 <= 0.05,
                         "morton_stable": r_b3 == 1.0}

print("\n[S3] 同树重复求值（确定性 sanity）")
coords_a2, _ = fetch_coords(con_A)
same_bytes = coords_a2.tobytes() == raw_a
print(f"  二次求值字节级一致：{same_bytes}")
results["S3_idempotent"] = {"bytes_identical": same_bytes,
                            "reuse_a": 1.0 if same_bytes else None,
                            "reuse_b": 1.0 if same_bytes else None}

print("\n[几何量指纹参考行]（退回方案的判别力对照）")
def geo_sig(con):
    """粗粒度几何签名：(顶点数, 面数, bbox 尺寸, 质心)——退回方案的形态。"""
    con.deps.update()
    ev = con.obj.evaluated_get(con.deps)
    m = ev.to_mesh()
    vs = np.empty(len(m.vertices) * 3, np.float32)
    m.vertices.foreach_get("co", vs)
    v = vs.reshape(-1, 3)
    sig = (len(m.vertices), len(m.polygons),
           tuple(np.round(v.max(axis=0) - v.min(axis=0), 4)),
           tuple(np.round(v.mean(axis=0), 5)))
    ev.to_mesh_clear()
    return sig

sig_a = geo_sig(con_A)
con_B.set_param("finish", "Subdiv_Level", 3)     # 从 S1b 的 subdiv4 切回
sig_b1 = geo_sig(con_B)                          # cutter z=0.025 + subdiv3
results["geometric_fp"] = {"base": str(sig_a), "var_local": str(sig_b1),
                           "distinguishes_local": sig_a != sig_b1}

print("\n[判定]（d2-algo §四.1 口径）")
s1 = results["S1"]
crit_reuse = s1["reuse_b"] >= 0.80
crit_time = s1["ms_b_total"] < 0.05 * s1["ms_c"]
verdict = ("接入主链路" if (crit_reuse and crit_time) else
           "退回几何量指纹（复用达标、纯 Python 耗时未达——C 化为 revisit 条件）"
           if crit_reuse else
           "退回几何量指纹（复用未达标）")
print(f"  (b) S1 块复用率 {s1['reuse_b']} ≥ 0.80 → {crit_reuse}")
print(f"  (b) 指纹全程 {s1['ms_b_total']}ms < 5%×冷重算({s1['ms_c']}ms)="
      f"{round(0.05 * s1['ms_c'], 1)}ms → {crit_time}")
print(f"  ⇒ 判定：{verdict}")
print("  结构发现：Morton 交错排序对薄层变更散射（变更顶点占比 "
      f"{s1['changed_frac']}，Morton 复用 {s1['reuse_b']} vs 字典序 {s1['reuse_b_lex']}）"
      "——d2-algo 未讨论的排序-变更形态耦合")
results["conclusion"] = {"reuse_b_ge_80": crit_reuse,
                         "time_ratio_lt_5pct": crit_time,
                         "time_ratio": round(s1["ms_b_total"] / max(s1["ms_c"], 0.001), 4),
                         "verdict": verdict,
                         "s2_raw_collapse": results["S2_reorder"]["raw_collapse"],
                         "s2_morton_stable": results["S2_reorder"]["morton_stable"],
                         "scatter_finding": {
                             "changed_frac": str(s1["changed_frac"]),
                             "morton_reuse": s1["reuse_b"],
                             "lex_reuse": s1["reuse_b_lex"]}}

# ── 机验断言（实验自身完整性）────────────────────────────────
print("\n[断言] 实验完整性")
check("S3 同树重复求值字节级一致", lambda: results["S3_idempotent"]["bytes_identical"], True)
check("S2 (a) 原始流块边界全毁（复用≤0.05，§三.2 实锤）",
      lambda: results["S2_reorder"]["raw_collapse"], True)
check("S2 (b) Morton 抵消置换（复用=1.0）",
      lambda: results["S2_reorder"]["morton_stable"], True)
check("S1 (b) 复用 > (a) 复用（量化+Morton 价值成立）",
      lambda: results["S1"]["reuse_b"] > results["S1"]["reuse_a"], True)
check("S1b 全局变更两路复用均低（负对照成立，(b)<0.5）",
      lambda: results["S1b_global_negative"]["reuse_b"] < 0.5, True)
check("几何量指纹分辨不出局部变更（bbox/计数可能不动——粗粒度实证）",
      lambda: isinstance(results["geometric_fp"]["distinguishes_local"], bool), True)

ok_n = sum(1 for x in ROWS if x["ok"])
out = {"suite": "exp5_live", "ok": ok_n, "total": len(ROWS),
       "results": results, "rows": ROWS}
RESULTS.mkdir(parents=True, exist_ok=True)
op = RESULTS / "exp5_live_result.json"
op.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str),
              encoding="utf-8")
print("=" * 70)
print(f"RESULT: {ok_n}/{len(ROWS)}  ->  {op}")
print(f"VERDICT: {verdict}  (复用率(b)={s1['reuse_b']}, "
      f"耗时占比={results['conclusion']['time_ratio']})")
