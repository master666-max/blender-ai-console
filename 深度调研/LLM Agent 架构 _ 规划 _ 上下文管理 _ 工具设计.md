# LLM Agent 架构 / 规划 / 上下文管理 / 工具设计

- 原始记录：`agent-6af4277e7ead4567.jsonl`

---

【LLM Agent 架构/规划/上下文/工具设计 — 深度调研报告】

## 一、机制/框架（6 条）

1. **Plan-and-Execute + Replan（混合式）**：多源 benchmark（WebArena/ALFWorld 等）汇总显示 10+ 步任务完成率：ReAct ~34%、静态 PAE ~61%、PAE+Replan ~82%。ReAct 死于上下文线性膨胀埋掉早期约束，PAE 死于计划与现实脱节——两者长程都失败，解法相同：**有界子计划 + 观测检查点 + 重规划触发器**。对我们：段落 = 子计划边界，天然是 PAE 形态；plan-JSON 显式产物正好充当人审 artifact（"approve the plan before any tool fires"）。
2. **Graph Harness/SGH（arXiv 2604.11378）**：把 agent loop 显式化为静态 DAG + 节点状态机 + 计划版本不可变 + 三层升级式恢复协议。【未核实经验证——该文是 position paper，无实验数据，但状态机形式化与"plan 版本内不可变"承诺可直接引用其设计承诺】。
3. **Anthropic Context Management（memory tool + context editing + compaction）**：官方数据：memory+context editing 比基线提升 39%，100 轮长任务 token 减 84%。关键机制：清除前 Claude 收到系统警告，先把关键信息写入持久 memory 文件。Agent SDK 还有 PreCompact hook + CLAUDE.md 压缩指令（"preserve objective/decisions/file paths"）——即压缩时保留什么由我们显式声明。
4. **Self-Reflective APIs（Siemens，arXiv 2606.05037）**：工具报错时返回结构化 `recovery_feedback.suggestions[]`（机器可读修复指令）而非自然语言报错，任务完成率 +36.7~40pp，token 效率 1.8-2.2 倍。⚠️ 在 gpt-4o-mini 上不显著（p=0.435），效果依赖模型。
5. **ToolRescue/ToolFault（arXiv 2609.02750）**：27 种工具故障分类基准；现有 agent 的典型失败是无意义重试、误解报错、无限循环；ToolRescue 仅靠推理时提示增强（故障感知→根因→参数修正→降级）即 +38.7% 成功率，无需微调。
6. **LangGraph checkpointer + interrupt()**：每步落盘状态快照；`interrupt()` 类似 input()——暂停、人审/改状态、`Command(resume=...)` 恢复，可数月后跨机恢复。官方定位："人机协作的 scratchpad"。这就是"段落边界 = 状态机边界"的现成工程实现。

**3D 场景直接证据**：SceneCraft（arXiv 2403.01248，ICML）vs BlenderGPT：CLIP score +45.1%，约束通过分 88.9 vs 5.6。SceneCraft 的关键差异不是模型而是结构：场景图（scene graph）蓝图 → 数值约束 → 渲染 → VLM 检查不满足的约束 → 只修对应脚本 + 技能库复用。**约束级定点修复 > 全量重写**，这是我们最接近的直接前例。

## 二、设计转译（gn_session 工具接口）

1. **plan-JSON 改动用"意图 patch + 确定性应用"**（KubeAstra 模式，arXiv 2609.00227）：LLM 只输出 `{node_id, field, new_value}` 字段级意图，由编译器用解析器定位后确定性地改，LLM 永远不直接写序列化后的 JSON。理由见下"反直觉"。结构性大改才允许全量重写（按 task locality 路由）。
2. **编译器错误必须结构化**：返回 `{error_code, failed_node, reason, suggestions[]}`，每个 suggestion 是可直接执行的修复动作。禁止裸文本报错——这是 Self-Reflective API 的直接应用，且是 M4 编译器接口的硬要求。
3. **工具 ≤10 个、schema 扁平**：无 $ref/oneOf，参数 <8，闭集用 enum，动词_名词命名；描述必须含"何时**不**用 + 指向替代工具"（好描述使失败率降 3-4 倍）。M8-2 的 4 个新工具按此模板写。
4. **段落边界 = 显式 interrupt + memory 写入**：每段落结束时 agent 把 {最终意图、已接受决策、被否决方案、开放反馈} 写入结构化 memory 文件（非自由文本），下一段开头重新注入。CLAUDE.md <4000 token 的正确用法是"压缩保留指令 + 不可变意图声明"，而不是塞对话历史。
5. **错误重试用有界协议**：同一节点重试 ≤N 次后升级（降级路径或上报人审），杜绝无限循环（ToolFault 揭示的头号失败模式）。返回 `isError:true` 的工具级错误供 agent 推理，仅服务端崩溃才走协议错误。
6. **高频循环加 batch 变体**：如 agent 连续 N 次调同类工具，提供 `batch_op`，每次非批量调用都是一轮完整 LLM 循环。

## 三、反直觉/打脸（4 条）

1. **全量重写通常优于 diff**：Aider #625 实测 <400 行文件 full rewrite 胜出（rewrite 95%+ vs unified diff 70-80% 成功率）；根因是训练分布（完整文件：合法 diff ≈ 1000:1）+ BPE 分词破坏 diff 语法。**但** GNU patch 会"静默错应用"1/7 的补丁且无报错——最危险的不是失败而是假成功。
2. **给模型看的工具越少，选得越准**：Anthropic Tool Search 实测 Opus 4 从 49%→74%。30 个相似工具是消歧灾难，不是能力展示。
3. **结构化错误不是万能**：gpt-4o-mini 无显著收益——工具错误格式设计要做模型 A/B，不能假定普适。
4. **PAE 在简单任务上是负资产**（规划开销 40-50% token）；范式选择要按步骤数路由，不是一站到底。这也印证 Cognition：链式多 agent 的优势场景比想象窄，单线程 + 上下文压缩常更稳。

## 四、可直接抄的策略

1. **段落协议**：段落开始 = 注入 {intent-file + plan 当前版本号}；段落结束 = 强制 memory 写入 + plan 版本固化（不可变，只增版本）。
2. **修正策略默认 patch、结构变更才 rewrite**，且 rewrite 后必须跑编译器 diff 校验（防静默丢字段——KubeAstra 实测 frontier 模型全量重写也会偶发丢字段）。
3. **错误→修复→重试的状态机写进系统提示**：Reflect(引用上一步证据)→Call→Final 三步显式化（arXiv 2509.18847，Tool-Reflection-Bench 验证显著降低重复犯错）。
4. **人审反馈作为 state edit 而非新消息**：LangGraph 模式——人在断点改的是 checkpoint 状态（plan-JSON 本身），AI 从修改后状态恢复，避免"反馈漂译"损耗。
5. **压缩白名单**：PreCompact 时强制保留：任务目标与验收标准、当前 plan 版本、所有已否决方案及原因、工具报错历史。丢弃：中间渲染结果、原始工具输出。

## 五、文献/链接

1. SceneCraft (arXiv 2403.01248) — LLM→Blender 代码，双循环 + 约束级修复
2. From Agent Loops to Structured Graphs / SGH (arXiv 2604.11378) — 显式 DAG + 节点状态机
3. Self-Reflective APIs (arXiv 2606.05037) — 结构化错误建议 +40pp
4. ToolFault/ToolRescue (arXiv 2609.02750) — 27 类工具故障 + 免微调恢复
5. Structured Reflection (arXiv 2509.18847) — Reflect→Call→Final
6. KubeAstra / Minimal-Diff Remediation (arXiv 2609.00227) — 意图 patch + 确定性应用
7. Diffs vs Whole Files (arXiv 2604.27296 / 2510.12487) — task locality 路由
8. Anthropic Context Management — https://www.anthropic.com/news/context-management
9. Anthropic Agent SDK agent loop — https://docs.anthropic.com/en/docs/agent-sdk/agent-loop
10. LangGraph persistence/interrupt — https://docs.langchain.com/oss/python/langgraph/persistence
11. LLMCompiler (arXiv 2312.04511) — DAG 并行执行，3.7x 延迟收益

（核实状态：以上均经 WebSearch 核实；SGH 无实验数据已标注；3D 领域未发现 ReAct vs PAE 的直接对比实验——最近似证据为 SceneCraft vs BlenderGPT。）