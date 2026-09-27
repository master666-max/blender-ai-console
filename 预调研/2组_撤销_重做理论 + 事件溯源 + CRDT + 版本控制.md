# [2 组] 撤销/重做理论 + 事件溯源 + CRDT + 版本控制

- 原始记录：`agent-babc1d19e97f449a.jsonl`（614 KB）
- 报告来源：SendMessage 完整报告 ｜ 正文 6038 字符

---

第 2 组调研交付（撤销/重做理论 + 事件溯源 + CRDT + 版本控制）。以下每条均经 WebSearch 核实，无法核实的已标注。

## 1. 里程碑成果
1) **Berlage 1994**《A selective undo mechanism for GUI based on command objects》, ACM TOCHI 1(3):269-294, DOI 10.1145/196699.196721（GINA 系统）。核心主张：linear undo 无法撤销孤立命令；selective undo 把目标命令的**逆操作**复制到当前状态执行，"若在当前状态下有意义"才做；判据只看「被撤销的命令 + 当前状态」，不依赖中间历史。→ 这直接是本项目的**意图层回退**原型。
2) **Cass, Fernandes & Polidore 2006**《An Empirical Evaluation of Undo Mechanisms》, NordiCHI '06, DOI 10.1145/1182475.1182478（首个对比 linear / script-selective / cascading-selective 的用户实验）。结论：**无引导条件下受试者自发偏好 cascading（依赖感知）undo**，胜过 linear 和 script。→ 本项目"推翻某个 Thought 并重推下游"正是 cascading，有实验背书。配套形式化：**Cass & Fernandes 2007**《Using Task Models for Cascading Selective Undo》, LNCS 4385:186-201, DOI 10.1007/978-3-540-70816-2_14。
3) **Fowler, Event Sourcing / Parallel Model**（martinfowler.com/eaaDev/EventSourcing.html、ParallelModel.html）。主张：事件日志是唯一真相，状态可随时重建；**快照 + 前向重放**是标准优化；若事件可反转，从最近快照**倒着走**通常更快（Subversion 就是这样：最新版存快照、历史用反向 delta）；selective replay 可大幅减量但**风险是事件间存在微妙耦合**。→ FlowAxis = 事件日志，状态层 = snapshot interval。
4) **Dolan 2020**《Brief Announcement: The Only Undoable CRDTs Are Counters》, PODC 2020, DOI 10.1145/3382734.3405749（arXiv:2006.10494）；**Kleppmann 等, arXiv:2404.11308**《Undo and Redo Support for Replicated Registers》。前者是硬定理：若要求 undo 能把 CRDT 恢复到某个前状态，则只有计数器可行；后者用"内部状态永远前进、只恢复外部状态"绕开。→ CRDT 不是本项目撤销主干的答案。
5) **Blender MemFile undo 实测**（projects.blender.org issues #106903，Jacques Lucke 2023）。Blender 的 global undo 本质是**把整个 bmain 序列化成内存里的 .blend**（Sergey 原话："equivalent of saving current .blend file in memory"）。引入 implicit sharing 后：数据从 O(n) 拷贝+比对变成 O(1) 共享，undo step 创建/解码快 **2–5 倍**，同一高细分网格场景内存 **1.62GB → 1.03GB**。代价：MemFile 不能再落盘成 .blend，自动保存变慢最多 3 倍。→ **快照不必然贵，去重后完全可用**。
6) **rr / 时间旅行调试**（O'Callahan et al.）。关键洞察：只记录**非确定性输入**（syscall 结果、信号、RDTSC），其余靠确定性重算；用硬件性能计数器（retired-branch）定位事件点；录制开销仅 20–50%（Firefox 测试套件约 1.2x），配合周期性 checkpoint 实现反向执行与 reverse-watchpoint。→ "记录足够重建的输入 + 稀疏 checkpoint" 是压低定位成本的标准解法。

## 2. 已解决的问题（可直接抄）
- **状态层**：不要"每步全量快照"，改成「段落边界全量快照 + 段内事件重放」的混合策略（Fowler 明确推荐，且可先做纯重放、快照后加）。Blender 自己已被迫走去重路线，证明可行。
- **意图层**：不要做成"撤销某个操作"，改成 **cascading selective undo**——ThoughtGraph 的因果边就是依赖图，推翻一个节点自动失效所有下游（Cass 2007 给出了现成的算法骨架）。
- **撤销主干**：不要用 CRDT。本项目是单人单写者（AI）+ 中心化日志，Dolan 定理说明引入 CRDT 只会换来"不可真正撤销"。
- **持久化**：不要把 undo 栈只放内存。事件日志用 WAL 落盘，快照由后台任务异步生成（Fowler：快照可随时并行生成，不打断运行）。这条直接消灭 Blender 的跨会话丢失问题。
- **定位**：FlowAxis 除"做了什么"外，必须记录足够重建的**输入**（参数、随机种子、选中集），否则重放不确定。

## 3. 已知的坑 / 反直觉发现
- **用户不偏好"最灵活"的那个**。Cass 实验：cascading > linear 与 script。反直觉点在于这是在"无任何引导"下测的——说明人默认的心智模型是依赖感知的。推论：导演模式若不给提示，人会以为推翻一个 Thought 会自动带走下游；**必须显式显示"影响 N 个下游"**。
- **Berlage 的原始警告被低估**：GUI 中"先前的动作在另一个状态下未必有合理解释"，所以 selective undo 可能根本无意义。3D 建模更严重（布尔/细分的顺序一变，结果就不同）。→ **重推下游必须允许失败并向上报告，不能静默执行**。
- **script 与 inverse 结果不同，必须二选一并公开宣告**。Berlage 经典例：改色 A → 复制 B，选择性撤销 A 时，script 模型下两个对象都回原色，inverse 模型下只有原件回原色。两套语义混用会直接摧毁用户心智模型。
- **Git 对二进制资产确实无能为力**（Microsoft/Oracle 官方口径一致）：Git 无法 diff/merge 二进制，每个版本存全量，仓库随修改次数线性膨胀，clone/branch 变慢；LFS 只是把内容挪到外部存储 + 提供文件锁，**仍需人工协调，且每个客户端都要装 LFS**，否则克隆下来是指针文件。→ .blend 不能当 Git 对象管理，但**操作脚本是文本、可 diff**，这正是本项目的机会窗口。
- **CRDT 的隐藏成本**：Yjs 用 LWW 寄存器，并发更新直接丢失，undo 不恢复兄弟节点；tombstone 只增不减（Automerge 1.0 曾对 100KB 文档产生 3000x 内存开销，2.0 降到约 10x，Yjs 约 2–5x）。
- **Blender undo 的实测坑**：undo 栈**不写入 .blend**，退出即丢；edit/sculpt 的 local stack 极不稳定（访问任一 local stack 会使其他对象的 stack 全丢，global undo 一步也会清空）；默认 32 步、可调至 256；Memory Limit 会在未达步数上限前就淘汰旧步。
- **redo 天然不对称**：Blender 明确"一旦产生新改动，Undo History 在该点被截断"。→ "重推下游"应建模为**重放（replay）而非 redo**，redo 是脆弱的分支概念。

## 4. 对本项目的具体建议
1. **用混合，且按层分工**（回答你的核心问题）：**状态层用快照、意图层用 script 重放、操作层用 inverse**。理由是 Blender 实测数据：全量快照在去重后内存只多 30%（1.62→1.03GB 是省了 36%，说明未去重时开销巨大但可控），而 inverse 在布尔运算、细分、雕刻、重拓扑这类（近）不可逆操作上根本写不出来。不要试图纯 inverse。
2. **段落粒度用双条件触发**：语义闭合（一个 Thought 节点出口）+ 成本阈值（段内操作数 20–50，或"重放一次的耗时 > 加载快照的耗时"）。参考 Blender 默认 32 步这个量级——它不是随便定的，是内存与可用性长期折衷的结果。**GoodPoint 质量锚点应当就是快照点**，两者合并，不要两套。
3. **FlowAxis 按对象/区域建索引**，不只按时间线性。AZURITE（Yoon & Myers, CMU-ISR-15-103）证明：让用户"选区域"而不是"从操作列表里选一条"，才是压低定位成本的正确交互——因为人记不住第 37 步做了什么，但记得住"这个把手坏了"。
4. **别急着上协同**。单人单写者下撤销是已解问题；多人同时改一个 3D 场景的 CRDT 方案在研究和工业界都未解决。若未来要做，只做**段落级（快照级）合并**，不做操作级 CRDT。
5. **给导演模式加"影响预览"**：推翻 Thought 前先静态分析 ThoughtGraph 的因果闭包，显示"将重推 N 段、其中 M 段可能失败"。这是 Berlage + Cass 两条结论的共同推论。

## 5. 关键文献 / 工具 / 链接（均已核实真实存在）
1. Berlage 1994, ACM TOCHI 1(3):269-294, DOI 10.1145/196699.196721 — https://www.acm.org/pubs/articles/journals/tochi/1994-1-3/p269-berlage/p269-berlage.pdf
2. Cass, Fernandes, Polidore 2006, NordiCHI, "An Empirical Evaluation of Undo Mechanisms", DOI 10.1145/1182475.1182478
3. Cass & Fernandes 2007, "Using Task Models for Cascading Selective Undo", LNCS 4385:186-201, DOI 10.1007/978-3-540-70816-2_14 — https://cs.union.edu/~fernandc/pub/tamodia06.pdf
4. Fowler, Event Sourcing — https://martinfowler.com/eaaDev/EventSourcing.html ；Parallel Model（快照/反向事件/selective replay）— https://www.martinfowler.com/eaaDev/ParallelModel.html
5. Dolan 2020, "The Only Undoable CRDTs Are Counters", PODC 2020, DOI 10.1145/3382734.3405749（arXiv:2006.10494）；Kleppmann et al., "Undo and Redo Support for Replicated Registers", arXiv:2404.11308 — https://www.arxiv.org/pdf/2404.11308
6. Blender issue #106903（implicit-sharing undo 的实测数据）— https://projects.blender.org/blender/blender/issues/106903 ；devtalk 提案 — https://devtalk.blender.org/t/remove-support-for-saving-memfile-undo-steps-as-blend-files-proposal/33544 ；Blender 2.8 undo 讨论（Sergey 解释 global undo 语义）— https://devtalk.blender.org/t/blender-2-8-undo-system-discussion/6898
7. Yoon & Myers, "Backtracking Support in Code Editing" (AZURITE), CMU-ISR-15-103 — http://reports-archive.adm.cs.cmu.edu/anon/home/ftp/isr2015/CMU-ISR-15-103.pdf （含 linear/script/inverse/cascading/regional 五种模型的完整综述与冲突处理方案）
8. rr 时间旅行调试器 — https://rr-project.org/ ；O'Callahan et al., "Engineering Record and Replay for Deployability"（rr 设计论文）

未核实项：Berlage 1994 论文本身我读到的是摘要与二手引述（ACM 页面与 CMU 综述），未逐页精读全文；Cass 2006 的具体样本量与统计显著性（论文提到用 Benjamini-Hochberg 校正）我只看到摘要，未读到数值表。其余数据来源均为一手页面（Blender 官方 issue/devtalk、Fowler 官网、arXiv 原文、ACM DOI）。

---

## 附：派单 prompt 原文

<teammate-message teammate_id="team-lead" summary="Initial task assignment for general-purpose-2">
你是跨学科预调研的第 2 组，负责【撤销/重做理论 + 事件溯源 + CRDT + 版本控制】这条线。

【项目背景 — 必读】
本项目「Blender AI 建模控制台」：LLM 通过 MCP 驱动 Blender 做 3D 建模。架构五要素：
① FlowAxis 流程轴 —— 记录每一步做了什么（What 层，线性、操作级，折叠成语义段落）
② ThoughtGraph 思维图 —— 记录 AI 为什么这么做（Why 层，有向图、决策级）
③ 可回退三层 —— 状态层(快照)、语义层(GoodPoint 质量锚点)、意图层(推翻某个 Thought 并重推下游)
④ ExperienceLibrary 经验库（黑盒）⑤ 导演模式 —— AI 整段自动执行，人只在段落边界给审美反馈
北极星：把「定位成本」和「回退成本」压到接近零。逐条审批只是这两项成本昂贵时的劣质替代品。
关键类比：Git 之所以能让程序员放心让 AI 写代码，是因为 revert/branch 的成本≈0；3D 建模缺的就是这个。

【你的调研任务】
必查方向（用 WebSearch 核实，不要凭记忆编造）：
- 撤销模型的经典理论：Berlage 1994《A selective undo mechanism for graphical user interfaces based on command objects》(ACM TOCHI)；linear undo vs selective undo vs script/region undo 的差别与用户实验结果
- 反向操作(inverse) vs 状态快照(checkpoint) vs 重放(replay) 三种回退实现的成本对比；redo 与 undo 的不对称性
- 命令模式 Command Pattern 与 memento 模式的适用边界
- Event Sourcing / CQRS（Fowler 等人）在长期存档与「重建任意时刻状态」上的做法；快照+重放的混合策略（snapshot interval）
- CRDT 与协同编辑（如 Yjs / Automerge）如何解决「并发修改 + 任意回退」；CRDT 能否用于非线性撤销
- Git 模型的已知局限：线性历史、merge 冲突、大文件(LFS)痛点；以及 Git 为什么不适用于二进制资产
- Blender 自身 undo system 的实现限制（undo stack 内存态、不持久化、跨会话丢失、步骤上限、内存占用）—— 查 Blender 官方文档/源码说明
- 时间旅行调试（time-travel debugging / rr / replay debugger）的启发

【输出格式】中文，900-1300 字，密集具体：
1. 里程碑成果 4-6 条：名称/作者/年份 + 核心主张 + 与本项目关联
2. 已解决的问题（可直接抄）：3-5 条，每条具体到「本项目架构里 X 应该改成 Y」
3. 已知的坑 / 反直觉发现：3-5 条（尤其是实验/实测证据，如 selective undo 用户实验结论）
4. 对本项目的具体建议：3-5 条（特别回答：本项目应该用 inverse 还是 snapshot 还是混合？段落粒度怎么定？）
5. 关键文献/工具/链接 5-8 条（WebSearch 核实过、真实存在）

铁律：查不到证据的说法标注「未核实」。绝不编造文献名或 URL。
</teammate-message>