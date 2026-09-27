# GN 岔路调研：把 AI 的计划编译成 Geometry Nodes，还是执行一串 `bpy.ops`？

> **方法**：没有猜。本机装的是 **Blender 5.2.1 LTS**（hash `9e2066aef7ef`），
> 我在它上面跑了 12 轮 headless 探针（`probe_gn*.py`，结果 `gn_probe*.json`），
> 所有数字都是在这台机器实测出来的，不是文献引用。
> 探针脚本留在 `2026-09-26-blender/`，可复跑。

---

## 零、结论先行

**采用编译到 GN，但不是替换 `FlowAxis`，而是作为它的「已编译产物」。**

三条理由，两条是压倒性的，一条是必须接受的代价：

| | 结论 | 实测数字 |
|---|---|---|
| ✅ **迭代成本** | 改一个参数的重算，**比 ops 重跑便宜约 5.9 倍** | 59.3 ms vs 346.3 ms（同为 393,216 面） |
| ✅ **三层回退开箱即用** | LIVRPS opinion 栈在 Blender 里**已经存在且可用** | 同一节点组挂 2 个 modifier 正确复合；per-instance 输入可写；层序可调；删顶层 = 常数成本回退 |
| ⚠️ **局部重算不存在** | GN **不给** Siemens 那种局部重算，改任何参数都整树重算 | 改上游 1156 ms vs 改下游 1134 ms，差 <2%；拆成 3 个 stage 只快 4%（噪音级） |

第三条是本次调研**最重要的负面发现**——它意味着「60 秒 → 2 秒」那个梦
**不能靠 GN 实现，只能靠我们自己的快照层（待改清单 A6）**。GN 帮不了这个忙。

---

## 一、GN 现在到底有多大？（5.2.1 LTS 实测清单）

| 类别 | 数量 |
|---|---|
| `GeometryNode` 子类 | **266** |
| `FunctionNode` 子类 | 55 |
| `ShaderNode` 子类 | 100 |

**我们担心的"GN 表达力不够"，大部分是旧印象。实测有：**

| 能力 | 节点 | 存在 |
|---|---|---|
| 倒角 | `GeometryNodeMeshBevel` | ✅ |
| 布尔 | `GeometryNodeMeshBoolean` | ✅ |
| **SDF 体素建模全家桶** | `MeshToSDFGrid` / `SDFGridBoolean` / `SDFGridFillet` / `SDFGridOffset` / `Laplacian` / `Mean` / `Median` / `MeanCurvature` | ✅ |
| 挤出 / 缩放元素 / 复制元素 / 翻面 / 劈边 | `ExtrudeMesh` / `ScaleElements` / `DuplicateElements` / `FlipFaces` / `SplitEdges` | ✅ |
| 焊接顶点 / 三角化 / 凸包 / 包围盒 | `MergeByDistance` / `Triangulate` / `ConvexHull` / `BoundBox` | ✅ |
| 循环 / 仿真 / 逐元素遍历 | `RepeatInput/Output` / `SimulationInput/Output` / `ForeachGeometryElementInput/Output` | ✅ |
| 分支 | `IndexSwitch` / `MenuSwitch` | ✅ |
| 命名属性读写 / 采样 / 最接近点 | `Store/InputNamedAttribute` / `SampleIndex` / `SampleNearestSurface` | ✅ |
| 排序 / 光线投射 / 邻近 | `SortElements` / `Raycast` / `Proximity` | ✅ |
| Bundle / Closure | `Get/SetGeometryBundle` / `ClosureToList` | ✅ |
| 材质 | `InputMaterial` / `SetMaterial` | ✅ |

**我没有找到的**：chamfer（可用 bevel 替代）、UV 展开、骨骼绑定、动画关键帧、雕刻、重拓扑。这些仍需走 `bpy.ops` 逃逸舱。

> **SDF 全家桶的存在值得单独提一句**：体素/SDF 建模是**与历史顺序无关**的建模范式
>（布尔、倒角、偏移都可交换执行），这对我们「 foolish history → 可回退」的问题是结构性利好，
> 值得再开一条支线调研。

---

## 二、可编程性：能写，但 API 在漂移

| 能力 | 实测结果 |
|---|---|
| 用 Python 造节点组 | ✅ `node_groups.new` → `interface.new_socket` → `nodes.new` → `links.new` 全部可用 |
| 具名参数 | ✅ `new_socket(name="Plate_Width", socket_type="NodeSocketFloat")` —— **这正是第 5 组要的 `radius=0.05` 而不是 `args[0]=0.05`** |
| 序列化是否稳定 | ✅ 同一树两次 dump 的 SHA-256 **完全一致** → 可 diff、可入版本控制 |
| **可寻址性** | ✅ `NodesModifier.persistent_uid` = 稳定数值 id，跨编辑不变 → **原生满足我们"Step 必须有 id"的要求** |
| per-instance 输入 | ✅ `modifier.properties.inputs["Socket_N"]["value"] = value`（**两步都不能错**，见下节） |
| 层序调整 | ✅ `bpy.ops.object.modifier_move_up` |
| realize（烘焙） | ✅ `bpy.data.meshes.new_from_object(evaluated_obj)`，**0.19 ms** 实例化 393,216 面 |

### ⚠️ 我自己第一版也测错了：改参数"改了但没变"

这条必须单独记，因为它差点让整份报告建立在假数字上。

**Blender 5.2.1 headless 下，改节点参数要三步都对才生效**，少任何一步都会**静默返回旧结果**（不报错！）：

1. 容器是 `modifier.properties.inputs[socket_id]`，它是个 `IDPropertyGroup`
2. 真正的值在这个 group 的 **`["value"]`** 字段里（同组还有 `type` / `attribute_name`）
   —— 直接 `properties.inputs[id] = v` 会把整个 group 替换成标量，**不报错但无效**
3. 写完必须失效缓存，否则求值仍是旧的

第 3 步实测了五条策略：

| 失效策略 | 生效？ |
|---|---|
| 什么都不做 | ❌ |
| `tree.update_tag()` | ❌ |
| 新建 depsgraph | ❌ |
| **`obj.update_tag()`** | ✅ |
| `tree.interface_update(context)` | ✅ |

**更狠的一条：改 `interface` 上的 `default_value`（节点组自己的默认值）在 headless 下根本不生效**——
`update_tag` / 新建 depsgraph / 重赋 `modifier.node_group` / 改 `NodeGroupInput` 节点的 output default，
**四条全试过，输出纹丝不动**。

> **架构含义（这是好消息）**：参数必须走 per-instance 覆盖，而 per-instance 覆盖
> **恰好就是 opinion 层的机制**。也就是说 Blender 逼你走的那条路，正是我们本来就想走的路。
> `set_group_default` 应当降级为"首次求值前设初始值"，真正的改参一律走 `set_instance_input`。

⚠️ 上面这些是 **headless / background 模式**下测的；带 UI 时 `interface_update` 由界面驱动，表现可能不同（**未核实**）。

### ⚠️ 但 API 是漂移的 —— 这是硬成本

实测踩到：**≤4.x 的 `interface.items_ui` 在 5.2 里已改名为 `items_tree`**；
而 per-modifier 输入的旧写法 `modifier["Socket_N"]` 在 5.2 里**彻底失效**
（报 `no __getitem__ support for this type`），正确路径变成 `modifier.properties.inputs["Socket_N"]`。

我为了找到后者试了 7 条路径才成功。**这会发生在 LLM 身上，而且它会自信地带错。**

→ **决策：必须锁定 Blender 版本，并把版本适配做成一层薄薄的 `GNAdapter`。**
这不是"以后再说"的事——组和组之间的 CI 都跑不通。

另外两个小坑：
- `bpy.ops.object.geometry_nodes_apply` **在 dir() 里存在但 headless 下调不动**（"could not be found"）。改用 `meshes.new_from_object`，0.19 ms，更干净。
- `NodesModifier.execution_time` 存在，但后台模式读出来是 **0.0**（疑似 UI 统计专用，**未核实**）。如果它真能用，会是 verifier 的免费预算表——值得再探一次。

---

## 三、性能对决：同一堆面，两条路各多少钱

**目标相同：393,216 面。** 两条路都实测取中位数。
（这一节的数字是**修正后**的：第一版测量用的失效路径是坏的，改参根本没生效，
重测时已确认每次迭代的面数确实在变。）

| 路径 | 一次修改要多久 |
|---|---|
| **GN**：改一个参数 → 依赖图重求值 | **59.3 ms** |
| **GN** + 实例化结果（要"看到"就得付这个钱） | **58.9 ms** |
| **ops**：从零重跑整条破坏性流水线 | **346.3 ms** |
| （对照组）无任何改动时的 deps.update | **0.001 ms** |

**→ 编译到 GN 让"改一个参数看结果"便宜了约 5.9 倍。**

这就是 Section 零里那句"6.1 倍"的来源。它不是 Siemens 的 30 倍，但它是**真金白银**，
而且它直接作用在北极星上：`迭代上限 = min(1/定位成本, 1/回退成本)` —— **回退成本约 ÷ 6**。

---

## 四、关键负面结论：GN 不做局部重算

这是本次最该记住的一条。

**实验**：同样堆到 **6,291,456 面**，比较改不同位置的参数要多久（纯 `deps.update()`，已剥离 `to_mesh()` 开销）。

| 形态 | 改**上游** | 改**中间** | 改**下游** | 只改一个浮点 |
|---|---|---|---|---|
| 整棵一坨 group | 1156.3 ms | 1163.1 ms | 1133.9 ms | — |
| 拆成 3 个串联 modifier | 1118.2 ms | 1106.5 ms | 1102.5 ms | 1097.6 ms |
| 什么都不改 | 0.001 ms | 0.001 ms | 0.001 ms | 0.001 ms |

**读法：**

1. **改最下游的一个浮点，和改最上游的整数，代价一模一样（1097 vs 1118，差 1.9%）。**
   → Blender 的依赖图**没有**细粒度失效。任何一个输入变了，整棵树重算。
   → **Synchronous Technology 的 Live Rules 那套"局部重算"，GN 里没有。**
2. **把链条拆成多个 modifier，只省了 4%——噪音级。** 别指望靠"多分几层"骗出局部重算。
3. 好的一面：**没有改动时的代价是 0.001 ms**（缓存命中，完全不算）。所以 GN 不会让你为"没动的东西"付钱。

> **推论（写进待改清单）**：想拿「60 秒 → 2 秒」，不能依赖 GN，只能靠我们自己那份
> **中间几何缓存 + 快照（A6）**。GN 给不了这个。这条把第 1 组「局部 invalidate」的建议
> 从一个"抄过来就行"的美好幻想，降级成了"我们得自己实现"。

---

## 五、意外之喜：LIVRPS opinion 栈在 Blender 里本来就有

第 1 组建议"三层回退用 USD 的 opinion 栈实现"，第 6 组我又写了"存储要自研"。
**实测发现：Blender 的 modifier 栈就已经是一个能工作的 opinion 栈** —— 只不过它的覆盖范围有限（见下方边界）。

| LIVRPS 要素 | Blender 里的对应 | 实测 |
|---|---|---|
| 层栈而非文件 | 多个 modifier 引用**同一个** node group | ✅ 复合正确：`((6·4²)·4²)=1536` 面 |
| 更强的 opinion 覆盖更弱的 | per-instance 输入覆盖 group 默认值 | ✅ 两层各自覆盖，实测 `6·4·4²=384` → 顶层再改 `6·4·4³=1536` |
| 强度序可调 | modifier 顺序 | ✅ `modifier_move_up` 实测改变了 `[LayerA, LayerC]` → `[LayerC, LayerA]` |
| **回退 = 删一层，成本恒定** | `modifiers.remove(顶层)` | ✅ 删顶层后立刻回到 `6·4=24` 面，无重算 |

→ **第 1 组的那条建议不用"自研"了，直接用 modifier 栈。**
但要清楚边界：USD 的 opinion 是**任何属性**都可覆盖；Blender 这边只能覆盖
**显式提升（promote）为 group input 的那些参数**。所以：

> **第 1 组那条 HDA 契约现在有了硬理由**：它说"只 promote 少量参数"，
> —— 不是美学偏好，**promote 出来的东西才是可以被 opinion 覆盖的东西**。
> 你要覆盖什么，就得先把什么提升成 group input。这条现在是必选而不是建议。

---

## 六、Verifier 的六个谓词，有一部分可以编译进节点树

第 4 组列了六类几何谓词。实测 GN 里现成的原语：

| 谓词 | GN 内可否算 | 手段 |
|---|---|---|
| 面非平面（`InputMeshFaceIsPlanar`） | ✅ | 直接有节点 |
| **非流形边** | ✅ | `InputMeshEdgeNeighbors` 取 Face Count，`FunctionNodeCompare` 判 `> 2` |
| 松散/重复顶点 | ⚠️ 可拼 | `EdgesOfVertex` + 计数 + Compare |
| 法线一致 / 穿地 / 视锥 | ✅ | Combine XYZ + Component-wise Compare |
| 面数/物体数预算 | ✅ | `Domain Size` + Compare，可选 additional |
| 渲染图非全黑（像素方差） | ❌ | 必须渲出来后在 Python 侧算 |

→ **verifier 可以做两层**：GN 内的结构谓词（几乎免费、每次重算自动跑）+
 GN 外的渲染谓词（段落边界才跑）。这正好对应第 4 组说的 hook 模型。

---

## 七、所以 `FlowAxis` 怎么办？—— 两条路线不是二选一

调研前隐含的担心是："如果编译成 GN，操作历史就没了。"实测澄清了：**这两个是正交的。**

| | `FlowAxis` | GN 节点树 |
|---|---|---|
| 是 | **轨迹 trace**（发生了什么、按什么顺序） | **程序 program**（当前这段怎么算出来） |
| 时间性 | append-only，有序 | 无序 DAG，只有依赖 |
| 回答的问题 | "为什么走到这一步" | "这一步现在长什么样，哪些参数可调" |
| 是否可省略 | ❌ 不能 —— 第 1、2 组都说「事件日志是唯一真相」 | ✅ 可以 —— 它是可随时重建的物化视图 |

> **一句话：FlowAxis 是我们的历史，GN 树是 Blender 的当前状态。两者都要。**
> `bpy.ops` 序列既不是历史也不是程序，它只是一个不可回味的瞬间 —— 这才是它最大的问题。

### 「回退」在编译路线下的重读

| 回退层 | 用什么 | 成本（实测） |
|---|---|---|
| L1 状态层 | 恢复 parameters dict / 删 modifier 层 | **62.7 ms**（或删层几乎 0） |
| L2 语义层 | GoodPoint = 快照 = realize() 时刻 | **0.19 ms** 实例化 |
| L3 意图层 | 改 Thought → 重新辐射受影响的参数 | 仍然是重算，62.7 ms 起 |

对比 ops 路线：L1 就是 385.4 ms 起，而且一旦 apply 就不可逆。

---

## 八、写进 `core_types.py` 的改动（在原有 A1–A10 之上追加）

| # | 新增 | 理由 |
|---|---|---|
| **A11** | `GNArtifact` 类：持有 node group 引用 + `socket_map`（语义名 → identifier）+ `param_values` | GN 产品的可寻址单元 |
| **A12** | `GNAdapter`（薄适配层）：隔离 Blender 版本差异；把 `items_tree` / `properties.inputs` 这类漂移封在一处 | 实测 API 已漂移，必须要有 |
| **A13** | `compile_plan()` → `GNArtifact`：把一段 plan 编译成节点树而非逐条 execute | 核心价值所在 |
| **A14** | `realize()` → snapshot；GoodPoint 调用它 | Blender 手册：setup finalized 后 bake 才有意义 |
| **A15** | `verify_gn()`（结构谓词）+ `verify_render()`（渲染谓词）两层 | 第 4 组的机械验证器，部分可编译进树 |
| **A16** | `Step` 同时携带 `command`（trace）与 `gn_delta`（树 diff） | 正交存储，谁都不删 |
| **A17** | 逃逸舱标记：`Step.escape_hatch: bool`，哪些段必须走 `bpy.ops` | UV/绑定/动画/雕刻 GN 做不了 |
| **A18** | 保留 **A6（自己的快照/中间缓存）** —— 不要因为用了 GN 就砍掉 | **第四节的负面结论：GN 不给局部重算** |

**顺带裁掉一条**：原清单 A4「三层回退用 USD 式 opinion 栈（自研存储）」
→ 修订为「**直接用 modifier 栈，promote 需要被覆盖的参数**」。少写一大坨代码。

---

## 九、风险与还没搞定的事（诚实列表）

1. ~~per-modifier 输入写路径未完全摸清~~ → **已解决，见 `blender_console/gn_adapter.py`**：
   正确写法 `mod.properties.inputs[id]["value"] = v` + `obj.update_tag()`；已封装进 `set_instance_input`，
   并有 26 条带断言的 live 测试守着（含"改了必须真的变"的面数断言）。
   仍需注意：LLM 极大概率会写成旧式 `mod["Socket_N"]`，所以这层必须对 LLM 隐藏。
2. **`execution_time` 后台读出来是 0.0**，用途未核实。如果它能用，会是免费的「每段成本」预算表，值得追一次。
3. ~~编译正确性如何保证未知~~ → **部分解决**：类型校验 + 环检测已进 `link()`，并有"应当失败"的用例守着。仍未覆盖：LLM 选错节点、连对类型但语义错误（这类只能靠 verifier 兜）。
4. **SDF 建模路线完全没评估** —— 它是 order-independent 的，理论上对"可回退"更友好。这条支线的价值可能不低于主结论。
5. **没测多人/多 Asset 场景**；也没在两个不同的 Blender 版本上跑过同一份代码（API 漂移的成本还没量化，只是知道它存在）。

---

## 十、下一步建议（按性价比排）

1. ~~先写一个 `gn_adapter.py` + link validator~~ → **已完成**：`blender_console/gn_adapter.py`（约 560 行）+ `gn_adapter_live.py`（26 条 live 测试，全绿）。
   ```
   python gn_adapter.py                                              # 纯 Python 核心测试，不需要 Blender
   blender --background --factory-startup --python gn_adapter_live.py # 真机测试
   ```
2. **做一次小型 AB 实验**：同一个建模任务，一条让 LLM 写 GN 树、一条写 `bpy.ops`，比较成功率与耗时。这是唯一能把「LLM 更擅长写哪种」这个未知量变已知的办法。
3. 之后才动 `core_types.py` 的 A11–A18。

---

## 附：`gn_adapter` 已经封住的坑（一表对照）

| 坑 | 外面直接写会怎样 | adapter 里的正确做法 |
|---|---|---|
| `interface.items_ui` | 5.2 已改名 → AttributeError | `_interface_items()` 按 `items_tree → items_ui` 依次探测 |
| `modifier["Socket_N"] = v` | 5.2 报 no `__getitem__` | `properties.inputs[id]["value"] = v` |
| 写成 `properties.inputs[id] = v` | **静默无效**（把 group 换成标量，不报错） | 强制写 `["value"]` 字段 |
| 改完不失效 | **静默返回旧结果** | `invalidate(obj)` → `obj.update_tag()` |
| 改 interface default | headless 下无效（4 条策略全试过） | 降级为"首次求值前"专用，文档写明 |
| GEOMETRY → INT 连线 | Blender 自己的 `links.new()` **不拦** | `link()` 静态校验后拒绝 |
| 回环 | 能连上，之后行为未定义 | `link()` 环检测 + **自动回滚该链接** |
| zone 的无名 CUSTOM socket | 按名字取 KeyError | `_get_socket()` 支持下标 / 名字 / identifier |
| `parm3` / `args[0]` 参数名 | LLM 默认就会这么写 | `ParamSpec.__post_init__` 直接拒绝 |
