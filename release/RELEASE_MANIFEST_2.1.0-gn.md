# 发布清单 manifest · 2.1.0-gn

> 生成时间 2026-09-27 23:19 · whl `brickfly_mcp-2.1.0-gn-py3-none-any.whl`（111223 B，SHA256 `f6fb592cd5c1…`）
> 工具面 11 gn 工具 · 主线↔gn_deploy 零漂移已校验 · 发布门禁见 L3

## L1 主体代码 — 主体资产：blender_console 全模块 + m9_web 前端 + 桥接三件

| 文件 | 字节 | SHA256 前 12 位 |
|---|---|---|
| `blender_console/_probe_intake_schema.py` | 657 | c23d88bc6d10 |
| `blender_console/_probe_modprop.py` | 461 | 5adb780dd026 |
| `blender_console/console.py` | 51726 | 6fb67c1dc9b0 |
| `blender_console/console_live.py` | 5453 | 34d7dc2827c0 |
| `blender_console/core_types.py` | 32174 | 3d72195157bf |
| `blender_console/director.py` | 17248 | 2a886a163f09 |
| `blender_console/escape.py` | 11942 | 29cf1b7bb809 |
| `blender_console/experience.py` | 21032 | 11ae2a6ffa37 |
| `blender_console/gn_ab.py` | 15822 | 377b495a7e96 |
| `blender_console/gn_adapter.py` | 31055 | 55d9f6da2a8c |
| `blender_console/gn_adapter_live.py` | 10918 | 0b7979c8dd8a |
| `blender_console/gn_artifact.py` | 5133 | 8fc88b053b99 |
| `blender_console/gn_console.py` | 22522 | f4a7bb132040 |
| `blender_console/gn_session.py` | 31462 | 7306bf93f5da |
| `blender_console/gn_session_live.py` | 14824 | a9011c45c806 |
| `blender_console/gn_verify.py` | 14876 | f066e4fca15b |
| `blender_console/intake.py` | 12672 | 44b870ce6a96 |
| `blender_console/m1_core.py` | 32814 | 3825f7531792 |
| `blender_console/m2_dfm_probe.py` | 2078 | 06b498d47981 |
| `blender_console/m2_edge_live.py` | 3903 | 038330ff53ee |
| `blender_console/m2_predicates_live.py` | 13478 | 5ee03d789566 |
| `blender_console/m36_live.py` | 7442 | 3d16d4719b6c |
| `blender_console/m411_live.py` | 9073 | 25d3c29ff61b |
| `blender_console/m413_live.py` | 5541 | cd598f879a2e |
| `blender_console/m42_live.py` | 7484 | ddd67f54c45b |
| `blender_console/m45_live.py` | 8016 | f6c0c7b49585 |
| `blender_console/m45_probe.py` | 2064 | 4d956c6cc0f3 |
| `blender_console/m45_probe2.py` | 1258 | 8c4c2a4c9594 |
| `blender_console/m45_probe3.py` | 2950 | f4e8864a8c8a |
| `blender_console/m4_compile_live.py` | 10667 | b880989ae331 |
| `blender_console/m5_ab_live.py` | 10336 | 9f09734e7f49 |
| `blender_console/m5_spec_live.py` | 9433 | af6fca07ef26 |
| `blender_console/m6_live.py` | 11438 | 1296b8ba183d |
| `blender_console/m7_director_live.py` | 11316 | b0cfa21afb12 |
| `blender_console/m7v2_live.py` | 8980 | 85e049e02c73 |
| `blender_console/m92_live.py` | 6916 | f430492c9083 |
| `blender_console/m9_intake_live.py` | 6049 | b6276890f0af |
| `blender_console/mat_compiler.py` | 12428 | 926843d177c5 |
| `blender_console/op_compiler.py` | 26008 | 24550b9272d4 |
| `blender_console/plan_schema.py` | 15866 | e5c5e05d533f |
| `blender_console/postfx.py` | 9247 | da5014acde3a |
| `blender_console/render_diff.py` | 13232 | dacf9261515a |
| `blender_console/render_diff_live.py` | 8187 | cf7788bfdd1e |
| `blender_console/test_escape.py` | 4448 | 1d6b5f52c0b2 |
| `blender_console/test_experience.py` | 14158 | d9e804d8dfbd |
| `blender_console/test_intake.py` | 5938 | 9f242b46603f |
| `blender_console/test_upstream_store.py` | 4412 | b949a80d8995 |
| `blender_console/ui_panel.py` | 7006 | a7a6342133fb |
| `blender_console/upstream_store.py` | 7542 | 79f4bea92eeb |
| `m9_web/_selftest.mjs` | 7414 | c552162bd233 |
| `m9_web/flicker.html` | 7156 | c5472c4bfbb7 |
| `m9_web/index.html` | 27671 | 8746e1a1e77b |
| `m9_web/README.md` | 1622 | 15e5a9dbdd67 |
| `m9_web/state.json` | 2782 | a46298011cdd |
| `m8_bridge/bootstrap_blender.py` | 2019 | c845908b27f0 |
| `m8_bridge/gn_bridge.py` | 8106 | 5d391f3b2998 |
| `m8_bridge/start_gn_bridge.bat` | 401 | 15a61bce17db |

## L1 传输壳 — 传输壳（fork Brickfly MCP + gn 工具薄封装，非主体）

| 文件 | 字节 | SHA256 前 12 位 |
|---|---|---|
| `m8_bridge/brickfly_mcp_src/brickfly_mcp/__init__.py` | 415 | ce9a354f526a |
| `m8_bridge/brickfly_mcp_src/brickfly_mcp/addon_manager.py` | 17952 | 8e190d21a4e4 |
| `m8_bridge/brickfly_mcp_src/brickfly_mcp/bundled/__init__.py` | 0 | e3b0c44298fc |
| `m8_bridge/brickfly_mcp_src/brickfly_mcp/bundled/addon.py` | 204738 | 8e99f8493afa |
| `m8_bridge/brickfly_mcp_src/brickfly_mcp/config.py` | 917 | a70c8e3d707e |
| `m8_bridge/brickfly_mcp_src/brickfly_mcp/consent_prompt.py` | 7583 | 9f6ef0b97ea2 |
| `m8_bridge/brickfly_mcp_src/brickfly_mcp/safe_mode.py` | 43987 | d3bc1f43f470 |
| `m8_bridge/brickfly_mcp_src/brickfly_mcp/server.py` | 101807 | c2aabbaf7e57 |
| `m8_bridge/brickfly_mcp_src/brickfly_mcp/telemetry.py` | 12852 | 09c5bc161f85 |
| `m8_bridge/brickfly_mcp_src/brickfly_mcp/telemetry_decorator.py` | 17439 | fea2b67a3524 |
| `m8_bridge/brickfly_mcp_src/brickfly_mcp/trajectory.py` | 57820 | 607d0a1b070c |

## L2 部署载荷 — Blender 侧部署载荷 gn_deploy（与主线零漂移已校验）+ whl 分发件

| 文件 | 字节 | SHA256 前 12 位 |
|---|---|---|
| `m8_bridge/gn_deploy/console.py` | 51726 | 6fb67c1dc9b0 |
| `m8_bridge/gn_deploy/console_live.py` | 5453 | 34d7dc2827c0 |
| `m8_bridge/gn_deploy/core_types.py` | 32174 | 3d72195157bf |
| `m8_bridge/gn_deploy/director.py` | 17248 | 2a886a163f09 |
| `m8_bridge/gn_deploy/escape.py` | 11942 | 29cf1b7bb809 |
| `m8_bridge/gn_deploy/experience.py` | 21032 | 11ae2a6ffa37 |
| `m8_bridge/gn_deploy/gn_ab.py` | 15822 | 377b495a7e96 |
| `m8_bridge/gn_deploy/gn_adapter.py` | 31055 | 55d9f6da2a8c |
| `m8_bridge/gn_deploy/gn_adapter_live.py` | 10918 | 0b7979c8dd8a |
| `m8_bridge/gn_deploy/gn_artifact.py` | 5133 | 8fc88b053b99 |
| `m8_bridge/gn_deploy/gn_bridge.py` | 8106 | 5d391f3b2998 |
| `m8_bridge/gn_deploy/gn_console.py` | 22522 | f4a7bb132040 |
| `m8_bridge/gn_deploy/gn_session.py` | 31462 | 7306bf93f5da |
| `m8_bridge/gn_deploy/gn_session_live.py` | 14824 | a9011c45c806 |
| `m8_bridge/gn_deploy/gn_verify.py` | 14876 | f066e4fca15b |
| `m8_bridge/gn_deploy/intake.py` | 12672 | 44b870ce6a96 |
| `m8_bridge/gn_deploy/m1_core.py` | 32814 | 3825f7531792 |
| `m8_bridge/gn_deploy/m2_edge_live.py` | 3903 | 038330ff53ee |
| `m8_bridge/gn_deploy/m2_predicates_live.py` | 13478 | 5ee03d789566 |
| `m8_bridge/gn_deploy/m36_live.py` | 7442 | 3d16d4719b6c |
| `m8_bridge/gn_deploy/m411_live.py` | 9073 | 25d3c29ff61b |
| `m8_bridge/gn_deploy/m413_live.py` | 5541 | cd598f879a2e |
| `m8_bridge/gn_deploy/m42_live.py` | 7484 | ddd67f54c45b |
| `m8_bridge/gn_deploy/m45_live.py` | 8016 | f6c0c7b49585 |
| `m8_bridge/gn_deploy/m4_compile_live.py` | 10667 | b880989ae331 |
| `m8_bridge/gn_deploy/m5_ab_live.py` | 10336 | 9f09734e7f49 |
| `m8_bridge/gn_deploy/m5_spec_live.py` | 9433 | af6fca07ef26 |
| `m8_bridge/gn_deploy/m6_live.py` | 11438 | 1296b8ba183d |
| `m8_bridge/gn_deploy/m7_director_live.py` | 11316 | b0cfa21afb12 |
| `m8_bridge/gn_deploy/m7v2_live.py` | 8980 | 85e049e02c73 |
| `m8_bridge/gn_deploy/m92_live.py` | 6916 | f430492c9083 |
| `m8_bridge/gn_deploy/m9_intake_live.py` | 6049 | b6276890f0af |
| `m8_bridge/gn_deploy/mat_compiler.py` | 12428 | 926843d177c5 |
| `m8_bridge/gn_deploy/op_compiler.py` | 26008 | 24550b9272d4 |
| `m8_bridge/gn_deploy/plan_schema.py` | 15866 | e5c5e05d533f |
| `m8_bridge/gn_deploy/postfx.py` | 9247 | da5014acde3a |
| `m8_bridge/gn_deploy/render_diff.py` | 13232 | dacf9261515a |
| `m8_bridge/gn_deploy/render_diff_live.py` | 8187 | cf7788bfdd1e |
| `m8_bridge/gn_deploy/test_escape.py` | 4448 | 1d6b5f52c0b2 |
| `m8_bridge/gn_deploy/test_experience.py` | 14158 | d9e804d8dfbd |
| `m8_bridge/gn_deploy/test_intake.py` | 5938 | 9f242b46603f |
| `m8_bridge/gn_deploy/test_upstream_store.py` | 4412 | b949a80d8995 |
| `m8_bridge/gn_deploy/ui_panel.py` | 7006 | a7a6342133fb |
| `m8_bridge/gn_deploy/upstream_store.py` | 7542 | 79f4bea92eeb |
| `m8_bridge/brickfly_mcp-2.1.0-gn-py3-none-any.whl` | 111223 | f6fb592cd5c1 |

## L3 验收结果 — 验收结果：R5 完结批次（2026-09-27 21:30-22:38，Blender 侧代码零变更故有效）+ R6 传输链重跑

| 文件 | 字节 | SHA256 前 12 位 |
|---|---|---|
| `console_result.json` | 944 | 154ca5776a63 |
| `exp1_result.json` | 186 | 1bbe5cecd1a8 |
| `gn_ab_result.json` | 3975 | bafe703270a0 |
| `gn_adapter_live_result.json` | 3487 | 18f29fc8486b |
| `gn_probe_result.json` | 21415 | cb80fd76102b |
| `gn_session_live_result.json` | 4389 | 43bb56730976 |
| `m2_predicates_result.json` | 4246 | d81dbed0ca03 |
| `m36_result.json` | 2905 | 220865a5296f |
| `m411_result.json` | 2982 | 819752459bf9 |
| `m42_result.json` | 2981 | 8c92849bfdd7 |
| `m45_result.json` | 2909 | 435ae515cd59 |
| `m4_compile_live_result.json` | 2990 | 3e5d7230381f |
| `m5_ab_live_result.json` | 3190 | b7d96dcfcc4c |
| `m5_spec_result.json` | 3723 | 0fa18601d59b |
| `m6_live_result.json` | 2718 | a0e8d6785def |
| `m7_director_live_result.json` | 2499 | e9072da6474f |
| `m92_result.json` | 2838 | 60cfd65c3bf6 |
| `m9_intake_live_result.json` | 2140 | fdd4d3b4fd42 |
| `probe_m43_result.json` | 2489 | cdf4d3a25271 |
| `probe_m49_result.json` | 1356 | 192b935119b8 |
| `probe_m49c_result.json` | 837 | 8158caba9939 |
| `probe_nodeids_result.json` | 1187 | 625b0a45dbc1 |
| `probe_ops_result.json` | 3539 | 107d1b751f8b |
| `probe_render_result.json` | 711 | 64f6e920d94f |
| `render_diff_live_result.json` | 1678 | 503cc2711e7b |
| `m8_bridge/e2e_result.json` | 1413 | a68175f17254 |
| `m8_bridge/mcp_smoke_result.json` | 2183 | f8d5a136b8a5 |
| `m8_bridge/sandbox_probe_result.json` | 3376 | 8859183c861a |

## L4 文档 — 工单/交接/规划/审计/交付与发布说明

| 文件 | 字节 | SHA256 前 12 位 |
|---|---|---|
| `m8_bridge/M8-R2交付说明.md` | 3012 | 58bc49235217 |
| `m8_bridge/M8-R6发布说明_2.1.0-gn.md` | 5020 | 11b894217af0 |
| `工单_v2_BlenderAI建模控制台.md` | 50323 | df36c34d457e |
| `总工单审计_2026-09-27.md` | 6195 | b83e8d03c26a |
| `进度规划_2026-09-27.md` | 7504 | 7b11cb69a868 |
| `零损失交接文档.md` | 58181 | a01868d8cd51 |