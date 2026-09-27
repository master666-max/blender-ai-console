# 程序化材质 / PBR / Blender 材质节点 / 光照预设

- 原始记录：`agent-9cd3daabf5a54cd3.jsonl`

---

【程序化材质 / PBR / Blender 材质节点 / 光照预设 调研报告】

一、机制/系统 5 条 + 与 GN 编译路线的映射

1. 材质节点树与 GN 节点树同源不同域。ShaderNodeTree、GeometryNodeTree、CompositorNodeTree 都是 NodeTree(ID) 的子类，共享同一套核心 API：`nodes / links / interface`（4.0+ 统一用 `tree.interface.new_socket(in_out='INPUT', socket_type=...)` 声明接口）。**结论：gn_adapter 架构可复用**——同一套"建树四步法"（new tree → interface → nodes.new(bl_idname) → links.new），只需换节点前缀（ShaderNode* vs GeometryNode*）和 socket 类型（Shader 域用 NodeSocketShader/Float/Color/Vector，没有 NodeSocketGeometry）。已核实：https://docs.blender.org/api/latest/bpy.types.NodeTree.html
2. 关键差异在求值引擎而非 API：Shader 树编译成 GPU shader（GPU_material_from_nodetree），GN 是 lazy function 图求值；GN 有 field/simulation zone，Shader 没有；材质树挂在 `bpy.data.materials[].node_tree`，GN 树挂在 modifier 上。所以复用 gn_adapter 时"挂载层"要重写，"建图层"可直接复用。
3. ShaderNode bl_idname 清单已核实（Blender 5.2 手册 + 社区全集）：ShaderNodeBsdfPrincipled / MixShader / AddShader / TexNoise / TexVoronoi / TexWave / TexBrick / TexChecker / TexImage / TexEnvironment / Mapping / NormalMap / Bump / ValToRGB(ColorRamp) / Mix / Math / SeparateColor / Fresnel / LayerWeight / OutputMaterial 等约 80 个。有趣的是 GN 树里可以直接用 ShaderNodeTexNoise 等纹理节点——纹理节点是跨域共享的。
4. Substance 的"材质图"与 Blender ShaderNode 图同构（节点+暴露参数），且已有"plan-JSON"先例：.sbsar 把图编译为黑盒、只暴露参数；ComfyUI 的 SubstanceInfoExtractor 用 `sbsrender info` 把参数/输出解析成 JSON 做程序化覆盖。**这证明"AI 写参数 plan → 编译/实例化"是工业验证过的模式**。.sbs 源文件的 XML 结构可否直接读写【未核实】。
5. 材质与几何的衔接点：GN 有 Set Material / Material Selection 节点，可在几何流程内按段指派材质索引——几何 plan 和材质 plan 可以在 GN 层握手。

二、设计转译：材质 plan-JSON schema 建议（6 条）

1. 顶层结构（对齐 glTF 2.0 material JSON——已核实的最强先例）：
```json
{ "name": "glazed_ceramic", "preset": "ceramic",
  "surface": { "base_color": [0.85,0.2,0.15], "roughness": 0.15, "metallic": 0.0, "ior": 1.5 },
  "layers": { "coat": {"weight":1.0,"roughness":0.05,"ior":1.5} },
  "procedural_detail": {"noise_scale":4.0,"bump_strength":0.02},
  "assignment": {"mode":"slot0|face_range|gn_segment"} }
```
2. preset 字段做"语义→参数"映射（ceramic/metal/plastic/glass），AI 只写语义 + 覆盖参数，编译器负责全参数填充——这是 opinion 层的核心：AI 不写裸数值，写"意图+偏差"。
3. 编译器固定产出 Principled BSDF 单核节点图（Verge3D/业界共识：Principled 足以覆盖绝大多数材质），复杂节点图仅作为 L2 扩展。
4. 参数 schema 必须带物理约束元数据（见三），JSON 里可写超出范围的值，由 verifier clamp 或报错——对齐 gltf-json 的 Validate 机制。
5. 贴图类输入（image texture）用 URI 引用而非内嵌，支持 MatFuse 生成的 SVBRDF 四图（diffuse/normal/roughness/specular）直接接入。
6. 光照 plan 独立成档：`{"hdri": {"url":"polyhaven CC0","strength":0.5,"rotation_deg":30}, "rig": {"key":{"type":"AREA","energy":1000,"color_k":3200,"pos":[3,-3,3.5]},"fill":{"energy_ratio":0.3},"rim":{"energy_ratio":0.6}}}`。已核实三点布光参数化规范：Key:Fill = 2:1(高调)/4:1(人像)/8:1+(低调)，Rim = Key 的 50-100%；色温 2700-3000K 暖调、5000-6500K 日光；HDRI strength 建议 0.3-0.8。**"光照 plan-JSON"无正式工业标准【未核实】**，glTF 的灯光 JSON 扩展可作为参照【未核实】。

三、材质 opinion 层架构（3 层回退映射）

物理约束已核实（Blender 手册），verifier 完全可行：
- 范围约束：Metallic/Transmission/Coat/Sheen Weight ∈[0,1]；Roughness ∈[0,1]；IOR ∈[1.0,2.0]（水1.33/玻璃~1.5/钻石2.4）；Specular IOR Level 0-1（0.5=无调整，映射 0-8% 反射率，Nature 论文确认）；Subsurface Anisotropy [-0.9,0.9]；Emission Strength [0,10]。
- 组合约束：metallic=1 时 diffuse 应趋黑（金属无漫反射）；transmission>0 要求 IOR>1.0；非金属 specular F0 实际 2-5%。
- 三层回退映射：L1 语义预设（ceramic→{roughness 0.1-0.3, IOR 1.5, coat on}，硬编码物理合理值）；L2 AI 覆盖参数（plan-JSON 的 surface/layers，过 verifier 校验）；L3 失败回退 L1 预设并报告。材质"每段一层"用 slot 系统实现：已核实 obj.material_slots + polygon.material_index 机制（每面存索引，槽可空），材质 op 是**覆盖语义**（slot 指派），混合只发生在节点图内部（Mix Shader/纹理混合）——所以 opinion 层应设计为"slot 级覆盖 + 节点内参数微调"双层，而非 painter 式混合。

四、文献/工具/链接（8 条）

1. Blender Shader Nodes 手册（节点全集）: https://docs.blender.org/manual/en/5.2/render/shader_nodes/index.html
2. Principled BSDF 参数与物理范围: https://docs.blender.org/manual/en/latest/render/shader_nodes/shader/principled.html
3. bpy.types.NodeTree API（四种树共享接口）: https://docs.blender.org/api/latest/bpy.types.NodeTree.html
4. Substance .sbsar 发布机制（暴露参数/编译黑盒）: https://experienceleague.adobe.com/en/docs/substance-3d-designer/using/substance-graphs/publishing-substance-3d-asset-files-sbsar
5. glTF 2.0 PBR metallic-roughness JSON schema + KHR 材质扩展族（transmission/ior/specular/sheen/clearcoat）: https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#materials
6. MatFuse (CVPR 2024)：扩散模型生成 SVBRDF 四图，支持文本/草图/调色板条件，代码开源 https://github.com/giuvecchio/matfuse-sd —— 注意它生成的是"贴图"不是"节点图"
7. TANGO (NeurIPS 2022)：文本驱动给裸模生成 SVBRDF+法线+灯光：https://cyw-3d.github.io/tango/
8. 3DTopia-XL (2024)：文/图直出带 PBR 的 GLB 资产：https://arxiv.org/abs/2409.12957

核心结论：**材质完全能走编译路线，且比几何更适合**。学术 AI 生成工作（MatFuse/TANGO/3DTopia-XL）全部产出 SVBRDF 贴图或参数，没有发现成熟的"AI 直接生成节点图"工作【未核实到反例】——这印证 AI 写 plan（语义+参数+贴图引用）、确定性编译器组装 Principled 节点图是当前最可靠架构。verifier 用 Principled 手册的物理范围做静态校验即可起步。gn_adapter 建图层可直接复用，挂载层需为材质/light/world 重写。