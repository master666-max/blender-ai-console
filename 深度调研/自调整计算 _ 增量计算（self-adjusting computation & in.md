# 自调整计算 / 增量计算（self-adjusting computation & incremental computation）

- 原始记录：`agent-452cdc41bd66438b.jsonl`

---

【调研报告：自调整计算 / 增量计算】（已用 WebSearch 核实，未核实处已标注）

一、里程碑成果
1. Self-Adjusting Computation（Umut Acar，CMU 博士论文 CMU-CS-05-129，2005）：程序运行时自动构建动态依赖图（DDG），输入变更后由 change propagation 算法只重放受影响的子计算；依赖追踪开销 O(1)，用 trace stability 分析证明多个应用（凸包、排序、树收缩）的更新复杂度接近专用动态算法最优界。→ 这是"局部重算"的正规理论，直接对应你们最痛的 GN 全量重算问题。
2. 一致性语义（Acar/Blume/Donham，ESOP 2007）：change propagation + memoization 组合的形式语义，用 Twelf 机器证明 from-scratch 一致性。→ 保证增量结果 = 全量重跑结果，回退层可以放心用。
3. Adapton（Hammer 等，PLDI 2014）：改为需求驱动（demand-driven）的 Demanded Computation Graph（DCG），只有被 demand 的计算才传播变更；Rust 实现（adapton crate）避免 GC 对增量系统的拖累。→ "按需失效"优于"急切传播"。
4. Incremental Computation with Names（Hammer 等，OOPSLA 2015）：一等"名字"做 nominal memoization，程序员控制跨运行复用的粒度，实测比 Adapton 和全量重算都有大幅加速（具体倍数随负载，原文有 benchmark，未核实具体数字）。
5. Salsa / rustc 红绿算法（rust-analyzer、Ruff、Turbopack 在用）：全局 revision 计数器 + 每个查询记录 last_changed/last_verified revision；重执行后若输出未变则 backdate（标绿），阻断级联失效。这是工业界最成熟的可抄方案。
6. Jane Street Incremental（OCaml，生产级）：v0.17 文档给出硬数字——每节点 ~216 字节、触发 50–150ns；配套 cutoff（phys_equal/set_cutoff）控制传播。

二、已解决的问题（可直接抄）
1. 失效判定用 revision 号而非全图重染：Salsa 每个结果存 R_changed/R_verified 两个整数，检查 O(1)。→ 你们"状态层快照"应升级为"每个 modifier 存 (参数指纹, 输出 hash, revision)"，而不是整场景快照。
2. backdating 截断级联：重执行后发现输出与上次相同 → 标绿，下游不失效。→ 你们 L3"重推下游"应改为"重推+比对，结果不变即停"，避免语义未变也重推。
3. durability 分层：rustc 把 crates.io 输入标高耐久、工作区标低耐久，变更检查按耐久档 O(1) 跳过。→ 你们的基础 mesh/材质/静态资源应标高耐久，AI 迭代参数标低。
4. restat 机制（Ninja）：命令重跑后 re-stat 输出，mtime 未变就不向下游传播失效。→ 等价于你们的"modifier 重算后输出 hash 未变则不触发下游"，验证了这是构建系统级别的成熟做法。
5. 参数离散化保缓存命中（CADbuildr，CAD as a Service）：连续 float 是缓存杀手，滑块按视觉可分辨步长离散化；mesh 按 content-hash 复用 BufferGeometry。→ 你们的 GN 具名参数应定义量化步长。

三、坑 / 反直觉发现
1. 增量化没有免费午餐：Jane Street 官方文档明确警告——incrementalization 降低更新代价但抬高从零重算代价和内存，"不要 incrementalize 一切"；且节点数按 O(N) 膨胀（~216B/节点）。rust-analyzer 100K LOC 规模下查询缓存 200–400MB + 依赖图 100–200MB（第三方分析数据，未在官方文档核实）。
2. "改了但结果没变"必须执行一次才能发现（backdating 的代价），hash/等价比较函数（cutoff）设计直接决定收益；返回整值包装会 defeat cutoff（Jane Street 反模式）。
3. 异常会炸掉整个增量世界：Jane Street stabilize 期间用户函数抛异常后系统永久不可用。→ 你们的编译/重推函数必须纯函数化、可重入。
4. 持久化依赖图会积累过时边：Ninja deps log 在构建计划变更后产生 stale edges，Fuchsia 文档承认无法检测，只能 clean build。→ 你们改"编译器本身"（计划→GN 编译逻辑）后，旧指纹/依赖必须整体作废。
5. Acar 理论的 O(1) 追踪开销是摊还意义上的，常数因子不小时（如 GC、对象分配）反而可能拖慢——Adapton 换 Rust 的动机之一就是 GC 问题。

四、对本项目的建议
(a) 理论支持吗？支持，但切分粒度受 Blender 黑盒限制。自调整计算要求依赖可追踪，而 Blender GN 求值对 Python 是黑盒，GN 内部节点级脏标记不暴露（未核实 Blender depsgraph 是否可利用）。所以最小失效单位应定在 **modifier（= opinion 层）**，不是 GN 内部节点、更不是参数：每个 modifier 编译为 Salsa 式 tracked query，输入=具名参数集，输出=GN 结果 hash。参数→modifier 的依赖边由你们编译器**静态生成**（你们本来就产出显式 DAG），比 Salsa 运行时动态追踪还便宜——这是你们相对通用增量系统的天然优势。
(b) 成本拐点：无几何领域公开实测数据（未核实）。可用的经验锚点：Jane Street 单节点维护 ~216B + 50–150ns/次触发，意味着依赖图维护比一次 GN modifier 求值（毫秒级）便宜 4 个数量级以上，维护成本几乎不会成为瓶颈；真正的拐点在"失效比例"——rust-analyzer 1% 改动时增量 1.2s vs 全量 12–20s（10–20×收益），但当改动波及大部分图时增量优势消失且内存代价还在。建议：失效 modifier 数 > 总数约 40%（经验阈值，需自测标定）时直接放弃增量走全量（bpy.ops 346ms 或 L3 50ms 都可接受）。
1. 三层回退映射：L1=失效标记、L2=snapshot memoization、L3=change propagation——你们的架构与 SAC 理论惊人同构，缺的只是红绿算法的 backdating 和 revision 判定，补上即可把 L3 从"重推下游"变成"重推+比对+截断"。
2. 输出 hash 粒度：modifier 输出 mesh 做（近似）hash 可用 LOD 降采样顶点做指纹，避免全 mesh hash 本身成为瓶颈（具体方案未核实有现成实现）。
3. 立刻可做实验：用 Blender 实测"重算单个 modifier + hash 比对"的耗时 vs 你们 L3 的 50ms，确定按 modifier 切分是否已把收益吃满。

五、关键文献/工具（均已核实存在）
1. Acar 博士论文 Self-Adjusting Computation：http://reports-archive.adm.cs.cmu.edu/anon/2005/abstracts/05-129.html
2. Adapton: Composable, Demand-Driven Incremental Computation（PLDI 2014）：http://plum-umd.github.io/adapton
3. Incremental Computation with Names（OOPSLA 2015）：https://arxiv.org/abs/1503.07792
4. Salsa 红绿算法官方文档：http://salsa-rs.netlify.app/reference/algorithm
5. Jane Street Incremental（OCaml 生产库）：https://github.com/janestreet/incremental
6. Adapton Rust 实现：https://github.com/Adapton/adapton.rust（crates.io: adapton）
7. Ninja 手册（restat/depfile 机制）：https://ninja-build.org/manual.html
8. A Consistent Semantics of Self-Adjusting Computation（ESOP 2007）：https://arxiv.org/abs/1106.0478