# Blender 建模步骤 RAG 化 —— 方案整理

> 来源：智谱清言分享页（原问题："AI，用blender建模，怎么把每一步存到rag库里，以达到，项目可持续开放"）
> 本文档在原回答基础上做了**结构化重排 + 技术纠错 + 落地到你现有工具链**的处理。

---

## 一、核心思想（一句话）

**不要把 `.blend` 当资产，要把"操作过程"当资产。**

`.blend` 是**状态快照**（只记录结果），RAG 库存的是**过程历史**（记录怎么来的）。
建一条 `操作 → 结构化记录 → 向量索引 → 检索复用 → 反馈加权` 的闭环管道，项目才能跨人、跨时间、跨 AI 会话持续演进。

"可持续开放"拆解成四个可验证的目标：

| 目标 | 含义 | 验收标准 |
|---|---|---|
| 可复现 | 任一历史步骤能重放 | 给定 op_id，能在干净场景复现结果 |
| 可追溯 | 知道某步是谁、何时、为什么做的 | 每条记录带 author/timestamp/rationale |
| 可复用 | 新项目能检索到旧步骤并改参数复用 | 检索命中率 + 采纳率可统计 |
| 可协作/开放 | 团队或社区能贡献与消费 | 多租户隔离 + license 字段 + 公开子集导出 |

---

## 二、原回答要点速览（忠实浓缩）

原回答给出五层架构：

```
Blender 操作
  → 捕获层（Python handler / operator 日志 / MCP 脚本归档）
  → 归一化层（JSON 化 + 元数据标注）
  → 向量化层（Embedding）
  → 存储层（向量库 + 原始脚本归档）
  → 检索层（查询 → 重放/改参数）+ 反馈层（标注优劣 → 更新索引）
```

**三种捕获方案对比（原表）**

| 方案 | 覆盖度 | 侵入性 | 适用场景 |
|---|---|---|---|
| A. Handler 抓 `wm.operators` | 高（GUI/脚本都能捕） | 低（被动监听） | 全量操作流水 |
| B. MCP Server 归档 AI 脚本 | 中（只记 AI 生成部分） | 中（需开 Socket） | AI 驱动工作流 |
| C. Undo History + 保存快照 | 中（需主动触发） | 低 | 离线复盘、回溯 |

原回答推荐 **A + B 组合**，写入同一个 JSONL。

**存储选型（原表）**：Chroma（轻量原型）/ LanceDB（本地长期存档，支持版本）/ Qdrant（生产、多租户）。

**可持续机制四招**：双轨存储（.blend 走 Git LFS，过程走 RAG 库）、索引版本管理（metadata 记 version，防 embedding 漂移）、反馈闭环（adopted/rating/usage_count 回写）、协作开放（author/license + 多租户）。

---

## 三、我的判断：哪里靠谱，哪里会翻车

### ✅ 靠谱的部分

- **五层管道分层**是对的，捕获/归一化/向量化分开，便于分别替换。
- **"不要只存 .blend"** 这个洞察是整套方案的价值根基。
- **code + 自然语言描述 + 上下文元数据 三元组**作为向量化单元 —— 这个设计正确，纯代码 embedding 效果差，必须配 NL 描述。
- **索引版本管理**（embedding 模型/切分策略变了要重建并保留旧版）—— 这是实战经验，很多 RAG 项目死在这。

### 🚨 会翻车的部分（原回答的技术错误，必须改）

| # | 问题 | 原代码 | 为什么错 | 修正 |
|---|---|---|---|---|
| 1 | `dir(op)` 全属性遍历 | `{attr: getattr(op, attr) for attr in dir(op)...}` | 会捞到 `bl_rna`、`rna_type`、`properties` 等几十个内部属性，含不可序列化对象，且 `dir()` 会触发 RNA 反射，极慢 | 只取 `op.properties` 或白名单字段；用 `op.as_keywords()` 拿已修改参数 |
| 2 | 用 `depsgraph_update_post` 当触发器 | 每次依赖图更新都写日志 | 拖动鼠标一次可触发几十次，日志文件几小时就爆炸，且大量重复 | 换成 **去噪 + 去重**：`(bl_idname, props_hash)` 在时间窗内去重；或改用 `save_post` + 手动快照 + 脚本层捕获三轨并行 |
| 3 | `wm.operators` 不是完整历史 | 当作"操作栈"全量抓取 | `WindowManager.operators` 实际是 **operator redo 注册表**，只有带 `REGISTER` 选项的 operator 会进，且条目有限、会被清空。GUI 里的绝大多数操作（选择、视图旋转、模式切换）根本不在里面 | 别指望它做全量流水。**脚本层捕获才是主力信号源** |
| 4 | `exec()` 有返回值 | `result = exec(code)` | `exec` 永远返回 `None`，原样写进 MCP 里会把结果丢光 | 用 `exec(code, namespace)` + 从 namespace 取值，或改 `eval` / 捕获 stdout |
| 5 | `"usage_count": +1` | 元编程占位符 | 不是合法 Python，无法运行 | 先 `collection.get(ids=[op_id])` 读旧值再 +1，或单独维护计数表 |
| 6 | Embedding 默认走 OpenAI | `OpenAIEmbeddingFunction` | 联网 + 付费 + 数据出域，和"本地可持续"的目标冲突 | 换本地 embedding（见第五节） |

### 💡 更关键的一层：信噪比问题（原回答没提）

这是整套方案能不能跑通的分水岭。

- **operator 流水的信噪比极低**：真实建模过程里，一个"倒角"动作背后可能是 40 次框选、3 次视图旋转、2 次参数试错。全量流水里 95% 是噪音。
- **真正值得入库的是"语义化的建模配方"**，不是 operator 流水。

所以捕获层应该是**三轨、按价值排序**：

| 优先级 | 轨道 | 内容 | 信噪比 | 捕获方式 |
|---|---|---|---|---|
| P0 | **脚本轨** | AI/你主动执行的每段完整 Python | 高 | MCP `execute_code` 劫持归档（你已有 blender-mcp） |
| P1 | **快照轨** | 每个"里程碑"的场景 diff（对象树/修改器/材质） | 高 | `save_post` handler + 手动打点 |
| P2 | **操作轨** | `wm.operators` 采样 + 去噪 | 低 | 后台低频采样，仅作补充上下文 |

**结论：原回答把 A（操作轨）当主力，方向反了。应以 P0 脚本轨为主力。**

---

## 四、修正后的架构（五层）

```
┌─ 捕获层 ────────────────────────────────────────────┐
│  P0 脚本轨 (MCP execute_code 劫持)  ← 主力           │
│  P1 快照轨 (save_post / 里程碑打点)                  │
│  P2 操作轨 (wm.operators 采样 + 去噪) ← 补充         │
└────────────────────────────────────────────────────┘
                    ↓ ops_log.jsonl
┌─ 归一化层 ──────────────────────────────────────────┐
│  ① 可执行化：把 operator 记录还原成 bpy.ops 调用串    │
│  ② LLM 生成 50 字内自然语言描述                      │
│  ③ 打标签（建模/材质/UV/渲染/程序化）                 │
│  ④ 打上下文（blender_version / mode / 活跃对象）      │
│  ⑤ 去重（code hash + props hash）                    │
└────────────────────────────────────────────────────┘
                    ↓
┌─ 向量化层 ──────────────────────────────────────────┐
│  本地 embedding（bge-m3 / Qwen3-Embedding GGUF）     │
│  向量化文本 = description + "\n" + code              │
│  ⚠️ 记 version，模型/策略变更必须重建索引             │
└────────────────────────────────────────────────────┘
                    ↓
┌─ 存储层 ────────────────────────────────────────────┐
│  向量库：Weaviate（你 Dify 栈里已有）                │
│  关系库：Neo4j（操作依赖图：基元→修改器→材质）        │
│  原始归档：JSONL + Git LFS 的 .blend                 │
└────────────────────────────────────────────────────┘
                    ↓
┌─ 检索复用层 ────────────────────────────────────────┐
│  检索（只取 success=true）→ 拼进 prompt → LLM 改参数 │
│  三种复用：直接重放 / 参数化改造 / 多步组合成"配方"  │
└────────────────────────────────────────────────────┘
                    ↓
┌─ 反馈层 ────────────────────────────────────────────┐
│  adopted / rating / usage_count 回写 → 好步骤权重上升 │
└────────────────────────────────────────────────────┘
```

---

## 五、落地到你现有工具链（重点）

你手上已经具备**全部基础设施**，不需要新装任何东西：

| 环节 | 现成资产 | 用法 |
|---|---|---|
| Blender ↔ AI 通道 | **blender-mcp**（v1.9.1 / protocol 5 addon，在 `.dsh/skills/blender-mcp/`） | 直接当 P0 脚本轨的采集底座，在其 `execute_code` 处加一行归档 |
| 向量库 | **Weaviate**（Dify 栈 Docker 里跑着） | 建 `BlenderOp` class，存向量 + metadata |
| 关系/知识图谱 | **Neo4j**（同栈） | 存操作依赖链，支持"这个倒角是在哪个基元上做的"这类追问 |
| Embedding | **llama.cpp** + GGUF | 跑 `bge-m3` 或 `Qwen3-Embedding` 的 GGUF，**本地、中文强、免费、不出域** |
| 版本归档 | Git LFS | `.blend` 大文件 |

> ⚠️ 原回答推荐 Chroma + OpenAI embedding —— 那是给"从零开始的人"的方案。你已有 Weaviate/Neo4j/llama.cpp，**直接复用，别再起一套 Chroma**。

---

## 六、数据 Schema（定稿）

```json
{
  "id": "op_20260926_001",
  "track": "script",                        // script | snapshot | operator
  "type": "mesh_primitive_add",
  "code": "bpy.ops.mesh.primitive_cube_add(size=2, location=(0,0,1))",
  "description": "在原点上方创建一个 2 单位立方体",
  "tags": ["modeling", "primitive", "cube"],
  "context": {
    "blender_version": "4.5.0",
    "mode": "OBJECT",
    "active_object": "Cube",
    "deps": ["op_20260926_000"]             // 前序步骤 id → Neo4j 建边
  },
  "snapshot": "D:/rag/snaps/001.blend",     // P1 轨才有
  "author": "you",
  "license": "MIT",
  "success": true,
  "adopted": null,                          // 反馈层回填
  "rating": null,
  "usage_count": 0,
  "embed_version": "bge-m3@v1",             // 索引版本，防漂移
  "timestamp": "2026-09-26T20:00:00"
}
```

**检索用的 prompt 模板**

```
你是一个 Blender 建模助手。以下是历史操作库中检索到的相似步骤：
{context}

当前需求：{query}

要求：
1. 优先修改历史步骤的参数，不要重写
2. 输出可直接 exec 的 Python，不要省略 import
3. 若历史步骤都不适用，明确说明原因再写新代码
```

---

## 七、行动清单（按序执行）

| # | 动作 | 产出 | 依赖 |
|---|---|---|---|
| 1 | 在 blender-mcp addon 的 `execute_code` 加归档钩子 | `ops_log.jsonl` 开始落盘 | 无 |
| 2 | 跑通本地 embedding（llama.cpp 起 bge-m3 GGUF 服务） | 一个可调用的 embedding HTTP 端点 | 已有 llama.cpp |
| 3 | 写 `index.py`：JSONL → Weaviate | 向量库有数据 | 1、2 |
| 4 | 写 `query.py`：检索 + 拼 prompt | 命令行能查"怎么建圆柱" | 3 |
| 5 | 加 `save_post` 快照轨（.blend 里程碑 + Git LFS） | P1 数据 | 1 |
| 6 | 加反馈回写（adopted/rating/usage_count） | 权重开始分化 | 4 |
| 7 | Neo4j 建操作依赖图（deps 边） | 可追问"这步基于哪步" | 3 |
| 8 | 导出公开子集（去敏 + license） | 可对外共享 | 7 |

**MVP 定义**：跑完 1–4 就算闭环成立。别一开始就上 Neo4j 和反馈层。

---

## 八、一句话总结

> 整套方案的价值不在"存了多少条 operator 日志"，而在**把建模过程沉淀成可检索、可改参数复用、可追溯来源的"配方库"**。
> 所以优先级是：**先把 AI 执行的脚本原样归档（P0），再谈全量操作捕获。** 反了就变成日志灾难。
