# DFM / 制造可行性约束 / 工艺限制参数化

- 原始记录：`agent-40ca22f097eb4c12.jsonl`

---

【DFM / 制造可行性约束调研报告】（数值均已 WebSearch 核实，来源见文末）

## 一、DFM 规则四类（可参数化谓词）

**A. 注塑成型**
1. 壁厚范围：均匀壁厚 1.5–3mm 为通用规则；实用下限约 0.8mm（薄壁需高压填充，易短射）。材料相关：ABS 1.2–3.5mm、PP 1.0–4.0mm、PC 1.0–3.5mm、PA6 1.5–3.5mm、PEEK 0.5–3.0mm（Fictiv/中德数据）。
2. 拔模角度：抛光面 ≥0.5°，一般面 1–2°；纹理面每 0.025mm 纹理深度追加 1°；深腔每 25mm 深度加 1°。
3. 内圆角半径：≥0.5× 壁厚（推荐 0.75–1×），外圆角 = 内圆角 + 壁厚。
4. 壁厚均匀性：全件偏差 ±10–25% 内，厚薄过渡 ≤3:1 渐变（突变 >2:1 即翘曲风险）。
5. 流长比：流动长度 <250mm（材料相关）。

**B. 3D 打印（FDM/SLA/SLS）**
1. 最小壁厚：FDM 支撑壁 1.0–1.2mm / 无支撑悬壁 1.2–1.6mm；SLA 0.5 / 1.0mm；SLS 0.7–0.8mm；FDM 壁厚应为喷嘴直径整数倍（0.4 喷嘴→0.8/1.2/1.6mm）。
2. 悬垂角 45° 规则：与竖直方向夹角 >45° 需支撑（PLA 短跨可容忍 60°；SLA ~30–45°；SLS 粉床自支撑）。
3. 桥接跨度：FDM 无支撑桥 ≤10–12mm（保守；PLA 优化冷却下可至 50–60mm）；SLA ≤5–20mm。
4. 最小特征：FDM 雕刻深度 ≥1.2mm、最小孔径 ≥2.0mm、竖直细销 ≥2.5mm；SLA 特征 ≥0.3mm、孔 ≥0.5mm。
5. 逸出孔：SLS/MJF 中空件需 ≥3–5mm 排粉孔；SLA 空腔需 ≥3mm 排液孔。
6. 各向异性：Z 向强度弱于 XY（SLS PA2200 Z/XY=87.5%，MJF=91.8%，ASTM D638 数据）。

**C. CNC 加工**
1. 最小壁厚：金属 ≥0.8mm、塑料 ≥1.5mm（薄壁颤振）。
2. 内角半径：≥型腔深度 1/3（铣刀是圆的，尖内角物理不可行）；经验公式 R=(深度/10)+0.5mm。
3. 孔深径比：≤4×直径（标准钻），特殊刀具至 10×。
4. 型腔深径比：≤4×刀具直径。
5. 细高特征：高厚比 <4:1。刀具可达性/装夹面检测主要靠 B-Rep + CAM 仿真，纯 mesh 只能做内角半径与深径比近似【部分未核实：mesh 级刀具可达性自动检测无成熟公开算法】。

**D. 材料属性**
收缩率（注塑）：ABS 0.4–0.7%、PC 0.5–0.8%、PP 1.5–2.5%、PA66 1.0–2.0%、POM 1.5–2.5%、PLA ~0.5%。高收缩材料（PP/PE/POM）壁厚均匀性要求更严。强度/脆性差异支撑"壁太薄容易碎"类反馈。

## 二、设计转译（verifier 新增谓词）

1. **`min_wall_thickness`**：每三角面质心沿 -normal 射线求对面命中距离（BVH raycast，即 3D-Print Toolbox Thickness 同款算法，qualiteg 报告 846 面 11ms）。阈值=Material Token 的 wall_min。现有 7 谓词无此项——**最高优先级**。
2. **`overhang_angle`**：face_normal·build_axis，>45° 且非贴床面 → 违规（trimesh/Toolbox Overhang 已有，但 Toolbox 缺"按工艺/材料分阈值"，PLA 60°/SLA 30° 需 token 化）。
3. **`draft_angle`**：对每三角面 θ=asin(n·d)（d=脱模方向，杯类默认 Z），|θ|<阈值（默认 1°）面积占比 >5% → 违规；配射线遮挡检测倒凹（qualiteg AICAD 方案，15ms/件）。
4. **`bridge_span`**：Toolbox **缺**此项。检测近水平悬空面片连通域，量两端支撑间距，>10mm（FDM 默认）报警。
5. **`min_feature`**：Toolbox 有 Edge Sharp 但**缺**孔径/细销检测；对孔洞闭环做最小外接圆，<2mm（FDM）报警。
6. **`escape_hole`**：SLS/SLA token 启用时，检测封闭空腔（volume 拓扑）无 ≥3mm 开孔 → 违规。Toolbox 完全没有。

## 三、Material Token Schema（plan-JSON 参数预设）

```json
{
  "material_id": "pla",
  "process": "fdm",
  "wall": {"min": 1.2, "min_unsupported": 1.6, "max": 10.0, "nozzle_multiple": 0.4},
  "overhang": {"self_angle_deg": 45, "bridge_max_mm": 10},
  "feature": {"min_hole_dia": 2.0, "min_pin_dia": 2.5, "min_engrave_depth": 1.2, "min_clearance": 0.3},
  "shrinkage_pct": 0.5,
  "strength_z_xy_ratio": 0.85,
  "needs_escape_hole": false,
  "dfm_feedback": {"thin_wall": "壁太薄容易碎，建议至少 {wall.min}mm"}
}
```
process ∈ {fdm, sla, sls, injection, cnc}；注塑 token 增加 draft_min、shrinkage、flow_max_mm。同一 mesh 换 token 即切换验证口径（0.4mm 壁杯：注塑 token 红灯、金属 3D 打印 token 绿灯）。

## 四、非技术用户 DFM 反馈

双层消息：机器层（谓词名+实测值+阈值）→ 用户层（后果+动作）。如 `min_wall_thickness: 0.4mm < 1.2mm` → "这个杯子壁只有 0.4mm，倒热水可能烫变形/容易摔碎——要我加厚到 1.2mm 吗？"规则：①说后果不说术语；②给一键修复（对应 Blender Solidify modifier 参数）；③视口高亮违规区域（Toolbox 已支持 select 高亮，直接复用）；④严重度三档（警告/建议/阻断），仅"阻断"拦截 plan。

## 五、来源

1. Blender 3D-Print Toolbox 官方检查项（Solid/Intersections/Degenerate/Thickness/Overhang/Edge Sharp 等）
2. ISO/ASTM 52910（DfAM 通用设计准则）、ISO/ASTM 52911-1（PBF 工艺）
3. JLC3DP《Design for Additive Manufacturing》工艺参数表（FDM/SLA/SLS/MJF 对比）
4. Get It Made 3D Printing Guide（各工艺壁厚/悬垂/桥接/孔径极限表）
5. Text2Cad dfam-check process-limits（GitHub，含 ray-cast 厚度测量实现注记）
6. qualiteg AICAD Journal Part 3（mesh 级拔模角 asin(n·d) + 射线遮挡倒凹 + DDA 厚度测量，15ms 级）
7. Fictiv Injection Molding Specifications（材料壁厚/收缩/拔模表）
8. myplasticmold.com / jbrplas.com（注塑 DFM 分材料设计规则、缺陷-成本表）
9. Sendot/JUDA CNC DFM 12 Rules（内角 R≥深度/3、深径比 4×、ISO 2768-m）
10. JLC3DP 各向异性数据（ASTM D638 Z/XY 强度比）

【未核实项】mesh 级 CNC 刀具可达性自动检测无成熟公开算法（需 CAM 仿真）；浇口位置自动化检测仅见于商用模流分析（Moldflow），无开源 mesh 算法。