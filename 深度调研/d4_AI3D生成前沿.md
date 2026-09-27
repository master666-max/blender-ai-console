# [d4-ai3d] AI 3D 生成前沿：Text-to-3D / Image-to-3D / 3D 基础模型

- 调研代理：d4-ai3d ｜ 回报 2026-09-27 ｜ 本文为原文落盘
- 定位：评估"AI 生成 3D 作为起点 + 我们做精修"的架构可行性

## SOTA 系统（8 个）

1. **Meshy**（2023起，Meshy-4）：Text/Image-to-3D，GLB/FBX/OBJ/STL/USDZ/BLEND，PBR 四图，Smart Remesh 1k-300k 面。Blender/Unity/UE 插件+REST API。~1 分钟。评级：★★★☆（快、格式全；幻觉较多 2-3/10 分）
2. **Tripo/VAST**（Tripo 3.0 2025.09，20B 参数；H3.1 2026.03）：Ultra 200 万面；API quad=True、face_limit、**generate_parts（分件输出）**、part segmentation。Smart Mesh P1.0 二秒级四边面重拓扑。开源 TripoSR/TripoSG 1.5B（MIT）/UniRig。$0.10/次。评级：★★★★（API 工程化最好，分件/quad 最关键）
3. **Rodin Gen-1.5/Gen-2**（影眸，Gen-2 10B）：业界首个直出**四边面**+锐利硬表面边缘。4B。内置 3D ControlNet+LoRA。PBR。面数/LOD 控制。**递归分件生成**（车辆/机械按部件分解）。已接 Blender MCP。~$0.75/次。第三方横评 8.5-9.5/10 质量第一。评级：★★★★★
4. **TripoSR**（Stability+VAST 2024.01）：单图 0.5-5 秒 LRM。质量最低（GSO PSNR 20.3）。评级：★★
5. **InstantMesh**（腾讯 ARC 2024.04）：多视角扩散+FlexiCubes，~10 秒 mesh。GSO SSIM 0.880。Apache 2.0。拓扑不规则。评级：★★★
6. **TRELLIS**（微软+清华 2024.12，CVPR 2025 Spotlight）：SLAT 结构化隐表示（稀疏体素×DINOv2），2B 参数。**局部编辑已被论文演示**（"去机甲手臂""换履带"）。Asset Variants。MIT 开源。评级：★★★★★（可编辑性最强）
7. **3DTopia-XL**（NTU 2024.09）：PrimX 表征，DiT 1B，5 秒直出带 PBR 的 GLB。评级：★★★★
8. **Hunyuan3D 2.x/Studio**（腾讯 2025.01）：形状 DiT+PBR 贴图分离；开源社区事实 base model。Studio 内置 SAMesh/PartField/X-Part 分件分解——分件显著降低重拓扑与 UV 难度。评级：★★★★

## 集成方案

**方案 A：AI 生成→GLB 导入→作为 opinion 层基底**（社区已验证）。Blender MCP 已有 Rodin→GLB→bpy 自动入场景链路；Tripo 有官方 Blender 扩展。我们的架构：AI mesh 导入→挂 GN 修饰器链作 opinion 覆盖。优点：入口现成、侵入最小。缺点：AI mesh 无参数历史。
**方案 B：TRELLIS SLAT 做语义级修改→GN 最终精修**。修改在 latent 层，比改 mesh 更接近"导演指令"抽象层级。缺点：需 GPU 16GB+。
**方案 C：AI 直接输出 GN 节点组**。**未核实**。最接近的是 Articulate-Anything（VLM 写 URDF）和 SolidGen（B-rep 自回归）。

## 质量瓶颈
**可自动化**：拓扑三角汤→四边面（Tripo Smart Mesh/QuadRemesher）；UV（分件后逐件展开）；分件（SAMPart3D/PartCrafter/HoloPart/X-Part/Tripo generate_parts）；PBR 贴图。
**必须人做**：CAD 级精度与公差；布线意图（edge loop 沿变形方向）；**无参数历史**（与我们 GN 编译路线的根本冲突，也是差异化价值所在）；复杂透明/反光件。

## 战略判断：机会大于威胁
1. AI 生成恰好卡在我们管线**上游缺口**——AI 出第一稿几何，GN 编译层恢复可编辑性。定位从"AI 建模工具"升级为"AI 资产的精修与参数化层"
2. 生成质量曲线对我们极其有利：Rodin 硬表面锐利边缘可直出，Tripo 面数到 200 万，quad/分件有 API 开关。上游越强，下游精修杠杆价值越大
3. **"可编辑性"仍是全行业短板=我们的护城河**。TRELLIS/Rodin 都在补这块，但没有一家做到"段落级导演指令+opinion 层可回放修改"。若不接 AI 生成，别人接了，完整故事就被竞品讲走

## 链接（10 条）
TRELLIS trellis3d.github.io (arXiv:2412.01506) · 3DTopia-XL (arXiv:2409.12957) · InstantMesh (arXiv:2404.07191) · Tripo API github.com/VAST-AI-Research/tripo-python-sdk · Rodin 评测 hub.baai.ac.cn/view/42736 · Hunyuan3D Studio (arXiv:2509.12815) · SAMPart3D HF Papers 2024.11 · Blender MCP github.com/ahujasid/blender-mcp · 2025 横评 cyber-fox.net · Rodin 官方 globenewswire.com
