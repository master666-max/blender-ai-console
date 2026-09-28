# blender_console 架构图集

> 图即代码——全部 Mermaid 格式，GitHub/GitLab 原生渲染，PR 可 diff。
> 生成日期：2026-09-28 | 数据来源：AST 静态解析（不手画）

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
        INTAKE["intake.py<br/>M9-1b 提问协议"]
        LT["logic_tree.py<br/>逻辑树 v2.0"]
        PS["plan_schema.py<br/>plan-JSON 校验"]
        CONSOLE["console.py<br/>全链入口（M1-M9）"]
        OC["op_compiler.py<br/>op→GN 编译"]
        GA["gn_adapter.py<br/>GN 版本隔离"]
        GV["gn_verify.py<br/>机械验证器"]
        RD["render_diff.py<br/>M9-3 渲染 diff"]
        MC["mat_compiler.py<br/>材质编译"]
        RC["rig_compiler.py<br/>角色编译"]
        ESC["escape.py<br/>M4-4 逃逸舱"]
        M1["m1_core.py<br/>数据层（DAG/WAL/RT/VP/SC）"]
        EXP["experience.py<br/>M6 经验库"]
        DIR["director.py<br/>M7 导演模式"]
        NLG["nlg_bands.py<br/>谓词→带化判词"]
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
    AI --> INTAKE
    AI --> CONSOLE
    WEB -->|GET /api/state| STATE
    WEB -->|POST /api/compile| CONSOLE

    INTAKE --> LT
    INTAKE --> PS
    LT --> PS
    LT -->|"to_plan()"| PS
    CONSOLE --> OC
    CONSOLE --> GA
    CONSOLE --> GV
    CONSOLE --> M1
    CONSOLE --> EXP
    CONSOLE --> MC
    CONSOLE --> RC
    CONSOLE --> RD
    OC --> MC
    DIR --> CONSOLE
    OC -->|GN nodes| GN
    GA <--> GN
    GN --> VIEW
    RD --> VIEW
```

---

## ② 模块依赖图（AST 静态解析，非手画）

```mermaid
graph LR
    subgraph ENTRY["入口层"]
        CONSOLE["console.py<br/>987 行"]
        DIR["director.py<br/>323 行"]
    end

    subgraph COMPILE["编译层"]
        OC["op_compiler.py<br/>552 行"]
        MC["mat_compiler.py<br/>380 行"]
        RC["rig_compiler.py<br/>537 行"]
    end

    subgraph ADAPT["适配层"]
        GA["gn_adapter.py<br/>695 行"]
    end

    subgraph VERIFY["验证层"]
        GV["gn_verify.py<br/>428 行"]
    end

    subgraph DATA["数据层"]
        M1["m1_core.py<br/>770 行"]
    end

    subgraph PROTO["协议层"]
        INTAKE["intake.py<br/>402 行"]
        LT["logic_tree.py<br/>266 行"]
        PS["plan_schema.py<br/>321 行"]
        NLG["nlg_bands.py<br/>53 行"]
    end

    subgraph GOV["治理层"]
        ESC["escape.py<br/>247 行"]
        EXP["experience.py<br/>402 行"]
    end

    subgraph VISUAL["视觉层"]
        RD["render_diff.py<br/>272 行"]
    end

    CONSOLE --> OC
    CONSOLE --> GA
    CONSOLE --> GV
    CONSOLE --> M1
    CONSOLE --> MC
    CONSOLE --> RC
    CONSOLE --> RD
    CONSOLE --> EXP
    CONSOLE --> PS
    OC --> MC
    DIR --> CONSOLE
    INTAKE --> LT
    INTAKE --> PS
    LT --> PS
```

### 依赖规则（从 import 语句 AST 解析，非手写）

| 被依赖方 | 被谁依赖 | 循环风险 |
|---|---|---|
| m1_core | console | 无（数据层不反向依赖） |
| gn_adapter | console, op_compiler | 无（适配层自包含） |
| op_compiler | console, mat_compiler | 无 |
| plan_schema | console, intake, logic_tree | 无 |
| experience | console | 无 |
| logic_tree | intake | 无（logic_tree 不依赖 plan_schema） |

---

## ③ 时序图：建模作业全流程（intake → plan → compile → verify → render）

```mermaid
sequenceDiagram
    actor U as 用户/导演
    participant I as intake.py
    participant LT as logic_tree.py
    participant PS as plan_schema.py
    participant C as console.py
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
    I->>I: to_plan_skeleton(logic_tree=lt)

    rect rgb(240, 248, 255)
        Note over I,LT: M7 两桥合一：逻辑树 deps 并行
        LT->>LT: to_plan(tree) → sections + constraints
        LT-->>I: plan-JSON（SEGMENT_OPS 白名单内）
    end

    I->>PS: validate_plan(plan)
    PS-->>I: issues[]（零 error = 放行）

    rect rgb(255, 248, 240)
        Note over C,GA: 逐段编译（M4-3 EXP1 路线 A）
        loop 每个section
            C->>OC: compile_op(spec)
            OC->>GA: add_node / link / group_io
            GA-->>OC: (node, socket)
            OC-->>C: (node, socket_name)
            C->>C: dag.add(StepRecord) + WAL.append
        end
    end

    rect rgb(240, 255, 240)
        Note over C,GV: 机械验证（A20 零逃逸纪律）
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

    building --> passed: verify PASS + G1 human: actor
    building --> failed: verify FAIL / Gate 拦截

    failed --> pending: retry(sees) 修正后重排队
    failed --> blocked: 需上游先修复

    pending --> blocked: deps 中有 failed

    passed --> [*]: 段落交付

    note right of building
        G1 铁门禁（M7-3）：
        blockout 层（depth==0）
        pass_gate 需 human:* actor
        即使 AUTOPILOT 档
    end note

    note left of failed
        失败也入账（6组 人类学）：
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
        LT_TOPLAN["to_plan(tree) → SEGMENT_OPS 映射"]
        LT_RUNNER["LogicTreeRunner.next_ready()"]
    end

    subgraph OUT["产出"]
        PLAN["plan-JSON<br/>sections + constraints<br/>PlanSchema 零 issue"]
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
        A2 --> A3["PlanSchema 零 issue"]
        A3 --> A4["Console.compile GN 编译"]
        A4 --> A5["verify PASS"]
    end

    subgraph VIS["视觉反馈环"]
        B1["渲染 diff PNG"] --> B2["谓词 diff JSON"]
        B2 --> B3["NLG 带化判词"]
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
            GNSERVER["m9_web/server.py<br/>HTTPServer:8377"]
            GN_NODES["GN 节点组<br/>（op_compiler 产物）"]
        end
        subgraph SYSPY["系统 Python 3.13 进程"]
            STATIC["python -m http.server:8377<br/>（备用静态服务）"]
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

    BROWSER --> GNSERVER
    GNSERVER --> BPY
    GNSERVER --> STATE
    GNSERVER --> GN_NODES
    BPY --> GN_NODES
    STATIC --> STATE
    GNSERVER --> EXPJSON
    REPO -->|git clone| LTJSON
```

---

## ⑧ 维护策略

| 图 | 更新频率 | 维护方式 |
|---|---|---|
| 容器图（①） | 架构变更时 | 手画（Mermaid） |
| 模块依赖图（②） | **每次 import 变更** | AST 自动生成 |
| 时序图（③） | 流程变更时 | 手画（Mermaid） |
| 状态机（④） | 新增状态时 | 手画（Mermaid） |
| 数据流图（⑥） | 三环接口变更时 | 手画（Mermaid） |
| 部署图（⑦） | 部署变更时 | 手画（Mermaid） |

**图即代码**：全部 Mermaid 文本放进仓库 `docs/architecture/` 目录，PR 里可 diff，十年后还能打开。
