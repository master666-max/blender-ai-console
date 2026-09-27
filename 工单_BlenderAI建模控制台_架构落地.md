# 工单 · Blender AI 建模控制台 架构落地

| | |
|---|---|
| **工单号** | WB-MUG-2026-001 |
| **日期** | 2026-09-27 |
| **状态** | 待开工 |
| **来源** | 三轮调研（跨学科六路 + GN 岔路实测 + 算法路线六路）+ 端到端原型 + AB 实验 |
| **验收标准** | 见各工作项；总验收 = 原型场景（马克杯"把手太粗了"）在改完后全部指标不退化 |
| **执行人** | 待定 |
| **工作区** | `<工作区>/`（代码）、`2026-09-26-blender/`（探针与实验结果） |

---

## 一、一页背景（执行前必读）

**做什么**：LLM 经 MCP 驱动 Blender 建模。AI 的计划**编译成 Geometry Nodes 节点组**
（声明式、显式 DAG、具名参数），每个语义段落 = 一个 modifier = 一个 opinion 层（USD LIVRPS 式）。
人在段落边界看渲染 diff 给审美反馈，默认不逐条审批（导演模式）。

**北极星**：
```
最终质量 = 迭代次数 × 反馈速度 × 审美介入深度 × 解空间多样性
迭代上限 = min(1/定位成本, 1/回退成本)   ← 不由 AI 能力决定
```

**已用代码证明的事实**（全部在本机 Blender 5.2.1 LTS 实测，可复跑）：

| 事实 | 数字 | 出处 |
|---|---|---|
| 编译到 GN 比执行 bpy.ops 迭代便宜 | **5.9×**（59.3 vs 346.3 ms，同 393,216 面） | gn_perf2 |
| 三层回退成本分档 | L1 删层 **0.7ms** / L2 回快照 **0.6ms** / L3 重推 **50ms** | gn_console |
| Blender GN **没有**局部重算 | 改上游 49.7ms vs 改下游 45.3ms，比值 **1.10** | gn_console [9] |
| 无改动时代价 | **0.001 ms**（缓存命中） | gn_probe6 |
| realize（bake 边界） | **0.19 ms** / 393,216 面 | gn_probe8 |
| 改参数必须三步都对 | `properties.inputs[id]["value"]` + `obj.update_tag()`；**headless 下改 interface default 无效** | gn_sync/probe_fix |
| 布尔的"手术区域"局部性 | 只动 **9–27%** 顶点 | probe_surgery |
| 按索引存缝合映射存活率 | **0–1.6%**（TNP 实锤） | probe_surgery |
| 错误面静默率 | GN **20%** vs ops **60%**（各注入 5 个真实坑位） | gn_ab |
| 精确恢复布尔前状态 | **信息论不可能**（多对一映射），必须存数据 | 算法路线调研/5 |

---

## 二、现有资产

| 文件 | 状态 | 说明 |
|---|---|---|
| `blender_console/core_types.py` (893 行) | 冒烟通过 | Command/Step/Thought/FlowAxis(线性)/Transaction/GoodPoint/TrustPolicy/DirectorConsole |
| `blender_console/gn_adapter.py` (647 行) | 纯 Python 7 组 + 真机 26/26 | 版本守卫、socket 兼容、环检测、per-instance 输入、realize、dump/fingerprint/diff |
| `blender_console/gn_adapter_live.py` | 真机 26/26 全绿 | 含"应当失败"用例与**面数断言** |
| `blender_console/gn_verify.py` | 原型可用 | 7 个机械谓词（非流形/零面积/松散顶点/面预算/scale/穿地/非空） |
| `blender_console/gn_console.py` | 端到端跑通 | 编译→求值→verifier→GoodPoint→推翻重推→三层回退 全链 |
| `blender_console/gn_ab.py` | 跑完 | 错误面基准（错误样本库可复用） |

---

## 三、工作项（按里程碑分组，含验收标准）

> 编号规则：`M{里程碑}-{序号}`。每项标注依据（调研编号）与验收标准。
> 标 ✅ 的已完成或部分完成；标 ★ 的是本次新增、性价比最高的。

### M1 · 数据层骨架 —— **✅ 已落地并集成：`m1_core.py`（纯测 PASS）+ `gn_session.py`（真机 23/23，2026-09-27）**

**M1-1 ✅ 完成（含集成）：FlowAxis 显式 DAG + 依赖边 + 环检测**（A1）
- 依据：Rhino 4 隐式历史失败 → Grasshopper 显式 DAG + 禁回环
- 交付：`m1_core.FlowDAG`（add 时环拒绝、`topo_order()`、`descendants()` 影响预览、`segments()` 折叠）；
  `gn_session.compile_segment` 默认线性链 + `set_deps()` 显式跨段依赖；**旧线性 FlowAxis 已标退役**（core_types 留档）
- 验收：真机「依赖缺失被拒」「DAG 步数=3 / 拓扑序」断言通过

**M1-2 ✅ 完成：区域反查**（A2）
- 交付：`FlowDAG.steps_for_object(obj)` / `steps_for_thought(tid)`；`SegmentSpec` 增加 `obj` 区域键（S2 段=Handle）
- 验收：真机 `steps_for_object('Handle') == ['step:S2_把手']`

**M1-3 ✅ 完成：WAL 落盘 + 哈希链 + compaction**（A6、A32）
- 交付：`WALLog`（append-only JSONL、prev-hash 链、`verify()` 篡改检测、`replay()`、`compact()` checkpoint 截断）
- 真机证据：**跨进程 WAL 持久化实际发生**（第二次运行自动载入前次事件——「杀进程重开可重建」被意外实证）
- 纪律：只录非确定性输入（编译/参数/verify/pivot/override/checkpoint），求值结果不落盘

**M1-4 ✅ 完成：Step 可确定性重放 + gn_delta**（A10、A16）
- 交付：`StepRecord` 携带 `seed/params/selection/deps/thought_refs/revision/gn_delta`；
  `gn_session.recompile_segment()` 产出新旧树 `adapter.diff`，WAL 留档且旧组不销毁（内容寻址精神）
- 验收：真机「重编译 S2 → gn_delta 非空 + diff 报告 params_added ['Handle_Fillet']」

**M1-5 ◐ 过渡完成：版本化参数表 + 内容寻址 commit**（A31、A33）
- 交付：`VersionedParams`（量化浮点、逐版指纹）、`SegmentCommits`（内容寻址、去重、diff）
- 过渡声明：参数表当前为"每版整份拷贝"（KB 级小状态可接受）；**HAMT/路径复制留 M1-5b**
- 验收：同参数同输出 → 同 commit 哈希（去重）；不同 → 新 commit；diff 可检出

**M1-6 ✅ 完成：revision + backdating**（A28，性价比最高）
- 交付：`RevisionTable`（Salsa 红绿语义：`touch` 置脏 → `report_output` 回报 → 输出未变则**级联截断**；`mode()` 失效 >40% 走全量）
- 真机断言：改 S2 → S2/S3 脏、S1 净 ✓；同值再写 → 零失效 ✓；几何未变 → report False ✓
- 剩余：输出 hash 接 LOD 顶点指纹；40% 阈值真实负载标定（EXP-2）

**M1-7 ✅ 完成：Command 逆运算机械化 + pivot 纪律**（A7、A29）
- 交付：`ParamUpdate`（逆由 `(old,new)` 互换机械生成）、`LogOnly`（pivot）、`SagaTag`、`PivotBlocked`
- 真机：checkpoint 记录**参数表快照** → revert = 逐参数机械逆写回（不是盖网格数据）；log_pivot 后 revert 被 `PivotBlocked` 拒绝 ✓

**M1-8 ✅ 新增：Web 前端状态契约**（M9-4a）
- 交付：`export_state()` → `mug-console-state/1` schema；真机产出 `gn_session_state.json`（3 steps / 2 thoughts / 1 override）

### M2 · 验证层（机械门禁）

**M2-1 ✅→补全 verifier 六类谓词**（A5、A15）
- 依据：verifier's law——学习型 proxy 必被攻破；已有 7 个谓词原型
- 待补：① 面预算/物体数/材质数/修改器栈深度；② **父子成环**；③ 命名约定；④ 修改器未应用就导出
- 验收：每谓词至少 1 个"应当失败"用例（A20：门禁只 PASS 过等于没有）

**M2-2 ★ 新增四条谓词**（A24、A25、A9）
- A24 物体数/段落数一致性（我自己 join 少并一个都"通过"了 baseline）
- A25 局部性：段落执行后受影响顶点占比 >40% 告警 → 该拆段（实测布尔只动 9–27%）
- A9 修改/删除操作占比（GitClear：重构行 24.1%→9.5%，AI 只会加不会改）
- 验收：各 1 个正例 + 1 个故意的反例

**M2-3 渲染类谓词（第二层）**（A15 后半）
- 依据：GN 内可算拓扑谓词，渲染类必须渲出来后算
- 验收：非全黑（像素方差）、目标物体像素占比、固定视角渲图 + 感知哈希回归（≡ PASS_TO_PASS）各 1 例

**M2-4 段落验收必须同时查 evaluated 与 baked**（A23）
- 依据：AB 实验——ops 的 3 个静默失败**只有** baked 面数能暴露（34 vs 9984，视口完全正常）
- 验收：验收函数返回 `(eval_stats, baked_stats)` 两个值，单测覆盖"视口正常但 baked 错"的场景

**M2-5 断言与 diff 一律用几何量**（A19）
- 依据：实测把手 11mm→7mm，面数 17,152→17,152 **完全不变**
- 验收：diff 返回表面积/包围盒/体积，面数仅作参考；单测含"拓扑不变但几何变了"的用例

### M3 · 回退层（三层，语义必须宣告）

**M3-1 opinion 栈直接用 modifier 栈**（A4 修订版）
- 依据：实测——同一节点组挂 2 个 modifier 正确复合；per-instance 输入可写；层序可调；**删顶层 = 常数成本回退**
- 验收：两层层栈复合、层序调整、删层回退三例全过（已有 gn_adapter_live 用例，迁移进正式测试）
- ⚠️ 前提：**只 promote 需要被覆盖的参数**（promote 出来的东西才是可覆盖的东西）——HDA 契约从建议升级为必选

**M3-2 GoodPoint = 快照 = bake 三合一**（A3、A14，升级为硬约束）
- 依据：Blender 手册"bake 在 finalized 后最有意义"；实测 realize 0.19ms；**GN 路由下 obj.data 是空的，导出前必须 realize**
- 验收：① 打锚点原子地完成"存快照 + realize + 写 GoodPoint（含 thought_refs）"；② realize 后再改参数不生效的语义有测试；③ **A26**：bake 后禁止在网格上累积操作，必须回参数层（有拒绝路径）

**M3-3 语义宣告**（A7、A21）
- 依据：Berlage——script 与 inverse 结果不同，混用摧毁心智模型；实测删顶层 ≠ 回到过去（17152→1058 是"少一层加工"）
- 验收：① UI/文案区分「删一层加工」与「回到某时刻」两个操作；② script/inverse 的选择写进文档并在 API 命名中体现

**M3-4 影响预览**（B7）
- 依据：Cass 2006——人自发偏好 cascading undo，所以必须显式显示"将影响 N 个下游"，否则是背叛心智模型
- 验收：推翻 Thought 前静态算出因果闭包，显示「将重推 N 段，其中 M 段可能失败」（原型已有 `impact_preview`，转正）

**M3-5 L3 重推改为 zipper 式惰性调度**（A31 后半）
- 依据：Okasaki 惰性 thunk 把 50ms 摊到多次读；zipper = one-hole context，左侧历史零拷贝
- 验收：重推后下游节点标为 thunk，读时才算；连续回退/分叉不急切全推

### M4 · 编译层

**M4-1 ✅ GNAdapter（版本隔离层）**——已完成
- 已封住 9 个坑（`items_ui→items_tree`、`properties.inputs[id]["value"]`、invalidate、类型校验、环回滚、zone 无名 socket、parm3 拒绝、realize、dump 确定性）
- 待办：把「版本守卫 + 漂移点清单」写成文档，新版本 Blender 发布时照单检查

**M4-2 GNArtifact 类**（A11）
- 内容：持有 node group 引用 + `socket_map`（语义名→identifier）+ `param_values`
- 验收：与 `dump()/fingerprint()` 打通；两个 GNArtifact 能 diff

**M4-3 compile_plan() 转正**（A13）
- 现状：`gn_console.py` 的 `compile_and_mount` 是原型
- 验收：从声明式 spec（段落/参数/Thought 绑定）到 opinion 层全链编译；编译失败时错误信息**指向 spec 的哪一段**（可定位性）

**M4-4 逃逸舱**（A17）
- 依据：UV 展开/绑定/动画关键帧/雕刻/重拓扑 GN 做不了（实测清单）
- 验收：`Step.escape_hatch: bool`；escape 段必须走 ops 且**强制**打快照（不可逆边界）

**M4-5 ★ 破坏性段落 SDF 中间表示**（A30）
- 依据：Blender GN 已原生内置 `sdf_grid_boolean`；SDF 布尔 = min/max，交换/可逆/局部
- 内容：含布尔/切割/偏移/平滑的段落用 SDF；窄带分辨率作为段落参数写入 GoodPoint；自由雕刻段落跳过
- 验收：① 同一布尔用 SDF 与普通 Mesh Boolean 各跑一次，verifier 都过；② 窄带分辨率变更触发重算；③ 内存对比数据记录在案

**M4-6 参数具名化与量化**（HDA 契约 + 第 1 路）
- 依据：LLM 靠名字理解参数；连续 float 是缓存杀手（会 defeat backdating）
- 验收：① 参数名必须是艺术家语义（ParamSpec 已拒 parm3）；② 每个 float 参数带量化步长，写入 spec

### M5 · 交互层（导演模式的前置，B 系列）

| 项 | 内容 | 验收 |
|---|---|---|
| B1 | 段落边界只交三样：**渲染 diff** + 一句"这段做了什么" + **一条**可反驳假设 | 边界对象字段固定为这三个 |
| B2 | 反馈做成 **A/B 二选一**，不用 approve/reject | 无 approve 按钮；61.4% agent PR 零评审是依据 |
| B3 | 接受与打回**点击成本完全相同**；override 率作为唯一健康指标 | 打回不需要填表；override 率有埋点 |
| B4 | 边界处**先让人预测再揭晓** | 先出渲染图，AI 的说法延迟注入 |
| B5 | ThoughtGraph = **可一键反驳的按钮** + partial explanation（结论+关键理由，留白） | 点反驳 = 重做该 Thought；默认只展开分叉点/可争议假设/已回退决策 |
| B6 | 面向人的建议**入队到段落边界**；面向 AI 的 verifier **每次写后立即跑** | 两条通路分开，互不阻塞 |
| B8 | 段落 = 上下文压缩边界；ThoughtGraph 压成 <4000 token 的 `PROJECT.md` | 每段结束写 recap；压缩函数有 token 预算检查 |

**段落粒度判定线**（写进编译器）：人看渲染图 **3 秒内**能说好看/不好看 → 边界成立；需要先读文字 → 切太大。

### M6 · 经验库

**M6-1 多样性闸门**（A8）
- 依据：Doshi & Hauser 2024 / Kobiella CHI'26 / Agarwal CHI'25——高迭代+AI 建议=收敛到平庸
- 验收：返回强制拉开差异的 N 候选（非 top-1），显式标注"本段取自经验库 #X，相似度 Y%"

**M6-2 经验条目契约**（第 1 组 HDA + 第 5 组）
- 验收：① 版本字段 + changelog；② 仅 promote 少量参数；③ 参数名艺术家语义 + 单位 + 取值域；④ 带"适用前提"与作用域限制（subshape 识别 NP-hard，不加作用域定位会爆炸）；⑤ 原子单位是"规则"不是"成品网格"

**M6-3 override 回写**：每次 override 写回 ExperienceLibrary（第 3 组）

### M7 · 导演模式放开（最后）

前置条件：M1–M6 全部完成。放开后必须带：
- override 率监控（**长期为 0 = 人已经不看了 = 系统失效**）
- 总时长监控（HBR 2026：AI 不减少工作而是**加密**工作——只降单段成本可能让人开更多段更累）

### M8 · 融合工程：并入 blender-mcp-skill（详见《融合可行性报告》）

> 载体仓库：`master666-max/blender-mcp-skill`（v2.9.4，MIT 分区许可，Agent Skills 标准，
> MCP 三层传输 + AST 沙箱 + 96 条款发布门 + ED25519 签名）。已克隆至 `_external/blender-mcp-skill`。
> **融合方向已定：本会话编译架构为核，仓库为载体**（理由见可行性报告第二节：
> 核心有实测数字、执行模型更优——AI 写规格而非代码，消灭其第一大错误类与原生崩溃风险、
> 测试资产现成、双方独立实测出同一条 API 生死簿、MIT/同版本/同文档语言零摩擦）。
> 同步方向**单向**：会话 workspace → 仓库 release；会话项目为源。

| 项 | 内容 | 验收标准 |
|---|---|---|
| M8-1 | 建 integration 分支；`compiler/` 新目录收录 `core_types/gn_adapter/gn_verify/gn_console` 四模块，加 provenance 头（源自本工单） | check-deploy 基线更新后全 PASS；单向同步约定写进分支 README |
| M8-2 | brickfly fork（默认通道）注册 4 工具：`gn_compile(plan_json)` / `gn_verify()` / `gn_checkpoint(name)` / `gn_revert(target)` | 协议 7 能力集自报 +1；`get_addon_status` 走 F-148 三态判据（判据表同步）；四工具各有 happy path + 1 反向探针 |
| M8-3 | references/15-compiler-route.md 新分册（编译路线/三层回退/verifier/北极星）；**重写** references/05：双路线（编译优先/自由代码兜底），"三种写法生死簿"取两方并集 | 新分册过其文档纪律（实测/文献双标记）；05 保留原 75 行有效内容 |
| M8-4 | SKILL.md 任务路由表 +1（结构化建模路线）；铁律 +2（改参必失效 / pivot 后只许 forward recovery）；版本 **v2.9.4 → v2.10.0（minor）** | 96 条款全 PASS + 12 反向探针全过 + ED25519 重签 + CHANGELOG 按其格式记 minor |
| M8-5 | evals 增补：26 条 live 测试 → 条款；EXP-1 的 11 份候选 → 回归集；**新增"verifier 逃逸率=0"条款** | runner 全 PASS；回归集跑通 11/11 |
| M8-6 | 纪律对齐：物体默认前缀（`TUT_`/`MCP_SKILL_TEST`）、`tree.is_modifier = True` 进 adapter.attach、确认不 `save_mainfile` | attach 后 modifier 出现在其文档所述位置；console 建的物体全部带前缀 |
| M8-7 | experience/ 收录本会话实测 5 条：迭代 5.9×、三档回退 0.6/0.7/50ms、GN 静默失败三坑、EXP-1 首版 0%→80%、GN 无局部重算+红绿解法 | 每条按其 EXP 格式（【实测】标记）；INDEX.md 登记 |

**M8 依赖与顺序**：M8-1 不依赖任何项（可立即做）；M8-2 依赖 M1–M3 编译核心定型；
M8-3/4/5 依赖 M8-2 的工具面定型；M8-6/7 随时可做。
**执行纪律**：融合全程遵守对方版本纪律——**每一处破坏以通过其 96 条款门 + 反向探针为完成态**；
`assets/` 两个第三方捆绑包不动；上游回退通道不动。
**2026-09-27 确认：仓库为用户本人所有**——无许可/归属摩擦，改动自由；96 条款门保留作质量自检。

### M9 · 前端与可视化（三阶段，与 M8 并行）

> 背景：本会话目前**没有图形前端**——操作路径 = 对话驱动 headless 脚本 + JSON/Markdown 报告。
> 已定义但未实现的交互面：段落边界三件套、A/B 二选一、FlowAxis 折叠、可反驳假设、影响预览、override 率。
> 约束：MCP exec 沙箱**禁 AI 注册 Panel/Operator/bpy.props**——但 M8-2 之后编译器是**可信模块**，
> 注册 N 面板不受此限（同一条信任边界：AI 写数据，可信代码写 UI）。另守 F-144：主线程绝不被脚本轮询堵死。

| 项 | 内容 | 开发量 | 验收标准 |
|---|---|---|---|
| **M9-1 对话即前端**（Phase 1，随 M8-2 即得） | AI 把段落边界三件套（渲染 diff 图 + 一句话 + 一条可反驳假设）作为工具返回值回传多模态；A/B 二选一与影响预览（N 段/M 段）以结构化文本卡片呈现 | **≈0** | 用户在对话里完成一次完整循环：看 diff → 选 A/B → override 率 +1；返回值格式有 schema |
| **M9-2 Blender N 面板最小控制台**（Phase 2，随 M8-2 addon 侧注册） | FlowAxis 段落列表（DAG 拓扑序、可折叠，显示每段 revision/verifier 状态/受影响占比）；GoodPoint 列表；A/B 对比按钮；override 率计数器 | 小 | Blender N 面板可见"段落 × 状态 × revision"；A/B 二选一按键即可触发回退/重推；**注册代码在可信模块内（不进 AI exec 路径）**；遵守 F-144（timer 纪律） |
| **M9-3 渲染 diff 管线**（B1/A23 的依赖，先于一切图形） | 固定相机位 → 前后渲图 → 感知哈希比对 → 差异区域高亮图；失败（全黑/方差异常）走门禁 | 中 | 同一场景改动前后产出 diff 图与哈希比对记录；全黑/异常能 FAIL |
| **M9-4 Web 只读控制台**（**必须**——用户 2026-09-27 定盘） | 本地静态页读 `mug-console-state/1` JSON（`export_state()` 契约，M1-8 已交付）：流程轴 DAG 图、思维图、override 率曲线、GoodPoint 时间线 | 中（a ✅ schema 已交付 / **b ✅ `m9_web/index.html` 单文件零依赖，13 项无头自检 PASS** / c 本地服务：`cd m9_web && python -m http.server 8000`） | 只读（写操作仍走对话/工具）；离线可用；随包分发；schema 变更必须升版本号 |

**不变量（三阶段共用，先定契约再写 UI）**：渲染 diff 三件套（图 + 一句话 + 一条可反驳假设）、
A28 的 revision/输出 hash、verifier 状态、override 率埋点——**任何前端都是这些状态的视图，不是新的真源**。





---

## 四、红线（禁止事项，与工作项同等效力）

| # | 禁止 | 依据 |
|---|---|---|
| R1 | 禁止用 CRDT 做撤销主干 | Dolan PODC 2020 定理：可撤销 CRDT 只有计数器；且我们单写者 |
| R2 | 禁止再调研/引入里奇流类"演化-回退"方案 | 抛物方程反向不适定；佩雷尔曼证明引擎是单调量（棘轮） |
| R3 | 禁止追求"任意程序自动求逆" | 非单射无唯一逆 + 符号求逆指数慢，双封死；唯一前沿是受限 DSL |
| R4 | 禁止让网格级布尔"可逆" | 信息论封死（多对一）；布尔延迟到烘焙，或走 SDF |
| R5 | 禁止让 LLM 给几何打分 | verifier's law：学习型 proxy 必被攻破；只用机械谓词 |
| R6 | 禁止引用拓扑元素（元素索引/元素名）作为跨步骤引用 | TNP：FreeCAD 十年才部分解决；我们靠"引用可再生物"绕开（A27） |
| R7 | 禁止砍快照层 | Bennett pebble game：纯重算空间代价可超线性；快照是复杂度保险（三条独立路径 + 实测四方背书） |
| R8 | 禁止跳过 `invalidate()` 直接改参数 | 实测三处静默失败：不报错、结果不变、骗过所有检查 |
| R9 | 禁止在 Blender 不同小版本间假设 API 不变 | 实测漂移 2 处；必须走 GNAdapter |
| R10 | 禁止多 agent 链式执行建模 | Cognition 实测链式成功率 20–40%；单 AI + 显式 DAG |
| R11 | 经验库禁止返回 top-1 | 同质化效应：20 次迭代产出 20 个长得很像的模型 |

---

## 五、待定实验（唯一剩余的大未知量）

**EXP-1 LLM 产出 SPECS 的成功率**
- 方法：同一句需求（"做个带把手的马克杯，把手要细一点"），让 LLM 分别产 SPECS（声明式段落）与 bpy.ops 脚本，各 N≥10 次
- 度量：编译/执行成功率、verifier 通过率、首版可用率、与 baseline 的几何偏差
- 现有兜底：adapter 已拦 80% 机械错误（AB 实测）；剩"选错节点/类型对但语义错"未测
- 产出：决定 M4 的编译器要不要加语义 rerank

**EXP-2 A28 的失效阈值标定**：在真实建模负载上标定"失效比例 >X% 走全量"的 X（经验值 40%）

**EXP-3 depsgraph 脏标记可利用性**：若 Python 能读到 GN 内部脏标记，A28 粒度可细化（未核实）

---

## 六、推进顺序与依赖

```
M1 数据层（1-3, 5, 6, 7）──► M2 验证层 ──► M3 回退层 ──► M5 交互层 ──► M6 经验库 ──► M7 导演模式
        │                        │
        └──► M4 编译层（可与 M2/M3 并行）─┘
M8 融合工程：M8-1 可立即做；M8-2 依赖 M1–M3 定型；M8-3/4/5 依赖 M8-2；与 M4–M7 并行推进
```
- M1-1/1-3/1-6 是阻塞项，最先做
- M2 与 M4 可并行（不同文件）
- M7 是唯一依赖全链的项；**前置条件不满足就别放开**——第 6 问"别审了"能被答成"同意"却漏了前提的教训
- M8 与主线并行：融合以**对方 96 条款门 + 反向探针**为完成态，不抢主线资源

---

## 七、证据索引

| 调研 | 产出文件 |
|---|---|
| 跨学科六路（参数化/撤销/交互/编程Agent/图检索/认知） | `算法路线调研` 同级：`跨学科预调研汇总报告.md` + `预调研/` |
| GN 岔路实测（12 轮探针） | `GN岔路调研_编译到GN还是执行bpy.ops.md` + `2026-09-26-blender/probe_*.py` |
| 端到端原型 | `架构可行性验证报告_端到端原型.md` + `blender_console/gn_console.py` |
| AB 错误面实验 | `AB对照实验_错误面可检出性.md` + `blender_console/gn_ab.py` |
| 算法路线六路 | `算法路线可行性汇总.md` + `算法路线调研/*.md` |
| 里奇流裁决 | `裁决_里奇流手术能否解决可撤销.md` |
| 载体仓库融合可行性 | `融合可行性报告_blender-mcp-skill.md` + `_external/blender-mcp-skill/`（已克隆） |
| EXP-1 盲写成功率 | `EXP1报告_LLM盲写成功率.md` + `2026-09-26-blender/exp1_harness.py` + `exp1_candidates/` |
| 会话全量导出 | `会话全量导出_Blender建模想法.md` + `conversation-data.json` |
