# 心理学 / 人因工程 × agency 与技能习得

- 原始记录：`agent-2fe39ea921714627.jsonl`

---

【deep-psych 调研结果：心理学/人因 × agency 与技能习得】

一、深读发现（机制/文献/年份 + 一句话 + 架构约束）

1. agency 三条件有神经实证基础，"可否决"是独立条件。Intentional binding（Haggard, Clark & Kalogeras 2002）证明动作-结果时间压缩即 agency 的内隐指标；可预测性是 FoA（感觉 agency）最大因子（Sato & Yasuda 2005；Tanaka & Kawabata 2020 复现：不可预测反馈+时间延迟独立降低评分与 binding）。HCI 实证：语音界面降低 agency、中空/触觉界面升高（Limerick et al. 2014；TOCHI 2022 综述）。约束：AI 输出必须保持"用户动作→结果"的时间邻近与结果可预测性；段落生成延迟越长，越需要过程可见化补偿。

2. "能取消"本身产生 agency。Brass & Haggard 2007 发现意图抑制（veto/"free won't"）有独立神经基质（背内侧前额叶 dFMC），有否决权的行动 binding 更强。约束：你们的"三段回退"是事后撤销，应升级为提交前否决窗口——这是 ≥25% ownership 惩罚最直接的解药。

3. agency 是默认假设，只被反面证据撤销（Chambon & Haggard 的 action-selection fluency 研究；Wenke et al. 2010）：选择越流畅，控制感越高，无需证明"这是你做的"，只需避免不匹配线索。约束：GN 编译失败的报错展示方式要克制——每个"不匹配信号"都在扣 agency 分。

4. Dreyfus 五阶段（Dreyfus & Dreyfus 1980/1986）：新手靠规则、高级新手要快速信息、胜任者要目标、精通/专家要全局与直觉；叠加 expertise reversal（Kalyuga et al. 2003）：对新手的脚手架对专家是负资产。现成系统：SQL-Tutor 自适应褪火（辅助分驱动，学习增益 0.73 vs 0.56，效应量 d≈0.75，Najar, Mitrovic & McLaren，AIED）；"AI as co-regulator"（Frontiers 2026）给出可逆自适应褪火曲线+褪火理由可见性设计。约束："外化判据×专长"可映射成阶梯：新手段落带判据全文→胜任层只留判据名→精通层只给 diff；褪火必须可逆且告知原因。

5. 心理负荷客观测量：瞳孔最可行。TEPR 六十年证据链（Kahneman/Beatty）；IPA/LHIPA 开源算法可分离认知性瞳孔波动与光反射（Weber et al. 2020 验证）；RIPA2（Jayawardena et al. 2025, J Eye Mov Res）实现低延迟实时估计，明确面向 adaptive UI。PupilWare（2015）证明普通 webcam 可测瞳孔，精度接近红外眼动仪，但对深色虹膜/头姿敏感。HRV 可经摄像头 PPG 低成本采集但特异性差（受情绪/光照污染）；EEG 前额 alpha 需佩戴设备，桌面场景成本高。约束：负荷自适应切段可用 webcam 瞳孔做，但必须固定屏幕亮度做基线，且只做"切段/降密度"这种低风险决策，不做高权威判断。

6. 评价焦虑损害的恰好是复杂任务。Evaluation apprehension（Cottrell 1972；Henchy & Glass 1968）：被评价感提升优势反应——简单熟练任务受益，新颖复杂任务受损。A/B 二选一本身选项负担极低（远低于 6-10 项过载阈值），风险不在选项数而在"考试框架"。

二、设计转译（X 改成 Y，因为机制）

1. 「三段回退（事后撤销）」改成「段落提交前 2-5 秒否决窗口 + 一键回退保留」：Brass & Haggard 2007，可否决性是 agency 的独立神经条件，"我能停"比"我能后悔"更能产生所有权。
2. 「AI 直接产出结果」改成「AI 先给参数→预期效果的 mini 映射预览，再编译」：可预测性是 FoA 最大因子（Sato & Yasuda 2005），预测-结果匹配即 agency。
3. 「AI 建议用祈使句呈现」改成「选项+理由+置信度」：被命令执行时 intentional binding 显著下降（Caspar, Cleeremans & Haggard 2016, Current Biology）；SDT 中"控制型"工具触发动机挤出（PLOS ONE 2025 AIGC autonomy paradox）。
4. 「固定判据面板」改成「按 override/接受遥测自适应褪火且可逆、显示褪火原因」：expertise reversal + adaptive fading 证据（Kalyuga 2003；SQL-Tutor d≈0.75）。
5. 「A/B 硬二选一」改成「A/B + '都不满意/重掷'第三出口 + 定向为 steering 而非评分」：评价焦虑在复杂/新颖任务上降低质量（Cottrell 1972），第三出口消解预期后悔、把框架从"被评"改为"我在驾驶"。
6. 「段落长度固定」改成「webcam 瞳孔 LHIPA/RIPA2 连续监测，超阈值自动切段或降密度」：RIPA2 2025 已验证实时可行性且有 adaptive UI 先例。

三、反直觉/打脸

1. 「费力=我的」不完全对：动作选择流畅性本身提升 agency（Chambon & Haggard）——减少摩擦反而增强控制感；但注意与 Kobiella 所有权削弱并存，二者作用于不同层面：流畅性喂养 FoA（即时感觉），努力喂养 JoA（事后归属）。解法：选择界面做流畅，编辑痕迹保留可见。
2. 决策疲劳的"能量账户"模型已被大规模预注册重复失败打脸（Hagger et al. 2016, ego depletion 复现≈0）——不要把"段落间决策预算"建立在资源耗竭上，可建立的只有选项数与结构过载。
3. Intentional binding 对观察到的动作也会出现（Poonian & Cunnington）——内隐测量会被"看 AI 做"污染，不要把 binding 类指标当用户 agency 的直接证据。
4. 越是全自动跑完（减少用户决策点）越危险：AI 认知替代绕过因果归因、直接掏空自主感（Frontiers in Education 2026）——导演模式"AI 整段跑"本身是 SDT 自主感的结构性威胁，段落边界不只是审核点，是归因锚点。

四、可测指标（进 override/评估体系）

- 段落否决使用率（提交前 veto 窗口）：正指标， veto 常用说明用户仍在校准而非 rubber-stamping；零成本（遥测）。
- 显式 JoA 单项量表（"这段有多少是你做的"7 点）：段落边界弹出，零成本，可与 override 率交叉验证。
- A/B 决策延迟与"重掷率"：评价焦虑/过载代理指标，零成本。
- 脚手架褪火触发：判据接受率、跳过率连续 N 次达标则降级外化；零成本。
- 瞳孔 LHIPA/RIPA2：webcam 采集，低成本但需亮度控制与基线校准；建议只做灰盒（切段建议）不上黑盒。
- BPNSFS 短版（SDT 基本需求 6 项）：周级问卷，零成本，监控三需求中最先受损的自主感。

五、文献（均经本轮检索核实，1 条标注部分核实）

1. Haggard, Clark & Kalogeras (2002). Voluntary action and conscious awareness. Nature Neuroscience.
2. Brass & Haggard (2007). To do or not to do: the neural basis of voluntary action inhibition. J Neurosci.
3. Chambon & Haggard (2012) 动作选择流畅性综述；经 Springer Neuroethics 2022 转引核实；Wenke et al. (2010) 原文同源。
4. Caspar, Cleeremans & Haggard (2016). Coercion changes the sense of agency in the human brain. Current Biology.
5. Limerick, Coyle & Moore (2014). The experience of control in HCI. TOCHI 2022 "Sense of Agency and User Experience" 综述。
6. Kalyuga, Ayres, Chandler & Sweller (2003). The expertise reversal effect. Educational Psychologist.
7. Najar, Mitrovic & McLaren. SQL-Tutor 自适应辅助分研究（AIED；效应数据已核实，具体年份【未核实】）。
8. Jayawardena, Jayawardana & Gwizdka (2025). Measuring mental effort in real time using pupillometry (RIPA2). J Eye Mov Res.
9. Cottrell (1972). Social facilitation / evaluation apprehension（经多源核实）。
10. Frontiers in Education (2026). The paradox of AI cognitive substitution；PLOS ONE (2025). The autonomy paradox in AIGC adoption；Ryan & Deci (2017). SDT。

核心一句话：ownership 惩罚的解药不在"让 AI 少做"，而在把 agency 三条件（可预测、邻近、可否决）显式做进段落协议——否决窗口是最便宜也最被实证支持的一刀。