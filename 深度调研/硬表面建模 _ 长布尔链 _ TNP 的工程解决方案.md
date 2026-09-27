# 硬表面建模 / 长布尔链 / TNP 的工程解决方案

- 原始记录：`agent-d252bfa7dcad461d.jsonl`

---

【硬表面 / 长布尔链 / TNP 工程解决方案——深度调研报告】

一、解法清单（按成熟度排序）

1. **稳定锚点替代拓扑引用**（Onshape Mate Connectors / FreeCAD Datum）
   - 原理：不引用"Face of Extrude1"这类易变拓扑，而是创建显式的基准面/坐标系/连接器对象作为特征附着点。Onshape 官方与社区确认：Mate Connector 是特征列表中的显式特征，有稳定 Internal ID，"即使周围几何删除重建仍存活"，社区实测可减少约 80% 的 dangling reference（第三方博客数据，仅供参考）。
   - 成熟度：高（商业 CAD 十年实践）｜复杂度：低｜对我们适用性：★★★★★——Blender 里等价物是空物体/自定义坐标/Named Attribute，编译器完全可控。

2. **Element Map 持久命名（FreeCAD 1.0 / Realthunder 算法）**
   - 技术细节（已核实 GitHub wiki）：TopoShape 挂 Tag（对象唯一 int ID）+ ElementMap（多对一名字映射，如 'F1'→'Face1'）；每个布尔/maker 操作用 makE* 函数生成新元素时，通过几何溯源（面积/中心/邻接比对）把旧元素名映射到新元素名；名字可哈希压缩；PropertyLinkSub 保存"原始名+映射名"双份影子引用，重算时自动更新。官方明确其三大目标：①识别断裂并报错定位 ②给出候选修复 ③高置信度才自动修复（"First, do no harm"）。
   - 存活率：官方未公布量化数字【未核实】；官方文档承认复杂布尔/中间插删操作时自动修复成功率下降，需用户手动确认。
   - 成熟度：中高（1.0 已落地）｜复杂度：极高（改造内核级）｜适用性：★★★★（思想必借鉴，但 Blender mesh 层无 OCCT 式溯源原语，需自建）。

3. **双命名体系 + 事后修复（商业 CAD 主流）**
   - Parasolid：会话内用 Tags，跨会话用持久 Identifiers；boolean 提供 "Retaining topologies during a boolean operation" 选项让应用层标记需要延续的实体。但注意：Parasolid 本身不保证特征树引用不断裂，persistent naming 是应用层（NX/SW）在 kernel 之上做的映射。
   - Onshape：改第一个特征后下游 face/edge ID 变化导致"some external references are missing"是社区高频抱怨（2025 年 5 月论坛帖仍在讨论）；官方应对是 Repair 工具——打开"最后健康时刻"双屏对照 + Replace Reference + 勾选 Propagate changes 向下游传播，一次替换修复全链。限制：仅 1↔1 替换，一个 Fillet 派生出两条边后无法传播。
   - 失败率：无官方统计【未核实】；论坛定性结论是"rearrange 就会断，正常参数编辑大多存活"。
   - 成熟度：高｜复杂度：中（需完整历史/回滚基础设施）｜适用性：★★★。

4. **GN 非破坏布尔栈（Blender 原生）**
   - Geometry Nodes 的 Boolean 节点树中，"引用"是节点连线而非拓扑索引——上游变化自动流经整条链，彻底绕开 TNP。Blender 内置 id 属性（整数、大数值无序）专为此设计："在输入网格形状变化时提供稳定性"。4.0+ 已移除实验性 Face Maps，官方推荐 Unified Attribute 系统（任意 domain 存自定义 INT attribute）。
   - 成熟度：中（布尔节点质量 4.x 起可用， Extrude/Scaled Extrude 等专用 hard-ops 节点组社区已成熟）｜复杂度：中｜适用性：★★★★★——这是我们的编译器最自然的输出格式。

5. **SDF / 隐式建模**
   - 布尔= min/max 数学运算，"Perfect booleans, no topology issues"（Chisel 文档），倒角是 smooth-min 免费送的。Chisel（Blender 生态 SDF add-on）证明工作流可行：全程数学函数，最后才 Dual Contouring/Marching Cubes 转网格。
   - 代价：无 UV、无精确 B-rep、转网格后 face 边界不对应原始图元（下游引用反而更难）；GPU 开销。
   - 成熟度：低中｜复杂度：高（需引入新表示）｜适用性：★★（可作为"探索模式"而非主链）。

6. **Creo Flexible Modeling 式几何规则引用**
   - 不存"第 N 条边"，存选择规则："凸台曲面组""相切传播""阵列/对称识别"。修改时按规则重选。成熟度：高（商业）｜复杂度：中｜适用性：★★★——适合"倒角/圆角跟随宿主面"这类语义操作。

二、设计转译（我们的编译器在硬表面场景应怎么做）

1. **放弃"永不断裂"，做"断得清、修得快"**：FreeCAD 与 Onshape 都承认断裂不可避免，把工程重点放在 (a) 第一个出错操作的精确定位报错（FreeCAD：标记 diverge 点）；(b) 依赖图 + 向下游传播的批量重映射。
2. **引用三级优先**：显式锚点（空物体/坐标系，编译器为每个孔位/接口自动生成）> 语义命名 attribute（面组 ID）> 裸索引（仅作最后回退）。禁止编译器生成裸索引引用。
3. **每步布尔后立即"语义盖章"**：操作输出 mesh 后立刻用 Store Named Attribute 在 FACE domain 打 int 标签（如 hole_id=3, wall_tag='housing'），后续步骤只认 attribute 不认 index——这是 Blender 层面可实现的类 Element Map，且 GN 全节点原生透传 attribute。
4. **长链切短、插入重锚点**：每 3–5 步布尔插入一次"重锚定"节点（GN 内用 attribute 重选目标面，而不是继承上游 index），把一次断裂的爆炸半径限制在段内。
5. **用 GN modifier 栈承载整条布尔链**：引用=连线，天然稳定；edit-mode 布尔只留给"终态一次性"操作。
6. **失败传播显式化**：编译器维护 op 级依赖 DAG，任何 op 重算失败即冻结下游并标红首因，模拟 Onshape Repair 的"从上往下修"体验。

三、最重要的一条建议
**建立"语义面组 attribute + 断裂重映射器"**：编译器在每步布尔输出上自动打稳定命名 attribute（face 组 ID），所有跨步骤引用一律指向 attribute；同时实现一个按几何相似度（面积/中心/法向/邻接）把旧 attribute 重映射到新 mesh 的修复器，失败时报出首个出错操作并给候选。这就是 FreeCAD Element Map + Onshape Repair 的 Blender 本土化最小闭环，不依赖 Blender 官方任何 TNP 计划。

四、Blender 5.x 官方进展
2025 官方路线图（code.blender.org，已核实）无任何 TNP 项目；5.0 重点在 Bundles/Closures、Volume Grids、Lists、模态节点工具。Right-Click Select 投票现状【未核实】。结论：**至少 2026 年前不要指望官方解法，必须自建**。

五、文献/链接
1. FreeCAD Wiki: Topological naming problem — https://wiki.freecad.org/Topological_naming_problem
2. Realthunder 论坛帖 "Topological Naming, My Take" — https://forum.freecad.org/viewtopic.php?t=27278
3. Realthunder 技术Wiki（ElementMap/Tag/makE 细节）— https://github.com/realthunder/FreeCAD_assembly3/wiki/Topological-Naming
4. Parasolid V35 Overview（Tags vs Identifiers、boolean retention 选项）— http://www.q-solid.com/Parasolid_Docs_V35/pdf/ov.pdf
5. Onshape Repair 官方文档（Replace Reference/Propagate）— https://cad.onshape.com/help/Content/repair.htm
6. Onshape 官方博客 "How Repair Tool Fixes Broken References" — https://www.onshape.com/en/blog/cad-repair-tool-fix-broken-references
7. Onshape 论坛 "external references are missing" 实战讨论 — https://forum.onshape.com/discussion/comment/117357
8. PTC Creo Flexible Modeling 数据表 — https://ptc-p-001.sitecorecontenthub.cloud/api/public/content/53131e1b9a234f2c830bfba4023426a6
9. Chisel (SDF for Blender) 文档 — https://chisel.ezelar.com/v2/getting-started/raymarching
10. SDF for CAD 思考 — https://incoherency.co.uk/blog/stories/sdf-thoughts.html
（Blender 2025 路线图 — https://code.blender.org/ 及 blendercn.org/22414.html）