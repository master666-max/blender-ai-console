# Blender AI 建模控制台

对话驱动的 Blender AI 建模系统：LLM 输出结构化 plan-JSON → 编译器确定性地落到 Blender（GN / 材质 / 相机 / 角色 rig）→ verifier 真机渲染验证 → 结构化错误码反馈自修。核心立场是 **plan–compile–verify 闭环**：LLM 不直接写 bpy 脚本，而是声明意图；确定性编译层负责幂等重放、指纹对账与可撤销。

## 架构

```
M1 数据层   FlowDAG / WAL+哈希链 / Step 可重放 / revision+backdating
M2 验证层   谓词族（结构/渲染/BIM）+ 分级门禁（可自修 → 需确认 → 拒绝）
M3 渲染层   同机位 Workbench diff 管线 + 感知哈希
M4 编译层   GN 编译器 / 材质编译器（含 procedural）/ rig 编译器（Rigify）
M5 交互层   结构化 spec 协议 + A/B 双编译对照
M6 经验库   AB→偏好学习方向 / override 回写 / 离线标定（EMD）
M7 导演模式 段落规划 / 机位导演 / 呈现档与 diff 两档并存
M8 融合工程 上游机制吸收 + 标准包发布（whl 2.1.0-gn + manifest）
M9 前端     对话即前端 / N 面板 / 闪烁 diff 查看器 / 提问协议
M10 Web     静态只读控制台（三级披露 + KPI + override 曲线）
```

## 仓库结构

| 目录 | 内容 |
|---|---|
| `blender_console/` | 控制台主体 + 29 套 `_live.py` 真机验收（≈688 断言） |
| `m8_bridge/gn_deploy/` | 部署载荷（55 py，与主线 diff 校验零漂移） |
| `m9_web/` | 静态 Web 控制台 + 闪烁 diff 查看器（`node _selftest.mjs` 自检 42/42） |
| `release/` | 发布 manifest（147 文件五层清单） |
| `上游隔离区/` | 只读上游素材（机制库/工艺库），隔离区纪律：不 import、只吸收 |
| `深度调研/` `预调研/` `算法路线调研/` | 方法学依据（增量/缓存/指纹、工艺约束、交互协议等） |
| 工单 / 交接文档 / 进度规划 | 过程台账：决策、验收口径、诚实缺口登记 |

## 运行

真机验收需要 Blender 5.2 的 `bpy` 环境：

```bash
# 例：运行 M8-R4 素材转正验收（20/20）
python blender_console/m8r4_live.py

# Web 控制台自检（无需 Blender）
cd m9_web && node _selftest.mjs
```

纯 Python 单测（无 bpy 依赖）：`pytest blender_console/test_escape.py blender_console/test_intake.py`

## 状态

M1–M10 主线全绿；R7 深水区 AI 可做项收官（M4-12 角色管线含 console 集成 / M6-4 EMD 标定 / M2-8 BIM 谓词 / M8-R4 素材转正 / EXP-5 顶点指纹判定 / EXP-7 工艺门禁）。回归基线 **29 套 ≈688 断言**。待办与远期项见《工单_v2》《进度规划》。

## License

[MIT](LICENSE)
