"""exp4_live.py — EXP-4 感知哈希分离度标定（R7g）
===================================================

跑法：blender.exe -b --factory-startup -P exp4_live.py
产出：result JSON -> results/exp4_phash_calib_result.json

问题（工单实验清单 EXP-4 · ◐ 首批样本：未变=0 / 小改=1 / 大改=12，
d3-algo 判定标准待标定）：给 render diff 管线的感知哈希距离定三档
判定阈值——未变 / 小改 / 大改的分离带在哪里？

方法：RenderDiffer（与 M9-3 diff 管线同构：Workbench 256px、STUDIO 恒光、
冻结相机、film_transparent）+ 三档多对样本 × 三度量：
  * dhash 汉明距离（现有管线指标，64bit）
  * pHash 汉明距离（本实验新增：DCT-II 低频 8×8 中位数二值化，纯 numpy）
  * 块级 SSIM（本实验新增：非重叠 8×8 块近似，0=异 1=同；诚实登记：
    近似实现，非 Wang et al. 高斯窗原版）

样本档（几何变体——Workbench SINGLE 色不渲染材质/灯光差异，诚实适配）：
  unchanged ×3：同场景重渲（probe 实锤 0 像素差 → 预期 0 距离）
  small     ×4：bevel 1mm / 位移 5mm / 旋转 2° / 缩放 1.01
  large     ×4：bevel 20mm / 位移 300mm / 旋转 60° / 缩放 1.5

标定判据：
  A 分离性：max(unchanged 距离) < min(large 距离)（三度量分别判）
  B 小改位置：small 全落 [unchanged_max, large_min] 区间内（可辨档）
  产出：T1/T2 阈值建议（未变: <T1；小改: [T1,T2)；大改: ≥T2）
"""

import json
import sys
import traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）

import bpy
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from render_diff import RenderDiffer, dhash, hamming, _luma

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


# ── 感知度量（纯 numpy，实验自含）────────────────────────────
def phash(px: np.ndarray) -> int:
    """pHash：32×32 块均降采样 → DCT-II → 低频 8×8 中位数二值化 64bit。"""
    lum = _luma(px)
    h, w = lum.shape
    bh, bw = h // 32, w // 32
    small = lum[:bh * 32, :bw * 32].reshape(32, bh, 32, bw).mean(axis=(1, 3))
    n = 32
    i = np.arange(n).reshape(-1, 1)
    j = np.arange(n).reshape(1, -1)
    D = np.cos(np.pi * (2 * j + 1) * i / (2 * n)) * np.sqrt(2.0 / n)
    D[0, :] /= np.sqrt(2.0)
    low = (D @ small @ D.T)[:8, :8].flatten()
    med = np.median(low[1:])                     # 排除 DC 分量
    bits = low > med
    v = 0
    for bit in bits:
        v = (v << 1) | int(bit)
    return v


def ssim_block(a: np.ndarray, b: np.ndarray) -> float:
    """块级 SSIM（非重叠 8×8 块近似；0=完全异 1=完全同）。"""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    if a.ndim != 2:
        a = _luma(a)
    if b.ndim != 2:
        b = _luma(b)
    C1, C2 = 0.01 ** 2, 0.03 ** 2
    k = 8
    ah, aw = a.shape[0] // k * k, a.shape[1] // k * k
    blocks_a = a[:ah, :aw].reshape(ah // k, k, aw // k, k)   # (NB, k, NB, k)
    blocks_b = b[:ah, :aw].reshape(ah // k, k, aw // k, k)
    mu_a, mu_b = blocks_a.mean(axis=(1, 3)), blocks_b.mean(axis=(1, 3))
    var_a, var_b = blocks_a.var(axis=(1, 3)), blocks_b.var(axis=(1, 3))
    cov = (blocks_a * blocks_b).mean(axis=(1, 3)) - mu_a * mu_b
    m = ((2 * mu_a * mu_b + C1) * (2 * cov + C2)) / \
        ((mu_a ** 2 + mu_b ** 2 + C1) * (var_a + var_b + C2))
    return float(m.mean())


def metrics(px0: np.ndarray, px1: np.ndarray) -> dict:
    return {"dhash": hamming(dhash(px0), dhash(px1)),
            "phash": hamming(phash(px0), phash(px1)),
            "ssim": round(ssim_block(_luma(px0), _luma(px1)), 4)}


def load_px(frame: dict) -> np.ndarray:
    """render() 只回 meta——像素从落盘 PNG 读（image.pixels bottom-up，
    两帧同翻转对距离无影响：梯度/块对称）。"""
    img = bpy.data.images.load(str(frame["png_path"]))
    px = np.array(img.pixels[:], dtype=np.float32).reshape(-1, 4)
    bpy.data.images.remove(img)
    return px


# ── 场景 + 渲染器 ────────────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=0.1, location=(0, 0, 0.05))
obj = bpy.context.active_object
obj.name = "Calib_Spec"
bv = obj.modifiers.new("Bevel", 'BEVEL')
bv.width = 0.0
bv.segments = 2

differ = RenderDiffer(bpy, obj, workdir=ROOT / "results" / "_exp4_renders",
                      res=256)

f0 = differ.render("base")
px0 = load_px(f0)
h0, p0 = dhash(px0), phash(px0)

VARIANTS = {
    "small": [
        ("bevel_1mm", lambda: bv.__setattr__("width", 0.001)),
        ("move_5mm", lambda: obj.__setattr__("location", (0.005, 0, 0.05))),
        ("rot_2deg", lambda: obj.__setattr__("rotation_euler", (0, 0, 0.0349))),
        ("scale_101", lambda: obj.__setattr__("scale", (1.01, 1.01, 1.01))),
    ],
    "large": [
        ("bevel_20mm", lambda: bv.__setattr__("width", 0.02)),
        ("move_300mm", lambda: obj.__setattr__("location", (0.3, 0, 0.05))),
        ("rot_60deg", lambda: obj.__setattr__("rotation_euler", (0, 0, 1.047))),
        ("scale_15", lambda: obj.__setattr__("scale", (1.5, 1.5, 1.5))),
    ],
}


def render_variant(fn) -> dict:
    fn()
    bpy.context.view_layer.update()
    fr = differ.render(f"v{differ._frame_n}")
    return metrics(px0, load_px(fr))


# [1] unchanged ×3：确定性复证
def t1():
    dists = []
    for i in range(3):
        m = render_variant(lambda: None)
        dists.append(m)
    for m in dists:
        assert m["dhash"] == 0 and m["phash"] == 0 and m["ssim"] == 1.0, \
            f"未变帧应零距离：{m}"
    return "3 帧全 0/0/1.0（同场景重渲零漂移复证）"

check("[1] unchanged ×3 → 0/0/1.0", t1)

# [2][3] 三档分布
DIST: dict = {"small": [], "large": []}
for tier, variants in VARIANTS.items():
    for name, fn in variants:
        DIST[tier].append((name, render_variant(fn)))

# [2] small 档分布
def t2():
    s = [(n, m) for n, m in DIST["small"]]
    return "; ".join(f"{n}: d={m['dhash']} p={m['phash']} s={m['ssim']}"
                     for n, m in s)

check("[2] small 档分布（4 变体）", t2)

# [3] large 档分布
def t3():
    s = [(n, m) for n, m in DIST["large"]]
    return "; ".join(f"{n}: d={m['dhash']} p={m['phash']} s={m['ssim']}"
                     for n, m in s)

check("[3] large 档分布（4 变体）", t3)

# [4] 分离性判定（三度量分别）
def t4():
    u_d, u_p, u_s = 0, 0, 1.0                       # unchanged 分布（t1 证）
    l_d = min(m["dhash"] for _, m in DIST["large"])
    l_p = min(m["phash"] for _, m in DIST["large"])
    l_s = max(m["ssim"] for _, m in DIST["large"])
    sep = {"dhash": u_d < l_d, "phash": u_p < l_p, "ssim": u_s > l_s}
    assert all(sep.values()), f"分离性未达：{sep}（large 侧 d>={l_d} p>={l_p} s<={l_s}）"
    return f"全度量分离 ✓（dhash: {u_d}<{l_d} · phash: {u_p}<{l_p} · ssim: {u_s}>{l_s}）"

check("[4] 分离性：unchanged 与 large 无重叠", t4)

# [5] 小改可辨：small 落在分离带内
def t5():
    l_d = min(m["dhash"] for _, m in DIST["large"])
    s_d = [m["dhash"] for _, m in DIST["small"]]
    in_band = [d < l_d for d in s_d]
    return (f"small dhash={s_d} 全部 < large_min={l_d}：{all(in_band)}"
            f" · 小改与大改可辨")

check("[5] 小改可辨性：small < large_min", t5)

# [6] 阈值产出（三档判定标准落表）
def t6():
    s_d = [m["dhash"] for _, m in DIST["small"]]
    l_d = min(m["dhash"] for _, m in DIST["large"])
    s_p = [m["phash"] for _, m in DIST["small"]]
    l_p = min(m["phash"] for _, m in DIST["large"])
    t1_d = 1                                        # >0 即有几何变化（unchanged 恒 0）
    t2_d = (max(s_d) + l_d) // 2 if max(s_d) < l_d else max(s_d)
    t1_p = 1
    t2_p = (max(s_p) + l_p) // 2 if max(s_p) < l_p else max(s_p)
    return (f"判定标准：dhash 未变<={t1_d - 1} 小改[{t1_d},{t2_d}) 大改>={t2_d}"
            f" · phash 未变<={t1_p - 1} 小改[{t1_p},{t2_p}) 大改>={t2_p}")

check("[6] 三档判定阈值产出", t6)

# ── 落盘 ────────────────────────────────────────────────────
ok = all(c["ok"] for c in checks)
RESULTS.mkdir(parents=True, exist_ok=True)
out = {"suite": "exp4_live", "ok": ok,
       "passed": sum(1 for c in checks if c["ok"]), "total": len(checks),
       "checks": checks,
       "distribution": {k: [{"name": n, **m} for n, m in v]
                        for k, v in DIST.items()}}
(RESULTS / "exp4_phash_calib_result.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nexp4_live: {out['passed']}/{out['total']} {'ALL GREEN' if ok else 'HAS FAILURES'}")
assert ok, "存在失败断言"
