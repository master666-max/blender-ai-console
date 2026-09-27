# AI 3D 生成前沿：Text-to-3D / Image-to-3D / 3D 基础模型

- 原始记录：`agent-4937d5f4a98c4942.jsonl`

---

【AI 3D 生成前沿调研报告：Text-to-3D / Image-to-3D / 3D 基础模型】（约1600字）

一、SOTA 系统盘点（8 个）

1. **Meshy**（Meshy LLC，2023起，Meshy-4 为 2024.08）：Text/Image-to-3D，输出 GLB/FBX/OBJ/STL/USDZ/BLEND，PBR 四张贴图齐全。Smart Remesh 支持 1k–300k 面且可选三角/四边拓扑；有 Blender/Unity/UE 原生插件与 REST API。生成约 1 分钟。评级：★★★☆（速度快、格式全；第三方实测幻觉较多——多尾巴、贴图糊，2-3/10 分）。

2. **Tripo / VAST**（北京，Tripo 3.0 2025.09，20B 参数；H3.1 2026.03）：Ultra 模式可达 200 万面；API 提供 quad=True（换 FBX）、face_limit、**generate_parts（分件输出）**、part segmentation。Smart Mesh P1.0 二秒级四边面重拓扑。开源线：TripoSR（与 Stability 合著）、TripoSG 1.5B（MIT）、UniRig。$0.10/次。评级：★★★★（API 工程化最好，分件/quad 选项对我们最关键）。

3. **Rodin Gen-1.5/Gen-2**（影眸 Deemos，2024.12 / 2025，Gen-2 达 10B 参数）：业界首个直出**四边面**+锐利硬表面边缘（圆滑当道时代的"锐利异类"），4B 参数，内置 3D ControlNet 与 LoRA，PBR，支持面数/LOD 控制。学术底座 Clay（SIGGRAPH 2024 荣誉提名）与 BANG 架构（SIGGRAPH 2025 顶会论文），**递归分件生成**——车辆/机械按部件分解生成并保持装配关系。已接入 Blender MCP。~$0.75/次。第三方横评 8.5-9.5/10，质量第一。评级：★★★★★（硬表面场景对我们价值最高）。

4. **TripoSR**（Stability+VAST，2024.01）：单图 0.5-5 秒 LRM 重建，质量四小龙中最低（GSO PSNR 20.3），背面塌陷。评级：★★（仅适合预览草稿）。

5. **InstantMesh**（腾讯 ARC，2024.04，arXiv:2404.07191）：多视角扩散+FlexiCubes 等值面，约 10 秒出 mesh，几何指标全面优于 TripoSR/LGM/CRM（GSO SSIM 0.880）。开源 Apache 2.0。但拓扑不规则、背面质量差、"不适合直接进引擎"。评级：★★★。

6. **TRELLIS**（微软+清华，2024.12，CVPR 2025 Spotlight）：SLAT 结构化隐表示（稀疏体素×DINOv2 特征），2B 参数，50 万资产训练，同一 latent 可解码为 Radiance Field / 3DGS / mesh。**关键能力：局部编辑（Local Manipulation）已被论文演示——"去掉机甲手臂""加光束武器""履带替换腿"均可按体素区域改局部不动全局；还有 Asset Variants（类似 img2img 的材质变体）**。这就是"3D inpainting / latent 空间编辑"的正面答案。MIT 开源。评级：★★★★★（可编辑性最强）。

7. **3DTopia-XL**（NTU/SUTD 等，2024.09，arXiv:2409.12957）：PrimX 表征（表面锚定体素基元编码 SDF+RGB+材质），DiT 1B 参数，**5 秒直出带 PBR 的 GLB**，可直接导入 Blender 渲染。评级：★★★★（快+PBR，但无编辑能力）。

8. **Hunyuan3D 2.x / Studio**（腾讯混元，2025.01 起）：形状 DiT 与 PBR 贴图扩散分离训练，**开源社区事实上的 base model**。Hunyuan3D Studio（arXiv:2509.12815）打通端到端：内置 SAMesh/PartField/X-Part 分件分解，论文明确指出**分件能显著降低重拓扑与 UV 展开难度**。评级：★★★★（开源可私有化部署）。

Luma Genie：仅确认存在 text-to-3D 网页版，2024 后更新停滞，输出低模草稿【细节未核实】。

二、集成方案（AI 生成 → 我们的 GN 编译架构）

**方案 A：AI 生成 → GLB 导入 → 作为 opinion 层的"基底网格"**（已被社区验证）。Blender MCP（ahujasid）已实现 Rodin 生成→GLB→bpy.ops.import_scene 自动入场景的完整链路；Tripo 有官方 Blender 扩展。在我们的架构里即：AI mesh 导入 → 挂 GN 修饰器链（remesh/boolean/倒角/材质分配）作为 opinion 覆盖在其上，AI 产物相当于"初始 opinion 输入"，GN 精修指令保持可编辑可回放。优点：入口现成、侵入性最小、保留我们的编译语义；缺点：AI mesh 无参数历史，"为什么长这样"不可追溯，只能整体替换不能改参。

**方案 B：TRELLIS SLAT 做"语义级修改"，GN 做最终精修**。用 TRELLIS 局部编辑（换部件/材质变体）迭代概念稿，定稿后解码 mesh 进 Blender。优点：修改发生在语义/latent 层，比改 mesh 面片更接近"导演指令"抽象层级，与 opinion 思路天然同构；缺点：需要 GPU 部署（16GB+ VRAM），SLAT 局部编辑边界控制在实践中仍粗糙。

**方案 C：AI 直接输出 GN 节点组/参数化历史**。【未核实】目前无任何系统做到；最接近的是 Articulate-Anything（2024，VLM 写 URDF 装配程序）和 SolidGen（B-rep 自回归），证明"AI 产出结构化建模程序"路线活跃但距 GN 还远。结论：C 是长期方向，当下应做 A 为主、B 为辅。

三、质量瓶颈清单

**可自动化修（后处理管线已成熟）**：① 拓扑三角汤→四边面：Tripo Smart Mesh/QuadRemesher/quad remesh/quadriflow，TRELLIS 直出 mesh 也够均匀；② UV：各平台自动 UV 基本可用，分件后（SAMPart3D/HoloPart/PartCrafter/X-Part）逐件展开更干净；③ 分件：body/handle 等语义分件已有 zero-shot 方案（SAMPart3D 2024.11、PartCrafter 2025、HoloPart 2025），Tripo API 甚至原生 generate_parts；④ PBR 贴图：普遍直出。

**必须人做（或目前无解）**：① CAD 级精度与公差——生成几何"像"但不"准"，需制造的件必须重建；② 布线意图——edge loop 沿表面而不沿变形/设计意图，动画区仍需手工；③ 无参数历史——这是与我们 GN 编译路线的根本冲突，也是我们的差异化价值所在；④ 复杂对象（透明/反光件）单图重建仍然失效。

四、战略判断：机会大于威胁，但要尽快"接住"

论据一：**AI 生成恰好卡在我们管线的上游缺口**。我们原型里 AI 的角色是写 plan-JSON（参数化描述），而 AI 3D 生成提供的是"第一稿几何"。两者互补不互斥——用 Rodin/Tripo 出基底，用 GN 编译层恢复"可编辑性"（remesh、布尔、参数化修饰），这把我们的定位从"AI 建模工具"升级为"AI 资产的精修与参数化层"，是顺势而非对抗。

论据二：**生成质量曲线对我们极其有利**。Rodin Gen-1.5（2024.12）证明硬表面锐利边缘已可直出，Tripo 3.0 面数上限到 200 万，quad 拓扑与分件从"完全没有"到"API 开关"。威胁的是纯手工建模流程，不是编译精修层——上游越强，下游精修的杠杆价值越大。

论据三：**"可编辑性"仍是全行业短板，正是我们的护城河**。TRELLIS 的局部编辑、Rodin 的 ControlNet 都在补这块，但没有一家做到"段落级导演指令 + opinion 层可回放修改"。若我们不接 AI 生成，别人接了，"导演模式 + AI 第一稿"的完整故事就被竞品讲走；且"AI 生成→opinion 层→段落边界人工精修"的完整管线【未核实】尚无公开先例，存在先发窗口。

五、链接（10 条）

1. TRELLIS 项目页 http://trellis3d.github.io/ （arXiv:2412.01506）
2. TRELLIS 局部编辑演示（去手臂/换履带）见项目页 Editing 栏目
3. 3DTopia-XL https://3dtopia.github.io/3DTopia-XL/ （arXiv:2409.12957）
4. InstantMesh arXiv:2404.07191 / github.com/TencentARC/InstantMesh
5. Tripo API（quad/generate_parts 参数）github.com/VAST-AI-Research/tripo-python-sdk
6. Rodin Gen-1.5 硬表面评测 hub.baai.ac.cn/view/42736；官方发布 globenewswire.com/news-release/2025/05/08/3077597
7. Hunyuan3D Studio arXiv:2509.12815（含分件辅助重拓扑的量化对比）
8. SAMPart3D（零样本 3D 分件）Hugging Face Papers，2024.11
9. Blender MCP（Claude+Rodin 生成→导入 Blender 全链路）github.com/ahujasid/blender-mcp
10. 2025 横评（Rodin 8.5-9.5 分 vs Meshy 2-3 分）cyber-fox.net/blog/ai-3d-generators-review-in-2025

（完）