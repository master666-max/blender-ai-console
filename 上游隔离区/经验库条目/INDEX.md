# 经验区索引（experience/INDEX.md）

> **活区**：源根条目可随时追加，本仓发行 zip 为快照（快照时点：v2.7.0，2026-09-23）。
> **只增不改**：条目永不编辑，修订=新版本条目（supersedes 链）。
> **出处三件套**缺一不收：任务产物锚 + 关键输出原话 + 可复算命令。
> **状态机**：draft → verified → promoted / pending / rejected；未复核条目永不进分册。
> **引擎接口（预留）**：演化引擎只允许以 `status: draft` + `source: engine:<id>` 追加；
> 晋升必须过人 + 发版门（免疫通道，对齐 self-evolving-kb 审计线做法）。
> EXP-001~014 为建区迁移（原 BMCP-ERR-001~014，编号映射见各条 legacy 字段）。

| id | 原编号 | 一句话 | 状态 | 晋升去向 |
|---|---|---|---|---|
| EXP-001 | BMCP-ERR-001 | 批量生成器双前缀（传入名已带前缀再拼前缀）+ 模式匹配清理 → 误删自建 353 物体 | promoted | 08 分册 §5 |
| EXP-002 | BMCP-ERR-002 | hide_set（眼标）≠ 渲染可见性；恢复用户可见性/World 后渲染 → 坦克入镜/天光过曝 | promoted | 03 分册 §6 |
| EXP-003 | BMCP-ERR-003 | 用户 World 的 Background 颜色被贴图驱动时改 default_value 无效 → 天光过曝 | promoted | 03 分册 §6.3 |
| EXP-004 | BMCP-ERR-004 | 变换后立即读 matrix_world 拿到旧矩阵（depsgraph 延迟求值） | promoted | 03 分册 §6.5 |
| EXP-005 | BMCP-ERR-005 | 渲染隔离窗口内 orphans_purge 删掉 users==0 的用户 World（DSH 实测真事故，快照规则救命… | promoted | 03 分册 §6.3 / SKILL §5 |
| EXP-006 | BMCP-ERR-006 | 四阶段隔离是单向的：只重跑几何 → 下游材质指派全部静默丢失（无报错） | promoted | 12 分册 §2 |
| EXP-007 | BMCP-ERR-007 | 组实例节点按 `'NodeGroup'` 创建 → 报错（中文本地化：尚未定义节点类型 'NodeGroup'） | promoted | nodes/WD_wood.py |
| EXP-008 | BMCP-ERR-008 | 被墙环境资产获取全链路 000（SNI 阻断）；webReader 拒带参 URL；PolyHaven 未启用报 Unk… | promoted | 06 分册 §5A |
| EXP-009 | BMCP-ERR-009 | 集合跨调用持久性异常（隔离集合下个调用消失）+ 半途报错留孤儿块 | promoted | 08 分册 §6 |
| EXP-010 | BMCP-ERR-010 | 父化矩阵三定律：新 location 后读 matrix_world 得旧值致多级父化整链偏移；跨调用验收；同名重建 .… | promoted | 01 分册 §6 |
| EXP-011 | BMCP-ERR-011 | ShaderNodeMix Factor 方向反了（Factor=0 输出 A/inputs[6]）→ 全车呈磨损色 | promoted | 02 分册 §4 |
| EXP-012 | BMCP-ERR-012 | 5.2 Sky Texture 枚举变更：'NISHITA' 删除 → SINGLE_SCATTERING 等（参数随迁… | promoted | 03 分册 §4 |
| EXP-013 | BMCP-ERR-013 | 动态 setattr（非字面量属性名）秒拒 | promoted | 09 分册 §2 |
| EXP-014 | BMCP-ERR-014 | 烘焙方向反了**不报错**只产出平图（active 必须低模；EMIT 取源着色）——两次静默失败，法线整套作废 | promoted | 07 分册 §7.2A |
