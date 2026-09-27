# [5 组] 图检索 / GraphRAG / 结构化混合检索 / 代码检索 / embedding 版本漂移

- 原始记录：`agent-9ebed2798008420a.jsonl`（991 KB）
- 报告来源：SendMessage 完整报告 ｜ 正文 5514 字符

---

# 第5组：图检索 / GraphRAG / 结构化混合检索 / 代码检索 / embedding 漂移

## 一、里程碑与现状

1. **Microsoft GraphRAG（2024）**：LLM 抽实体关系 → Leiden 社区检测 → 逐社区 LLM 摘要。官方实测：100 万 token 播客语料用 GPT-4-turbo 索引 281 分钟；实体/关系抽取约占索引成本 75%，社区检测走 graspologic 本地计算，成本可忽略。
2. **LazyGraphRAG（2024.11）**：把 LLM 全推到查询期。索引用 NLP 名词短语 + 共现图 + Leiden，零 LLM 调用，索引成本≈纯向量 RAG、为 full GraphRAG 的 0.1%。5590 篇 AP 新闻/100 查询上，Z500 配置在 local 与 global 两类查询上均胜过 8 个对照（含向量 RAG、RAPTOR、GraphRAG global、DRIFT），查询成本仅为 GraphRAG global 的 4%。方法论价值大于方法本身：**能推迟的 LLM 调用就推迟**。
3. **LightRAG（HKUDS, arXiv:2410.05779, EMNLP 2025 Findings）**：砍掉社区检测与社区摘要，只留实体/关系双向量索引（低层实体 + 高层主题），支持增量插入。代价是丢掉"可复用的社区报告"这个产物。
4. **HippoRAG（NeurIPS 2024）/ HippoRAG 2（ICML 2025）**：OpenIE 三元组建无模式图 + 同义边（cosine>0.8）+ 个性化 PageRank + node specificity（图原生 IDF）。2WikiMultiHopQA R@5 从 ColBERTv2 的 68.2 提到 89.1；MuSiQue 仅 49.2→51.9，**HotpotQA 反而退步（60.5 vs 64.7）**。对"这个倒角在哪个基元上"这类 path-finding 最有效，两跳内可解的不如向量。
5. **确定性图 vs LLM 抽取的正面对决（arXiv:2601.08773, 2026.1）**：Java 仓库三路对比——纯向量 / LLM-KB / Tree-sitter AST 派生图 DKB。结论：DKB 秒级建图；LLM-KB 慢得多且**在 Shopizer 上漏掉 377 个文件**（索引覆盖不全）；正确性 DKB 最高、LLM-KB 紧随、纯向量最差且幻觉风险最高。
6. **SAP（arXiv:2507.03226, CIKM 2025）**：完全不用 LLM，用工业级依存句法建图做企业 GraphRAG，达到 LLM 建图 94% 的效果（61.87% vs 65.83%），legacy code migration 场景比传统 RAG 高 15%（LLM-as-Judge）。

## 二、已解决的问题（可直接抄）

1. **图骨架用确定性解析，语义标注才用 LLM**（证据即 2601.08773 与 SAP 那篇）。我们比普通代码仓库更占便宜：bpy 调用是显式 op 序列，RNA 反射能拿到参数签名/默认值/单位，拓扑指纹可从几何算——这是运行时真值，不是静态猜测。**架构上 X（LLM 抽关系）改成 Y（AST/RNA 建边，LLM 只写节点属性 intent / semantic_tag / failure_mode）**。
2. **代码检索必须双通道**。纯 embedding 会丢结构信息（SYNC, IJCNLP 2023：CodeBERT 类模型检索出错误的数据类型与方法签名）。改为：结构化侧按 `op_name + 参数维度 + 前置拓扑指纹` 精确匹配，向量侧只做语义兜底。
3. **参数反查的成熟答案在 CAD：特征树 + 命名参数 + 设计表 + 参数分层**（L0 顶层/L1 部件/L2 零件/L3 特征，上层用表达式驱动下层）。翻译成我们的 schema：每个步骤节点存 `params: {radius: 0.05}` 具名数值属性，参数反查退化为"按参数名+值域过滤"，不需要 embedding 里存在"粗细"这个语义维度。
4. **增量更新用哈希差分**：对源文件/操作块做 SHA-256，只对变更部分重跑索引（ByteBell 开源方案即如此），避开 GraphRAG 那种"新文档进来→社区重划→摘要失效"的级联。
5. **embedding 是版本化的 schema，不是函数**：每条向量记 `{model_id, revision, chunking_policy, preprocess_version}`，缓存 key 也带上。换模型走 blue-green：新 collection 并行建 → 双写 → 影子流量 → 灰度切流 → 保留旧索引到回滚窗口结束。

## 三、已知的坑 / 反直觉发现

1. **图库内置向量索引明显弱于专用向量库**。TigerVector（SIGMOD-Companion 2025）实测 SIFT100M：Neo4j 召回 67.50%/208 QPS，TigerVector 90.94%/1079 QPS（5.19× QPS、+23% recall）。KTH 2025 毕业论文同样得出 FAISS+Neo4j 在准确率/延迟/可扩展性上均优于 Neo4j 内置向量。→ 别指望 Neo4j 顺手把向量做了。
2. **过滤是向量搜索的阿喀琉斯之踵**。post-filter 在高选择性下会**静默返回少于 top_k 甚至 0 条**；top-10 + 1% 选择性实际等于 top-1000 查询。Weaviate 默认 post-filter（可请求 pre-filter/ACORN）；Qdrant 的 payload-aware HNSW 在 5% 选择性下 QPS 仅掉 20%，Weaviate/Milvus 掉 40–60%。**我们的"参数值域过滤"正好落在 1–20% 选择性这个最痛区间，必须先 oversample（top_k≥100）再过滤。**
3. **噪声实体在图里被放大，比在向量库里更致命**：向量库里一个坏 chunk 只是多一条无关结果，图里一个错实体会造出假连接并沿遍历污染。HippoRAG 消融还显示换 Llama-3-70B 做 OpenIE 反而因格式错误变差，8B 却与 GPT-3.5-turbo 相当——"更大的模型"在图构建上不成立。
4. **RAGAS 无参考指标在某些数据集上上下文相关性准确率仅 15–36%**（ARES 论文对比，ARES 稳定在 67–92%）。别把 RAGAS 分数当验收金标准，自建 golden set：50–100 条真实查询，标注"应召回第几步操作"。
5. **CAD 的经典反模式会原样复现**：直接以模型边线作后续特征参考，倒角顺序一变边线 ID 就变、特征重建失败。Blender 里按 bpy 顶点/面索引选择完全同构——**必须给拓扑元素持久命名（或几何指纹哈希），不能裸存 index。**
6. （单一来源，**未核实**）有研究主张换模型不必立即全量重嵌：先以 ~1% 配对样本拟合 Procrustes/低秩对齐可恢复新模型 95–99% 质量。主流共识仍是旧新向量绝不能混在同一个 collection。

## 四、对本项目的建议

**(a) 判断对，但要改成"骨架确定性 + 属性 LLM"。** AST/RNA 建边是 100% 确定的、零 LLM 成本、零抽取漏项（不会发生 LLM-KB 漏 377 文件那种事）。**反过来用 LLM 的条件只有两个**：① 需要节点上"这一步想干什么/为什么失败"这类语义标签（AST 给不了，GraphCodeBERT 类模型也答不了业务语言问题）；② 用户用自然语言描述需求需先映射到 op 名（做 query 侧，不是 index 侧）。**绝不要让 LLM 抽关系边。**

**(b) 有现成做法可抄：CAD 特征树 + 设计表。** 落地三件事：① 参数具名化（不存 `args[0]=0.05`，存 `radius=0.05` + 单位 + 取值域）；② 参数反查走"结构化过滤 → 语义重排"两阶段，别指望 dense 向量编码"粗细"；③ 给每个基元算几何指纹（可借鉴形状检索：FPFH/SHOT 手工描述子、PointNet/DGCNN 学习特征；Scan2CAD 上学习特征 top-1 检索 0.68 vs FPFH 0.14），把"长得像"做成独立检索通道，这正对应"同一个挤出在立方体和圆柱上意义不同"所需的**前置拓扑指纹**。

**(c) 双库保留，但理由要换。** 不是"图+向量天然要两个库"，而是图库自带向量索引确实弱（Neo4j 67.5% vs 90.9% recall）+ 过滤检索在 1–20% 选择性是性能陷阱，而 Weaviate 原生 BM25/RRF 与 bge-m3 的 dense+sparse+multi-vector 三路融合开箱可用。职责划清：**Neo4j = 时序 DAG、依赖/影响分析（改这个尺寸影响哪些下游步骤 = 反向可达集查询）；Weaviate = 语义+词汇混合召回 + 参数范围过滤 + 几何指纹向量。** 判断依据：若数据量降到十万级以下且过滤选择性 >30%，可退成 Neo4j 单库 + 应用层 BM25；但在"参数反查"这种高选择性过滤为主的负载下，双库划算。

**补充两条工程约束**：① bge-m3 一次前向同时产出 dense/sparse/colbert 三路（官方 `s_rank = w1·s_dense + w2·s_lex + w3·s_mul`），sparse 那一路对 `bpy.ops.mesh.bevel` 这类精确 token 命中极关键，别浪费；② 索引 schema 给每个 op 节点留 `model_version` 字段，并始终把"操作序列原文"保留为可重嵌的 canonical source，别只存向量。

## 五、关键文献 / 工具

1. Microsoft GraphRAG（2024）github.com/microsoft/graphrag ；LazyGraphRAG 官方博客（2024.11）
2. LightRAG — arXiv:2410.05779（EMNLP 2025 Findings），代码 HKUDS/LightRAG
3. HippoRAG — arXiv:2405.14831（NeurIPS 2024）；HippoRAG 2（ICML 2025）
4. **Reliable Graph-RAG for Codebases: AST-Derived Graphs vs LLM-Extracted Knowledge Graphs — arXiv:2601.08773（2026.1）** ← 已在 arxiv.org/abs/2601.08773 核实，直接验证我们的核心判断
5. Efficient KG Construction and Retrieval from Unstructured Text（SAP, CIKM 2025）— arXiv:2507.03226
6. TigerVector（SIGMOD-Companion 2025）cs.purdue.edu/homes/csjgwang/pubs/SIGMOD25_TigerVector.pdf ← 图库向量性能硬数据
7. BGE-M3（BAAI 2024）huggingface.co/BAAI/bge-m3 —— dense/sparse/multi-vector 三头一体，8192 token
8. SYNC（IJCNLP 2023）aclanthology.org/2023.ijcnlp-main.7.pdf —— 纯 embedding 代码检索失效机理
9. Joint Embedding of 3D Scan and CAD Objects（arXiv:1908.06989）—— 形状描述子检索基线对比（FPFH 0.14 / PointNet 0.49 / 学习特征 0.68）
10. Embedding 版本漂移实践：nalar.dev/version-embeddings-for-safe-semantic-search ；mixpeek.com/glossary/embedding-versioning

---
给其他组的交叉提示：
- 第1组（参数化建模/CAD特征树）：本文第三节第5条"边线 ID 反模式"与第二节第3条"参数分层 L0-L3"直接可用，建议他们重点展开。
- 第2组（撤销/重做/事件溯源）：我们的"操作序列 canonical source 必须保留、不能只存向量"与他们的事件日志设计是同一份数据，建议统一为一份 append-only 日志，向量/图都是它的物化视图。


---

## 附：派单 prompt 原文

<teammate-message teammate_id="team-lead" summary="Initial task assignment for general-purpose-5">
你是跨学科预调研的第 5 组，负责【图检索 / GraphRAG / 结构化混合检索 / 代码检索 / embedding 版本漂移】这条线。

【项目背景 — 必读】
我们在设计「Blender AI 建模控制台」：LLM 通过 MCP 驱动 Blender 做 3D 建模。需要把每一步建模操作存起来供后续检索复用。
关键特殊性（这是我们要你重点攻的问题）：
- 数据主体是 **bpy.ops 结构化代码**，不是自然语言文本
- 需要支持「参数反查」：人说"把手太粗"，向量库里没有"粗细"这个语义维度，需要按参数维度+取值范围检索
- 需要支持「关系查询」：这个倒角是在哪个基元上做的？哪一步引入了这个破面？改这个尺寸会影响哪些下游步骤？
- 上下文强依赖：同一个"挤出"在立方体和圆柱上意义完全不同，需要前置拓扑指纹
- 时序依赖：操作有严格前序关系
技术栈已有：Weaviate、Neo4j、llama.cpp（本地 bge-m3 / Qwen3-Embedding GGUF）、blender-mcp。
我们的初步判断是：图的部分应该直接 parse AST / 读 Blender RNA 反射来建（确定性、零 LLM 成本），而不是像 LightRAG 那样让 LLM 从文本抽实体关系。请你验证或反驳这个判断。

【你的调研任务】
必查方向（用 WebSearch 核实，不要凭记忆编造，优先 2024-2026）：
- Microsoft 的 GraphRAG（2024）、LazyGraphRAG，以及 community detection / 分层摘要的做法与成本
- LightRAG（2024-2025，港大）的双层检索 + 增量更新，实测成本对比
- 其他结构化 RAG：StructRAG、KGGen、RAPTOR（树状摘要）、HippoRAG（受海马体启发的 PPR 索引）
- 混合检索：BM25 + 向量的融合（RRF reciprocal rank fusion）、late interaction（ColBERT / ColPali）在多模态/代码上的表现
- 代码检索：CodeSearchNet、CoNaLa、以及 embedding 模型在代码上的表现；为什么纯 embedding 代码检索差；AST 感知的检索（如 GraphCodeBERT、UniXcoder）
- 参数化/结构化过滤检索：向量 + 元数据过滤（如 Weaviate/Qdrant 的 pre-filter vs post-filter）的性能陷阱
- Embedding 版本漂移：换模型/换切分策略后旧索引失效，业界怎么做索引迁移与回滚（有没有成熟方案）
- 3D 形状检索 / 几何检索：ShapeNet、3D 形状描述子（如 FPFH、PointNet 特征）与「按几何相似度找模型」的成熟做法 —— 这对"参数反查"有启发
- RAG 评估：RAGAS / ARES 等指标，以及检索命中率的实测基线

【输出格式】中文，1000-1400 字，密集具体：
1. 里程碑/现状 4-6 条：名称/年份 + 核心机制 + 与本项目关联
2. 已解决的问题（可直接抄）：3-5 条，每条具体到「我们架构里 X 应该改成 Y」
3. 已知的坑 / 反直觉发现：3-5 条（必须有实测数据或明确的工程结论）
4. 对本项目的具体建议：3-5 条。特别回答：
   (a) 我们的「图从 AST 直接建 vs LLM 抽取」判断对不对？在什么条件下应该反过来？
   (b) "参数反查"（人说粗细/大小，库里按参数维度找）业界有没有现成做法可抄？
   (c) Weaviate + Neo4j 双库是否必要，还是单一图库（如 Neo4j 向量索引）就够？给出判断依据
5. 关键文献/工具/链接 5-8 条（WebSearch 核实过、真实存在）

铁律：查不到证据的说法标注「未核实」。绝不编造论文名、指标数字或 URL。
</teammate-message>