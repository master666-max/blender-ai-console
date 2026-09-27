# BIM / 建筑参数化建模 / Sverchok / Blender 生态

- 原始记录：`agent-c25467ae0a2242d2.jsonl`

---

【BIM/建筑参数化调研报告】（已用 WebSearch 核实，约1700字）

一、系统/工具（5条）

1. Bonsai（原 BlenderBIM，基于 IfcOpenShell）
- 架构：Python addon，IFC 文件是唯一真源，Blender 对象只是 IFC 实体的"视图"——Blender 对象通过 BIMMeshProperties.ifc_definition_id 映射回 IFC 实体 ID（DeepWiki 源码级核实）。
- 参数化方式：不是 GN 修改器，而是"参数→IFC 表示→重生网格"的命令式管线。墙由 BIMWallProperties（length/height/thickness）驱动 regenerate_wall_mesh_from_props；门窗/楼板走 DumbGenerator 模式调用 ifcopenshell.api.geometry.add_door_representation / add_slab_representation。
- 语义层：原生 IFC——实体+Pset+关系（IfcRelFillsElement/IfcRelVoidsElement/IfcRelContainedInSpatialStructure）全部可交换。
- 编辑模式："推拉墙→门跟着动"并非实时约束求解，而是显式两段式：门靠 IfcOpeningElement void 关系挂在墙上，移动门后需手动 Regen（Shift+G）重算墙的布尔开洞。parametric_lifecycle.py 负责校验元素可否参数化编辑。官方文档自认 Blender 场景↔IFC 同步是"最高优先级问题"。
- 映射：我们的 plan-JSON≈它的 IFC，编译器≈它的 Generator。教训：不要学它"手动 Regen"，应把 host 依赖显式写进 plan 并自动重建。

2. Sverchok
- 与 GN 的区别（官方 FAQ 核实）：Sverchok 纯 Python、600+ 节点，面向建筑师，含 NURBS/场/OpenCASCADE 实体节点、IFC 扩展、可输出 GCode/SVG/DXF，支持 Scripted Node 与循环子树；GN 是 C++ 内置修改器，主打网格/动画，无法便捷添加自定义节点。二者只能经网格顶点/属性交换，不能互调。
- "配方库"：无中心库，配方=分享的节点树（如 twisted facade 教程），输入为 Object In（建筑轮廓）+滑块参数，靠列表/数据树思维组织。对比：Sverchok 配方是"图+隐式参数"，我们的 plan-JSON 是"声明式 JSON+显式 schema"——后者对 LLM 生成与程序化校验更友好，这是我们的差异化优势。

3. IFC 语义模型
- 几何与非几何彻底分离：Pset_WallCommon{IsExternal,LoadBearing,FireRating:"REI90",AcousticRating,ThermalTransmittance}；Pset_DoorCommon（开闭类型/防火等级）；Qto_SpaceBaseQuantities{NetFloorArea} 等数量集。Pset 经 IfcRelDefinesByProperties 附加，标准集由 buildingSMART 定义，允许自定义 Pset 扩展。
- 关系即语义：门-墙=IfcRelFillsElement，洞-墙=IfcRelVoidsElement，材质=IfcRelAssociatesMaterial（含 IfcMaterialLayerSet 多层构造），空间层级 Project→Site→Building→Storey→Space。
- 类型/实例分离：IfcTypeProduct 定义一次、多实例引用。IFC4.3 支持属性表达式（"StoreyHeight - 0.3"）且 2024 年起可 IFC-JSON 序列化——与我们 plan-JSON 高度同构，是最值得对齐的标准。

4. Archipack
- 架构：对象即参数容器、实时更新；支持 linked copy（Alt+D）与"Copy to selected"参数同步。
- 参数接口（官方文档核实）：窗=Type(Swing/Rail)+Width/Height/Altitude+Shape(矩形/椭圆顶/整圆)+组件化子参数（Frame/Handle/Blind/Shutter/Panels 的行列分布与 col%）；门=开洞尺寸+Frame+Panels(model/分布/间距/斜角)；楼梯=直/L/U/旋梯+踏步高深+扶手。核心是 preset 系统：参数组合存为带缩略图的预设文件（presets/ 目录，可打包分享）——正是我们 plan-JSON"preset 层"的成熟范本。

5. Rhino.Inside.Revit
- 架构：Revit 进程内嵌 Rhino/GH，"Revit"节点组直接创建原生图元（Wall.ByCurve、Floor.ByOutline、FamilyInstance.ByGeometry）。
- 关键实践（Reope/官方 Guides）：Revit 定框架（轴网/标高/幕墙网格）+GH 填充规则化变化；避免 DirectShape 静态几何、要生成原生元素以支持标注/明细表/ interfere 检测；共享参数文件保证两侧一致；单位在组件内转换。
- 启示：编译路线在建筑落地的成熟形态="宿主 BIM 模型+参数化填充器"；我们 GN 编译器若要出 BIM，需加一层 geometry→IFC 原生元素化转换。

Genius Loci：同名包实为 Dynamo 的 350+ 节点库（已核实，MIT，含 Create Wall Type/层函数节点）；其 Blender 建筑插件的现状与参数接口【未核实】。

二、设计转译：plan-JSON 建筑 schema 扩展
{"type":"wall","path":[[x,y],...],"thickness":0.2,"height":2.9,"layers":[{"material":"gypsum","t":0.012},...],"pset":{"isExternal":true,"loadBearing":true,"fireRating":"REI90"}}
{"type":"door","hostWall":"wall_01","t":0.4,"width":0.9,"height":2.1,"operation":"single_swing_right","pset":{"fireRating":"EI60"}}
{"type":"window","hostWall":"wall_01","t":0.7,"width":1.2,"height":1.4,"sillHeight":0.9,"shape":"rectangle","rows":[{"panels":2}]}
{"type":"slab","outline":[...],"thickness":0.2,"preset":"parquet_15x3"}
{"type":"stair","kind":"straight|L|U|spiral","rise":3.0,"steps":14}
要点：(1) hostWall+t（沿墙参数）参照引用替代世界坐标——Bonsai void 关系与 Archipack 参数联动的共同经验，墙变则门窗自动跟随；(2) layers 对应 IfcMaterialLayerSet；(3) pset 直接借 IFC 标准字段名，未来可无损导出 IFC；(4) type/preset 与 instance 分离（IfcTypeProduct 模式）；(5) operation 枚举沿用 Bonsai 命名（SINGLE_SWING_RIGHT 等）。

三、BIM 语义层对 verifier 的启示
在几何谓词（洞贴合墙、门在内墙、楼梯 2h+b≈600-640mm）之上，verifier 可增加四类语义检查：
1. Pset 完备性：外墙必须 IsExternal=true 且 FireRating 非空；门应有防火等级。
2. 关系一致性：每个 door/window 的 hostWall 必须存在且不跨墙（对应 IfcRelFillsElement 校验）；slab 应落在墙轮廓内。
3. 材料层一致性：layers 各厚度之和 == thickness。
4. 空间拓扑与数量集：每个 room 有门连通（可达性，对应 IfcSpace 边界）； verifier 自算的 NetFloorArea 与 plan 声明值一致（容差内）。
即 verifier 从"几何对了"升级为"数据模型对了"——这是 BIM 对我们最有价值的一点：plan-JSON 不只描述形状，还携带可校验的工程语义。

四、文献/链接（10条）
1. Bonsai Parametric Geometry 文档 http://docs.blenderbim.org/guides/authoring/advanced_modeling/parametric_geometry.html
2. Bonsai Door authoring https://docs.blenderbim.org/guides/authoring/basic_modeling/door.html
3. IfcOpenShell DeepWiki·Model Authoring https://deepwiki.com/IfcOpenShell/IfcOpenShell/4.1-model-authoring-and-element-creation
4. Sverchok 官方 FAQ（vs GN）https://github.com/nortikin/sverchok/wiki/FAQ
5. OSArch 社区：Sverchok↔IFC 工作流 https://community.osarch.org/discussion/1867/
6. IFC 格式指南（Pset 体系）https://kaijuconverter.com/guides/ifc-industry-foundation-classes-bim-format
7. TU Wien IFC Fundamentals（Pset 实操）https://cookbooks.git-pages.tuwien.ac.at/private/bim-point-cloud-intelligence/notebooks/ifc-fundamentals
8. Archipack objects 官方文档 https://blender-archipack.gitlab.io/user/archipack%20objects.html
9. Rhino.Inside.Revit Guides https://www.rhino3d.com/en/inside/revit/1.0/guides
10. Reope：Revit×Rhino 五大工作流 https://www.reope.com/bimagination/revit-x-rhino-interoperability-5-smart-workflows-to-save-time-and-headaches