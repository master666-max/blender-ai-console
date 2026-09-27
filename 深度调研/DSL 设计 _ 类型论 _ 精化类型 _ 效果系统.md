# DSL 设计 / 类型论 / 精化类型 / 效果系统

- 原始记录：`agent-8c99f35ad7044c06.jsonl`

---

【d2-dsl 调研报告：把 plan-JSON 升级为类型安全 DSL —— 精化类型 / 效果系统 / 可逆性】

## 一、机制/理论（6 条）

1. **精化类型（Refinement Types）**：Freeman & Pfenning 1991（ML）提出，Liquid Types（Rondon et al. 2008）+ Liquid Haskell 使其自动化——`{v:Float | v > 0 && v < 0.5}` 这类谓词由 SMT 求解器（Z3）在编译期自动判可满足性，零运行时开销。对 plan-JSON 的参数范围约束表达力**足够**：JSON Schema 的 minimum/maximum/exclusiveMinimum/enum 恰好都是线性算术+枚举片段，处于 SMT 可判定逻辑内（【已核实】Liquid Haskell 教程与 refinement types 综述均确认）。
2. **代数效果系统（Koka v3，2026-03 发布）**：效果只标注在函数上（`fun foo(): exn ()`），效果可组合可推断、支持效果多态，handler 可恢复（resumption）不炸栈。关键性质：**效果签名是编译期检查的操作能力声明**——这正是把 revertible/irreversible 写进类型的位置。
3. **Saga/补偿的形式化前例**：SAGAS 演算（Garcia-Molina & Salem 1987 起源；Lanese 等的 Static vs Dynamic SAGAs 给出了嵌套补偿的进程演算语义）+ Temporal Haskell SDK 的 `SagaT` monad transformer（`compensated :: m () -> m a -> m a`，【已核实】Hackage 文档）。用效果系统建模 Saga 的直接论文**未找到**【未核实】，但 monadic 前例证明补偿可以进类型签名，搬到 effect row 上是直接转译。
4. **渐进类型（Siek & Taha 2006）**：核心是"一致性关系 ~"（任何类型与 ? 一致）+ 边界处自动插入运行时 cast + blame 追踪（Wadler & Findler 2009）+ 渐进保证（加注解不改行为）。区分两条路线：optional typing（TS/Flow，类型会被擦除）vs sound gradual typing（Typed Racket，边界强检查）。这直接给出"先运行时校验→逐步收紧"的理论模板。
5. **ADT + 穷尽模式匹配**：discriminated union 让"非法 plan 不可表示"（Zod 的 `z.discriminatedUnion` 是 JSON 世界的现成对应物，【已核实】）。Theseus（James & Sabry）更极端：用模式覆盖完整性在类型层面保证"所有良类型程序可逆"。
6. **部分可逆语言 Sparcl（Nishida, Yokoyama et al., ICFP 2021 / JFP）**：突破 Janus/Theseus 要求的"全程序双射"，允许程序片段可逆、片段借 helpers 不可逆，用 splice 机制组合——这是对 Blender 操作语义**最匹配**的理论（大多数建模操作是部分可逆的）。

## 二、设计转译（6 条）

1. **`params` 字段 → 精化类型**：`radius: {v:Float | v > 0 && v < 0.5}`。编译路径：JSON Schema 的数值约束 → SMT-LIA 谓词 → 预审期用 Z3 检查（不必引入 Haskell，只需把约束生成 VC 丢给 z3 CLI）。字段拼错/缺依赖在同一个 VC 生成器里一起拦。
2. **`op` 字段 → discriminated union**：`Plan = Compile(SegmentSpec) | ParamUpdate(id, RefineParams) | Checkpoint | Pivot(CompensableOp)`，用 `"kind"` 做 tag；Ajv/Zod 编译期拒绝未知 kind（配 `additionalProperties: false`）。
3. **`revertible` 从标签升级为效果行**：每个构建函数签名变为 `{ fn, effects: {revertible: bool, compensation: Program?} }`；`Pivot` 操作在类型上**只能引用** effects.revertible = true 的函数——写错时预审编译器报"效果不匹配"，而非运行时发现 pivot 不了。
4. **Checkpoint → 补偿作用域类型**：借 SagaT 语义，`Saga[Compensation]` 容器类型包裹 plan 段落，使"没有补偿的操作不得出现在 checkpoint 作用域内"成为类型规则。
5. **渐进收紧路径（Siek & Taha 直接套用）**：阶段 1 所有字段 `?`，Ajv 运行时校验（= cast 插入点）；阶段 2 高频字段（kind、依赖 id、数值范围）收紧为静态 schema；阶段 3 精化谓词上 SMT。每次收紧遵守 gradual guarantee：收紧不改变已通过 plan 的行为。
6. **工具链现实**：quicktype/json-schema-to-typescript 能从 JSON Schema 生成 TS 类型+Ajv 校验器（结构层），但 quicktype 从样本推断时**会丢失 minimum/positive 等语义约束**（【已核实】教程明确指出"无法推断 price 为正"）——所以必须 schema-first、样本只做 fixture。"JSON Schema → 精化类型"的现成编译器【未核实】（未找到），最接近的是 Zod `.refine()` 做运行时级精化。

## 三、反直觉/打脸（3 条）

1. **可逆计算语言救不了 pivot**：Janus/Theseus/Π 系保证的是"全双射、信息守恒"，而 Blender 的 pivot 恰恰是*部分*可逆（依赖图可回退、但几何结果有信息损失）——照搬全可逆类型系统会把大多数合法操作判为非法。正确理论是 Sparcl 的部分可逆性。
2. **quicktype 式"从样本生成类型"是反模式**：样本推断天生丢约束（正数、exclusiveMinimum 全丢），EXP-1 里 0% 失败恰恰说明约束不在样本里而在 schema 里——必须 schema 单一事实源。
3. **渐进类型的"收紧"会引入运行时开销悖论**：sound gradual typing 在边界插 cast，收紧字段越多、AI 生成 plan 的每步校验点越多；TS 式 optional typing 零运行时但零保证。对 AI 输出这种不可信输入，应选 sound 一侧（校验点=blame 定位点），不要学 TS 擦除。

## 四、推荐类型栈 + 迁移路径

**一句话**：JSON Schema（结构，单一事实源）+ discriminated union（plan 变体）+ Ajv/Zod（边界运行时校验，即 cast）+ 线性算术精化谓词 → Z3（参数范围编译期判定）+ 效果行（revertible/compensation 进函数签名）。理由：全链路避开 Haskell/F* 的采用成本，但保留 Liquid 的 SMT 判定内核与 Koka 的效果建模力，且每一步都有成熟工具。
**迁移**：① 给现有 plan-JSON 写 schema + `additionalProperties:false`（EXP-1 的错误立即全拦）；② discriminated union 化 + 效果行标注；③ 数值约束导出为 LIA 谓词接 Z3；④ Pivot/Checkpoint 规则类型化。

## 五、文献/工具

1. Siek & Taha, *Gradual Typing for Functional Languages*, 2006
2. Wadler & Findler, *Well-typed programs can't be blamed*, ESOP 2009
3. Rondon, Kawaguchi & Jhala, *Liquid Types*, PLDI 2008；Vazou, *Liquid Haskell*（Haskell Symposium 2014）
4. Freeman & Pfenning, *Refinement Types for ML*, PLDI 1991
5. Plotkin & Pretnar, *Handling Algebraic Effects*；Koka v3（koka-lang.github.io，2026-03）
6. Nishida et al., *Sparcl: A Language for Partially Invertible Computation*, ICFP 2021 / JFP
7. James & Sabry, *Theseus*（所有良类型程序可逆，基于 Π 类型同构）
8. Yokoyama & Glück, *A Reversible Programming Language (Janus)*, 2007
9. Lanese et al., *Static vs Dynamic SAGAs*（补偿演算）；Garcia-Molina & Salem, *SAGAS*, SIGMOD 1987
10. 工具：Ajv（ajv.js.org）、Zod（zod.dev，`.refine()`）、quicktype（~25 语言，支持 JSON Schema 输入）、json-schema-to-typescript；Temporal Haskell SDK `Temporal.Workflow.Saga`

（本报告约 1500 字；除两处标注【未核实】外，其余均经 WebSearch 对 PLDI/ICFP/JFP 论文及官方文档核实。）