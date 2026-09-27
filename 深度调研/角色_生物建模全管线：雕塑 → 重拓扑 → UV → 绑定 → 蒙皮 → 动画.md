# 角色/生物建模全管线：雕塑 → 重拓扑 → UV → 绑定 → 蒙皮 → 动画

- 原始记录：`agent-36a52fcd68144796.jsonl`

---

【角色/生物建模全管线编译可行性调研】（深度版，~1650字）

## 一、管线步骤清单（8步，标注可编译性）

**1. 概念/雕塑（ZBrush / Blender Sculpt，百万面）【必须人工】**
雕塑是纯艺术判断——大形、解剖、风格化全部依赖手感。ZBrush DynaMesh / Blender Voxel Remesh 这类体素重建只是"继续雕刻"的基建（reformsculpt.com 对比文），不产生动画可用拓扑。AI 只能在此步提供概念图或生成式初稿（Meshy/Tripo，2026 年已在做），但 hero 资产一致性差，行业共识是"blockout 层"。

**2. 重拓扑（百万面→万面四边面）【半编译】**
算法原理已查实：主流是"方向场对齐四边面化"——在表面计算平滑十字场（cross-field，N-RoSy 方向场+位置场），再全局优化使边对齐曲率线。Instant Meshes（ETH，局部优化线性时间）、QuadriFlow（Blender 内置，min-cost flow 消奇异点）、ZRemesher/Quad Remesher（Exoside 作者 Maxime Rouca 即 ZRemesher 原作者，检测凹凸/分叉后策略性布边环）同属此族。QuadWild（SIGGRAPH 2021）用特征线驱动 patch 分解，Thingi10K 批处理失败率 <0.5%，全自动。**但**：自动工具"几何驱动、近乎均匀"，缺乏语义感知——关节处环形边、肌肉走向边流、极点编组这些"为变形服务的拓扑"必须人工引导（RetopoFlow 手动、QuadRemesher 画引导）。参数（目标面数、曲率自适应、硬边阈值）可编译，边流方向判断不可。ML 前沿（MeshGPT/QuadGPT 自回归、QuadLink、TopGen-220K、NeurCross）在学"艺术家级边流"，但 2026 年仍处论文阶段，无生产级可用产品【未核实其工程成熟度】。

**3. UV 展开【半编译】**
拆开看：**接缝放置**=艺术判断（有机模型 Smart UV Project 效果差、碎片岛多，社区公认"auto-unwrap 任何软件都很烂"）；**展开求解**（LSCM/Angle-Based）和**打包**（UVPackmaster 实测利用率 89.4% vs Smart UV 72.3%，零重叠）=纯算法可编译。RizomUV 是失真最小化专精。所以 UV 可以编译成"seam spec（人工/AI 给）+ 自动求解打包（机器）"的两段式。

**4. 骨骼绑定（Rigify 层）【可编译，条件是限定模板】**
关键发现：Rigify 本身就是一个"编译器"——metarig（骨骼位置数据）+ 模板（Python 生成代码）→ 控制骨架。骨骼/约束/驱动器在 Blender 里都是数据+确定性 API 调用，不是神秘资产。Houdini 21 的 KineFX Autorig Builder 走得更远：拖拽组件装配、APEX 图融合、整个 rig 打包成 HDA、跨角色 rig 模板迁移——证明"rig=图数据"在工业界已成立。可编译部分：metarig 摆位（UniRig，MIT 开源 SIGGRAPH 2025，可预测双足/四足/鸟类骨架）、模板选择、IK/FK 配置。不可编译：非标比例的特殊生物设计。

**5. 蒙皮/权重【可编译】**
Blender 自动权重即 Pinocchio/双调和权重族（Joshi 2007 / Botsch 2004）。真正的杠杆是 **Delta Mush**（Rhythm & Hues Voodoo 起源）：rest pose 下平滑+bake 切线空间偏移，形变后重应用——用二值绑定权重就能近似手工权重质量，Le & Lewis 的 Direct Delta Mush（TOG 2019）已做到实时引擎可用，纯参数算法（iterations/step size）。结论：自动权重+Delta Mush 的组合完全可写进 plan；修正权重留给人工。

**6. 形态键/表情【半编译】**
**"表情 plan-JSON"已经存在**——ARKit 52 blendshape 就是：52 个命名 float（0-1），表达式=系数叠加（smile = mouthSmileL 0.8 + mouthSmileR 0.8 + cheekSquint 0.5）。MetaHuman/Character Creator/VTuber 生态全兼容此标准。参数层、命名约定、驱动逻辑可编译；但**每个形态键的目标网格本身是雕塑品**（52 个修正雕塑），只能作为外部资产在 plan 里引用，不能编译生成。

**7. 蒙皮后修正/CFX【必须人工】**（肌肉/脂肪模拟、shot sculpting——Houdini 21 Otis 是专用求解器+ML Deformer 路线，属高阶人工/TD 域）

**8. 动画/重定向【可编译（数据层）】**
mocap 是录制数据，retarget 是模板映射（HumanIK/Rigify+第三方）。Houdini 21 Animation Catalog/Motion Mixer 证明动画片段库可资产化。创意 keyframe 动画仍人工。

## 二、设计转译（我们的架构切在哪里）

1. **编译路线的输入点应定在"重拓扑之后"**：AI spec 不直接生成角色几何，而是消费一个 retopo 好的低模（或引用 QuadRemesher 外部工具跑完再进）。雕塑高模→烘焙法线/置换，这段是外部工具链。
2. **rig-as-data 是最大可编译红利**：plan 里写 `rig_json`（骨骼位置、模板选择、IK 开关、命名约定 DEF-/CTL-），编译器调 Rigify 或自家模板生成器。Rigify 证明了这条路在 Blender 原生可行。
3. **表情直接采用 ARKit-52 作为 schema**：plan 引用外部形态键资产+驱动器配置 JSON，不做自创标准，白嫖整个生态（Live Link Face、mocap、MetaHuman 互通）。
4. **硬伤必须内置桥接 op**：已查实 Blender GN 生成几何只能输出 generic attribute，**无法直接输出 Vertex Group / UV Map**，Armature 修改器读不到（blenderartists 多轮确认，官方文档注明 realize 后是 generic float）。所以编译管线必须含"Apply GN → attribute 转 VG/UV"的固化步骤，这是架构级设计点，不是细节。
5. **Delta Mush 设为编译管线的标准后处理节点**，把蒙皮质量下限从"自动权重灾难"抬到"可用"。
6. **ML 重拓扑/ML 蒙皮不做依赖**，挂在外部工具调用层观察。

## 三、逃逸舱粒度设计（角色走自由代码路线）

三层粒度共存：
- **L1 参数层（全编译）**：rig JSON、表情驱动 JSON、蒙皮参数（Delta Mush iterations）——进 plan。
- **L2 模板层（受控代码）**：Rigify 式生成器、约束网络模板——版本管理的固定代码库，plan 只引用模板名+参数，不允许 plan 内改模板。
- **L3 脚本层（自由代码）**：特殊变形器、修正形状逻辑、自定义约束——单文件 .py，经人工签名/静态审查（API 白名单限定 Armature/Constraint/ShapeKey 域，禁 io/net）后作为 plan 的 `scripts` 段与编译产物同存。
共存契约：**脚本产物必须落到稳定数据接口**（标准骨架命名、VG/UV/形态键命名约定），保证 L1 参数层后续可回编译、可被引擎导出链消费。编译产物=GN 修改器+rig JSON+资产引用；脚本只准操作数据接口之上的行为，不得替换几何本体。

## 四、文献/工具/链接

1. Instant Meshes（ETH，N-RoSy cross-field 开源）：github.com/wjakob/instant-meshes
2. QuadWild — Reliable Feature-Line Driven Quad-Remeshing（SIGGRAPH 2021）：quadmesh.cloud
3. Quad Remesher（Exoside/ZRemesher 原作者，blendernation.com FAQ 技术细节）
4. Le & Lewis, Direct Delta Mush Skinning, ACM TOG 2019：dl.acm.org/doi/10.1145/3306346.3322982
5. Blender 手册 Realize Instances 泛型属性限制：docs.blender.org
6. Rigify 文档（metarig→generate 编译模型）：docs.blender.org
7. ARKit 52 Blendshapes 协议（realtime-avatars.com/learn/metahuman/concepts/arkit-protocol）
8. UniRig（MIT 开源，SIGGRAPH 2025，骨骼+蒙皮预测）
9. Houdini 21 KineFX Autorig Builder / APEX / Rig Builder HDA：sidefx.com/tutorials/intro-to-rig-builder
10. ML 四边面前沿：TopGen（arXiv 2603.10606）、QuadLink（arXiv 2605.16813）【未核实生产可用性】

（完）