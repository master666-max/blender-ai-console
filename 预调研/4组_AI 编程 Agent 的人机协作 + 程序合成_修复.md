# [4 组] AI 编程 Agent 的人机协作 + 程序合成/修复

- 原始记录：`agent-1fe518c119564e7b.jsonl`（884 KB）
- 报告来源：SendMessage 完整报告 ｜ 正文 6193 字符

---

# AI 编程 Agent 的人机协作 + 程序合成/修复（第 4 组）

## 一、里程碑与现状

1. **Claude Code 介入点阶梯（2025-2026）**：默认每操作询问 → Shift+Tab 三态（normal / auto-accept edit / plan mode）→ `--dangerously-skip-permissions`（YOLO）→ 2026-03 新增 **auto mode**（内置 prompt-injection 探针 + transcript 分类器逐动作审批，Anthropic 自称"deliberately conservative"）+ `/sandbox` 沙箱 Bash。Anthropic 工程博客称用户批准了 **93%** 的权限提示（二手引用，未核实）。→ 导演模式不该是二元"全管/全放"，而是**分级**。

2. **Plan-first**：Claude Code 创造者 Boris 的工作流是先 Plan mode 反复讨论到满意，再切 auto-accept 一次做完——"计划质量决定结果上限"。把高价值判断前置到段落边界，正是同一思路。

3. **验证闭环**：CLAUDE.md 里写"改完跑 typecheck+test"是*建议性*的；确定性做法是 hook——PostToolUse（matcher `Edit|Write`）跑 tsc/eslint，exit 2 把 stderr 注回 agent 上下文；Stop hook 用 agent 类型跑完整测试套件，失败则不许 turn 结束。这是"验证器驱动自主循环"的最小可复制骨架。

4. **SWE-bench 饱和**：Verified（500 题，2024-08）从 33.2%（GPT-4o+Agentless）到 2026 年 Opus 4.7 的 87.6% / Opus 4.8 的 88.6%；**OpenAI 2026-02-23 正式弃用**，理由是最难未解任务中 >59% 测试损坏/不公平 + 污染。后继 SWE-bench Pro 解决率仍 <25%。

5. **APR 定位粒度实证**（arXiv 2604.00167, Fujitsu 2026）：**完美定位**前提下 SWE-Bench-Mini 上 Function 45.6% > Line 43.6% > File 42.6%（Friedman χ²=12.8, p=0.0017），Function 标准差最低（1.5）。但最优粒度**随难度分层变化**，且即使定位完美修复率仍不足 50%。

6. **上下文持久化**：`/compact`（实测 15-20x 压缩）、auto-compact 约 95% 触发、可用 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70` 提前、PreCompact hook 把状态外置到文件、CLAUDE.md 内可写 "Compact instructions" 指定压缩时保留什么。AGENTS.md 正成为跨工具标准。共识：CLAUDE.md 应 **< 4000 tokens**，密集而非冗长。

## 二、已解决、可直接抄

1. **导演模式应显式加 Plan 阶段**：FlowAxis 每段自动执行前先产出可审阅的"段落计划"（要改哪些物体/参数、预期视觉结果），人确认后才切 auto-accept。Boris 工作流 + Shift+Tab 三态的直接移植。
2. **验证器用 hook 强制而非提示**：MCP 每次几何写入（加修改器/改顶点/改材质）都应触发等价 PostToolUse——自动跑"几何体检"，把失败结构化注回 LLM 上下文，而不是等人在段落边界发现。
3. **项目记忆分三层**：CLAUDE.md 只放全局硬约束（<4000 token）；可变任务状态写 `state.md` 由 PreCompact 式钩子外置；每段结束写"下一段做什么"的 recap。
4. **定位粒度用"函数级"且自适应**：3D 的"函数级"= **物体/修改器节点级**，不是顶点级。给"哪盏灯/哪个修改器/哪个材质槽有问题"比给精确顶点索引更稳（σ 最低），也比只说"这个物体"有效。
5. **sketch 思路 → 人给骨架 + 洞**：Sketch/Synquid 教训是**约束的表达方式决定搜索空间是否爆炸**（Solar-Lezama 可用性研究：学生都能成功，但多数因描述方式导致综合超时），且 SOSRepair(TSE 2021) 发现粒度更高（3-7 行块）的补丁质量更好、手工改进定位后 70% 通过独立测试。人应给**结构约束**（拓扑/比例/层次），AI 填数值洞。

## 三、坑 / 反直觉（均带数字）

1. **审查疲劳是量化事实**：Faros AI《AI Engineering Report 2026》（22,000 开发者 / 4,000+ 团队）高 AI 采用下 **PR 中位评审时间 +441%、31% 更多 PR 零评审合并、PR 体积 +51.3%、人均 bug +54%、每 PR 事故 +242.7%**。LinearB 2026（810 万 PR）：AI PR 30 天合并率 **32.7%** vs 人写 **84.4%**。arXiv 2605.02273（33,596 个 agent PR）：**61.38% 完全无评审活动**。→ 审查不是变慢，是**被跳过**。
2. **METR RCT**（arXiv 2507.09089, 2025-07）：16 名资深 OSS 开发者 / 246 个真实任务，事前预测快 24%、事后自评快 20%，实测**慢 19%**；经济学与 ML 专家预测快 39%/38%，全错。
3. **代码膨胀 + 重构消失**：GitClear 纵向（2.11 亿行，2020-2024）两周内 churn 5.5%→7.9%（相对 +44%）；复制粘贴行 8.3%→12.3%；"移动/重构"行 **24.1%→9.5%**，重复代码块 **8 倍**——2024 年首次出现复制 > 重构。arXiv 2603.28592（6,275 仓库 / 304,362 条 AI commit）：**89.1% 是 code smell**，各工具 **15%+ commit 引入新 issue**，其中 **24.2% 一直存活到最新版未被发现**。
4. **多 Agent 是结构性失败**：Cognition（Devin 团队）《Don't Build Multi-Agents》原则"每个动作都必须由此前全部动作的完整记录所告知"，fleet 无法满足。实测链式 agent 成功率跌到 **20-40%**；3-agent 工作流 demo 成本 $5-50 → 生产 **$18k-90k/月**；延迟 1-3s → 10-40s；可靠性 95-98% → 80-87%。Devin 因此**完全不用并行 agent**。Claude Code 文档也承认 subagent 会漏掉父 agent 的战略目标与约束。
5. **信任缺口扩大**：Sonar 2026（1,100+ 开发者）42% 提交代码归因 AI，但 **38% 说审 AI 代码比审人写代码更费力**；CodeRabbit（2025-12）AI 共同创作代码每 PR 问题数是纯人写的 **1.7 倍**。

## 四、对本项目的建议

**(a) 3D 的弱验证器能造什么？** 核心教训：机械验证器（编译器/测试/证明器）不可攻破，学习型 proxy 必被攻破（Goodhart / verifier's law）。3D 虽无编译器，但有一批**完全确定、零成本、不可攻破的几何谓词**，应做成每次 MCP 写入后的强制巡检：
- **拓扑合法性**：非流形边数==0、零面积面/零长度边==0、自相交面数、松散顶点数、重复顶点数（Blender 3D-Print Toolbox 的 Check All 与 `bmesh` 已可全量计算，`is_watertight` 有现成脚本）。
- **朝向/尺度**：法线外向一致性（Face Orientation 红/蓝比例）、未应用变换（scale≠1）、包围盒与用户给定物理尺度是否匹配、是否穿地（min z<0）、是否越出相机视锥。
- **预算类**：三角面数 / 物体数 / 材质数 / 修改器栈深度是否超预算（AI 天然倾向"加"，见坑 3）。
- **结构类**：父子关系是否成环、命名是否符合约定、孤立空物体、修改器未应用就导出。
- **渲染类（最弱但可机械化的代理指标）**：渲染图非全黑/非纯背景（像素方差阈值）、目标物体像素占比落在区间、深度图存在合理分层。
- **回归类**：每段固定视角渲图 + 感知哈希，下段改动后比对，把"我没动的东西被改了"变成可报警的差异集（等价于 PASS_TO_PASS）。
关键：做成**机械门禁**（不过就回退该段），绝不能做成"让 LLM 自己打分"。

**(b) CLAUDE.md 的启示**：它的本质不是说明书，而是**跨会话压缩态 + 硬约束注入层**，且遵循度高于用户 prompt。
- **ThoughtGraph（Why）不该全量入上下文**，而应压缩成稠密 `PROJECT.md`（<4000 token 硬上限），只留"作品要传达什么、哪些审美决策已定、哪些绝对不能碰"。
- **FlowAxis（What）= 状态文件而非对话历史**：每段结束把"已完成/进行中/下一步/本段意图"写进 `state.md`，下段由它冷启动——即 PreCompact hook + `/resume` 模式，也是多 Agent 中唯一有效的"文件即共享内存"。
- **人的每次审美反馈应沉淀为规则条目**：不是"这张不好看"，而是"角色肩线不能低于 X"。规则条目才是可复用、可压缩、可跨段生效的记忆。
- 反直觉点：Claude Code 实践强烈建议**分段**（30-45 分钟一块后 /compact）而非一条长会话跑到底。本项目的"段落"应同时是**上下文压缩边界**。

**(c) 导演模式如何避免审查疲劳**：
1. **段落边界必须短且等长**。编程域惨剧源于 PR 体积 +51% → 评审时间 +441% → 61% 被直接跳过。段落要**默认小**（借鉴"PR 控制在 400 行内"），宁可多几个边界。
2. **边界处只呈现 diff 不呈现全量**：人看的是本段新增/改动了哪些物体、哪些参数、哪几张对比渲图，而非重新审视整个场景。定位成本趋零的关键在此。
3. **机械门禁先行，人只看机器判不了的部分**：装好 (a) 后，人在边界处**不需要检查"有没有坏"**，只需回答"好不好看"——对应 Claude Code 社区那句总结："hook 装好后，审 diff 不再是抓错误的手段，而是抓**决策**的手段。"
4. **给"通过"一个代价**：31% 零评审合并说明通过 cheapest 时人就会无脑通过。边界反馈应是**二选一比较**（A/B 选一个）而非"批准/驳回"——前者几乎无法敷衍，后者会被系统性跳过。
5. **警惕"AI 只会加不会改"**：GitClear 显示重构行 24.1%→9.5%。3D 等价灾难是 AI 不停加新物体而非改好已有物体。验证器应显式加"修改/删除操作占比"指标，并在段落计划阶段强制回答"本段是改还是加"。

## 五、文献与工具（均 WebSearch 核实）

1. METR, *Early-2025 AI & Experienced OS Dev Productivity* (arXiv:2507.09089) — https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/
2. *Fault Localization Granularity for Repository-Scale Code Repair* (Fujitsu, arXiv 2604.00167, 2026)
3. ARISE: Repository-level Graph for Agentic FL & Program Repair (arXiv 2605.03117)
4. GitClear, *AI Copilot Code Quality Report*（2.11 亿行纵向）— https://www.gitclear.com/
5. Faros AI, *AI Productivity Paradox* (2025) / *AI Engineering Report 2026*
6. Cognition《Don't Build Multi-Agents》；GitHub Blog《Multi-agent workflows often fail...》
7. Solar-Lezama *Program Sketching* (PLDI 2006) / CEGIS；Synquid (POPL 2016)；Smyth (arXiv 1911.00583)；SOSRepair (TSE 2021)
8. SWE-bench Verified 官方页 + OpenAI 2026-02 弃用公告；SWE-bench Pro
9. Blender 3D-Print Toolbox（Check All / Make Manifold）+ `bmesh` 非流形检查脚本（Blender SE #160109）
10. RLVR Book, Ch.7 *Reward Hacking and Verifier Robustness* — http://rlvrbook.com/chapters/07-reward-hacking-and-verifier-robustness.html

**未核实标注**：Anthropic"用户批准 93% 权限提示"、"auto mode 2026-03 发布"、"高级工程师审 AI 建议 4.3 分钟 vs 人写 1.2 分钟"三项均来自二手转述，未找到一手出处。

**对核心判断的回应**：你的三要素判断成立，但需补一条——**真正让软件工程跑通的不是"有验证器"，而是验证器是机械的、不可攻破的、且成本近零**。3D 缺的不是"可分解单元"（物体/修改器/材质槽天然可分解），而是**机械验证器**。第 (a) 条清单说明这个缺口可以用几何谓词补上大半，剩下"好不好看"才是人该管的。


---

## 附：派单 prompt 原文

<teammate-message teammate_id="team-lead" summary="Initial task assignment for general-purpose-4">
你是跨学科预调研的第 4 组，负责【AI 编程 Agent 的人机协作 + 程序合成/修复】这条线。这是本项目最重要的参照系。

【项目背景 — 必读】
本项目「Blender AI 建模控制台」：LLM 通过 MCP 驱动 Blender 做 3D 建模。架构五要素：
① FlowAxis 流程轴（What）② ThoughtGraph 思维图（Why）③ 可回退三层（状态/语义/意图）
④ ExperienceLibrary 经验库（黑盒）⑤ 导演模式 —— AI 整段自动执行，人只在段落边界给审美反馈
北极星：把「定位成本」和「回退成本」压到接近零。
核心判断（供你验证或反驳）：软件工程是目前最成熟的 AI 人机协作领域，因为它同时具备三样东西——客观验证器（测试/编译器）、近乎零成本的版本控制（Git）、以及可分解的任务单元（文件/函数/diff）。3D 建模三样都缺。

【你的调研任务】
必查方向（用 WebSearch 核实，不要凭记忆编造，优先 2025-2026 的最新实践）：
- Claude Code / Cursor / Aider / Copilot Workspace / Devin / Windsurf 的「人类介入点」设计：checkpoint、diff review、auto-accept 模式、YOLO 模式、permission 系统、--dangerously-skip-permissions
- 业界对「审查疲劳 / slop」的反思：程序员抱怨审查 AI 代码比自己写还累；代码膨胀、PR 体积变大、review 质量下降的实测数据（如 2025-2026 的 DORA report / Google 工程报告 / LinearB / GitClear 关于 AI 代码质量与返工率的数据）
- 编程 Agent 的「验证器」如何驱动自主循环：测试驱动(TDD + AI)、编译/类型检查闭环、self-repair；Claude Code 的 test-driven loop、Cursor 的 bug finder
- Agent 会话的持久化与恢复：Claude Code 的 /compact 与上下文压缩、CLAUDE.md / .cursorrules 这类「项目记忆」文件的实践与效果评估
- 自动化程序修复(APR)领域的「故障定位 → 补丁生成 → 验证」三步范式；定位粒度（语句级/函数级/规范级）对修复成功率的影响
- Program synthesis 的「sketch / 约束求解」思路，以及它与「人给约束、AI 补全」的关系
- 多 Agent 协作做软件（如 Claude Code 的 subagent、Devin 的 planner/worker 分离）的经验与失败模式
- 关于「AI 生成代码的正确性验证」：是否有客观指标（如 SWE-bench、HumanEval、LiveCodeBench 的演进，2026 现状）

【输出格式】中文，1000-1400 字，密集具体：
1. 里程碑/现状 4-6 条：名称/年份 + 核心机制 + 与本项目关联
2. 已解决的问题（可直接抄）：3-5 条，每条具体到「本项目架构里 X 应该改成 Y」
3. 已知的坑 / 反直觉发现：3-5 条（必须有实测数据，给出具体数字）
4. 对本项目的具体建议：3-5 条。特别回答三个问题：
   (a) 3D 建模没有编译器/测试，本项目能造出什么样的「弱验证器」？具体到几何层面可自动检查哪些东西？
   (b) 编程 Agent 的 CLAUDE.md 这类「项目记忆」对本项目的思维图/流程轴有什么启示？
   (c) 编程领域踩过的「审查疲劳」坑，本项目的导演模式怎么避免重蹈覆辙？
5. 关键文献/工具/链接 5-8 条（WebSearch 核实过、真实存在）

铁律：查不到证据的说法标注「未核实」。绝不编造数据、文献名或 URL。
</teammate-message>