# m9_web — Web 只读控制台（M9-4）

工单 WB-MUG-2026-001 · M9-4。**只读**状态视图：前端是状态的视图，不是新的真源（写操作走对话 / MCP 工具）。

## 文件

| 文件 | 说明 |
|---|---|
| `index.html` | 单文件控制台（零依赖、离线可用、随包分发） |
| `state.json` | 状态契约 `mug-console-state/1` 的示例（由 `m1_core.export_state()` 产出） |
| `_selftest.mjs` | 无头自检：`node _selftest.mjs`（13 项，校验纯函数与两份状态可渲染） |

## 用法

```bash
# 推荐（fetch 同目录 state.json 自动加载）
cd m9_web && python -m http.server 8000
# 浏览器打开 http://localhost:8000

# 或直接双击 index.html（file:// 下 fetch 受限，用内置示例 / 拖入 state.json）
```

## 功能（对照工单 M9-4 验收）

- 流程轴 FlowAxis：DAG 分层布局（最长路径），节点按语义段落着色，dirty 段虚线描边，点击看详情
- 段落 opinion 层：每段 revision / 输出 hash / green·dirty 徽标
- 假设面板：ThoughtGraph 的 claim 与状态（反驳按钮在 M8-2 工具化后接入）
- GoodPoint 锚点列表；mode 徽标（INCREMENTAL / FULL，A28 阈值 40%）
- override 率：schema/1 未含埋点，占位并注明判据（长期为 0 = 失效）

## 状态契约（mug-console-state/1）

由 `m1_core.export_state(dag, table, params, commits, goodpoints)` 产出。
字段：`steps[] / segments{} / revisions{} / mode / params / commits{} / goodpoints[]`，
可选扩展：`thoughts[]`（Why 层 claim）。**schema 变更必须升版本号**（工单 M9-4 验收）。
