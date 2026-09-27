# 3D 语义版本控制 / 资产 diff / merge

- 原始记录：`agent-79c5370a7aae42b7.jsonl`

---

【3D 语义版本控制 / 资产 diff / merge — 深度调研】

一、研究与工具（6 条）

1. **SceneGit**（Carra & Pellacini，SIGGRAPH Asia 2019 / ACM TOG 38(6)，Sapienza）——目前最接近"3D Git"的系统。关键设计：① 按场景对象**最细粒度**版本化（shape/material/texture/animation 各自独立 commit），使仓库变小、允许多人同时改同一对象的不同资产；② 承认"最优 diff 不可计算"，用**应用无关的启发式**求变更集（基于图匹配/Bunke 最大公共子图思路）；③ 用户的 user study 证实有效。**diff 粒度是对象/资产级，几何本体被视为不透明 blob**——它不做"顶点改了哪个特征"的语义 diff。成熟度：论文原型，无维护中的开源实现。
2. **cSculpt**（Calabrese/Salvati/Tarini/Pellacini，TOG 2016）——罕见的**真·几何三方合并**：在协作雕刻场景下，把两个用户对同一 mesh 的编辑在体素空间分区后合并，同时支持几何与外观修改。局限：仅适用于雕刻类连续变形操作，不适用拓扑修改/建模操作。
3. **NodeGit**（Rinaldi/Sforza/Pellacini，TOG 2023）——diff/merge **程序化节点图**（Houdini/Blender 类 procedural graph），自称唯一能可靠识别"用户真实编辑"的算法。对我们的 FlowDAG 是最直接的同构参考。成熟度：论文。
4. **USD（Pixar/OpenUSD）**——生产界事实标准。核心哲学：**不合并数据，而是用 layer stack 避免冲突**——每人只写自己的 layer（opinion），合成时按 layer 强弱顺序解析，冲突预先被"layer 优先级"这一策略吸收。工具面：`usdstitch`（按时间片聚合，非语义 merge）、`.usda` 文本可直接 git diff；但**没有官方三方 merge 工具**。Pixar 2022《Schema Versioning in USD》白皮书明确承认：composition 使"某 prim 是什么版本"这个问题本身不可回答——schema 级版本控制仍未解决。成熟度：工业级（layer 模型），版本控制语义（低）。
5. **Onshape 分支合并**（唯一把 branch/merge 做进云 CAD 的产品）——机制与 Git 相差甚远：merge 是**有方向的覆盖**（Source 覆盖 Target），**没有三方合并、没有 rebase**。冲突规则：新增/删除（特征、零件、约束）双方都保留；**双方都改了同一 feature/sketch → Source 整体赢**；合并产生的新特征可能几何非法 → 仍合并但标红"待人工修复"，不自动回退。配套 Compare 工具 = 几何红绿可视化 + feature 列表 diff。社区结论：两边都动同一 sketch 的 merge 会静默丢失修改，实操准则是"一分支独占修改，短分支快合"。
6. **glTF 生态**——Khronos **没有任何版本控制 extension**（已核对 extension registry：KHR_* 全部是材质/压缩/交互类）。glTF 定位是传输格式，GLB 二进制对 git diff 完全不透明。实践方案是外挂：**Git LFS + 文件锁**（Anchorpoint：面向 Blender/UE/Unity 的 Git 客户端，自动 LFS、秒级文件锁、缩略图预览、元数据层不碰生产文件；另有 Unity 商店里的 SceneGit 插件做 GameObject 级快照 + 三方语义 merge）。成熟度：工程可用但停留在"文件级+锁"，无语义 diff。

二、网格语义 diff（问题①②）

学术上"语义 diff"的正确框架是 **functional maps**（Ovsjanikov et al., SIGGRAPH 2012）：把 shape 间对应关系表示为谱基（Laplace-Beltrami 特征函数）上的线性算子 C，其杀手锏是**映射可做代数运算（和/差/复合）**——两个版本的"差异"可以是一个矩阵减法，再配合 part-aware 分割把差异定位到"椅腿变细"这种部件级语义。但**没有发现把 functional maps 直接用于版本 diff/merge 的系统**（查不到即标注：该方向是空白）。现有的 MeshDiff 类工具全是几何级（体素占据红绿图/最近点距离），且都要求对齐、闭合流形、容差手调——"语义等价"判定在文献里同样没有公认解。语言侧倒有现成资产：**ShapeTalk**（CVPR 2023，53.6 万条判别式语句，专门描述两个 3D 形状的差异，80% 引用部件名）可当 diff→语言的语料/评测集。

三、"改了什么"的可读摘要（问题④）

**未发现 "NLG for 3D changelog" 的直接研究**——这是真空地带。最接近的是反向任务：ChangeIt3D/LADIS（语言→编辑）。可行路线：用你们的 **verifier 谓词当变更分类器**（面积差→"变矮/变薄"、包围盒差→"变宽"、拓扑差→"开洞"），谓词向量差作为结构化 changelog，再用 LLM+ShapeTalk 风格模板转自然语言。这个组合没有先例，反而是可发论文的创新点。

四、设计转译（落到我们的架构）

1. **SegmentCommits 增加 `predicates` 字段**：每个 commit 附 verifier 谓词向量（体积/包围盒/部件计数/对称性…）。语义等价判定 = 谓词向量在容差内相等，**不做几何精确比较**；等价类的 hash 可作 `semantic_id`。
2. **diff_kind 三级标注**：`transform`（只动变换）/`param`（参数/属性变）/`topology`（几何本体变）。transform/param 级 diff 存结构化编辑操作，topology 级直接换 content-addressed blob——与 SceneGit "几何当 blob" 的结论一致，不要试图 diff 顶点。
3. **merge 策略学 USD 不学 Git**：给每个 segment 引入 **override 层（opinion 列表）**，merge = 按确定性优先级叠 opinion，而不是改 base 几何。同一 segment 双方都改 → 不做几何三方合并，走 Onshape 模式：**声明性胜出 + 标记 `conflict` 待人工**；不同 segment 自动合并。
4. **合并后强制过 verifier**：吸收 Onshape "合并产物可能非法仍入库但标红" 的教训——合并 commit 先置 `unverified` 状态，跑一遍红绿校验通过才转正（与 RevisionTable 红绿失效天然契合）。
5. **glTF/USD 导出物当作 derived artifact**：内容寻址 + 记录源 commit 指针，只重新生成、从不 merge 导出物（USDZ 本来就是"扁平交付视图"的定位）。
6. **changelog 管线**：谓词 diff → 变更类型枚举（变矮/加宽/开洞/换材质…）→ LLM 生成口语摘要 → 用 ShapeTalk 子集做人评基准。

五、反直觉/打脸

1. SceneGit 的成功恰恰来自**放弃语义 diff**：对象级原子 commit + 启发式，user study 就够用——"语义级 diff"可能是伪需求，粒度选对比算法选对更重要。
2. Onshape 号称 "GitHub-style" 但**没有三方合并**，方向性覆盖 + 静默丢修改是用户最大槽点——CAD 圈也没解决 TNP，我们不必指望抄到现成答案。
3. USD 用"预先约定 layer 优先级"把合并问题**消解**而非解决——说明 3D 合并的最佳实践是流程设计，不是算法。
4. "3D Git" 提出 7 年无工业落地，而"文件锁 + LFS"的笨办法撑起了所有游戏工作室——二进制资产的现实约束压倒学术理想。

六、可直接抄的策略

1. 谓词向量等价类替代几何精确等价（成本 O(谓词数)，可增量更新）。
2. diff 三级分类：transform/param 存操作，topology 存 blob hash。
3. opinion 层叠 merge + 同段冲突显式标记，杜绝静默覆盖。
4. merge 产物强制 verifier 门禁（unverified→verified 两态）。
5. 导出格式（glTF/USDZ/OBJ）一律 derived+再生，不入 merge 图。

七、文献/链接

1. SceneGit: a practical system for diffing and merging 3D environments, SIGGRAPH Asia 2019. https://research.uniroma1.it/node/53880
2. cSculpt: a system for collaborative sculpting, ACM TOG 35(4), 2016.
3. NodeGit: Diffing and Merging Node Graphs, ACM TOG, 2023.
4. Functional Maps: A Flexible Representation of Maps Between Shapes, SIGGRAPH 2012. https://people.csail.mit.edu/jsolomon/assets/fmaps.pdf
5. Schema Versioning in USD (whitepaper), Pixar 2022. https://github.com/Unity-Technologies/OpenUSD/blob/main/docs/wp_schema_versioning.rst
6. USD Toolset（usdstitch）: https://graphics.pixar.com/usd/release/toolset.html
7. Onshape 合并规则官方 Tech Tip: https://www.onshape.com/en/resource-center/tech-tips/tech-tip-a-guide-to-successful-merging-in-onshape ；分支实践讨论: https://forum.onshape.com/discussion/comment/28305
8. ShapeTalk / ChangeIt3D, CVPR 2023. https://changeit3d.github.io/
9. LADIS: Language Disentanglement for 3D Shape Editing. https://arxiv.org/abs/2212.05011
10. Anchorpoint（Blender/UE 的 Git 工作流）: https://www.anchorpoint.app/tools/blender-version-control
11. Dobos & Steed, 3D Revision Control Framework, 3DTV-CON 2012.
12. Rawlings & Papanikolaou, openNURBS 的 diff/patch/merge 高层设计, IJAC 2023.

【未核实】Fusion 360 的具体 branch/merge 语义（本轮检索未命中其官方冲突处理文档）；functional maps 用于版本 diff 的系统级实现（疑为空白）。