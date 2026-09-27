# 持久化数据结构 / 多版本数据结构（persistent & versioned data structures）

- 原始记录：`agent-617d5d4d180243c3.jsonl`

---

【调研报告】持久化/多版本数据结构：能否让"开版本 O(1)、回退 O(1)、内存只付增量"

一、里程碑成果
1. Driscoll/Sarnak/Sleator/Tarjan 1989《Making Data Structures Persistent》(JCSS)：任意有界入度指针结构可机械转为部分/完全持久化；fat-node + node-copying 达到每次修改 O(1) 摊还时间与空间、读操作仅 O(1) 减速。这是"开新版本近似免费"的理论上限——但注意它针对的是单字段级修改，不是整段替换。
2. Okasaki 1998《Purely Functional Data Structures》(Cambridge UP)：惰性求值 + 借记调度使摊还分析与持久化兼容（多逻辑未来不重复付费），实时队列做到 O(1) 最坏情况。对我们的启示：惰性 thunk 可把"重推下游 50ms"摊到多次读上。
3. Huet 1997《The Zipper》(JFP Functional Pearl)：one-hole context——把树"从里翻外"，焦点处 O(1) 局部编辑/导航；McBride 2009 证明任意代数类型的"导数"即其 zipper 类型。这是编辑器 undo 的经典结构，与我们的"段落光标/分层回退"天然同构。
4. Clojure persistent vector（32 路基数树）：10 亿元素深仅 6 层，一次修改只复制 ~6 个节点（约 1.5KB），读 6 次间接寻址，追加比可变 ArrayList 慢 2-4×——工程上"结构共享"确实接近免费。
5. Blelloch/Burch/Crary/Harper/Miller/Walkington 2002《Persistent Triangulations》(CMU PSciCo)：纯函数式单纯复形（三角网格拓扑），遍历/加三角形 O(log n)，实验表明端到端只付小常数因子——"持久化 3D 网格"确实有人做过，可行但有对数代价。
6. Datomic (Hickey, 2012) 与 Git：append-only datom 日志 / SHA-1 Merkle DAG；分支=移动指针 O(1)，as-of 历史查询是一等操作。两者证明"全历史 + 免回退"在数据库级规模可用。

二、已解决的问题（可直接抄进架构）
1. 全量快照 → 结构共享版本树：参数表用 persistent map（路径复制 O(log n)，每版本仅付增量 KB 级），"每段快照"退化为"每段只存新根指针"；回退=读旧根，O(1)。可把现有 0.6ms 快照回退进一步压到指针操作。
2. FlowAxis 日志本身就是 partial persistence 的标准形态（线性版本史：历史只读 + 末尾追加）。日志天然持久，无需再叠全量快照；DSST 证明维持全历史只需 O(1) 摊还/次修改。
3. Git 模型给段间依赖：每个 modifier 段=一次 commit（内容寻址 DAG 节点）。删段不物理删除，只移 ref、延迟 GC——与"删层 0.7ms"兼容，且意图层分叉重推=从旧 commit 拉新分支（full persistence 允许对任意历史版本再更新，版本史成树）。
4. 批量构建用 transient（可变）阶段、构建完冻结转持久（Clojure/immer 的标准做法）——参数表初始化不该逐条走不可变路径。

三、坑/反直觉发现
1. 传统摊还在持久化下会失效：Okasaki 指出多逻辑未来会重复"花同一笔储蓄"，必须惰性+借记。若我们急切批量重推，分叉后每个分支都重复付全款。
2. immer(JS, Proxy 型"伪不可变")对大集合是 O(n) 每写、整体 O(n²)：实测 1 万条插入 8.8s，而真 persistent 的 Immutable.js 仅 47ms（coder-mike 2021 实测）。C++ 侧的 immer 库（arximboldi/immer，持久 vector）语义正确，但那是另一个项目，别混淆。结论：要么真持久结构，要么干脆可变，不要 Proxy 式 COW。
3. Persistent Triangulations 的拓扑操作从 O(1) 退化到 O(log n)。"每步都写"的建模负载（几十万顶点）下写放大与 GC 压力，未见针对 Blender 类负载的实测数据【未核实】。
4. USD layer stack 是"opinion 组合"而非持久化数据结构：LIVRPS 强度序解决"谁覆盖谁"，不解决"任意历史 O(1) 回退"。两者正交，USD 不白给时间旅行；但它的 opinion 层语义与我们的 modifier=opinion 层架构同源，值得对标术语。
5. 内容寻址有哈希成本：对参数行这类小对象，逐条哈希去重开销占比高；Datomic 用直接 append + 索引而非逐条内容寻址，是更贴我们规模的选型。

四、对本项目的具体建议
1. (a) FlowAxis 日志：保持 append-only 链（每事件含前事件指针/哈希），即 Datomic log 做法；参数表换 persistent HAMT。省掉：全量快照的存储与序列化，回退降为指针移动。zipper 视角：日志"当前段"=焦点，意图层推翻=从该 one-hole context 只重生成右侧（未来）分支，左侧历史零拷贝——三层回退语义与 zipper 一一对应，重推 50ms 只付分叉点右侧。
2. (b) 几十万顶点的网格几何不适合整体不可变：顶点缓冲保持可变，持久化只用于参数表、日志、场景图拓扑这类小状态；几何级回退引用 Geometry Nodes 每节点输出缓存即可（缓存命中本身就是版本）。若确需顶点级版本，用大块写时复制 chunk 而非逐元素持久结构【Blender 内部缓存细节未核实】。
3. 段=内容寻址 commit：同参数段自动去重，意图层重推产生新 DAG 节点不改旧节点，调试时可对两版本 DAG 直接 diff——把 Git 的对象模型缩到段粒度。
4. 重推下游改为惰性调度（Okasaki 式）：新分支下游节点标为 thunk、读时才算；用户连续回退/分叉时避免急切全推，摊销掉 50ms。
5. 只做 partial persistence（线性历史）为主，full persistence 仅在意图层分叉局部启用——我们是单写者，无需为多写者付 confluent persistence 的复杂度。

五、关键文献/工具
1. Driscoll, Sarnak, Sleator, Tarjan, "Making Data Structures Persistent", J. Computer and System Sciences, 1989.
2. Okasaki, "Purely Functional Data Structures", Cambridge University Press, 1998（第 6 章"Amortization and Persistence via Lazy Evaluation"）.
3. Huet, "The Zipper", Journal of Functional Programming 7(5), 1997. 原文 PDF: https://www.st.cs.uni-saarland.edu/edu/seminare/2005/advanced-fp/docs/huet-zipper.pdf
4. Blelloch, Burch, Crary, Harper, Miller, Walkington, "Persistent Triangulations", CMU PSciCo, 2002. https://www.cs.cmu.edu/~glmiller/Publications/BBCHMW02.pdf
5. McBride, "The Derivative of a Regular Type is its Type of One-Hole Contexts", 2009（zipper 的一般化理论）.
6. immer (C++ 持久数据结构库): https://github.com/arximboldi/immer ；JS immer: https://github.com/immerjs/immer ；性能对照实测: https://coder-mike.com/blog/2021/03/05/immutable-js-vs-immer
7. Datomic（immutable database values / as-of 查询）: http://www.datomic.com/
8. NVIDIA Learn OpenUSD, "Composition Arcs and Strength Ordering": https://docs.nvidia.com/learn-openusd/latest/composition-basics/strength-ordering.html ；另见论文 "SceneGit: A Practical System for Diffing and Merging 3D Environments"（3D 场景图版本控制/diff/merge，Sapienza 团队方向，发表 venue 未核实）。

核心一句话结论：把 persistent 结构用在"参数表+日志+段 DAG"这三样小状态上（近零成本拿到 O(1) 开版本/回退），几何大数据仍走可变缓冲+节点缓存引用；zipper 是"意图层从分叉点重推"最贴切的心智模型。