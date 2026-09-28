"""
gn_verify.py — 机械几何验证器（第 4 组：verifier 必须是机械的，不能让 LLM 自己打分）

原则来自 verifier's law / Goodhart：
    **学习型 proxy 必被攻破。** 所以这里全部是确定性谓词，零模型参与。
    能自动验的都自动验掉，剩下的才是人的审美判断 —— 这才是"管得松"的前提。

用法：
    v = GeometryVerifier(budget_faces=200_000)
    report = v.check(mesh, obj)
    if not report.ok: ...回退该段...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence
import re

__all__ = ["Finding", "VerifyReport", "GeometryVerifier"]


@dataclass(frozen=True)
class Finding:
    predicate: str
    ok: bool
    value: Any = None
    limit: Any = None
    detail: str = ""

    def __str__(self) -> str:
        flag = "ok " if self.ok else "FAIL"
        return f"[{flag}] {self.predicate}: {self.value} (limit={self.limit}) {self.detail}".rstrip()


@dataclass
class VerifyReport:
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(f.ok for f in self.findings)

    @property
    def failures(self) -> list[Finding]:
        return [f for f in self.findings if not f.ok]

    def __str__(self) -> str:
        head = "VERIFY PASS" if self.ok else f"VERIFY FAIL ({len(self.failures)})"
        return head + "\n" + "\n".join(str(f) for f in self.findings)


class GeometryVerifier:
    """确定性几何体检。每个谓词都必须"不可攻破"：不打分、不学习、不猜。"""

    def __init__(
        self,
        budget_faces: int = 200_000,
        budget_objects: int = 500,
        ground_z: float = 0.0,
        check_ground: bool = True,
        check_applied_scale: bool = True,
    ) -> None:
        self.budget_faces = budget_faces
        self.budget_objects = budget_objects
        self.ground_z = ground_z
        self.check_ground = check_ground
        self.check_applied_scale = check_applied_scale

    # ── 主入口 ────────────────────────────────────────────────
    def check(self, mesh: Any, obj: Any = None) -> VerifyReport:
        import bmesh  # 延迟导入：只在 Blender 内可用

        rep = VerifyReport()
        nv = len(mesh.vertices)
        nf = len(mesh.polygons)

        rep.findings.append(Finding("non_empty", nv > 0 and nf > 0,
                                    f"verts={nv} faces={nf}", ">0"))

        if nv == 0:
            return rep

        bm = bmesh.new()  # type: ignore[attr-defined]
        try:
            bm.from_mesh(mesh)
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            bm.verts.ensure_lookup_table()

            # M8-R3 边级分型（吸收隔离区 mesh_audit.py，审计条目 1）：
            # 非流形/边界/线框/绕向不连续 四分型——比聚合计数多给"在哪类坏"的信息
            nonman = boundary = wire = flipped = 0
            for e in bm.edges:
                if e.is_boundary:
                    boundary += 1
                elif not e.is_manifold:
                    if e.is_wire:
                        wire += 1
                    else:
                        nonman += 1
                elif not e.is_contiguous:
                    flipped += 1            # 绕向不连续：法线方向在边两侧打架
            rep.findings.append(Finding("manifold", nonman == 0, nonman, 0, "非流形边数"))
            rep.findings.append(Finding(
                "edge_topology",
                flipped == 0,               # 边界边对开放网格合法（如杯子口），不算坏
                {"flipped_winding": flipped, "boundary": boundary, "wire": wire},
                {"flipped_winding": 0},
                "绕向不连续边（法线打架）——布尔/烘焙/3D 打印的隐形杀手"))

            zero = 0
            for f in bm.faces:
                try:
                    if f.calc_area() <= 1e-10:
                        zero += 1
                except Exception:  # noqa: BLE001  退化面计算可能失败
                    zero += 1
            rep.findings.append(Finding("no_degenerate_faces", zero == 0, zero, 0, "零面积面数"))

            loose = sum(1 for v in bm.verts if not v.link_edges)
            rep.findings.append(Finding("no_loose_verts", loose == 0, loose, 0, "松散顶点数"))
        finally:
            bm.free()

        rep.findings.append(Finding("face_budget", nf <= self.budget_faces,
                                    nf, self.budget_faces, "三角面/面预算"))

        if obj is not None:
            if self.check_applied_scale:
                s = tuple(round(x, 6) for x in getattr(obj, "scale", (1, 1, 1)))
                applied = all(abs(x - 1.0) < 1e-6 for x in s)
                rep.findings.append(Finding("applied_scale", applied, s, "(1,1,1)",
                                            "未应用变换会让导出/布尔出错"))
            if self.check_ground:
                # M8-R2 修正（EXP-010 同族教训）：v.co 是**物体局部空间**——
                # 物体被移动后局部 z 不变，穿地检查必须用**世界空间**（matrix_world 变换）
                mw = obj.matrix_world if obj is not None else None
                if mw is not None:
                    zs = [(mw @ v.co).z for v in mesh.vertices]
                else:
                    zs = [v.co.z for v in mesh.vertices]
                minz = min(zs) if zs else 0.0
                rep.findings.append(Finding("above_ground", minz >= self.ground_z - 1e-6,
                                            round(minz, 6), self.ground_z, "穿地(世界)"))

        return rep

    # ── 给"AI 只会加不会改"的专项指标 ─────────────────────────
    @staticmethod
    def edit_vs_add_ratio(before_faces: int, after_faces: int) -> float:
        """GitClear 的教训：AI 的"移动/重构"行 24.1%→9.5%，复制粘贴涨 8 倍。

        3D 等价灾难是"不停加新物体而不是改好已有物体"。
        这里用一个粗代理：面数增长比。>1 很多说明在"加"，≈1 说明在"改"。
        """
        if before_faces <= 0:
            return float("inf")
        return round(after_faces / before_faces, 3)

    # ── A25 局部性：段落执行后受影响顶点占比 ─────────────────
    @staticmethod
    def moved_fraction(before_keys: set, mesh: Any) -> float:
        """after 顶点中，坐标签名（1e-5 精度）不在 before 集合里的占比。

        实测基线：布尔差只动 9–27% 顶点（probe_surgery，本机 5.2.1）。
        阈值 0.4：超过说明这段的"手术范围"失控——该拆段（A25 告警）。
        """
        after = {(round(v.co.x, 5), round(v.co.y, 5), round(v.co.z, 5))
                 for v in mesh.vertices}
        if not after:
            return 1.0
        moved = sum(1 for k in after if k not in before_keys)
        return moved / len(after)

    @classmethod
    def check_locality(cls, before_keys: set, mesh: Any,
                       threshold: float = 0.40) -> "Finding":
        moved = cls.moved_fraction(before_keys, mesh)
        return Finding("locality", moved <= threshold, round(moved, 4),
                       threshold, "受影响顶点占比（超=手术范围失控，该拆段）")

    # ── A24 物体数一致性 ─────────────────────────────────────
    # ── M2-1 补全谓词（工单 v2.1；吸收隔离区 mesh_audit 思路）──
    #: M2-1a 面预算**分类**：按工艺阶段差异化（blockout 小、detail 放开）——
    #: 上游 13 分册"DETAIL_LEVEL 只决定停手位置"的机械版
    BUDGET_BY_STAGE = {"blockout": 2_000, "structure": 20_000,
                       "detail": 50_000, "cleanup": 50_000, "deliver": 200_000}

    @classmethod
    def check_budget_class(cls, faces: int, stage: str) -> "Finding":
        limit = cls.BUDGET_BY_STAGE.get(stage, cls.BUDGET_BY_STAGE["detail"])
        return Finding("budget_class", faces <= limit, faces, limit,
                       f"stage={stage!r} 面预算")

    @staticmethod
    def check_stack_depth(obj: Any, max_depth: int = 8) -> "Finding":
        """M2-1b 修改器栈深度：层数失控 = 段落粒度失控（A25 告警的静态面）。"""
        n = len(getattr(obj, "modifiers", []))
        return Finding("stack_depth", n <= max_depth, n, max_depth, "修改器栈深度")

    @staticmethod
    def check_parent_cycle(obj: Any) -> "Finding":
        """M2-1c 父子成环：沿 parent 链走，回到起点即环（A5/Grasshopper 铁律的层级版）。"""
        seen = set()
        cur = obj
        while cur is not None and getattr(cur, "parent", None) is not None:
            if cur.name in seen:
                return Finding("parent_cycle", False, cur.name, None,
                               "父子链成环——层级数据流被破坏")
            seen.add(cur.name)
            cur = cur.parent
        return Finding("parent_cycle", True, sorted(seen), None, "父子链无环")

    _BAD_NAME = re.compile(r"^(parm|arg|args|Socket_|Input_|obj|mesh|Cube|Plane|Sphere|"
                           r"Circle|Cylinder)[\. _]?\d*$", re.IGNORECASE)

    @classmethod
    def check_naming(cls, obj: Any) -> "Finding":
        """M2-1d 命名约定：对象名须是艺术家语义名（禁 parm3/Cube.001 式默认名）。

        依据：EXP-001（双前缀+模式匹配清理误删 353 物体）——命名纪律是清理安全的
        前置；plan_schema 的 NON_SEMANTIC_NAME 同思想，这里是对象级。
        """
        name = getattr(obj, "name", "")
        base = name.split(".")[0]                       # 去掉 .001 尾巴再判
        bad = bool(cls._BAD_NAME.match(base)) or base == ""
        return Finding("semantic_naming", not bad, name, "艺术家语义名",
                       "默认名/无语义名（.001 家族）会让清理与反查失效")

    @staticmethod
    def check_object_count(expected: int, actual: int) -> "Finding":
        """我自己 join 少并一个物体时 baseline 都"通过"了——此谓词为堵这个洞而生。"""
        return Finding("object_count", expected == actual, actual, expected,
                       "物体数/段落数一致性")


# ══════════════════════════════════════════════════════════════
# M2-6 · DFM 制造可行性谓词（d3-dfm 调研，全部有物理依据）
# ══════════════════════════════════════════════════════════════
_DFM_LIMITS = {
    "fdm": {"wall_min_mm": 1.2, "overhang_deg": 45, "bridge_max_mm": 10},
    "sla": {"wall_min_mm": 0.5, "overhang_deg": 30, "bridge_max_mm": 5,
            "escape_hole": True},
    "sls": {"wall_min_mm": 0.7, "overhang_deg": 999, "bridge_max_mm": 30,
            "escape_hole": True},
    "injection": {"wall_min_mm": 0.8, "draft_deg": 1.0,
                  "inner_fillet_deg": 45.0, "wall_ratio_max": 2.0},
    "cnc": {"wall_min_mm": 0.8},
}


def check_dfm(mesh, process="fdm", material_token=None, obj=None):
    """制造可行性谓词组——全部机械谓词，非学习型 proxy。

    返回 list[Finding]，每条有物理依据（d3-dfm 调研）。

    M2-6 对账（2026-09-27 R2）修掉两处"从未执行过"级别的 bug：
      ① bmesh.types.BMesh 根本没有 ray_cast（一调就 AttributeError——
         本函数此前零调用方+零测试，写下之日起从未成功运行）；
         正确姿势 = mathutils.bvhtree.BVHTree.FromBMesh。
      ② 原写法 origin 沿 +normal **外偏** 1e-5 再向内打——第一命中是
         自己这张面（距离 ≈1e-5，恰好落进 1e-7 < d < wall_min 判薄区间），
         任何封闭网格都会被判"壁厚过薄"。改为**内偏**起点向内打，
         首命中即对侧壁（真厚度）。零厚度面片漏检由 dfm_manifold 兜底。
    M2-6 缺口补全（2026-09-28 R7g，四谓词）：
      DFM-5 dfm_draft（injection）：零拔模竖直壁——壁面拔模角 θ 的法线
        z 分量 = sin(θ)，θ < draft_deg ⟺ |nz| < sin(draft_deg)；
        物理：注塑侧壁无拔模刮伤脱模（d3-dfm）。
      DFM-6 dfm_inner_fillet（injection）：凹内角边——凹边且两面法线夹角
        > inner_fillet_deg（45° ⟺ 材料内角 > 225°，典型凹直角 270° 必中）；
        物理：注塑凹角无圆角 → 应力集中 + 填充不满（典型 R ≥ 0.5-1mm）。
      DFM-7 dfm_wall_uniformity（injection）：壁厚均匀性——DFM-1 射线
        样本的 p95/p05 比 ≤ wall_ratio_max（2:1 均厚规则；样本 < 6 跳过）；
        物理：壁厚悬殊 → 缩水痕/翘曲。
      DFM-8 dfm_escape_hole（sla/sls）：封闭内腔——连通分量洪泛 + 封闭
        分量 Euler genus（g=(2-χ)/2, χ=V-E+F）+ bbox 嵌套：内分量封闭
        且 g==0 → 全封闭腔无逃逸孔（树脂困死/粉末排不出）。
    仍维持诚实缺口（mesh 层无特征语义，不虚标）：CNC 深径比（需孔特征
    识别）；独立 min_feature（与 wall_min 面级同源，细分网格假阳性不可控
    ——由 dfm_min_wall + dfm_inner_fillet 联合近似）。
    """
    import bmesh
    import math
    from mathutils.bvhtree import BVHTree

    limits = dict(_DFM_LIMITS.get(process, _DFM_LIMITS["fdm"]))
    if material_token:
        limits.update(material_token)

    findings = []
    nv, nf = len(mesh.vertices), len(mesh.polygons)
    if nv == 0:
        return [Finding("dfm_non_empty", False, 0, ">0", "空网格")]

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bvh = BVHTree.FromBMesh(bm)

        # DFM-1 最小壁厚（内偏起点 + BVH 射线：首命中 = 对侧壁）
        # R7g：同一循环沉淀厚度样本 → DFM-7 均匀性复用（一次射线两用）
        wall_min = limits.get("wall_min_mm", 1.2) / 1000
        thin = 0
        thick_samples: list[float] = []
        for f in bm.faces:
            c = f.calc_center_median()
            n = f.normal.normalized()
            h = bvh.ray_cast(c - n * 1e-5, -n)[0]
            if h is not None and 1e-7 < (c - h).length < wall_min:
                thin += 1
            if h is not None:
                d = (c - h).length
                if d > 1e-7:
                    thick_samples.append(d)
        findings.append(Finding("dfm_min_wall", thin == 0, thin, 0,
            f"壁厚 < {wall_min*1000:.1f}mm"))

        # DFM-2 悬垂角
        if process in ("fdm", "sla"):
            lim = math.cos(math.radians(90 - limits.get("overhang_deg", 45)))
            oh = sum(1 for f in bm.faces
                     if f.normal.z < -lim and f.calc_area() > 1e-10)
            findings.append(Finding("dfm_overhang", oh == 0, oh, 0,
                f"悬垂面数（> {limits.get('overhang_deg', 45)}°）"))

        # DFM-3 桥接跨度
        if process == "fdm":
            bmax = limits.get("bridge_max_mm", 10) / 1000
            lb = sum(1 for e in bm.edges
                     if len(e.link_faces) == 1 and e.calc_length() > bmax)
            findings.append(Finding("dfm_bridge_span", lb == 0, lb, 0,
                f"桥接跨度超限（> {limits.get('bridge_max_mm',10)*1000:.0f}mm）"))

        # DFM-4 非流形
        nm = sum(1 for e in bm.edges if not e.is_manifold)
        findings.append(Finding("dfm_manifold", nm == 0, nm, 0, "非流形边数"))

        # DFM-5 拔模角（injection）：零拔模竖直壁面计数
        # 几何：壁面拔模角 θ（相对脱模轴 Z）⟺ |nz| = sin(θ)；
        # θ < draft_deg ⟺ |nz| < sin(draft_deg)。水平顶底面 |nz|≈1 不计入。
        if "draft_deg" in limits:
            sin_lim = math.sin(math.radians(limits["draft_deg"]))
            n_draft = sum(1 for f in bm.faces
                          if abs(f.normal.z) < sin_lim
                          and f.calc_area() > 1e-10)
            findings.append(Finding("dfm_draft", n_draft == 0, n_draft, 0,
                f"零拔模竖直壁面数（拔模 < {limits['draft_deg']}°）"))

        # DFM-6 凹内角（injection）：凹边且两面法线夹角 > inner_fillet_deg
        # 凹凸符号（loop 一致绕向，m2_predicates_live L 形真机校准）：
        # cross(n1, n2)·t < 0 = 凹（t 为 loop1 的边方向）
        if "inner_fillet_deg" in limits:
            cos_lim = math.cos(math.radians(limits["inner_fillet_deg"]))
            n_sharp = 0
            for e in bm.edges:
                if len(e.link_faces) != 2 or not e.is_manifold:
                    continue
                l1, l2 = e.link_loops
                n1, n2 = l1.face.normal, l2.face.normal
                # BMLoop 无 .next——面内沿边方向 = link_loop_next.vert - vert（5.2 实锤）
                t = (l1.link_loop_next.vert.co - l1.vert.co)
                if t.length < 1e-12:
                    continue
                concave = (n1.cross(n2).dot(t.normalized()) < 0)
                sharp = n1.dot(n2) < cos_lim  # 法线夹角 > 阈值
                if concave and sharp and e.calc_length() > 1e-6:
                    n_sharp += 1
            findings.append(Finding("dfm_inner_fillet", n_sharp == 0, n_sharp, 0,
                f"凹内角边数（法线夹角 > {limits['inner_fillet_deg']:.0f}°）"))

        # DFM-7 壁厚均匀性（injection）：DFM-1 厚度样本 p95/p05 ≤ ratio 上限
        if "wall_ratio_max" in limits and len(thick_samples) >= 6:
            ts = sorted(thick_samples)
            p05 = ts[int(0.05 * len(ts))]
            p95 = ts[min(int(0.95 * len(ts)), len(ts) - 1)]
            ratio = p95 / max(p05, 1e-9)
            findings.append(Finding("dfm_wall_uniformity",
                ratio <= limits["wall_ratio_max"], round(ratio, 3),
                limits["wall_ratio_max"],
                f"壁厚 p95/p05 比（均厚规则 ≤ {limits['wall_ratio_max']}:1）"))

        # DFM-8 封闭内腔（sla/sls）：分量洪泛 + 封闭分量 genus + bbox 嵌套
        if limits.get("escape_hole"):
            seen: set = set()
            comps: list[list] = []
            for f0 in bm.faces:
                if f0 in seen:
                    continue
                stack, comp = [f0], []
                seen.add(f0)
                while stack:
                    f = stack.pop()
                    comp.append(f)
                    for e in f.edges:
                        for nf in e.link_faces:
                            if nf not in seen:
                                seen.add(nf)
                                stack.append(nf)
                comps.append(comp)
            info: list[tuple] = []  # (min, max, closed, genus)
            for comp in comps:
                edges = {e for f in comp for e in f.edges}
                verts = {v for f in comp for v in f.verts}
                closed = all(len(e.link_faces) == 2 for e in edges)
                chi = len(verts) - len(edges) + len(comp)
                genus = (2 - chi) / 2 if closed else None
                bmin = [min(v.co[i] for v in verts) for i in range(3)]
                bmax = [max(v.co[i] for v in verts) for i in range(3)]
                info.append((bmin, bmax, closed, genus))
            trapped = 0
            for i, (bmin_i, bmax_i, closed_i, g_i) in enumerate(info):
                if not closed_i or g_i != 0:
                    continue
                for j, (bmin_j, bmax_j, _, _) in enumerate(info):
                    if i == j:
                        continue
                    if all(bmin_j[k] > bmin_i[k] and bmax_j[k] < bmax_i[k]
                           for k in range(3)):
                        trapped += 1  # j 封闭 genus0 且嵌套于 i → 全封闭腔
                        break
            findings.append(Finding("dfm_escape_hole", trapped == 0, trapped, 0,
                "全封闭内腔数（无逃逸孔；嵌套封闭 genus-0 分量）"))
    finally:
        bm.free()

    return findings
