# 虎式坦克建模作业 · 执行状态表

> 生成于 2026-09-28 23:30 | 数据来源：tiger_tank_plan.json + logic_trees/tiger_tank.json（磁盘实测）

## 测试结果

| 套件 | 结果 |
|---|---|
| test_logic_tree | 21/21 ✅ |
| test_bim | 19/19 ✅ |
| test_console | 16/16 ✅ |
| test_escape | 26/26 ✅ |
| test_experience | 44/44 ✅ |
| test_intake | 22/22 ✅ |
| test_upstream_store | 16/16 ✅ |
| test_wal | 19/19 ✅ |
| m1_core 内嵌 | PASS ✅ |
| **合计** | **9/9 套件全绿** |

## 逻辑树 → plan 桥转换（14 sections）

| ID | 名称 | Tier | op（SEGMENT_OPS） | Stage | deps | 参数数 |
|---|---|---|---|---|---|---|
| `1.1` | 车体装甲盒 | 1 | `boolean_diff` | blockout | — | 3 |
| `1.2` | 行走机构 | 1 | `array_radial` | structure | 1.1 | 2 |
| `1.3` | 履带 | 1 | `sweep_circle` | structure | 1.2 | 2 |
| `1.4` | 动力舱格栅 | 2 | `array_linear` | structure | 1.1 | 2 |
| `2.1` | 炮塔 | 1 | `revolve_profile` | structure | 1.1 | 2 |
| `2.2` | 主炮 | 1 | `cylinder` | structure | 2.1 | 3 |
| `2.3` | 同轴机枪 | 3 | `cylinder` | structure | 2.1 | 2 |
| `2.4` | 舱门 | 2 | `cylinder` | structure | 2.1 | 2 |
| `2.5` | 防盾 | 2 | `boolean_union` | structure | 2.1, 2.2 | 1 |
| `3.3` | 细节挂载 | 3 | `array_linear` | structure | 1.1, 1.1 | 1 |
| `4.1` | 迷彩 | 2 | `set_material` | structure | 1.1, 2.1 | 3 |
| `4.2` | 旧化 | 3 | `set_material` | structure | 4.1, 1.3, 1.4 | 1 |
| `5.1` | 展台 | 2 | `cube` | structure | 1.3, 1.4, 2.5, 3.3, 4.2 | 1 |
| `1.5` | 排气系统 | 3 | `cylinder` | structure | 1.1 | 2 |

## Constraints（gate 节点转约束）

| ID | 判据 | Tier |
|---|---|---|
| `3.1` | 长:高 ∈ [2.05,2.15]（铁门禁） | 1 |
| `3.2` | 装甲面法线平行车身轴 ±0.5° | 1 |

## 渲染产物

| 文件 | 视角 |
|---|---|
| `tiger-front34.png` | 前 3/4 视角 |
| `tiger-side.png` | 侧面 |
| `tiger-rear34.png` | 后 3/4 视角 |
| `tiger-chain-front34.png` | 正链编译产物渲染 |

---
*由 tiger_tank_plan.json + logic_trees/tiger_tank.json 磁盘实测生成，非手填。*
