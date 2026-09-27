# [1 组] 参数化建模 / 程序化生成 / CAD 特征树

- 原始记录：`agent-672c9df5d509470d.jsonl`（882 KB）
- 报告来源：SendMessage 完整报告 ｜ 正文 5288 字符

---

# 第1组：参数化建模 / 程序化生成 / CAD 特征树

## 一、里程碑成果（6条）

1. **Shape Grammar**（Stiny & Gips 1972；《Introduction to Shape and Shape Grammars》1980）：规则 α→β 直接作用于**形状**而非字符串，从初始形状迭代派生。→ 经验的原子单位应是"规则"，不是"成品网格"。
2. **L-system → CityEngine**（Lindenmayer 1968；Parish & Müller《Procedural Modeling of Cities》SIGGRAPH 2001）：用**扩展 L-system**（全局目标+局部约束）以极小规则集生成整城，核心收益是 *database amplification*。→ ExperienceLibrary 只存规则+参数，不存结果。
3. **Split Grammar / CGA Shape**（Instant Architecture, Wonka et al. 2003；CGA shape 2006）：split 命令把形状递归分解为子形状，并让规则与可视操纵器绑定，实现"规则可复用 + 参数化变体"。→ 我们 FlowAxis 的"语义段落折叠"本质是 split 的层次。
4. **Siemens Synchronous Technology（2008）**：feature-based 但 **history-free**；Live Rules 实时发现并自动维持"强约束"（共面/相切/同心/对称），编辑只做**局部重算**而非全历史重放。白皮书实测：改一个圆角半径，历史系统全量重生成约 60 秒 → 同步技术 2 秒。→ 这是"回退成本"问题的工业级答案。
5. **Grasshopper**（David Rutten / McNeel）：Rhino 4 曾内置**隐式历史**——因历史树对用户隐藏、阶段属性无法调整、改一下 Loft 就断掉下游历史而被弃用；Grasshopper 改为**让用户显式搭出历史树**。两条铁律：canvas 永远处于已求解状态（改上游只重算下游）；**数据流单向、禁止回环**，这正是它可预测重算的前提。
6. **OpenUSD**（Pixar 开源；AOUSD 2023）：场景 = 层栈而非文件；override/variant/payload/reference 五种合成弧，冲突由 **LIVRPS 强度序**裁决（Local > Inherits > Variants > References > Payloads > Specializes），底层永不改写。

## 二、已解决的问题（可直接抄）

1. **FlowAxis 必须从"线性操作日志"改成"显式 DAG + 段落层级"，并硬性禁止回环。** Rhino 4 隐式历史的失败已证明：隐式 = 不可回退；Grasshopper 证明：显式 + 无环 = 可预测重算。
2. **重算粒度改成"局部 invalidate"而非"全量重放"。** 抄 Synchronous 的局部重算 + Live Rules：对"明显不该被破坏的关系"自动保持，把一次意图层回退的爆炸半径限制在下游子图。
3. **三层回退应实现为 opinion 栈，而非快照 diff。** 抄 USD 语义：不删除旧层，只在更强的层写 opinion，由 LIVRPS 式强度序决定谁赢——这天然就是"状态层(基底) / 语义层(GoodPoint opinion) / 意图层(推翻某 Thought 的局部 override)"。
4. **ExperienceLibrary 的经验按 HDA 契约封装**：版本字段 + changelog、仅 promote 少量参数并分组、带 bypass 开关、内部用相对引用、参数名用艺术家语义（"Wall Height" 而非 parm3——LLM 同样靠名字理解）。
5. **bake 时机由 GoodPoint 决定。** Blender 官方手册原话：*"Baking trades flexibility for performance, so it is most useful once a setup is finalized"*。我们的"质量锚点"正好就是这个 finalized 信号，用它触发 Houdini 式 File Cache / GN bake。

## 三、已知的坑 / 反直觉发现

1. **USD 不是我们的现成答案（对 Blender 而言）。** Blender 4.5 官方手册明写：导入器 *"does not yet handle certain USD composition concepts, such as layers and references"*；导出器 *"does not (yet) support exporting ... USD layers, variants"*。截至 2026-03 的 Pipeline & I/O 例会仍在推进 "Collection Import Stage 1"；Blender Lab 的 **"Core USD Authoring" 项目状态是 "Requires Funding and Stakeholders"，无发布时间表**。→ 想拿 USD layer 做回退，等于自己实现一台合成引擎。
2. **Blender 官方 MCP server 已存在且已 released**（Blender Lab，v1.0.0 于 2026-04-27；需 Blender 5.1+；GPL；官方示例用 llama.cpp 本地跑）。定位是**场景分析/调试/批处理脚本，不是生成艺术**。官方自己公布的翻车案例极具价值：让 LLM 分析 Classroom 场景找"高面数小体积"物体，首轮只统计了影响视口的 modifier，**漏掉 coat_1 上的 Solidify 使渲染面数翻倍**——找对了嫌疑对象，数字算错。→ 这是 Why 层必须外化可争议假设的直接实证。另注意：官方 server 执行模型写的 Python **无任何沙箱**。
3. **参数化历史的最大代价是"非作者不可编辑"。** Siemens 白皮书自己承认：历史树把变更意图埋在父子依赖里，非作者必须 *study and unravel* 约束才能改，且一处改动会引发下游**连续的 update failure**。→ ThoughtGraph 若只记"为什么"而不记"依赖了哪些假设"，意图层回退同样会连锁崩。
4. **规则的涌现与不可判定。** shape grammar 的经典弊病是 emergent behavior（规则组合产出艺术家未预期的结果）；参数化 subshape 识别已被证明 **NP-hard**（YKG09），所有实用系统都靠限制作用域（集合语法、仅 90° 旋转）规避。→ 经验规则不加作用域限制，定位成本会爆炸，直接压低"迭代上限 = min(1/定位成本, 1/回退成本)"。
5. **二进制 diff 至今无解。** .blend 是二进制，标准 Git 看不到内部变化；社区做法（如 Blender Git 插件，Blender 5.x）是每次 stage 把场景快照成 JSON，产出 "Object 'Cube' moved" 这类可读变更，但冲突解决仍是**文件级二选一**。→ 别指望 Git LFS 给语义 diff，状态层快照必须自己维护 JSON。

## 四、对项目的具体建议

1. **FlowAxis 节点 = 参数化特征，不是 bpy 调用序列。** 每条节点自带 seed + 参数集 + 输入引用，保证可重放；边只允许向下游，禁回环。
2. **三层回退用 USD 语义、自研存储。** 语义抄 LIVRPS opinion 栈，底层用 JSON/SQLite 自己实现，不要依赖 Blender USD（2026 年仍然只支持扁平导入导出）。
3. **接 Blender 官方 MCP 做传输层，把 FlowAxis/ThoughtGraph 做成它的上层。** 它已 released 且自带 Blender API reference / manual 检索工具（省掉 Weaviate 一部分活）；导演模式的"整段自动执行"务必限制在白名单工具集内，因为它 exec Python 无沙箱。
4. **经验入库必须带"适用前提"字段**（对应 shape grammar 的上下文敏感条件）+ 作用域限制，规避 NP-hard 的定位爆炸。
5. **给 GN 节点树留未来接口**：Blender 5.0 已落地 Bundles/Closures/Repeat Zones/Lists/String 字段，5.2（2026-07-14 LTS）继续扩展，GN 正从" modifier"走向可编程数据流——我们的语义段落未来可直接编译成 GN 节点组，而不是一串 bpy 命令。

## 五、关键链接（均已 WebSearch 核实）

- Siemens Synchronous Technology 白皮书 (2008)：https://www.plm.automation.siemens.com/legacy/docs/Synchronous_Technology_CPDA_WhitePaper.pdf
- Blender 4.5 官方手册 USD 页（明确列出 layers/variants/references 不支持）：https://docs.blender.org/manual/en/4.5/files/import_export/usd.html
- Blender Lab（Core USD Authoring 状态 / MCP Server Released）：https://www.blender.org/?p=95270/
- Wonka, SIGGRAPH 2007 course《Urban Design and Procedural Modeling》（含 Stiny80 原始定义）：http://peterwonka.net/Publications/pdfs/2007.SG.Wonka.UrbanDesignAndProceduralModeling.AllSlides.pdf
- Parish & Müller《Procedural Modeling of Cities》：http://www.naturewizard.at/papers/cities%20-%20p301-parish.pdf
- Lipp 2010（shape grammar 局限、NP-hard、涌现行为）：https://www.cg.tuwien.ac.at/research/publications/2010/lipp_markus-2010-DAC/lipp_markus-2010-DAC-Thesis.pdf
- Blender Geometry Nodes Workshop 2025-09（Bundles/Closures/Lists/物理求解器）：https://code.blender.org/2025/10/geometry-nodes-workshop-september-2025/
- Blender Git 插件文档（快照式场景 diff 的现成做法）：https://johndelta.github.io/blender_git_documentation
- Blender Pipeline & I/O 例会 2026-03-19（USD 进展一手信息源）：https://devtalk.blender.org/t/2026-03-19-pipeline-i-o-module-meeting/44700
- SideFX HDA Processor 官方文档（参数→cook 的工业化封装）：https://www.sidefx.com/docs/houdini/nodes/top/hdaprocessor.html

**未核实项说明**：Grasshopper 的确切首发年份未从官方源核实（仅见第三方称 Rhino 4 时期隐式历史、Rhino 7 内置 GH）；"60 秒 → 2 秒"来自 Machine Design 2008 评测报道，非西门子官方基准。


---

## 附：派单 prompt 原文

<teammate-message teammate_id="team-lead" summary="Initial task assignment for general-purpose-1">
你是跨学科预调研的第 1 组，负责【参数化建模 / 程序化生成 / CAD 特征树】这条线。

【项目背景 — 必读】
我们在设计「Blender AI 建模控制台」：LLM 通过 MCP 驱动 Blender 做 3D 建模。架构五要素：
① FlowAxis 流程轴 —— 记录每一步做了什么（What 层，线性、操作级，折叠成语义段落）
② ThoughtGraph 思维图 —— 记录 AI 为什么这么做（Why 层，有向图、决策级，外化可争议的假设）
③ 可回退三层 —— 状态层(快照)、语义层(GoodPoint 质量锚点)、意图层(推翻某个 Thought 并重推下游)
④ ExperienceLibrary 经验库（黑盒，只管 locate/suggest/record）
⑤ 导演模式 —— AI 整段自动执行，人只在段落边界看渲染图给审美反馈，默认不逐条审批
北极星：最终质量 = 迭代次数 × 反馈速度 × 审美介入深度；迭代上限 = min(1/定位成本, 1/回退成本)。
技术栈：blender-mcp、Weaviate、Neo4j、llama.cpp 本地 embedding、Git LFS。

【你的调研任务】
重点回答：这个领域已经解决了我们哪些问题？我们哪些设计是在重新发明轮子？
必查方向（用 WebSearch 核实，不要凭记忆编造）：
- CAD 参数化建模的「特征树 / history tree / parametric history」（PTC Creo、SolidWorks、CATIA），以及「基于历史 vs 直接建模 direct modeling」的争论（如 Siemens Synchronous Technology，约 2008）
- Houdini 的 SOP / 程序化节点图、digital asset(HDA) 的封装与参数暴露机制；Houdini 的 cook 缓存与重算模型
- Grasshopper (Rhino) 的可视化编程与「数据流重算」语义
- Blender Geometry Nodes 的现状（ modifier 堆栈、非破坏性、anonymous attributes、烘焙 bake、2024-2026 的新特性如 Grease Pencil / 重复性 zones bake）
- 程序化建模（procedural modeling）在城市生成/植被生成领域的「规则可复用 + 参数化变体」范式；citygen / L-system / shape grammar（Stiny）
- 非破坏性工作流（non-destructive workflow）与「什么时候必须 apply」的边界
- 3D 资产的版本管理与差异比较（diff）现状，是否有成熟方案；USD (Universal Scene Description, Pixar) 的 layer / variant / non-destructive override 模型
特别关注：USD 的 layer stacking 和 variant set 是不是我们「可回退 + 可复用」的现成答案？Blender 对 USD 的支持程度如何（2026 年）？

【输出格式】中文，900-1300 字，密集具体，不要泛泛而谈：
1. 里程碑成果 4-6 条：名称/提出方/年份 + 一句话核心主张 + 与本项目的关联
2. 已解决的问题（可直接抄）：3-5 条，每条给出具体到「我们架构里 X 应该改成 Y」的启示
3. 已知的坑 / 反直觉发现：3-5 条，最好有实验或业界证据
4. 对本项目的具体建议：3-5 条
5. 关键文献/工具/链接 5-8 条（WebSearch 核实过、真实存在的）

铁律：查不到证据的说法标注「未核实」。绝不编造文献名或 URL。
</teammate-message>