# 约束求解 / SMT / 参数推断 / 双向编程

- 原始记录：`agent-6db290c6b2ec4764.jsonl`

---

【约束求解 / SMT / 参数推断 / 双向编程 调研报告】

一、机制/工具 6 条

1. **Sketch-n-Sketch（Chugh 等，PLDI 2016 / UIST 2016/2019；Mayer 等 OOPSLA 2018 双向求值）**：程序与输出双向同步——用户直接改输出，系统"反向运行"程序推断小的参数修改。核心是受限 DSL + 双向求值，有歧义时给多解让用户选。**未在 Blender/GN 上做过**——它只做 HTML/SVG。但其"反向求值 + 多解合并"思想可直接移植：GN 节点图本质就是受限的函数式程序，单参数正向传播链的逆向求值是良定义的。
2. **Differentiable 3D CAD Programs for Bidirectional Editing（Quinn 等，Eurographics 2022）——重大发现**：就是一个 **Blender 插件**！用户直接拖 3D 几何，系统把"逆向编辑"形式化为**带约束的优化问题**，用自动微分对 CAD 程序求梯度，梯度下降求参数更新，同时保证程序有效性（约束）。这是"从几何反馈反推参数"的最近亲先例，且已在 Blender 生态验证（Blender 2.83 + NumPy/SciPy）。GN 参数链若可微（绝大部分节点可微），此方案几乎照搬。
3. **Z3 / νz 优化模块（Microsoft Research）**：线性算术约束毫秒级求解；支持 push/pop 增量求解（复用已学引理）和 assumptions 模式两种增量 API；νz 支持 MAXSMT（软约束+硬约束混合）。注意：非线性算术可能返回 unknown；且 s.model() 返回的是**任一**满足解，非规范化——纯 satisfiability 不够，必须配优化目标。
4. **D-Cubed 2D/3D DCM（西门子，Onshape/SolidWorks 的内核级求解器）**：官方文档明确披露——①约束与尺寸"同时求解"；②尺寸可用方程互相耦合（改一处联动多处）；③**维度可限定取值范围（bounded dimension）**——"方向性反馈"在商业内核里早有对应机制；④可选"最小移动"偏好求解模式（satisficing 而非优化）。
5. **Onshape regeneration**：官方博客披露草图层为"所有约束/尺寸联立同时求解"，求解失败时高亮冲突约束；特征树层为按序重算 + 拓扑 ID 持久化（外部引用靠 ID 存活）。是否做特征级增量重算**官方未披露【未核实】**——可观察行为更像全量重放，鲁棒性来自 ID 映射而非增量。
6. **Grasshopper Galapagos（GA/模拟退火）**：种群进化求单目标最优，秒到分钟级、不保证收敛，约束靠罚函数。是**优化**范式，与我们场景不匹配。

二、设计转译 6 条

1. **set_param 的 value 推断接 Z3 Optimize（MAXSMT）**：硬约束 = 全部参数合法性（radius>0、wall<outer/2、handle_ring>cup_r/2，以及跨参数耦合式写成方程而非数值）；软约束 = 方向偏好（p_new < p_old）+ 最小改动（minimize |p_new − p_old| 的加权和）。这同时回答问题②③：合法性交给硬约束，"方向+幅度模糊"交给软约束，联动交给方程耦合——求解器自动传播。
2. **改动幅度不要让 LLM 猜百分比，改成 LLM 出约束**：LLM 只负责把"太粗了"翻译成符号方向（< 或 >）和相对强度（如 soft: 尽量接近原值的 0.7~0.9 倍区间），数值由求解器在合法域内定。LLM 永远不直接给 value。
3. **增量求解用 Z3 push/pop**：把约束库常驻（push 基线），每次反馈只 push 新方向约束、check、pop。复用引理，典型草图级约束规模（几十个变量、线性）毫秒级，满足交互反馈回路。
4. **歧义处理学 SnS 多解 + DCM 最小移动**：若去掉方向约束后合法解构成一个区间，取"距当前值最近"（νz 的 minimize 目标即实现）；若软硬约束冲突（unSAT），用 unsat core 定位是哪条约束打架，回传给 Thought 层提示用户，而不是静默选值。
5. **多参数耦合传播**：把"把手环半径>杯半径/2"这类关系声明为 Z3 方程约束常驻，而不是每次重算时拼接；改杯径时只需改杯径变量，求解器给出全组一致解——这正是 DCM "couple dimensions with equations" 的开源复刻。
6. **可微路线作为 Plan B**：若约束涉及 GN 内部几何量（非参数本身，如实际网格厚度），参数级 SMT 覆盖不到，参考 EG2022 方案用 SciPy 对可微代理目标做投影梯度。先做 SMT（便宜、可解释），不够再上微分。

三、反直觉/打脸 4 条

1. **"求解器给合法值"是陷阱**：s.model() 是任意解、跨版本不稳定——纯 SMT 会给出合法但荒谬的值（比如"更细"解成 0.0001mm）。必须上 Optimize 软目标，"满足"≠"合理"。
2. **进化求解（Galapagos 类）是错误范式**：我们直觉上"参数推断=优化"，但交互式反馈回路要的是毫秒级 satisficing + 最小改动偏好，不是秒级全局最优。CAD 内核四十年都没用进化算法，就是这个原因。
3. **Onshape 并没有黑科技增量引擎**：靠的是"全量重放 + 拓扑 ID 持久化 + 草图联立求解"。别追求全图增量重算，把增量性只用在约束求解层（push/pop）即可。
4. **Blender 生态已有现成先例（EG2022）却几乎无人知**：不需要从零发明"几何反馈→参数"，至少有可运行参考实现。

四、立刻可做的实验（1 个）

**Z3 原型（半天）**：马克杯参数 {outer_r, wall, handle_ring_r}，硬约束如上 + 耦合方程；基线值 outer_r=40, wall=3, handle_ring_r=25。输入"把手太细了"（方向：handle_ring_r ↑）。
判定标准：① 求解 <10ms；② 输出值满足全部约束；③ 输出值是"最小改动"解（与手算最优一致）；④ 把杯径改成 80 后再触发，把手/壁厚联动且仍合法（模拟 unSAT 场景，验证 unsat core 能指出冲突约束）。

五、文献/工具 9 条

1. Ravi Chugh 等，"Programmatic and Direct Manipulation, Together at Last"，PLDI 2016
2. Hempel, Lubin, Chugh，"Sketch-n-Sketch: Output-Directed Programming for SVG"，UIST 2019
3. Mikaël Mayer, Viktor Kunčak, Ravi Chugh，"Bidirectional Evaluation with Direct Manipulation"，OOPSLA 2018
4. Quinn 等，"Differentiable 3D CAD Programs for Bidirectional Editing"，Eurographics 2022（github.com/paquinn/bimodel_eg22，Blender 插件）
5. Gonzalez 等，"Introducing Bidirectional Programming in CSG-Based CAD"，SUI 2023（arXiv:2408.01801；含 Antimony、libfive 综述）
6. Z3 Prover（github.com/Z3Prover/z3）+ νz 优化模块；push/pop 与 assumptions 两种增量 API
7. Siemens D-Cubed 2D/3D DCM 官方文档（bounded dimensions、方程耦合、最小移动偏好）
8. Onshape 官方博客 "Under The Hood: Onshape Sketches"（草图联立求解机制）
9. Pan 等，"Logic-LM: Empowering LLMs with Symbolic Solvers"，EMNLP 2023；及 SAT-LLM（ASE 2024）——"LLM 出逻辑约束 + 求解器出结论"范式的直接先例，证实问题⑤的混合架构成立

**核心结论**：最优架构 = LLM 翻译方向为符号约束 + Z3 Optimize（硬合法性 + 最小改动软目标 + push/pop 增量）。Blender 侧有 EG2022 现成参考实现兜底。