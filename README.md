[English](README.en.md) | **简体中文**

<div align="center">

# Blender AI 建模控制台

**让 LLM 声明模型，而不是写脚本。**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Blender](https://img.shields.io/badge/Blender-5.2-orange)](https://www.blender.org/)
[![Runtime](https://img.shields.io/badge/runtime-bpy-blue)](https://docs.blender.org/api/current/)
[![Tests](https://img.shields.io/badge/tests-29_suites_%7E688_assertions-brightgreen)](#验收状态)

[这是什么](#这是什么) · [核心特性](#核心特性) · [快速开始](#快速开始) · [架构](#架构) · [验收状态](#验收状态) · [路线图](#路线图)

</div>

## 这是什么

一套跑在 Blender 5.2 里的 AI 建模控制台。

主流「AI + Blender」方案让 LLM 直接写并执行 bpy 脚本——能跑，但无法重放、无法审计、无法撤销。这里换成另一条路：**LLM 只声明 plan-JSON，确定性编译器落地，机械 verifier 把守每一步**。

对话中的每个段落都是一个可重放、可回退、可审计的单元；每一次提交都有同机位渲染 diff 与 29 套真机验收套件（≈688 断言）背书。

## 核心特性

- **Plan–compile–verify 闭环** —— LLM 永不产出可执行代码；schema + 白名单校验拦截一切越界输入，编译器确定性落地。
- **零静默逃逸** —— 编译失败响亮抛错并回滚，几何缺陷由机械 verifier 拦截：11 个盲写样本中，通过 verifier 的产物语义全部正确。
- **契约即杠杆** —— 实测补 4 行缺失文档，LLM 首版成功率 0% → 80%；契约、错误码、schema 是一等公民。
- **段落 = 三重边界** —— 每个对话段落同时是执行单元、上下文压缩单元、回退单元（WAL + 哈希链，可重放、可回溯撤销）。
- **同机位渲染 diff 作地面真值** —— 固定机位渲染 + 感知哈希；呈现档与 diff 管线两档并存，每次渲染后恢复状态，互证 0 像素漂移。
- **负结果也是交付** —— 顶点指纹 A/B 判定「不接入」并发现 Morton 薄层散射；Blender 5.2 移除 Delta Mush 后裁决 Corrective Smooth 替代。

## 快速开始

```bash
git clone https://github.com/master666-max/blender-ai-console.git
cd blender-ai-console

# 真机验收（需 Blender 5.2 自带 Python / bpy）
python blender_console/m8r4_live.py     # 素材与呈现套件     20/20
python blender_console/m412b_live.py    # 角色管线集成       17/17

# Web 控制台自检（无需 Blender）
cd m9_web && node _selftest.mjs         # 42/42
```

纯 Python 单测（无 bpy 依赖）：`python blender_console/test_upstream_store.py`

**环境要求**：真机验收需 Blender 5.x（自带 Python ≥3.10）；纯单测与 Web 自检只需 Python 3.10+ / Node 18+。MCP 起桥入口：Windows `m8_bridge\start_gn_bridge.bat`，macOS/Linux `m8_bridge/start_gn_bridge.sh`——两者都会自动探测 Blender，找不到时设环境变量 `BLENDER_EXE` 指向可执行文件即可。

跑通即验收——每套 `_live.py` 都在真实 Blender 5.2 会话里断言。全仓库路径均相对仓库根推导，不含任何机器相关的绝对路径；验收结果统一落盘到仓库内 `results/`。

## 架构

```mermaid
flowchart LR
    subgraph INTENT [对话层]
        U[用户意图] --> L[LLM 生成 plan-JSON]
    end
    subgraph COMPILE [确定性编译层]
        P[schema + 白名单校验] --> C[M4 编译器<br/>GN · 材质 · rig · 相机]
        C --> B[("Blender 5.2 bpy")]
    end
    subgraph VERIFY [真机验证层]
        V[M2 谓词族<br/>M3 渲染 diff + 感知哈希]
    end
    L --> P
    B --> V
    V -- "结构化错误码 → 自修 / 升级" --> P
    V -- "通过" --> OK["提交 · 呈现 · 回滚锚点"]
    style INTENT fill:#e8f0fe,stroke:#4285f4
    style COMPILE fill:#e6f4ea,stroke:#34a853
    style VERIFY fill:#fef7e0,stroke:#f9ab00
```

十个模块各带验收套件：**M1** 数据层（FlowDAG / WAL+哈希链 / Step 可重放）、**M2** 验证层（结构/渲染/BIM 谓词 + 分级门禁）、**M3** 渲染层（同机位 diff）、**M4** 编译层（GN / 材质含 procedural / Rigify rig）、**M5** 交互层（A/B 双编译）、**M6** 经验库（偏好学习 + EMD 离线标定）、**M7** 导演模式、**M8** 融合与发布工程、**M9** 对话前端、**M10** 静态 Web 控制台。

## 仓库结构

| 路径 | 内容 |
|---|---|
| [`blender_console/`](blender_console/) | 控制台主体 + 29 套 `_live.py` 真机验收 |
| [`m8_bridge/gn_deploy/`](m8_bridge/gn_deploy/) | 部署载荷（55 py，与主线 diff 校验一致） |
| [`m9_web/`](m9_web/) | 静态 Web 控制台 + 闪烁 diff 查看器 |
| [`release/`](release/) | 发布 manifest（147 文件五层清单） |

## 验收状态

M1–M10 主线全绿；R7 深水区 AI 可做项收官。回归基线：**29 套 ≈ 688 断言**。

<details>
<summary><b>套件亮点（点击展开）</b></summary>

| 套件 | 覆盖 |
|---|---|
| `m8r4_live` 20/20 | Procedural 木纹编译 / 重放幂等 / 结构化拒绝 / 呈现档 + 0 漂移互证 |
| `exp5_live` 6/6 | 顶点指纹 A/B：Gear FastCDC 三路对照，判定"退回几何量指纹" |
| `m412b_live` 17/17 | 角色管线 console 集成 |
| `m412_live` 6/6 | rig 编译器，形变质量 IoU(128³) = 1.0 |
| `test_bim` 19/19 | BIM 谓词（数据级） |
| `exp7_live` 3/3 | 工艺门禁三组对照（左移效应） |
| `m6_live` 31/31 | AB → 偏好学习 / override 回写 / 多样性闸门 |
| 其余 20+ 套 | M1-M5 / M7 / M9 / M10 回归与冒烟 |

</details>

## 路线图

- [x] M1–M10 主线 + 发布反转（whl 2.1.0-gn 定版）
- [x] R7 深水区：角色管线（含 console 集成）/ EMD 标定 / BIM 谓词 / 材质素材 / 顶点指纹判定
- [ ] M9-5 闪烁 vs 并排偏好 A/B（flicker.html 已就绪，待真人实验）
- [ ] 远期：标注反查 · 声音通道 · HAMT · ARKit-52 表情 schema · 多 rig 共存

## 致谢

- **[mcp-for-blender](https://github.com/ahujasid/blender-mcp)**（MIT，© 2025 Siddharth Ahuja）——传输层（沙箱 / 遥测 / 知情同意 / 配置模块）以 vendored 方式收录于 [`m8_bridge/brickfly_mcp_src/`](m8_bridge/brickfly_mcp_src/)，并在其上扩展了 8 个 GN 工具绑定；原许可声明保留于该目录的 [LICENSE](m8_bridge/brickfly_mcp_src/LICENSE)。
- **[Blender](https://www.blender.org/)** 与 bpy 社区——一切运行其上的地基。

## License

<div align="center">

[MIT](LICENSE) © 2026 · *以工程纪律对待每一个像素。*

</div>
