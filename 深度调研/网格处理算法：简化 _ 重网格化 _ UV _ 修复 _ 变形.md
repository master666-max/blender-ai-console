# 网格处理算法：简化 / 重网格化 / UV / 修复 / 变形

- 原始记录：`agent-f7edb339ddfb43a3.jsonl`

---

【网格处理算法深度调研】（WebSearch 已核实，未核实处标注）

一、算法/工具盘点

1. QEM 边坍缩简化（Garland & Heckbert, SIGGRAPH 1997；属性扩展版 Hoppe 1999；离散曲率扩展 Tang et al. 2010）。复杂度：堆式贪心 O(n log n)。开源实现：meshoptimizer（zeux，MIT，支持带属性/UV 的 QEM、锁边界、绝对误差模式，工业级）；Fast-Quadric-Mesh-Simplification（约 4 倍速于 MeshLab，精度换速度）；quad_mesh_simplify（pip 可装，Cython）。QEM 之后的"进展"主要是属性保持与曲率加权，算法框架未变。Blender Decimate 的 Collapse 模式即 QEM 边坍缩，但实现较老：会三角化输出、破坏 UV/形状键/骨骼权重。Vertex Clustering（Lindstrom 2000）O(n) 更快但误差大，仅 GPU 场景值得用。

2. QuadWild（Pietroni et al., SIGGRAPH 2021，"Reliable Feature-Line Driven Quad-Remeshing"）：三阶段——特征对齐 cross-field 计算 → field tracing 出 patch 分解 → patch 内四边化。构造性保证特征线复现，全自动，Thingi10K 全库批量失败率 <0.5%。fork 版 quadwild-bimdf 用 Bi-MDF 求解器免掉 Gurobi 依赖，有 Win/Linux/Mac 预编译二进制。GPL3。对 GN 产出：要求三角网格输入，质量上限最高，但分钟级耗时。

3. Instant Meshes（Jakob et al., SIGGRAPH Asia 2015）：field-aligned 四边形重网格，交互级（3.7 亿三角 10 分钟/16 核），支持手绘引导边流。Blender 内置 QuadriFlow 与 Rhino 7 QuadReMesh 均属此路线。适合雕刻/有机体；不保留原 UV（所有 remesh 皆然）。

4. SLIM（Rüffer et al., ETH，SGP 2018 前后）：可伸缩局部单射映射，local-global 迭代，每轮 O(n)，面积+角度失真双低，迭代次数即"质量/时间"旋钮。已并入 Blender 4.3（UI 名"Minimum Stretch"，重写实现）。xatlas（GitHub, MIT）：现代自动 seam 预测 + chart 参数化 + atlas packing，游戏资产事实标准，秒级，有 Python 绑定。

5. MeshFix（Attene, The Visual Computer 2010，CNR-IMATI，GPLv3）：把输入当单一闭合实体，移除自交/退化/非流形，输出水密网格。可靠性高但**破坏性明确**：论文对比实验证实会丢弃伪孔周边部件与断开组件（LoD2 建筑实验中面数从 11.3k 降到 7k）。对比：PMP 孔洞填充（Sieger & Botsch 2019）保结构但会误填伪孔；PolyMender（Ju 2004）体素重构过平滑且面数暴涨。Blender 4.x Make Manifold 是这些思路的一键合并版，可靠性中等。兜底"最稳"方案：voxel remesh（make solid），保证封闭但细节全失。

6. Functional Maps（Ovsjanikov et al., SIGGRAPH 2012）：在 Laplace-Beltrami 特征函数基上表示映射，描述符保持/landmark/算子交换性等约束全部线性化，一次线性求解。等距形状上 SOTA（SHREC 等距基准）。但**不能保证"特征对特征"**：谱嵌入有对称歧义（左右手混淆），非等距/带自交输入时点级精度下降；需补 landmark 约束 + 点描述符（HKS/WKS）+ pointwise 精化（Ezuz & Ben-Chen 2017）或 ARAP/最近点投影 ICP 精化。对应关系建立三路线：functional maps（全局谱方法）、最近点/投影（局部但易错到对称侧）、ARAP 形变拟合。

7. PaMO（2025，Tiptree/Lacuna）：GPU 三阶段管线（Dual Marching Cubes 重网格 → 并行 QEM 简化含相交检测回退 → IPC 式安全投影）。RTX 4090 上 200 万面→2 万面 3 秒，Thingi10K 98% 模型 <2 秒，保证无自交流形。另有 DeCoro & Tatarchuk (I3D 2007) 经典 GPU vertex-clustering 与 NVIDIA GTC 2023 无锁并行边坍缩（交互级 remeshing）。

8. 库生态：trimesh（MIT，纯 Python + numpy，可装进 bpy 的 Python 环境，后端 manifold3d 做布尔/修复，优雅降级）；PyMeshLab（GPL，MeshLab 220+ 滤镜直调，含 QEM 简化/孔洞填充）；Open3D（MIT，偏点云/重建，布尔脆弱）；libigl（MIT header-only C++，算法最全但需子进程/C++ 封装）；CGAL（GPL/LGPL，最重）；MeshLib（商业，Python 绑定 + CUDA）。

二、设计转译（后处理管线建议）

1. 简化步升级：GN 求值结果 → numpy 顶点/面数组 → meshoptimizer 的 simplifyWithAttributes（保 UV/法线属性、可锁边界）→ 写回 mesh。理由：Decimate Collapse 会破坏 UV 和形状键，meshoptimizer 的属性 QEM 无此问题，且 MIT 协议干净。
2. 新增可选"游戏资产四边化"步：mesh → quadwild-bimdf 子进程 → 半规则四边形网格。理由：GN 编译产出是参数化三角/多边形汤，quadwild 失败率 <0.5% 且全自动，是唯一构造性保特征线的开源方案；用于 hero asset，普通资产走 meshopt。
3. 修复步用 trimesh+manifold3d 替代 Make Manifold：exact 算术、纯 Python 依赖、保证输出流形水密；孔洞单独用 PMP 填充并做伪孔过滤。MeshFix 仅作最后兜底（接受部件丢失风险时）。
4. UV 步：默认 xatlas（含 packing，直接写 UV 层），失败回退 Blender 4.3 SLIM（Minimum Stretch）迭代精化。"编译期保证可用 UV"：算法上不存在零失真保证，但管线可以保证"必有合法 UV"——编译期 GN UV 节点给粗 UV，后处理 xatlas/SLIM 必产出无重叠 packing，作为兜底契约。
5. 变形/权重传输：拓扑不同 mesh 间，先 landmark（用户点选或对称性自动）+ HKS 描述符 → functional map 线性求解 → pointwise 精化 → 传输。不要裸用 Data Transfer modifier（最近点，对称结构必错侧）。此为新增能力，建议 libigl 子进程封装或 MeshLib。
6. 超大网格（>500 万面）：引 GPU 路线——voxel remesh + 并行 QEM（PaMO 论文思路），或将 meshopt 的 batched collapse 用 compute shader 复刻；交互预览用 vertex clustering LOD 即可。

三、逃逸舱 vs 算法库边界

可升级为算法调用（numpy 直传，无 bpy.ops）：QEM 简化、UV 展开+packing、修复/水密化、布尔清理、连通分量/非流形检测。需子进程封装（一次性工程成本）：quadwild-bimdf、libigl 各工具。建议保留 bpy.ops：Smart UV Project（机械体够用但 xatlas 更优，可退役）、Planar Decimate（硬表面减面算法库无显著优势）、Limited Dissolve/Weighted Normal。完全新增（无现有逃逸舱）：functional maps 变形传输、GPU 并行简化、半规则四边化。

四、文献/链接

1. Garland & Heckbert 1997, Surface Simplification Using QEM — mgarland.org/files/papers/quadrics.pdf
2. meshoptimizer — github.com/zeux/meshoptimizer
3. quad_mesh_simplify (pip) — github.com/jannessm/quadric-mesh-simplification
4. Pietroni et al. 2021, Reliable Feature-Line Driven Quad-Remeshing, ACM TOG 40(4) — doi:10.1145/3450626.3459941
5. QuadWild — github.com/nicopietroni/quadwild；Bi-MDF 版 — github.com/cgg-bern/quadwild-bimdf
6. Instant Meshes — github.com/wjakob/instant-meshes
7. Blender UV 手册（ABF/LSCM/SLIM/Smart UV）— docs.blender.org/manual/en/latest/modeling/meshes/editing/uv.html
8. SLIM 并入 Blender 4.3 说明 — uvpackmaster.com/?p=5042/
9. Attene 2010, MeshFix — 轻量修复（GPLv3）
10. PMP 孔洞填充对比实验 — arxiv 2404.15892（含 MeshFix/PMP/PolyMender/MeshLab 可靠性对比）
11. Ovsjanikov et al. 2012, Functional Maps — history.siggraph.org（SIGGRAPH 档案含摘要）
12. PaMO 2025 GPU 管线 — lacuna.tiptreesystems.com/paper/pamo-...；DeCoro & Tatarchuk 2007 — gfx.cs.princeton.edu
13. trimesh — trimesh.org；libigl tutorial — libigl.github.io

【未核实】项：Blender 内置 QuadriFlow 的具体论文出处（社区确认存在但官方未标注算法来源）；MeshLib CUDA 具体覆盖哪些算法（仅官网宣传级信息）；SLIM 原始论文准确年份与作者全名。