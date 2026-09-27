# 工业设计流程 / 参数化思维 / 设计 Token

- 原始记录：`agent-35a0bff4226c43ed.jsonl`

---

【d3-design 调研报告】工业设计流程 / 参数化思维 / 设计 Token → plan-JSON schema

## 一、核心发现（5 条）与设计流程映射

**1. 专家建模 = "先策略后建模，先整体后细节"。** ASME 实验研究（Olechowski 组, JMD 2024）发现：专家拿到图纸后先解读并规划完整建模策略，迭代和返工显著少于普通用户（后者靠 trial-and-error）；3D 产品建模教程一致采用 "block out 主形状/体量 → 细化几何 → 修拓扑" 三步。工业设计公司流程（如 Sinclair：草图定稿 → Blender 快速 3D 验证比例 → SolidWorks 结构化）也证明：**比例/体量决策先于细节**。
→ 映射：plan-JSON 应强制"段落有序"——先 body（体量与主参数），后 handle/details（引用 body 参数），最后 finish（倒角/渲染）。AI 的 plan 应先输出"设计意图/策略"字段再输出几何段落。

**2. 实证研究支持"可改性"作为一等目标。** 30 名职业工程师对照实验（CAD 期刊）：以"易于修改"为目标的组比"求快"组多花 25% 时间，但模型更易改；Camba & Contero (CAD 2016) 比较了 Delphi 横向建模/显式参考建模/resilient modeling，结论：**减少不必要的特征父子依赖**是模型可复用的关键。
→ 映射：plan-JSON 中参数应集中声明（token 层），特征只引用不硬编码；依赖边要最小化、显式声明，而非隐式。

**3. 成熟 CAD 的参数表最佳实践（Fusion 360/Onshape 社区共识）。** 参数名无空格、snake_case、描述物理用途而非特征号；显式单位；每参数带 comment；表达式驱动派生（如 FlangeHeight = WallThickness * 3）；按前缀分组（p_ 产品输入 / s_ 零件尺寸 / c_ 计算派生）；改一个参数即测 rebuild。Design token 三层体系（global→alias→component）同样适用于实体产品：物理产品 token 就是 key:value 对（如 table-cornerRadius: 50mm），改 token 文件即可全产品变体（Mejlvang 的 Stykka/ShapeDiver 实践）。
→ 映射：plan-JSON 需要 `tokens`（全局值）+ 每段 `parameters`（引用 token 或表达式），字段必须含 name/unit/value/comment/role。

**4. 人机工学范围可直接做成 verifier 硬约束（均有行业来源核实）。** 杯口直径 75–95mm、杯高 90–115mm、容量 240–355ml（主流 11–12oz）；把手内环高/宽 35–45mm（两指，三指 50–55mm）、杆宽 12–15mm、杆厚 8–10mm、**指壁间距 ≥25mm（推荐 28–30mm，防烫）**、底径约 65–82mm（稳定）。把手截面宜"宽而薄"，圆截面最差（靠摩擦防旋转）。
→ 映射：plan-JSON 增加 `constraints` 块，每条含 parameter/min/max/rationale，verifier 直接消费。

**5. 变更传播 = 显式依赖图。** 工程变更管理（ECM）研究核心即依赖识别：通过参数依赖图（CPM/DSM/贝叶斯网络）预测传播；CAD 实证研究（arXiv 2025 依赖管理访谈）表明用户最痛的是"追不上依赖链"和"无预警的断链"。对杯子：改杯径 → 把手环半径、壁距、上下连接点位置、（若保持容量）杯高全部联动。
→ 映射：plan-JSON 增加 `dependencies`（有向边 + 派生表达式），编译器据此做联动更新与断链检测。

## 二、设计转译：马克杯 plan-JSON 完整示例

```json
{
  "version": "0.3",
  "intent": {
    "product": "coffee_mug",
    "strategy": "blockout_first",
    "brief": "11oz 日常咖啡杯，两指握持，经典 C 把手",
    "capacity_ml": 330,
    "style_keywords": ["classic", "stackable-friendly"]
  },
  "tokens": {
    "global": [
      {"name": "wall", "value": 4, "unit": "mm", "comment": "陶瓷注浆成型最小壁厚"},
      {"name": "corner_radius", "value": 3, "unit": "mm"}
    ],
    "derived": [
      {"name": "outer_diameter", "expr": "rim_diameter", "unit": "mm", "comment": "直筒杯，口底同径以利叠放"},
      {"name": "handle_loop_radius", "expr": "finger_gap_height / 2 + handle_bar_width", "unit": "mm", "comment": "内环高一半 + 杆宽，环心外推"}
    ]
  },
  "sections": [
    {
      "id": "body",
      "order": 1,
      "op": "revolve_profile",
      "parameters": [
        {"name": "rim_diameter", "value": 82, "unit": "mm", "role": "input"},
        {"name": "height", "value": 95, "unit": "mm", "role": "input"},
        {"name": "base_diameter", "value": 75, "unit": "mm", "role": "input"},
        {"name": "inner_cavity", "derived": ["rim_diameter", "wall", "height"]}
      ],
      "fallback": "cylinder_revolve"
    },
    {
      "id": "handle",
      "order": 2,
      "op": "sweep_rounded_rect",
      "depends_on": ["body"],
      "parameters": [
        {"name": "handle_bar_width", "value": 14, "unit": "mm", "role": "input"},
        {"name": "handle_bar_thickness", "value": 9, "unit": "mm", "role": "input"},
        {"name": "finger_gap_height", "value": 40, "unit": "mm", "role": "input"},
        {"name": "wall_clearance", "value": 28, "unit": "mm", "role": "input"},
        {"name": "attach_top_z", "expr": "height * 0.85", "role": "derived", "comment": "上连接点低于杯口，留拇指位"},
        {"name": "attach_lower_z", "expr": "height * 0.35", "role": "derived", "comment": "下连接点低以增力臂"}
      ],
      "fallback": "torus_segment"
    },
    {
      "id": "finish",
      "order": 3,
      "op": "fillet_and_shell",
      "depends_on": ["body", "handle"],
      "parameters": [{"name": "rim_fillet", "expr": "corner_radius", "role": "derived"}],
      "fallback": "no_fillet"
    }
  ],
  "constraints": [
    {"param": "rim_diameter", "min": 75, "max": 95, "unit": "mm", "source": "行业标准杯口范围"},
    {"param": "height", "min": 90, "max": 115, "unit": "mm"},
    {"param": "handle_bar_width", "min": 12, "max": 15, "unit": "mm"},
    {"param": "handle_bar_thickness", "min": 8, "max": 10, "unit": "mm"},
    {"param": "finger_gap_height", "min": 35, "max": 45, "unit": "mm", "comment": "两指握持"},
    {"param": "wall_clearance", "min": 25, "max": 35, "unit": "mm", "comment": "防烫硬约束"},
    {"param": "base_diameter", "min": 65, "max": 82, "unit": "mm", "comment": "底座稳定性"},
    {"check": "capacity", "min": 240, "max": 355, "unit": "ml"}
  ]
}
```

## 三、设计 Token 的通用提取方法（任何产品）

借鉴 digital token 三层法（global/alias/component）+ ECM 依赖识别，四步：
1. **拆部件清单**：把产品拆到最小功能单元（杯→杯体/把手/口沿/底圈），对应 plan 的 section。
2. **找"决策变量"而非几何尺寸**：问"设计师改什么来改变产品？"——跨部件共享的值（壁厚、圆角、间隙）是 global token；单部件主尺寸（杯径、杯高）是 component token。
3. **对人机工学/规范范围逐项找依据**：每个输入 token 查行业标准或人体测量数据（P95 手指宽等），没有依据就标【未核实】留给原型测试——这些就是 constraints。
4. **画依赖图**：改 token A 会迫使哪些 token 改？（几何邻接、装配配合、功能关系三类边），把联动写成表达式（derived token）而非靠 AI 隐式猜。ECM 研究表明依赖可从参数联动观测中提取，落地时可用"改 A→观察哪些 B 变"的方式半自动标注。

## 四、文献

1. Olechowski A. et al., "What Sets Proficient and Expert Users Apart?", ASME J. Mech. Design 146(1), 2024.
2. Camba J.D., Contero M., Company P., "Parametric CAD modeling: an analysis of strategies for design reusability", Computer-Aided Design 74, 2016.
3. "Analyzing the effect of alternative goals and model attributes on CAD model creation and alteration", Computer-Aided Design, 2012（30 工程师实验）.
4. Masmoudi M. et al., "Dependency Identification for Engineering Change Management: a CAD-based approach", Design Society, 2017.
5. Hamraz/Clarkson 等, "Concepts of change propagation analysis in engineering design", Research in Engineering Design, 2022（综述）.
6. "It's a Complete Haystack: Understanding Dependency Management Needs in CAD", arXiv 2508.05940, 2025.
7. Mejlvang A., "Design Tokens for Physical Products", blog.asbjornmejlvang.com（Stykka/ShapeDiver 案例）.
8. NearForm, "Implementing Design Tokens in Workflows"（token 三层体系）.
9. Custom Enamel Mug 厂商把手六尺寸规范（内环 35–45mm、壁距≥25mm 等）；NBEMugs 把手人机工学（握径 28–35mm、角度 45–60°）。【行业来源，非同行评审】
10. Fluent in Coffee / CoffeifyMug 杯具尺寸统计（口径 75–95mm、高 90–115mm、11–12oz 主流）。【行业来源，非同行评审】

**未核实项**：把手 45–60° 安装角、"把手顶部与杯口平齐"规范仅见于厂商博客，未见学术文献；杯体重心高度无直接量化标准（仅有"底径大更稳"的定性共识），verifier 可先用几何近似（重心 < 高度 1/2 且在底面投影内）替代。

—— d3-design