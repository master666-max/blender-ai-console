# Houdini / Unreal PCG / Unity 的程序化世界构建管线

- 原始记录：`agent-81342f832abd47bf.jsonl`

---

【Houdini / UE PCG / Unity 程序化世界构建管线——深度调研报告】

■ 一、管线机制（核实来源：SideFX 官方文档 / Epic 官方文档 / GDC 2018 Far Cry 5 演讲笔记 / 腾讯游戏学院）

1. **HDA = "远程执行的配方"而非"导入的资产"**：Houdini Engine 在宿主（UE/Unity/Maya）里不是导入模型，而是把输入（曲线/网格/参数）打包发给后台 Houdini 会话 cook，再把结果转译为原生对象（Static Mesh / Instanced Foliage / Landscape / Spline）。关键纪律：输出不可在宿主里手改（改了下次 cook 会被覆盖），"想改就回参数改"。→ 映射：我们的 plan-JSON 就是 HDA 配方，编译器是 Houdini Engine，"生成结果不可手改、改动只走 plan"应成为架构铁律。

2. **Cook / Rebuild / Bake 三级语义**（SideFX 官方定义）：Recook=参数变了重算节点网络；Rebuild=重算+重新导入 HDA 定义（配方本身变了）；Bake=生成脱离 HDA 的原生资产，不再依赖引擎。→ 我们需要同款三级语义：recook（重编译 plan）、rebuild（经验库条目升级后重建）、bake（把 plan 产物落成静态结果）。

3. **UE PCG 分块（Partitioned Generation）为了增量更新而非并行**：PCG 把 Volume 划分为 grid cell（默认对齐 World Partition 的 12800 units），每 cell 一个本地 PCG 组件独立求值；移动一条阻挡样条线只重算受影响 cell——这是"可持续编辑的生成系统"与"一次性随机散点脚本"的本质区别。跨 cell 问题（树冠伸进邻 cell）用 Cell Boundary Sampler 显式切分。→ 我们的 GN 编译器应支持"plan 局部失效"：依赖图按空间 cell 切分，脏标记传播到 cell 而非全场景。

4. **层级生成（HiGen）按尺度分解决策**：Epic 官方模式——大 grid cell 生成树/巨石（少而大），小 grid 生成草/花（多而小），大 grid 的输出作为小 grid 执行时的缓存数据，只允许大→小 cascade 不允许反向。社区成熟做法（StraySpark 生产模式总结）是三级：顶层 graph 决定 biome 分布 → 中层摆村庄/地标 → 底层铺细节。→ plan-JSON 应引入 grid_size/scale 层级字段，编译器按尺度分层求值并缓存上层结果。

5. **Bake-time 与 Runtime 双模式 + 帧预算**：Epic 官方四种生成模式（Non-partitioned / Partitioned / Hierarchical / Runtime）；工业界默认 bake-time（零运行时成本、可手改、确定性），仅对需要运行时变化的区域用 runtime。预算纪律：单 cell graph 执行 <50ms，热点路径 cell 预烘焙，其余按需生成，partitioned volume 默认开 worker 线程异步求值。→ 我们需要"预算字段"：plan 段落声明预算，编译器超预算降级（减密度/降 LOD）而非失败。

6. **Far Cry 5 的 recipe 流水线（GDC 2018，行业标杆）**：世界按 map(256m)/section/sector(64m) 分块，biome recipe 是"给定输入决定该位置放什么实体的规则集"；工具链互为输入（地形→cliff 工具→biome 工具），每晚在 build farm 上确定性重生成全世界（same input = same result），并保留 Point of Interest 供人工覆盖。→ 这就是我们整个架构的活样本：确定性、可分区重建、人工覆盖点（POI = 我们的 override 字段）。

■ 二、设计转译（具体到 plan-JSON / 编译器）

1. **plan-JSON 增加 `seed` 字段 + 确定性承诺**：所有生成算法（noise/L-system/WFC）共用一个 seeded RNG，同一 plan + 同一 seed = 同一世界。这不是可选优化，是 build farm 夜间重建、多人协作、调试拼接的前提（FC5 明确把 determinism 列为管线需求）。

2. **plan-JSON 增加 `biome_recipe` 段落：条件规则而非硬编码资产**。FC5/行业通用模式是"多张 mask 图（湿度/温度/坡度/高度/AO）+ 查找表决定该点生成什么"。转译：`{ "when": {"slope": [0, 0.3], "moisture": [0.5, 1.0]}, "place": {"tree_oak": {"density": 0.8, "priority": 1}} }`——植被类型是湿度/坡度条件的函数。这对 dependencies 的启示：**biome 规则输出的 mask 是下游 scatter 节点的显式依赖输入**，dependencies 应支持"mask 引用"类型（上游节点产出空间属性，下游按属性过滤），而不是只有资产级依赖。

3. **plan-JSON 增加 `po/override` 字段（POI 机制）**：程序化结果永远要留人工覆盖口。FC5 的 Points of Interest 是"为用户输入和编辑保留的地图位置"。我们的 plan 里对应"此区域程序化生成但允许用户覆盖标记"，用户改了之后程序化重算必须跳过该区域——这是"可编辑性与程序化的和解协议"。

4. **编译器学 PCG 的"点即数据"**：PCG 节点间传的不是 Actor 而是轻量 PCGPoint（Transform+密度+属性集），拷贝成本极低、无 GC 压力，万物皆点使任意节点可组合。我们的 GN 编译器中间表示应统一为"点云+属性"抽象，实例化是最后一步而非中间态。

5. **生成算法可封装为 plan 段落的"算子库"**：L-system（公理+产生式规则，参数化分支角度/密度）、WFC（tile 邻接规则表+坍缩求解，Maxim Gumin 2016 开源）、Space Colonization（吸引点集驱动枝干生长）都能表达为"输入 mask/点集 + 参数表 + 输出点云"的标准算子。industry 对照表（generalistprogrammer 综合）：Perlin/CA 低复杂度快但控制低，L-system/WFC 控制高，Agent-based（路网/城市）最贵。→ plan-JSON 的 `generator` 字段按此分类，附 control_level/performance 元数据供编译器做预算决策。

6. **缓存与失效策略学 UE5.8 运行时 PCG**：PCG Subsystem 按 cell 注册组件、生成物打 Cell ID、World Partition 加载/卸载时通知保留或释放；HLOD 用预烘焙代理（远 HLOD / 中低密度运行时 / 近完整 graph 三层）。→ 我们的缓存 key 应是 (plan_hash, cell_id, seed)，plan 变更只失效受影响 cell。

■ 三、HDA 参数暴露模式 = 经验库条目的最佳实践（重点转译）

SideFX 官方 + 行业实践总结出五条，直接就是"经验库条目该长什么样"：

1. **参数是"提升(promote)"出来的，不是天生的**：HDA 作者在节点网络里选哪个内部节点属性提升为对外参数（int/float/string/ramp/multiparam/toggle/color/menu/button 等 SideFX 官方支持类型列表）。ramp/multiparam 是灵魂——一根"植被密度随高度变化"的 ramp 曲线比十个魔法数字参数表达力强得多。→ 经验库条目的参数 schema 应支持 ramp/curve 类型和分组。

2. **默认值全隐藏、只暴露精选**（80.lv 教程实操）：创建 HDA 时先把全部参数设 Invisible，再只把要暴露的拖进 root——暴露面是刻意设计的最小集。→ 经验库条目应有 `exposed_params`（精选子集）与 `internal_params`（隐藏但可进阶展开）之分，UI 只显示前者。

3. **双向输入：引擎曲线/网格可以作为 HDA 输入**（SideFX 官方 Input 列表：Static Mesh/Spline/Landscape/Foliage Data Table/Blueprint…）。环境艺术家在引擎里画一条路，地形 HDA 沿路自动让位生成护坡。→ 经验库条目应声明 `inputs`（接受用户草稿：曲线、mask、参考网格），plan 编译器把用户场景里的 sketch 对象解析为算子输入，"宿主输入→规则→宿主输出"闭环。

4. **实例化输出 + 属性携带**：HDA 输出 instancer 点云时每个点携带属性（unreal_attrobute 约定）映射到宿主的材质选择/LOD 标记（腾讯团队甚至用 JSON/DataTable 描述植被实体参数）。→ 我们的 plan 段落输出应规范"点属性 schema"约定，让下游节点与渲染层可解析。

5. **文档即参数**：HDA 有 Help tab 强制作者用 wiki 标记写参数说明。→ 经验库条目每个参数必须带 description + 合理 range + 示例值，无文档的条目不入库。

■ 四、反直觉/打脸

1. **PCG 分块不是为并行，是为增量编辑**——多数人第一直觉是"分块=多线程加速"，实际 Epic 文档的设计动机是局部重算（spline 挪一下只脏一个 cell）。这直接打脸"编译全量执行"的朴素设计。

2. **runtime 生成是例外不是默认**：大家以为程序化=运行时生成，实际工业界（StraySpark 生产总结、FC5）默认 bake-time 全部冻成静态资产，runtime 只用于需要运行时变化的区域；bake 后编辑器里还能手改，程序化反而失去了"永生 editable"特权。

3. **"改结果"是反模式**：Houdini Engine 输出在 Maya/UE 里手改顶点，下次 cook 静默覆盖。反直觉在于用户以为拿到的是普通模型——我们的 AI 控制台若允许用户在生成结果上直接刷子编辑而不回写 plan，就会复刻这个坑（要么锁定，要么编辑自动转化为 plan override）。

4. **HDA 版本更新默认"静默升级"而非显式迁移**：SideFX 机制是 internal name 自带版本号（如 acme::explodo::1.0），新旧版本可同时安装，参数面板默认优先最新定义；对核心资产改动"即使在制作后期也会更新所有实例"（SideFX 管线文档原话）。也就是说工业界靠"重 cook 语义 + 可回退的多版本共存"解决兼容，没有复杂的 per-instance 参数迁移向导——新参数用默认值，被删参数静默丢弃。我们的 VersionedParams 不必过度设计：plan_hash + 经验库条目多版本共存 + recompile 即可，重要的是"可回退"而非"自动迁移"。【未核实：参数级 migration mapping 是否有官方 API，官方 versioning 文档页 404 未取到】

■ 五、链接
1. SideFX 官方 Houdini Engine for Unreal 介绍（cook/rebuild/bake 定义、输入输出类型）：https://www.sidefx.com/docs/houdini/unreal/intro.html
2. SideFX 官方 Creating and versioning digital assets（internal name 含 namespace::version）：https://www.sidefx.com/docs/houdini/assets/create.html
3. SideFX 官方 Increase Asset Version 对话框：https://www.sidefx.com/docs/houdini/ref/windows/increase_asset_version.html
4. Epic 官方 PCG Generation Modes（Partitioned/Hierarchical/Runtime/Unbounded grid）：https://dev.epicgames.com/documentation/unreal-engine/using-pcg-generation-modes-in-unreal-engine
5. GDC 2018 Far Cry 5 Procedural World Generation 笔记（biome recipe/确定性/夜间重建/POI）：https://tools.engineer/gdc2018-procedural-world-generation-of-far-cry-5
6. UE5 PCG 框架深度剖析（DAG/PCGPoint 数据流/增量更新）：https://www.2ds.cn/ue5-pcg框架深度剖析：从houdini式思维到程序化生成的数学本质
7. 腾讯游戏学院：过程化技术助力开放世界场景制作（自研 Houdini 植被插件/点云分层/权重层唯一性）：https://gameinstitute.qq.com/course/detail/10200
8. Houdini 驱动的 UE4 植被系统管线（Input/Output 规范、mask 禁摆区）：https://www.cnblogs.com/TracePlus/p/9239120.html
9. UE5.8 Runtime PCG 异步生成实战（Cell ID/边界采样/HLOD 预烘焙）：https://www.ixueyouxi.com/2026/07/15/ue58-runtime-pcg-async
10. 程序化生成算法对照（L-system/WFC/BSP/Agent-based 复杂度与控制力表）：https://generalistprogrammer.com/procedural-generation-games

（备注：UE 5.6→5.7/5.8 的 PCG 演进点——确定性执行排序变更、GPU Overrides、Blueprint Subgraph 提速、Level Instance 目标、Is Partitioned 原生 cell 感知——来自二手生产博客，方向可信但以 Epic 官方 release note 为准。）