# NLG / 几何变更描述 / 结构化数据到文本

- 原始记录：`agent-d0d72890f9e348fc.jsonl`

---

【NLG / 几何变更描述调研报告】

## 一、方法/系统与匹配度

1. **模板/规则式 Data-to-Text（SUMTIME-METEO、NWS 预报术语表）**：Reiter 等（AIJ 2005）研究了天气预报文本中"风速→措辞"的映射，发现人类预报员用固定阈值带选词（如 15-25mph="breezy"，20-30mph="windy"），NWS 官方至今维护这种"数值区间→术语"对照表。与我们场景高度匹配：verifier 的数值差本身就是结构化数据，阈值带化后可直接套模板。匹配度 ★★★★★。
2. **神经 NLG 与错误分类学（INLG 2024, Huidrom/Belz/Lorandi）**：对 15 个系统（3 规则式 + 12 神经含 LLM）在 WebNLG 上的语义错误做标注，结论：**规则/模板系统语义错误最少，LLM 的主要问题是"多余内容"（superfluous）**。支持"模板保真 + LLM 润色"的混合架构。匹配度 ★★★★。
3. **QUINTD（Kasner & Dušek, ACL 2024）**：无参考评测框架，发现开源 LLM 做 data-to-text 时 76-86% 输出含至少一个语义错误，且**流畅度会掩盖错误**（"fluency mask"）；实践经验：显式标注单位、用 response prefixing 可显著降低错误。匹配度 ★★★★（直接指导我们的 LLM prompt 工程和守卫设计）。
4. **ShapeTalk / ChangeIt3D（CVPR 2023）**：53.6 万条 3D 形状差异描述，30 类物体。但注意：它是**比较句**语料（"这个杯子的把手比那个细"），且任务方向是语言→编辑而非编辑→语言。不能直接用，但其词汇分布（部件、粗细/高矮等维度属性、开口等拓扑）是现成的"变更类型词汇表"。匹配度 ★★★（当词表和模板挖掘语料用）。
5. **Text2CAD（NeurIPS 2024）**：17 万 CAD 模型 + 66 万条文本，分 L0-L3 四级粒度（抽象→精确参数）。其多粒度理念和"预处理元数据以降低 LLM 幻觉"的管线可直接借鉴：我们同样该做两级输出（自然语句 + 括号内精确数值）。匹配度 ★★★。
6. **数值模糊量化研究（Williams & Power, ENLG 2009；numeric hedge words 研究, 2014）**：语料发现人类写数值时**先模糊后精确**——文档前部用"约三分之一"，后部才给"32.4%"；对 hedge 词（about/almost/approximately）的实证解码显示人类解读离散成约 3 档。证明"变矮了一点"不是不严谨，而是符合人类表达惯例。匹配度 ★★★★★。

## 二、设计转译（verifier 谓词 → 语言）

1. **数值带化表（NWS 式）**：|相对变化|<2% 不报；2-10%→"一点/略微"；10-30%→"明显/了不少"；>30%→"一大截/大幅"。每档配中英双语模板槽位。
2. **多谓词融合才能说"人话"，单谓词不许过度解读**：面积差单独只能生成"表面积减小了约 15%"，**不能**直接生成"变矮了"——那需要 bbox.Z 减小 + 面积同向 + 无拓扑变化的联合证据。融合规则例：Z↓ + 面积↓ + 非流形/零面积无新增 →"整体变矮了一点（高度 85→77mm，−9.4%）"。
3. **bbox 轴向→方向词表**：X→变宽/变窄，Y→变深/变浅，Z→变高/变矮；两轴以上联动时降级为"整体变大/缩小"。
4. **拓扑谓词重映射**：非流形/零面积面是**错误状态**不是语义编辑，应输出"模型出现结构问题：2 个非流形边"，绝不能说"开了个洞"——"开洞"需要 genus/欧拉示性数对比，当前 verifier 缺此谓词，建议补（这是映射完备性的已知缺口）。完备性评估无现成文献结论【未核实】，实用做法：用 ShapeTalk 高频属性词（厚薄/高矮/开洞/弯曲/部件增删）做 checklist 对照现有谓词。
5. **LLM 角色限定为"改写与合并"**：Python 模板层产出严格 JSON（每条事实带 predicate_id、old/new/band），LLM 只做语序润色与聚合，temperature=0，system prompt 明令"不得引入 JSON 之外的任何变更"；事后用谓词回查（把生成文本反解析回谓词 diff，比对是否一致）——字符串相似度指标（BLEU）检不出幻觉，回查可以。
6. **优先级排序**：穿地/非流形等"问题类"排在最前（可操作），尺寸类其次，面积/复杂度最后。人类先模糊后精确：首句用带化措辞，括号给精确数。

## 三、反直觉/打脸

1. **"直接丢给 GPT-4"不保险**：QUINTD 显示 LLM 的 data-to-text 流畅但错误率高，天气预报和时序数据最难（数值密集）。我们输入小（7 个谓词）风险低很多，但守卫（回查）必须做。
2. **模板不是低级方案**：INLG 2024 实证模板系统语义错误最少；van der Lee 等（INLG 2018）也发现模板化可在多种情况提升质量。工业界落地系统（气象/金融）全是混合式。
3. **"变矮了一点"比"−9.41%"更"正确"**：人类语料显示模糊量化是惯例而非缺陷，且 hedge 词的有效档位只有约 3 个——阈值带不用做细。
4. **ShapeTalk 直接用会翻车**：比较句("A 比 B 高")≠变更日志("从 v1 到 v2 变高了")，任务方向也相反；直接套用会生成通篇"比"字句。

## 四、立刻可做的原型

模板 schema（单条变更记录）：
```json
{
  "predicate_id": "bbox.Z",
  "old": 0.085, "new": 0.077,
  "rel_change": -0.094,
  "band": "slight",            // negligible|slight|noticeable|major
  "category": "dimension",     // dimension|topology|complexity|placement|error
  "fusion_evidence": ["bbox.Z↓", "area↓", "topology=unchanged"],
  "template_zh": "{主体}变{方向词}{量词}",   // → "杯子变矮了一点"
  "precise_zh": "高度 85→77mm（−9.4%）",
  "priority": 2
}
```
流程：verifier diff → 带化 → 融合规则 → 模板产出 → （可选）LLM 润色 → 谓词回查。半天可写完，先不接 LLM 也能用。

## 五、多语言

未找到中文 3D 变更描述数据集【未核实】。最接近的是 PartNet-M-Desc（GPT-4 生成的中文 PartNet 部件描述，非变更对）和 Cap3D（英文 caption）。建议自建：先中英模板对照表（变薄/变宽/高了一截），量大后再考虑回译 ShapeTalk 子集。

## 六、文献

1. Achlioptas et al., ShapeTalk, CVPR 2023 (changeit3d.github.io)
2. Huidrom, Belz, Lorandi, Differences in Semantic Errors Made by Different Types of Data-to-text Systems, INLG 2024
3. Kasner, Dušek, Beyond Traditional Benchmarks: Analyzing Behaviors of Open LLMs on Data-to-Text Generation, ACL 2024
4. Reiter, Sripada, Hunter, Yu, Davy, Choosing Words in Computer-Generated Weather Forecasts, Artificial Intelligence 167(1-2), 2005
5. Williams, Power, Precision and Mathematical Form in First and Subsequent Mentions of Numerical Facts, ENLG 2009
6. van der Lee, Krahmer, Wubben, Automated Learning of Templates for Data-to-Text Generation, INLG 2018
7. Mishra et al., Storytelling from Structured Data and Knowledge Graphs: An NLG Perspective, ACL 2019 Tutorial
8. Khan et al., Text2CAD, NeurIPS 2024
9. Natural Language of Uncertainty: Numeric Hedge Words, Journal of ASIS&T, 2014（作者名未核实）
10. NWS Forecast Terms 表（weather.gov/bgm/forecastTerms）——数值区间→措辞的行业先例