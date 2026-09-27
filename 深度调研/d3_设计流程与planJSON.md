# [d3-design] 工业设计流程 / 参数化思维 / 设计 Token → plan-JSON schema

- 调研代理：d3-design ｜ 回报 2026-09-27
- 定位：回答 plan-JSON 应该长什么样——**直接给出完整 schema 示例**

## 一、核心发现（5 条）

1. **专家建模 = "先策略后建模，先整体后细节"**。ASME 实验研究（JMD 2024）：专家拿到图纸后先解读并规划完整建模策略，迭代返工显著少；3D 教程一致采用"block out 主形状 → 细化 → 修拓扑"。→ plan-JSON 应强制"段落有序"——先 body，后 handle/details，最后 finish；AI 先输出"设计意图/策略"字段再输出几何段落。

2. **"可改性"是一等目标**。30 名职业工程师对照实验：以"易于修改"为目标比"求快"多花 25% 时间但模型更易改；Camba & Contero (2016)：**减少不必要的特征父子依赖**是复用关键。→ 参数集中声明（token 层），特征只引用不硬编码；依赖边最小化。

3. **成熟 CAD 参数表最佳实践**。参数名无空格 snake_case、描述物理用途；显式单位；每参数带 comment；表达式驱动派生；按前缀分组（p_ 产品 / s_ 零件 / c_ 派生）。Design token 三层（global→alias→component）适用于实体产品。

4. **人机工学范围 = verifier 硬约束**（均有行业来源核实）。杯口 75–95mm、杯高 90–115mm、容量 240–355ml；把手内环高/宽 35–45mm、杆宽 12–15mm、杆厚 8–10mm、**指壁间距 ≥25mm（防烫）**、底径 65–82mm。把手截面宜"宽而薄"。

5. **变更传播 = 显式依赖图**。ECM 研究核心即依赖识别；改杯径 → 把手环半径/壁距/连接点/杯高全部联动。

## 二、plan-JSON 完整示例（schema v0.3）

（JSON 代码太长此处略，见原文全文；核心结构：intent + tokens(global/derived) + sections[{id, order, op, parameters[{name,value,unit,role}], depends_on, fallback}] + constraints[{param,min,max,unit,source}]）

## 三、设计 Token 通用提取四步法

1. 拆部件清单（杯→杯体/把手/口沿/底圈 = plan 的 section）
2. 找"决策变量"而非几何尺寸——跨部件共享值 = global token；单部件主尺寸 = component token
3. 逐项查人机工学/规范范围 → constraints
4. 画依赖图（几何邻接/装配配合/功能关系三类边），联动写成表达式

## 四、文献
Olechowski JMD 2024 · Camba & Contero CAD 2016 · 30 工程师实验 CAD 2012 · Masmoudi ECM 2017 · Hamraz/Clarkson RED 2022 综述 · arXiv 2508.05940 · Mejlvang Design Tokens · NearForm token 体系 · 马克杯厂商尺寸规范
