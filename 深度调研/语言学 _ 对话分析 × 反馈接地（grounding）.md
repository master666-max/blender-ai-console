# 语言学 / 对话分析 × 反馈接地（grounding）

- 原始记录：`agent-4a518980575c4b8d.jsonl`

---

【deep-ling 语言学/对话分析 × 反馈接地 调研报告（深度版）】

## 一、深读发现

1. **Clark《Using Language》(1996)：贡献 = 呈现 + 接受两阶段**。沟通是联合行动，每条反馈都要获得"足够当前目的的 closure"证据才算落地；证据分层（行动阶梯 L1注意→L4联合项目），且"最小协作努力"原则决定人只付出最便宜的证据。→ 定位器约束：AI 不能只解析，必须在"段落边界"回放它理解的锚点（接受阶段的替代物），否则用户拿不到 closure，会重复/升级反馈。
2. **Clark & Wilkes-Gibbs (1986)：指称是协作过程而非一次性解码**。专家用递减式初始化（initial reference 越说越短），听话方用"过肩确认"校准。→ 约束：指称解析必须维护 per-referent 置信缓存，第二次"把手"应复用首次解析历史，且当置信下降时把历史判定作废（common ground 被上次执行结果污染）。
3. **Searle (1976) 言语行为五分类 + 间接言语行为**：断言（词→世界适配方向）、指令（世界→词）、表达（无适配方向）。"太粗了"表面是 expressive/assertive，实质通过"负评价+缺陷预设"间接执行 directive。→ 约束：定位器必须做 force 投影：expressive 表层 → (directive, 算子=减, 参数=粗细维度)；"太"是程度算子，隐含"超出预期带"而非绝对值。
4. **Repair 组织（Schegloff, Sacks & Jefferson 1977；Colman & Healey 2011）**：修正分四型（自启自修/自启他修/他启自修/他启他修），自修在真实对话中比其他所有类型加起来还多；修正发起有强度梯度（"呃?"最弱，"你是说X吗?"最强）。→ 约束："不，是再细一点"= P3 型自启自修，解析器必须把 trouble source 定位到上一条反馈的假设层（推翻"7mm 握感舒适"），而不是把"再细一点"当独立指令。
5. **澄清请求分类（Purver, Ginzburg & Healey 2003）**：CR 有 wh-问、片段复现、reprise、规约指示四种表面形式，可按"针对哪一层（信号/内容/意图）"分层。→ 约束：AI 的澄清问句应分层生成——意图层（"是想把径向变细吗"）优先于信号层（"哪个把手"），且最省力的 CR = 复述候选锚点让用户确认（对应"猜测式修正发起"，修正成本最低）。
6. **grounding 时机（Naszádi et al. EMNLP 2023 Findings；Dong et al. 2026 VoI 框架）**：何时问不用硬编码规则，用行动模型的不确定性/信息价值（VoI = 问的期望效用增益 vs 打断成本）决定。→ 约束：与"不在段落中间打断"纪律的调和方案 = **段落边界统一做 grounding check**：定位置信 < 阈值或下游重推成本高（VoI 大）时，把澄清排队到段落末尾；置信高则"执行+显式说出假设"（attempt-then-verify），不打断。

## 二、设计转译（定位器输入 X → 数据结构 Y）

1. **言语行为投影表**：输入"把手太粗了" → 先过 force 分类器 → {force: expressive表层/directive实质, polarity: 负, 程度: 太(超预期带), 维度形容词: 粗} → 结构 `FeedbackAct{act_type, operator(+/-), dim, degree, presuppositions[]}`。关键词重叠法跳过了这一步，所以无法区分"粗了"(改细)与"不够粗"(改粗)。
2. **维度词→参数通道映射表**：粗/细→半径/厚度通道；长/短→长度通道；胖/瘦→截面比；每词带默认通道集与歧义标记。"粗"在把手语境映射 {radius, thickness}，歧义度=2 需消歧。
3. **指称解析两段式**：名词短语 → 候选对象集（Blender 场景对象级）→ 唯一可辨识性检验（Clark & Marshall 1981）：候选=1 直接通过；候选>1 时按语境显著性排序；候选=0 时进入失败分支。输出 `RefAnchor{candidates[], confidence, resolution_path}`——不做 AZURITE 式的区域选择，先做对象/修改器节点级候选。
4. **"把手太粗了"最小正确解析管线**（分步，含失败分支）：
   - S1 指称解析："把手"→场景中把手 mesh 节点。失败 F0：0 个候选 → 入队澄清（段落边界发出："场景里我没找到把手，是指哪部分？"）；>1 个 → 按"最近被用户选中/最近创建"显著性取 top1，同时在回放中说"我理解为水杯的把手，不对请纠正"。
   - S2 言语行为投影：expressive→directive，op=reduce，dim∈{radius,thickness}。
   - S3 假设层定位：在思维图上找绑定该节点的参数 Thought，如"把手半径 7mm：握感舒适"——这就是要推翻的假设；生成 `HypothesisOverride{thought_id, new_op: reduce, dim: radius}`。
   - S4 参数语义化：无绝对数值 → 从 Thought 里的 7mm 取当前值，按"太"的程度算子给重推器一个方向+相对幅度（如 -20%±），而不是猜死数值。
   - S5 失败分支 F1：思维图中该节点无参数 Thought（用户从未显式设置）→ 定位退化为修改器节点级（Subdivision/Solidify 检查），仍失败则升级澄清。
   - S6 段落边界回放："已把把手理解成变细（半径 7→5.6mm），推翻了'7mm 握感舒适'这条假设并重推了倒角下游"——这是 Clark 接受阶段的机器版。
5. **修正缓冲区（Repair Resolver）**：输入增量反馈流 → 检测修正标记（"不/不是/是…一点"）→ 输出 `RepairOp{target: 上一条 FeedbackAct, type: P3自修, delta: "再细一点"→在已减基础上追加 -10%}`。"再"字触发的增量语义要求把上次执行量存进 common ground 状态机，而非每轮从头解析。
6. **VoI 门控**：每次解析输出 `grounding_decision{ask_now: bool, question?: CR, assumptions?: list}`，ask 条件 = (RefAnchor.confidence < θ) OR (dim 歧义度≥2 AND 重推成本>阈值)。这直接实现"打断纪律"：问句永远排队到段落边界。

## 三、反直觉/打脸

1. **关键词重叠错在最深的一步不是语义，是言语行为**。"太粗了"没有任何指令性词汇，但必须解析成指令——不建 force 投影层，embedding 相似度再高也只会返回"粗"字命中的节点，而不是"要推翻的 Thought"。
2. **backchannel 式 AI 确认不是好方案**：HCI 文献支持 attempt-then-verify 优于高频提问（VoI 框架实测打平或超过调优阈值基线）；频繁澄清正是 RLHF 训练会惩罚、用户也讨厌的行为。所以"AI 不打断"不仅合乎纪律，也合乎实证。
3. **最常见修正不是"AI 听错了"**：CA 语料统计里 P1SISR（说话人话中自修）占绝对多数——用户大多数修正发生在自己说话中途，即增量输入本身带修正；定位器若按"每条消息=一条完整指令"设计，会把用户自我修正解析成重复指令。
4. **唯一可辨识性对我们反而是低风险**：建模场景候选集天然小（当前编辑对象显著），真正的难点不在选对象而在"粗"映射到哪个参数通道——指称文献把全部努力放在消歧对象上，对部分参数级指称（"这个圆角"）只有 ShapeGlot 触及，是我们的空窗也是机会。

## 四、现成工具/模型/数据集（已核实）

1. **RefCOCO/+/g**（Yu et al. 2016；Mao et al. 2016）：2D 指称理解标准数据集，~142k 表达式；当前 SOTA 已 90+（Qwen-VL 系、Grounding DINO）。成熟度：极高，但对象级 bounding box，无参数级。
2. **ScanRefer / Nr3D / Sr3D**（Chen et al. ECCV 2020；Achlioptas et al. 2020）：3D 点云指称定位，ScanRefer 51,583 条描述/800 场景，98.7% 用到空间关系。成熟度：高；但均为真实扫描场景，非 CAD 参数模型。
3. **ShapeGlot**（Achlioptas et al. ICML 2019）：4,511 个 ShapeNet 椅子、78,789 条指称表达，专为"仅靠形状区分"设计；消融证明模型自发学会部件词→部件几何的对应。成熟度：中高；是与我们最同构的数据集（CAD 模型+部件级语言+RSA 语用模型），值得直接借用其 listener 架构与 part-word 消融方法。
4. **Text2CAD**（NeurIPS 2024 spotlight）：自然语言→参数化 CAD 操作序列（DeepCAD 数据 ~170k 模型、660k 描述）。成熟度：学术原型级——"recognizable ≠ 尺寸准确"，反向证明了"语言→参数精确值"仍是开放问题。
5. **Grounding DINO**（Liu et al. 2024）：开放词汇检测+指称定位，341M 可微调，RefCOCO 90.6。成熟度：高，可作为场景对象候选生成器。
6. **SWDA（Switchboard Dialog Act Corpus）**：42 类对话行为标注，语言行为分类器训练资源。成熟度：高，但为电话对话域，需迁移。

## 五、文献

1. Clark, H. H. (1996). *Using Language*. Cambridge University Press. （Ch.8 Grounding）
2. Clark, H. H., & Wilkes-Gibbs, D. (1986). Referring as a collaborative process. *Cognition*, 22(1), 1–39.
3. Schegloff, E., Sacks, H., & Jefferson, G. (1977). The preference for self-correction in the organization of repair in conversation. *Language*, 53(2).
4. Searle, J. R. (1976). A classification of illocutionary acts. *Language in Society*, 5(1), 1–23.
5. Purver, M., Ginzburg, J., & Healey, P. (2003). On the means for clarification in dialogue. *SIGdial*.
6. Colman, M., & Healey, P. G. T. (2011). The distribution and repair of blemished turns in conversation. *CogSci*.
7. Naszádi, K., et al. (2023). Aligning predictive uncertainty with clarification questions in grounded dialog. *Findings of EMNLP*.
8. Dong, Y. R., et al. (2026). Value of Information: A framework for human–agent communication. arXiv:2601.06407.
9. Achlioptas, P., et al. (2019). ShapeGlot: Learning language for shape differentiation. *ICML*.
10. Chen, D. Z., Nießner, M., & Chang, A. X. (2020). ScanRefer: 3D object localization in RGB-D scans using natural language. *ECCV*.

（未单独核实的推断均已用上列文献支撑；字数约 1580）