"""m64_lpips_score.py — M6-4 LPIPS 视觉多样性标定 · 打分侧（R7h）

跑法：<venv>/Scripts/python.exe m64_lpips_score.py（Blender 外——torch 不进 Blender embedded Python）
前置：m64_lpips_live.py 已产出 results/_m64_lpips_renders/ 64 PNG + m64_lpips_render_result.json
产出：results/m64_lpips_result.json

标定语义（工单 M6-4 口径：8 视角 LPIPS 均值）：
  L(a,b) = 8 方位角 LPIPS(alex) 距离的均值（每视角一次前向，输入 [-1,1] 归一化，
  8 视角 batch 成 (8,3,H,W) 一次前向）。
  LPIPS 本体 = 预训练 AlexNet 骨干 + 人眼偏好校准线性层（richzhang v0.1 权重，
  lin weights 随 lpips 包内置；AlexNet 骨干权重 torchvision 首跑自动下载 ~240MB）。
  纯推理零训练。

对账（对标 v2.14 判据框架；几何 V 由渲染侧同口径重算，见 m64_lpips_live.py）：
  ① Spearman(V, L) ≥ 0.80 —— 几何尺与视觉尺排序一致（V↔W 判据同口径 0.9639 参照）
     分层：V<0.3 参数级域子集 ≥ 0.85 更严口径（近邻域内两把尺仍要排得动）
  ② 近/远分离：mean(near L) < mean(far L)；严格分离 max(near L) < min(far L) 加分
  ③ 自比 sanity：L(cyl@az0, cyl@az0) = 0（同图输入，管线自检）
阈值产出（EXP-4 pHash 同套路：三档分离带落表）：
  t_same = max(near L) —— "视觉同款"建议上界（近邻对上包络）
  t_diff = min(far L)  —— "视觉不同"建议下界（远邻对下包络）
  灰区语义：落 [t_same, t_diff] 之间时闸门保守判"不同"（多样性闸门宁严勿松）。
"""
import json
import math
import time
from pathlib import Path

import numpy as np
import torch
import lpips
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
REN_DIR = RESULTS / "_m64_lpips_renders"

rr = json.loads((RESULTS / "m64_lpips_render_result.json").read_text(encoding="utf-8"))
d = rr["checks"][0]["detail"]   # 渲染侧字段都在 checks[0].detail 下（check() 包装约定）
variants = sorted({f["variant"] for f in d["frames"]})
az_list = sorted({f["az_deg"] for f in d["frames"]})
pairs = d["pairs"]

torch.set_num_threads(max(1, torch.get_num_threads() // 2))


def load_png(p: Path) -> torch.Tensor:
    a = np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)
    a = a / 127.5 - 1.0                      # [0,255] -> [-1,1]（LPIPS 口径）
    return torch.from_numpy(a.transpose(2, 0, 1))  # (3,H,W)


# ── 预载 64 张 ────────────────────────────────────────────────
t0 = time.perf_counter()
T: dict[str, list[torch.Tensor]] = {}
for v in variants:
    T[v] = []
    for az in az_list:
        p = REN_DIR / f"{v}_az{az_list.index(az):02d}.png"
        if not p.exists():
            raise FileNotFoundError(p)
        T[v].append(load_png(p))
print(f"loaded {len(variants) * len(az_list)} pngs in {time.perf_counter() - t0:.1f}s")

loss = lpips.LPIPS(net='alex').eval()


@torch.no_grad()
def lpips_mean(va: str, vb: str) -> float:
    """8 视角 batch 一次前向 → 均值。"""
    x = torch.stack([T[va][i] for i in range(len(az_list))], dim=0)   # (8,3,H,W)
    y = torch.stack([T[vb][i] for i in range(len(az_list))], dim=0)
    d = loss(x, y)                                                    # (8,1,1,1)
    return float(d.mean())


# ── [1] 自比 sanity ──────────────────────────────────────────
self_0 = lpips_mean("cyl", "cyl")
print(f"sanity L(cyl,cyl) = {self_0:.6f}  (期望 |值| < 0.01)")

# ── [2] 28 对 L（8 视角均值）─────────────────────────────────
rows = []
t0 = time.perf_counter()
for r in pairs:
    a, b = r["pair"].split("|")
    L = lpips_mean(a, b)
    rows.append({**r, "L_lpips8": round(L, 6)})
    print(f"  {r['pair']:>12}  V={r['V_voxel128']:.4f}  L={L:.4f}  {'NEAR' if r['near'] else ''}")
print(f"28 pairs scored in {time.perf_counter() - t0:.1f}s")

# ── [3] 对账判据 ─────────────────────────────────────────────
def spearman(xs, ys):
    n = len(xs)

    def rank(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 1.0


V = [r["V_voxel128"] for r in rows]
L = [r["L_lpips8"] for r in rows]
near = [r for r in rows if r["near"]]
far = [r for r in rows if not r["near"]]
near_L = [r["L_lpips8"] for r in near]
far_L = [r["L_lpips8"] for r in far]

sp_vl = spearman(V, L)
sub = [r for r in rows if r["V_voxel128"] < 0.3]
sp_vl_sub = spearman([r["V_voxel128"] for r in sub], [r["L_lpips8"] for r in sub]) if len(sub) >= 5 else None

t_same = max(near_L)
t_diff = min(far_L)

crit = {
    "spearman_VL_ge_080_full": sp_vl >= 0.80,
    "spearman_VL_ge_085_paramdomain": None if sp_vl_sub is None else sp_vl_sub >= 0.85,
    "separation_mean": (sum(near_L) / len(near_L)) < (sum(far_L) / len(far_L)),
    "separation_strict_maxmin": t_same < t_diff,
    "self_zero": abs(self_0) < 0.01,
}

out = {
    "suite": "M6-4 LPIPS calibration (8-view mean, alex backbone, inference-only)",
    "render_result": "m64_lpips_render_result.json",
    "backbone": "alexnet + v0.1 lin layers (richzhang)",
    "n_variants": len(variants), "n_views": len(az_list), "n_pairs": len(rows),
    "sanity_self_lpips": round(self_0, 6),
    "spearman_V_vs_L": round(sp_vl, 4),
    "spearman_V_vs_L_paramdomain": None if sp_vl_sub is None else round(sp_vl_sub, 4),
    "paramdomain_pairs": len(sub),
    "near_pairs_L": [round(x, 4) for x in sorted(near_L)],
    "far_pairs_L_min": round(min(far_L), 4),
    "far_pairs_L_max": round(max(far_L), 4),
    "far_pairs_L_mean": round(sum(far_L) / len(far_L), 4),
    "near_far_mean_separation": round(sum(far_L) / len(far_L) - sum(near_L) / len(near_L), 4),
    "thresholds": {"t_same_visual": round(t_same, 4), "t_diff_visual": round(t_diff, 4),
                   "gray_zone_semantics": "落灰区保守判不同（多样性闸门宁严勿松）"},
    "criteria": crit,
    "pairs": rows,
}
(RESULTS / "m64_lpips_result.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"\nSpearman(V,L) 全域 = {sp_vl:.4f}" + (f" · 参数级域 = {sp_vl_sub:.4f}" if sp_vl_sub is not None else ""))
print(f"近对 L 均值 = {sum(near_L)/len(near_L):.4f} · 远对 L 均值 = {sum(far_L)/len(far_L):.4f}")
print(f"阈值：t_same = {t_same:.4f} · t_diff = {t_diff:.4f} · 严格分离 = {crit['separation_strict_maxmin']}")
print("result ->", RESULTS / "m64_lpips_result.json")
