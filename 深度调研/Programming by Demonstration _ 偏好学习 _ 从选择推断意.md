# Programming by Demonstration / 偏好学习 / 从选择推断意图

- 原始记录：`agent-6a0a914e13264f61.jsonl`

---

【d3-pbd 调研报告】Programming by Demonstration / 偏好学习 / 从 A/B 选择推断意图

━━━ 一、方法/算法（6 条）━━━

1. **PbD 经典谱系 → 我们是"退化版 PbD"**：Pygmalion（首个 PbD）→ Tinker（Cypher, 1993）→ Eager（预测性 agent）→ 现代 Sugilite 等。Tinker 的核心洞见：多示例演示时系统要像"聪明学生"反问"你怎么决定用哪个分支？"——即**从少量示教中主动追问决策依据**。我们的"A/B 二选一"不是操作序列演示，而是偏好示教：信号弱一个量级。补偿方式有三：① 记录 A/B 的**参数差向量**（Δx），一比一即一个"往哪调"的方向样本；② 主动配对（下一对 A/B 尽量信息量大）；③ 用先验（经验库/其他用户）补方差。

2. **Bradley-Terry + reward model（RLHF 理论基座）**：P(A≻B)=σ(r(A)−r(B))（Bradley & Terry 1952）。InstructGPT 用 ~33K prompt × K=4~9 → 数十万对（已核实）；Anthropic 早期 ~300K 对。RLHF 的样本量对"5 次 A/B"是残酷的参照系——**照搬 reward model 范式必死**，必须换低维参数化模型（见下）。B-Pref（arXiv:2111.03026）还给出教师非理性建模：β=理性系数、γ=短视折扣、skip=弃权——启示：UI 要提供"都不满意"选项，且弃权样本应剔除而非计入。

3. **Preferential Bayesian Optimization（PBO，最适配的骨架）**：Chu & Ghahramani 2005（ICML）：GP 先验 + probit 似然建模成对偏好；Brochu et al. 2010 教程明确演示了在**材质参数空间（BRDF）**上用偏好画廊 + EI 采样找用户心仪参数——这是"设计参数空间"的先例（已核实）。LineSPAR（Cheng et al. 2020）：高维偏好 BO + 真人实验（辅助设备参数），6 维约 40-60 次迭代收敛到 0.95+——注意：**远超 5 次**，说明 GP 版需要 40+ 轮；5 次量级必须用低维线性/树模型。qEUBO acquisition（Lin et al. 2022 / Astudillo et al. 2023）直接给出"下一对 A/B 怎么出"的公式：最大化期望最优效用，且 k=2 时与"菜单选择"对偶（Viappiani & Boutilier）。

4. **可解释偏好模型（对信任校准直接有用）**：① 决策树代理替代 GP 做 PBO（arXiv:2512.14263）：天然可解释、能拟合"spiky"审美空间、支持用户树→物品树的冷启动迁移；② LP-tree / CP-net 等定性偏好模型（arXiv:1909.09064）：可视化"先比 A 属性、再比 B 属性"的字典序；③ ILASP：从选择对学出**英文规则**（"用户偏好少换乘>少走路"）——正是"你喜欢薄壁+大把手半径"的产出形态。④ Fargier et al. AAAI'18：只从**正例**（选中的物品历史）就能学 LP-tree——连被拒项都不需要。

5. **样本量实证（Qian et al. PVLDB 2016）**：自适应成对比较学用户偏好，真人实验：**~20 次比较前自适应反而输给随机**；30 次时精度 83%（随机 75%）；且"通用偏好"精度显著低于个体模型——**用户的偏好确实是异质的**。

6. **冷启动（Bonilla et al. GPPE, NICTA）**：GP 先验建在（用户特征 × 物品特征）联合空间，从老用户的偏好超参泛化到新用户——形式化答案："新用户默认值 = 经验库中相似用户的后验均值"，不是全体平均（见反直觉 2）。

━━━ 二、设计转译（6 条）━━━

1. **选择即梯度**：用户选 A 后，计算 Δx = x_A − x_B，做在线 BT 逻辑回归更新权重 w：w ← w + η·σ(−w·Δx)·Δx。5 次选择 = 5 个方向样本，d≤8 个参数时可收敛出粗略偏好方向。
2. **出题算法**：第 n+1 轮 A/B 用 qEUBO/EI：在前 5 个选择后，从生成器采 50 个候选参数组合，挑出使 |μ(w·(x_i−x_j))| 最近 0 且 Δx 覆盖不同参数轴的两个——即"最让系统拿不准的一对"。
3. **建议合成**：经验库 suggest() 给"人群先验 μ_0"，个人 BT 模型给"偏移量 w·x"，最终参数 = argmax(μ_0(x) + λ·w·x)，λ 随个人数据量从 0→1 增长（shrinkage 冷启动）。
4. **可解释报告**：每 5 轮后用决策树代理拟合成对选择，输出规则卡："9/10 次你选了壁厚<3mm 的变体（置信度 0.82）"——用 LP-tree/ILASP 风格产出自然语言规则。
5. **弃权通道**：A/B 卡片加"都不满意"，弃权对按 B-Pref 的 skip 机制剔除，并触发"重新生成而非调参"分支。
6. **经验库双写**：每次选择以 (任务特征, Δx, 结果) 写入库，作为下一个新用户的 GPPE 式先验。

━━━ 三、反直觉/打脸（4 条）━━━

1. **"5 次选择能学会 reward function"是幻觉**：RLHF 用 10^5 级样本，GP-PBO 真人实验 40-60 轮收敛。5 次 A/B 最多支撑 d 维线性方向估计 + 强先验。产品叙事应是"渐进校准"而非"学会了你的审美"。
2. **经验库"平均偏好"当默认值是错的**：Qian et al. 证明用户偏好异质，通用偏好模型精度显著更低。平均是先验不是答案；应按任务/用户特征检索相似子群。
3. **主动提问早期有害**：前 ~15 次比较，自适应选题精度低于随机（真人数据）。冷启动期应先随机/覆盖式出 A/B，攒够 ~15 对再开 active learning。
4. **BT 模型并非必要**：Rethinking BT（arXiv:2411.04991）证明 reward 只需保持序一致性（monotonic 变换下等价），任何序一致分类器皆可——工程上可直接用逻辑回归而非完整 GP。

━━━ 四、MVP 伪代码（≤30 行）━━━

```
# 状态: w (d维偏好权重), prior_mu (经验库人群先验), D=[] (选择历史)
def update_choice(xA, xB, chosen):          # 每次A/B选择后调用
    dx = xA - xB                            # 参数差向量(归一化)
    y = +1 if chosen == 'A' else -1
    D.append((dx, y))
    for _ in range(3):                      # 在线BT/逻辑回归(序一致即可)
        p = sigmoid(y * dot(w, dx))
        w += lr * (1 - p) * y * dx          # 朝"该往哪调"的方向走一步
    w = shrink(w, prior_mu, t=len(D))       # 先验收缩: 样本少→偏向prior

def suggest_next_pair(pool, n_choose=15):
    if len(D) < n_choose:                   # 冷启动: 随机覆盖式出题
        return random2(pool)                # (反直觉3: 早期主动提问有害)
    cands = sample(pool, 50)
    def info_gain(xi, xj):                  # qEUBO简化: 挑最不确定的一对
        return -abs(sigmoid(dot(w, xi-xj)) - 0.5)
    return argmax_pair(cands, info_gain)

def recommend_params(x_context):
    return argmax(pool, prior_mu(x) + lam(len(D)) * dot(w, x))

def explain():                              # 可解释规则卡
    rules = fit_decision_tree([ (dx, y) for dx,y in D ])
    return render(f"近{len(D)}次: 你偏好 {top_features(rules)} (置信{acc:.0%})")
```

━━━ 五、文献（已核实 8 条）━━━

1. Cypher, A. (1993). *Watch What I Do: Programming by Demonstration*. MIT Press.（含 Tinker/Eager 章节，acypher.com/wwid 可读全文）
2. Chu, W. & Ghahramani, Z. (2005). Preference Learning with Gaussian Processes. ICML '05, pp.137-144.
3. Brochu, E., Cora, V.M. & de Freitas, N. (2010). A Tutorial on Bayesian Optimization of Expensive Cost Functions (含 active user modeling/BRDF 偏好画廊实验). arXiv:1012.2599.
4. Cheng, M. et al. (2020). Preference-Based Bayesian Optimization in High Dimensions with Human Feedback (LineSPAR，真人实验). SCMLS@SDM.
5. Kim, S. et al. (2023). B-Pref: Benchmarking Preference-Based Reinforcement Learning. arXiv:2111.03026（教师非理性建模：β/γ/skip）.
6. Qian, Y. et al. (2016). Learning User Preferences By Adaptive Pairwise Comparison. PVLDB 8(11), p.1322（真人研究：~20 次阈值、偏好异质性）.
7. Bonilla, E., Guo, S. & Sanner, S. (2010). Gaussian Process Preference Elicitation（冷启动：老用户泛化到新用户，sushi 数据集）. NeurIPS.
8. Sun, H., Shen, Y. et al. (2024). Rethinking Bradley-Terry Models in Preference-Based Reward Modeling. arXiv:2411.04991（序一致性理论）.
9. 【未核实】Lin, Astudillo et al. (2022). Preference Exploration with qEUBO——仅经第三方综述转引，未直接读原文。
10. 【未核实】Lee, J.D. & See, K.A. (2004). Trust in Automation. Human Factors 46(1)——团队上下文已引用，本轮未独立检索原文。

补充核实来源：RLHF 样本量（InstructGPT ~33K prompt / K=4-9 → 数十万对；Anthropic ~300K）来自公开技术综述与 MemX glossary 汇总，非原始论文直接核对，量级可信、精确数字标【弱核实】。