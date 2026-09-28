# blender_console 架构图集

> 图即代码——全部 Mermaid 格式，GitHub/GitLab 原生渲染，PR 可 diff。
> v2（2026-09-29）：按 AST 实测 import 重制，修 v1 的三处矛盾与假边。
>
> **方法学收口（回应 v1 验收）**：
> 1. **数据锚**：每张依赖图可由 `python docs/architecture/ast_deps.py` 复算——
>    import 关系以 AST 解析为准，**不手写**。改完代码跑一遍，diff 即图 diff。
> 2. **黑话词典**：见文末 ⑨——所有 M/A/EXP 编号在词典里有出处与一句话解释，
>    图内不再出现未收录的黑话；新黑话先入词典再上图。
> 3. **过期挂单**：见文末 ⑩——每张图有"数据锚命令 + 生成日期 + 过期判据"。
>    图与代码打架时，**以代码为准、图挂单重画**（过期图比没图害人）。

---

## ① 容器图（系统架构）

```mermaid
graph TB
    subgraph SIDE["用户侧"]
        USER["👤 用户/导演"]
        WEB["m9_web<br/>Web 控制台"]
    end

    subgraph CHAT["对话层"]
        AI["🤖 LLM（会话层）"]
    end

    subgraph CORE["blender_console 核心"]
        INTAKE["intake.py<br/>提问协议（M9-1b ①）"]
        LT["logic_tree.py<br/>逻辑树 v2.0"]
        CONSOLE["console.py<br/>全链入口（M1-M9 ①）"]
        PS["plan_schema.py<br/>plan-JSON 校验"]
        OC["op_compiler.py<br/>op→GN 编译"]
        GS["gn_session.py<br/>GN 会话层"]
        GA["gn_adapter.py<br/>GN 版本隔离"]
        ART["gn_artifact.py<br/>产物留痕"]
        GV["gn_verify.py<br/>机械验证器"]
        RD["render_diff.py<br/>渲染 diff"]
        MC["mat_compiler.py<br/>材质编译"]
        RC["rig_compiler.py<br/>角色编译"]
        M1["m1_core.py<br/>数据层（DAG/WAL/RT/VP/SC）"]
        EXP["experience.py<br/>经验库（M6 ①）"]
        DIR["director.py<br/>导演模式（M7 ①）"]
        ESC["escape.py<br/>逃逸舱（M4-4 ①）<br/>⚠️ 当前零调用方"]
        NLG["nlg_bands.py<br/>带化判词<br/>⚠️ 当前零调用方"]
    end

    subgraph BLENDER["Blender"]
        GN["Geometry Nodes<br/>节点组"]
        VIEW["视口/渲染"]
    end

    subgraph STORE["数据"]
        LTJ["logic_trees/*.json<br/>课题逻辑树"]
        EXPJ["experience_library.json<br/>RAG 语料"]
        STATE["state.json<br/>m9_web 状态"]
    end

    USER --> WEB
    USER --> AI
    AI -->|"常规作业（提问协议）"| INTAKE
    AI -->|"小修小补快捷道（见注）"| CONSOLE
    WEB -->|"GET /api/state"| STATE
    WEB -->|"POST /api/*"| CONSOLE

    INTAKE --> LT
    CONSOLE --> OC
    CONSOLE --> GA
    CONSOLE --> GS
    CONSOLE --> ART
    CONSOLE --> GV
    CONSOLE --> M1
    CONSOLE --> EXP
    CONSOLE --> MC
    CONSOLE --> RC
    CONSOLE --> RD
    CONSOLE --> PS
    OC --> MC
    DIR --> CONSOLE
    OC -->|"GN nodes"| GN
    GA <--> GN
    GN --> VIEW
    RD --> VIEW
    LTJ -.-> INTAKE
    LTJ -.-> LT
    EXPJ -.-> EXP
```

> **注（AI → CONSOLE 快捷道）**：常规建模作业必须走 `intake` 提问协议
> （brief→提问卡→冻结 PRD），保证 parts 覆盖率留痕。允许直连 `console` 的
> 仅限：对**已冻结 PRD 的会话**做小修小补（set_param / 重编译单段）——
> 不新开 parts、不改 scope。新作业从快捷道进来 = 绕过覆盖率门 = 违规。

---

## ② 模块依赖图（AST 静态解析，非手画）

**数据锚**：`python docs/architecture/ast_deps.py`（生成于 2026-09-29）。
只画核心生产模块；`*_live.py` 实验、`test_*.py`、probe 脚本不入图。

```mermaid
graph LR
    subgraph ENTRY["入口层"]
        CONSOLE["console.py"]
        DIR["director.py"]
    end

    subgraph COMPILE["编译层"]
        OC["op_compiler.py"]
        MC["mat_compiler.py"]
        RC["rig_compiler.py"]
    end

    subgraph ADAPT["适配层"]
        GA["gn_adapter.py"]
        GS["gn_session.py"]
        ART["gn_artifact.py"]
    end

    subgraph VERIFY["验证层"]
        GV["gn_verify.py"]
        BIM["bim_predicates.py"]
    end

    subgraph DATA["数据层"]
        M1["m1_core.py"]
        EXP["experience.py"]
    end

    subgraph PROTO["协议层"]
        INTAKE["intake.py"]
        LT["logic_tree.py"]
        PS["plan_schema.py"]
    end

    subgraph VISUAL["视觉层"]
        RD["render_diff.py"]
        NLG["nlg_bands.py<br/>⚠️ 零调用方"]
    end

    subgraph GOV["治理层"]
        ESC["escape.py<br/>⚠️ 零调用方"]
        US["upstream_store.py"]
    end

    CONSOLE --> OC
    CONSOLE --> MC
    CONSOLE --> RC
    CONSOLE --> GA
    CONSOLE --> GS
    CONSOLE --> ART
    CONSOLE --> GV
    CONSOLE --> M1
    CONSOLE --> EXP
    CONSOLE --> PS
    CONSOLE --> RD
    OC --> MC
    PS --> OC
    DIR --> CONSOLE
    INTAKE --> LT
    US --> EXP
```

### 依赖规则（AST 实测，生成命令见数据锚）

| 被依赖方 | 被谁依赖（AST 实测） | 备注 |
|---|---|---|
| m1_core | console, gn_session | 数据层不反向依赖 ✓ |
| gn_adapter | console, gn_session, gn_ab | 适配层自包含 ✓ |
| gn_verify | console, gn_session, gn_ab | 验证器被两处复用 |
| gn_session | console | GN 会话组合层 |
| gn_artifact | console | 产物留痕 |
| op_compiler | console, **plan_schema** | plan_schema 反向 import 它取 SEGMENT_OPS 白名单 |
| mat_compiler | console, op_compiler | |
| rig_compiler | console | |
| plan_schema | console | **只此一家**（v1 表里的 intake/logic_tree 均实测不存在） |
| experience | console, upstream_store | |
| render_diff | console | |
| intake | _probe_intake_schema, m9_intake_live（实验脚本） | 核心模块暂无人 import 它——AI 会话层是它的运行时调用方 |
| logic_tree | intake（实测：intake import logic_tree） | **logic_tree 不 import plan_schema**——to_plan 产出纯 dict，校验在 console.compile 内 |
| director | exp7_live（实验脚本） | 运行时由 AI 会话层驱动 |

### v1 → v2 修正记录（验收裁决）

| v1 说法 | AST 裁决 | 修正 |
|---|---|---|
| 图② `LT --> PS` 假边 | logic_tree 不 import plan_schema | 删边 |
| 表：plan_schema 被 console, intake, logic_tree 依赖 | 只有 console | 改 |
| 注：logic_tree 不依赖 plan_schema | **正确** | 保留并升格为修正记录 |
| 时序图③ intake 调 PS 校验 | intake 不 import plan_schema；校验在 console.compile 内 | 改③ |
| op_compiler 依赖 gn_adapter | 实测不依赖 | 删 |
| plan_schema 依赖关系漏了它 import op_compiler | 实测 import（SEGMENT_OPS 白名单） | 补 |
| console 的 gn_session/gn_artifact 依赖没画 | 实测依赖 | 补 |

---

## ③ 时序图：建模作业全流程（intake → plan → compile → verify → render）

```mermaid
sequenceDiagram
    actor U as 用户/导演
    participant I as intake.py
    participant LT as logic_tree.py
    participant C as console.py
    participant PS as plan_schema.py
    participant OC as op_compiler.py
    participant GA as gn_adapter.py
    participant GV as gn_verify.py
    participant RD as render_diff.py
    participant M1 as m1_core.py
    participant EXP as experience.py

    U->>I: brief + parts + scene_facts
    I->>I: ask_round() 提问卡
    U->>I: submit(answers)
    I->>I: freeze() → PRD 卡
    I->>LT: to_plan_skeleton(logic_tree=lt)
    Note over LT: 逻辑树 deps 并行（两桥合一 ①）：<br/>to_plan() 产纯 dict plan-JSON<br/>（SEGMENT_OPS 白名单映射在 logic_tree 内）
    LT-->>I: plan-JSON（sections + constraints）

    I->>C: plan（经会话层传入）
    rect rgb(255, 248, 240)
        Note over C,PS: 校验在 console.compile 内部（AST 实锤：<br/>intake/logic_tree 均不 import plan_schema）
        loop 每个section
            C->>PS: PlanSchema 预校验（M4-7）
            PS-->>C: issues[]（零 error 才放行）
            C->>OC: compile_op(spec)
            OC->>GA: add_node / link / group_io
            GA-->>OC: (node, socket)
            OC-->>C: (node, socket_name)
            C->>C: dag.add(StepRecord) + WAL.append
        end
    end

    rect rgb(240, 255, 240)
        Note over C,GV: 机械验证（EXP1 零逃逸纪律）
        C->>GV: verify(label)
        GV-->>C: ok + summary + suggestions[]
    end

    rect rgb(255, 240, 255)
        Note over C,RD: 渲染 diff 三件套（M9-3/B1）
        C->>RD: render_diff(label)
        RD-->>C: render_diff_b64 + summary + refutable_assumption
        C-->>U: 渲染图 + 变更判词 + 可反驳假设
    end

    rect rgb(248, 248, 255)
        Note over M1,EXP: 数据层沉淀（三环闭环）
        C->>M1: WAL.append + SnapshotStore.put + commits.commit
        C->>EXP: record_ai(attention, story, params, evidence)
        Note over EXP: RAG 闭环：下次检索反哺 intake
    end
```

---

## ④ 状态机：段落生命周期

```mermaid
stateDiagram-v2
    [*] --> pending: to_plan() 生成 section

    pending --> building: Console.compile() 开始

    building --> passed: verify PASS + G1 human actor
    building --> failed: verify FAIL / Gate 拦截

    failed --> pending: retry(sees) 修正后重排队
    failed --> blocked: 需上游先修复

    pending --> blocked: deps 中有 failed

    passed --> [*]: 段落交付

    note right of building
        G1 铁门禁（M7-3 ①）：
        blockout 层（depth==0）
        pass_gate 需 human:* actor
        即使 AUTOPILOT 档
    end note

    note left of failed
        失败也入账（Orr war stories，见 ⑨）：
        verified_failure 带叙事
        是 RAG 核心资产
    end note
```

---

## ⑤ 逻辑树机制：节点转换流水

```mermaid
graph LR
    subgraph TREE["逻辑树（logic_trees/*.json）"]
        NODE["nodes[]<br/>id: 1.1/1.2/...<br/>tier: 1|2|3<br/>deps: [前置节点]<br/>build: {op, params_real}<br/>gate: {machine_spec, visual}<br/>status: pending|passed|..."]
    end

    subgraph FLOW["logic_tree.py 处理流水"]
        LT_VALIDATE["validate_logic_tree()"]
        LT_TOPO["topo_order() → deps 权威拓扑"]
        LT_TOPLAN["to_plan(tree) → SEGMENT_OPS 映射<br/>（白名单表在 logic_tree 内，<br/>与 plan_schema 的白名单是两份——见挂单 W-2）"]
        LT_RUNNER["LogicTreeRunner.next_ready()"]
    end

    subgraph OUT["产出"]
        PLAN["plan-JSON（纯 dict）<br/>sections + constraints<br/>由 console.compile 内 PlanSchema 校验"]
        READY["可开工节点集合<br/>deps 全 passed"]
        STATUS["节点状态回写<br/>passed/failed + evidence"]
    end

    NODE --> LT_VALIDATE
    LT_VALIDATE --> LT_TOPO
    LT_TOPO --> LT_TOPLAN
    LT_TOPLAN --> PLAN
    NODE --> LT_RUNNER
    LT_RUNNER --> READY
    READY --> STATUS
```

---

## ⑥ 数据流图：三环融合（管线 × 视觉 × RAG）

```mermaid
graph TD
    subgraph PIPE["管线环"]
        A1["逻辑树 deps 拓扑序"] --> A2["to_plan() SEGMENT_OPS 映射"]
        A2 --> A3["PlanSchema 零 issue（console.compile 内）"]
        A3 --> A4["Console.compile GN 编译"]
        A4 --> A5["verify PASS"]
    end

    subgraph VIS["视觉反馈环"]
        B1["渲染 diff PNG"] --> B2["谓词 diff JSON"]
        B2 --> B3["NLG 带化判词<br/>⚠️ 设计位：nlg_bands 当前零调用方（挂单 W-1）"]
        B3 --> B4["LLM 看图+读报告"]
        B4 --> B5["意图 patch（node_id / field / new_value）"]
        B5 --> A2
    end

    subgraph RAG["RAG 沉淀环"]
        C1["节点 passed/failed"] --> C2["record_ai 注意引导+叙事+gate 证据"]
        C2 --> C3["四层索引沉淀<br/>向量+参数+图+时序"]
        C3 --> C4["recall 反哺下个节点<br/>配方复用+verified_failure"]
        C4 -.-> A1
    end

    A5 --> B1
    B5 --> A2
```

---

## ⑦ 部署图（运行时拓扑）

```mermaid
graph TB
    subgraph DEV["用户设备"]
        BROWSER["浏览器<br/>http://127.0.0.1:8377"]
    end

    subgraph HOST["本机"]
        subgraph BP["Blender 5.2 进程"]
            BPY["bpy（Python 3.11）"]
            GNSERVER["API 服务：8377<br/>（Blender 内嵌——规划中，挂单 W-3）"]
            GN_NODES["GN 节点组<br/>（op_compiler 产物）"]
        end
        subgraph SYSPY["系统 Python 进程"]
            STATIC["python -m http.server:8377<br/>（纯静态兜底）"]
        end
        subgraph FS["文件系统"]
            LTJSON["logic_trees/*.json"]
            EXPJSON["experience_library.json"]
            STATE["m9_web/state.json"]
        end
    end

    subgraph GH["GitHub"]
        REPO["master666-max/blender-ai-console"]
    end

    BROWSER -->|"二选一互斥（同一端口 8377：<br/>Blender 内嵌 API 优先；未启动时<br/>静态兜底只读）"| GNSERVER
    BROWSER -.->|"备用"| STATIC
    GNSERVER --> BPY
    GNSERVER --> STATE
    GNSERVER --> GN_NODES
    BPY --> GN_NODES
    STATIC --> STATE
    GNSERVER --> EXPJSON
    REPO -->|"git clone"| LTJSON
```

> **端口语义（v1 撞车修正）**：`8377` 同一端口**互斥启用**——Blender 内嵌
> API 服务是主（可写：compile/revert/set_param）；纯静态 http.server 是兜底
> （只读 state.json，供无 Blender 会话时看流程轴）。**不能同时跑**——
> 端口冲突时后者启动失败，属预期行为。

---

## ⑧ 维护策略

| 图 | 数据锚 | 更新触发 | 维护方式 |
|---|---|---|---|
| 容器图（①） | 无自动锚 | 架构变更时 | 手画（Mermaid） |
| 模块依赖图（②） | `ast_deps.py` | **每次 import 变更** | AST 实测 + diff |
| 时序图（③） | 无自动锚 | 流程变更时 | 手画（Mermaid） |
| 状态机（④） | logic_tree 状态枚举 | 新增状态时 | 手画（Mermaid） |
| 数据流图（⑥） | 无自动锚 | 三环接口变更时 | 手画（Mermaid） |
| 部署图（⑦） | server.py 实测 | 部署变更时 | 手画（Mermaid） |

渲染回归：`python docs/architecture/verify_mermaid.py` → 无头 Chrome 实渲染，
逐块 PASS/FAIL（mermaid 语法炸点在 PR 前拦住）。

---

## ⑨ 黑话词典（图内编号的唯一出处——新黑话先入词典再上图）

| 黑话 | 出处 | 一句话解释 |
|---|---|---|
| M1-M9 | 里程碑编号 | M1 数据层 / M2 验证 / M3 回退 / M4 编译器 / M5 实验对比 / M6 经验库 / M7 导演模式 / M8 变体 / M9 交互层 |
| M4-4 | escape.py | 逃逸舱：AI 直出 op-JSON 被 R12 拒绝时的人工审核逃生通道（禁 AI exec 代码） |
| M4-7 | console.compile 预校验 | 声明式契约校验：编译前拦 schema 违例（结构化错误带 suggestions） |
| M6-2b | experience.py | 免疫通道治理：AI 写入强制 draft，晋升必须过人（human:* promote） |
| M7-3 | logic_tree.py | G1 铁门禁 + sees 字段：blockout 层验收需 human:* actor；修正提案必须引用所见 |
| M9-1b | intake.py | 提问协议：brief → 提问卡 → 冻结 PRD，保证 parts 覆盖率留痕 |
| M9-3 / B1 | render_diff.py | 渲染 diff 三件套：图 + 变更判词 + 可反驳假设 |
| A1/A2 | WAL/快照修复 | 快照内容寻址落盘；restore_point 与 compaction 边界分离命名空间 |
| A14 | checkpoint | GoodPoint：mesh+params 快照，回退锚点 |
| A20 | gn_verify | 零逃逸纪律：门禁 + 响亮失败，不允许静默跳过验证 |
| 两桥合一 | intake ↔ logic_tree | to_plan_skeleton 接逻辑树参数：PRD 骨架与逻辑树 deps 并行段合并成一份 plan |
| SEGMENT_OPS | plan_schema / logic_tree | plan 段合法 op 白名单（两份表：schema 校验用 / logic_tree 映射用，见挂单 W-2） |
| G1 | logic_tree 状态机 | 铁门禁等级：blockout 层（deps 深度 0）强制人工验收 |
| Orr war stories | 人类学调研（6 组访谈） | 失败经验与成功经验同等核心资产——verified_failure 不衰减不过期 |
| 6 组人类学 | 大调研产出 | 六组跨学科调研中的人类学组：经验 = 注意引导 + 叙事（含失败），支撑经验库设计 |
| EXP1 | 实验记录 | 门禁+响亮失败=零静默逃逸实验：迭代杠杆 0%→80% |
| 三环 | 架构总纲 | 管线环 × 视觉反馈环 × RAG 沉淀环（图⑥） |
| verified_failure | experience.py | 机器门禁验证过的失败：AI 可凭谓词证据入账，status 仍 draft（晋升过人） |

---

## ⑩ 过期挂单（图与代码打架时：以代码为准，图挂单重画）

| 挂单 | 内容 | 判据（何时销单） |
|---|---|---|
| W-1 | **nlg_bands 零调用方**：⑥ 视觉反馈环的 B3（NLG 带化判词）是设计位，代码里还没有 RD→NLG 的调用 | gn_verify/console import nlg_bands 并在 verify/render 后产判词时销单，图②⑥补实边 |
| W-2 | **SEGMENT_OPS 两份白名单**：plan_schema.py 与 logic_tree.py 各维护一份 op 白名单，漂移风险 | 合并为单一真源（logic_tree 从 plan_schema import）时销单 |
| W-3 | **Web 控制台 API 层缺失**：console.html 调 /api/revert 等，但 server.py 纯静态；回退能力已真机验证（revert_live.py 13/13）但 HTTP 不通 | Blender 内嵌 API server（bpy.app.timers 主线程队列）落地时销单 |
| W-4 | **escape 零调用方**：M4-4 逃逸舱是治理关键件但核心链路无人 import（设计上由 AI 会话层显式走） | AI 会话层接线 escape 通道时销单，图①②补实边 |
| W-5 | **intake 核心模块无内部调用方**：只被实验脚本 import，运行时调用方是 AI 会话层（进程外） | 会话层代码入库时销单 |

> 挂单纪律：图上每个"⚠️/规划中/设计位"标记必须对应 ⑩ 里一行挂单；
> 挂单销单与图修改同一个 PR，不允许只改图不销单（或反之）。
