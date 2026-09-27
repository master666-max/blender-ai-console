# Blender 材质系统的程序化操作——深度实现细节

- 原始记录：`agent-589f982024f746c3.jsonl`

---

【d3-material 第二轮深度调研：Blender 材质系统程序化操作——工程落地细节】

一、材质 API 深度细节（可直接写代码级）

1. **interface API 与 GN 完全同源，gn_adapter 可直接复用**。Blender 4.0+ 所有节点树（ShaderNodeTree/GeometryNodeTree/CompositorNodeTree）共享同一 `NodeTreeInterface` 基类：`interface.new_socket(name, in_out='INPUT', socket_type=..., parent=panel)`、`new_panel`、`move_to_parent`、`items_tree` 签名完全一致。gn_adapter 的 promote_input/promote_output/link 无需改逻辑，只需把 socket_type 字符串表扩展一层映射（材质侧常用：'NodeSocketShader'/'NodeSocketFloatFactor'/'NodeSocketColor'/'NodeSocketVector'/'NodeSocketFloat'）。官方接口文档证实 socket_type 是 Literal 字符串而非 RNA 类型，注册时自动解析到对应 InterfaceSocket 子类。
2. **Shader socket 不能与 Geometry socket 互连**。NodeSocketShader（bl_socket_idname='NodeSocketShader'）与 GN 的 NodeSocketGeometry 是不同数据族，links.new 跨族会直接抛错；shader socket 也没有 attribute_domain/structure_type（field）概念。因此 adapter 内的"类型校验"必须按 socket 的 bl_idname/type 判断，不能硬编码 GN 类型表。材质输出侧：Object 树终点是 ShaderNodeOutputMaterial（Surface socket），World 树是 ShaderNodeOutputWorld——GN 的"终点是 group output"假设需在 opinion 层特判。
3. **Principled BSDF 全参数清单（4.x 命名，官方 gist 核实，5.2 未逐项复核）**：Base Color(RGBA)、Metallic(0-1)、Roughness(0-1)、IOR(float, 默认1.45)、Alpha(0-1)、Normal、Weight；Subsurface Weight(0-1)/Radius(vec3, 默认(1,0.2,1))/Scale(≥0)/IOR/Anisotropy；Specular IOR Level(默认0.5)/Specular Tint(color)；Anisotropic/Anisotropic Rotation(0-1)/Tangent；Transmission Weight(0-1)；Coat Weight/Roughness/IOR(默认1.5)/Tint/Normal；Sheen Weight/Roughness/Tint；Emission Color/Strength；Thin Film Thickness(默认0)/IOR(默认1.33)。共 30 输入 + 1 输出(BSDF)。铁律：一律按名字访问 node.inputs["Metallic"]，禁止索引访问（3.x→4.0 有大改名：Subsurface→Subsurface Weight、Specular→Specular IOR Level、Clearcoat→Coat Weight、Transmission→Transmission Weight、Emission→Emission Color）。
4. **viewport 出图可行但有两个引擎级方案**。方案A：`bpy.ops.render.opengl(write_still=True)` 捕捉 3D viewport，可预先设 `space.shading.type='MATERIAL'`（Material Preview）——但它依赖 OpenGL 上下文，**后台 -b 模式不可用**（无 GL context）。方案B（verifier 推荐）：后台直接跑 Workbench 或 EEVEE——`scene.render.engine='BLENDER_WORKBENCH'`（用 scene.display.shading 配 color_type='MATERIAL'）或 'BLENDER_EEVEE_NEXT' + `bpy.ops.render.render(write_still=True)`，全程 headless 稳定。结论：快速验证用 Workbench（毫秒级），材质真值校验用 EEVEE headless。
5. **贴图自动获取：PolyHaven API 已核实完整链路**。`api.polyhaven.com/assets?t=textures&c={category}`（无 key、CC0，但**必须带唯一 User-Agent**）；`/files/{asset_id}` 返回各分辨率下各通道（Diffuse/AO/Rough/Normal/Displacement/GLTF）的 CDN URL。落地：requests 下载 → bpy.data.images.load → 每通道建 ShaderNodeTexImage 连 Principled 对应 socket，Normal 通道必须过 ShaderNodeNormalMap（Normal socket 不能直接吃颜色贴图）。Poly Pizza 仅模型（api.poly.pizza/v1，X-Auth-Token 头，glb 下载），不适合作贴图源。参考实现：blender-mcp 的 PolyHaven integration（addon.py:483-1108 有完整 download+set_texture 代码）。
6. **GN 段落→材质指派：Set Material 节点 + material_index 是正解**。GN 内置 "Set Material" 节点按 Selection 字段调整面域内置属性 material_index（材质已存在则复用索引）；配套 Material Selection / Replace Material / Material Index 节点。关键工程细节：材质必须先 append 到宿主对象 `obj.data.materials`（slot 列表），GN 里引用才在渲染时生效；无 slot 时 GN 产出的几何全部默认材质。对多段落 mesh，plan 编译顺序建议：Join 前对每分支 Set Material（用段名做 Selection），比事后按属性补救更可控。

二、材质 plan-JSON schema（完整版）
```json
{
  "version": "1.0",
  "materials": [{
    "id": "ceramic_body",
    "family": "ceramic",            // opinion 层选择预设族
    "preset": "glazed_porcelain",
    "principled": {                  // 键=BSDF socket 名，编译时直接查表
      "Base Color": "#E8E4DC",
      "Roughness": 0.08,
      "Coat Weight": 0.7, "Coat Roughness": 0.05,
      "IOR": 1.5
    },
    "procedural": [{                 // 可选：程序化纹理链
      "node": "ShaderNodeTexNoise", "output": "Fac",
      "remap": {"type": "ramp", "stops": [[0.4, "#FFFFFF"], [0.6, "#D8D2C4"]]},
      "target": "Base Color"
    }],
    "textures": [{                   // 可选：PolyHaven 贴图
      "source": "polyhaven", "asset": "ceramic_vase_01", "res": "2k",
      "channels": {"Diffuse": "Base Color", "Rough": "Roughness", "Normal": "Normal"}
    }],
    "blend": {"alpha_mode": "OPAQUE", "surface_render_method": "DRAWSHADOWED"}
  }],
  "assignment": [{"segment": "handle", "material": "ceramic_body"}],  // 对应 GN Set Material 的 selection
  "lighting": {
    "hdri": {"source": "polyhaven", "asset": "studio_small_09", "strength": 1.0, "rotation_z": 45},
    "rig": [
      {"id": "key",  "type": "AREA", "energy": 1000, "size": 1.0, "color": "#FFF2D9", "location": [3,-3,3.5]},
      {"id": "fill", "type": "AREA", "energy": 300,  "size": 2.0, "color": "#D9E6FF", "location": [-3,-2,2.5]},
      {"id": "rim",  "type": "SPOT", "energy": 600,  "spot_size": 40, "color": "#B3D9FF", "location": [0,4,3.0]}
    ]
  },
  "verification": {"engine": "EEVEE_NEXT", "res": [1024,1024], "samples": 64}
}
```

三、材质 opinion 层架构
- **编译管线**：plan-JSON → family 解析器（ceramic/metal/plastic 各一个 opinion 模块）→ Principled 参数展开 + 纹理链编译 → Blender 节点组实例化（复用 gn_adapter）→ assignment 段落绑定。
- **opinion 层职责**（对齐 GN 侧经验）：① family→参数先验（陶瓷=低Roughness+高Coat；金属=高Metallic+低Roughness+Tint；塑料=中Roughness+Specular微调），AI 只需给 0-10 强度词，opinion 层映射到具体 socket 值；② 版本兼容垫片（3.x/4.0 socket 改名表，统一内部名→运行时名）；③ 非法值钳制（socket 自带 min/max，out-of-range 由 adapter 钳制而非报错）；④ Normal 贴图强制 NormalMap 节点、透明强制 blend method。
- **验证回路**：plan 编译后自动挂 EEVEE headless 出图 → verifier 看图迭代。Workbench 作为 LLM 快速自检层。
- **sbs 结论**：Substance .sbs 有官方 pysbs（Substance Automation Toolkit）可程序化读改，但属商业授权、需 Designer 许可；无成熟开源 .sbs 解析器【未核实是否存有小型实验项目】。故自研 plan→Blender 节点路线不受影响，也不建议引入 Substance 依赖。

四、文献/链接
1. NodeTreeInterface API（官方）：docs.blender.org/api/dev/bpy.types.NodeTreeInterface.html
2. NodeTreeInterfaceSocketShader：docs.blender.org/api/main/bpy.types.NodeTreeInterfaceSocketShader.html
3. Principled BSDF 全输入清单 gist（don1138）：gist.github.com/don1138/c3569f6f7885a378aa91912be85f0f05
4. Set Material 节点手册：www.blender.org/manual/en/modeling/geometry_nodes/geometry/material/set_material.html
5. PolyHaven Public API（swagger + 政策）：github.com/Poly-Haven/Public-API；polyhaven.org/our-api
6. blender-mcp PolyHaven 集成（参考实现）：deepwiki.com/ahujasid/blender-mcp/3.1-polyhaven-integration
7. Poly Pizza API v1.1 规范：tessl.io/registry/skills/github/jasonkneen/tiny-world-builder/poly-pizza-api
8. Substance Automation Toolkit / pysbs：substance3d.adobe.com/documentation/sat/setup-and-getting-started/sat-cookbook
9. Workbench headless 渲染脚本（StackExchange）：blender.stackexchange.com/revisions/64b1d8e1-c9d3-4243-9ba1-4e6496a817bf/view-source
10. HDRI 世界节点 + 三点光配方（社区 skill，代码经核实与官方 API 一致）：skillsmp.com/creators/roble3/cc-blender-skill/plugin-skills-blender-lighting

说明：Blender 5.2 特有改动未单独复核，以上 API 以 4.x/官方 dev 文档为准；Principled 清单中 5.2 是否新增 socket 标【未核实】。"光照 plan-JSON"无业界标准 schema，上文 schema 为基于已核实 API 的自研设计，光照配方数值参考社区验证过的三点光实践（key:fill 2:1~8:1，rim 为 key 的 50-100%）。