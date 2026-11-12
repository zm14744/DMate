# DMate 离散数学证明表达规范

版本：3.0（仅限离散数学及其紧密相关的算法内容）

## 目标与边界

本规范服务于 DMate 的离散数学学习、解题、证明提示、完整解析、题库答案、概念笔记和证明批改。它不把 DMate 扩展成通用高等数学平台。

**覆盖范围：** 数理逻辑、集合、关系与函数、数论、组合数学、数学归纳与递归、图论与树、偏序与格、群环等离散代数结构、布尔代数、自动机与形式语言、离散概率、算法正确性与复杂度。

**不作为 DMate 专门证明模块的领域：** 实分析、ε-δ 极限、连续性与微积分、一般拓扑、线性代数课程、微分方程、复分析和连续优化。本规范中的共享逻辑术语与证明方法仅用于上述离散数学课程范围，不扩展这些学科的覆盖。

## 一、统一证明语言

1. **命题不变：** 保留原题定义域、条件、量词和结论；不把蕴含偷换成等价。
2. **变量有界：** 新变量首次出现时说明取值范围、来源和用途。
3. **量词准确：** 全称命题使用“任取”；存在命题给出见证、构造或有效存在性论证。遵循题目指定的证明方法；概率法、反证法等非构造证明不必强行构造具体见证。
4. **推理有据：** 关键结论必须来自题设、定义、已证命题、定理或合法变形。
5. **自然语言组织：** 用完整中文句子串联公式；除形式逻辑题外，不把证明写成逻辑符号堆叠。
6. **术语稳定：** 服从用户教材和教师约定；严格区分必要/充分、逆命题/逆否命题、反对称/非对称、单射/满射、同态/同构。
7. **简洁不跳步：** 可以省略常规运算，但不能省略量词变化、关键定义、逻辑方向或情形覆盖。
8. **结论闭合：** 明确回扣原命题；不能证明时说明条件不足、论证未完成或给出反例。
9. **公平批改：** 找到最早的实质性错误；认可有效的不同证明方法，不把表达风格差异误判为数学错误。

## 二、离散数学领域覆盖

以下规则均由同一数据源提供中文和英文版本，领域 ID 保持一致。

| 领域 ID | 中文覆盖内容 | 主要检查点 |
| --- | --- | --- |
| `logic_scope` | 逻辑形式与量词 | 命题、谓词、自由/约束变元、量词顺序与否定 |
| `logical_implications` | 蕴含、等价与证明方向 | 逆命题、逆否命题、充分必要条件 |
| `set_theory` | 集合论与集合运算 | 属于、包含、相等、幂集、笛卡尔积、基数 |
| `relations_functions` | 关系、函数与商结构 | 等价关系、偏序、单射、满射、双射、良定义 |
| `number_theory` | 数论与整除性 | 整除、素数、最大公因数、欧几里得算法 |
| `congruences` | 同余与中国剩余定理 | 模运算、约分条件、CRT 适用条件 |
| `induction_family` | 归纳、强归纳与最小反例 | 起点、归纳假设范围、归纳步骤 |
| `structural_induction` | 结构归纳与递归对象 | 每种基本构造和递归构造 |
| `recursion` | 递归与递推证明 | 初始条件、递推关系、递归规模 |
| `combinatorial_structures` | 组合结构与计数恒等式 | 排列、组合、二项式系数、构造与计数 |
| `bijection` | 双射与组合计数 | 映射、逆映射、单射与满射 |
| `double_counting` | 双重计数 | 同一对象集合、重数一致 |
| `pigeonhole` | 抽屉原理与极值 | 对象/抽屉对应、数量界 |
| `inclusion_exclusion` | 容斥与分类计数 | 交集、符号、互斥与覆盖 |
| `graph_theory` | 图论性质与同构 | 度、路径、连通、回路、同构 |
| `graph_planarity` | 平面性与图嵌入 | 欧拉公式前提、禁用结构 |
| `trees` | 树与森林 | 连通、无环、生成树、根树 |
| `graph_algorithms` | 图算法与算法正确性 | BFS、DFS、最短路、生成树、匹配、流 |
| `posets_lattices` | 偏序集与格 | 自反、反对称、传递、覆盖关系、上/下确界 |
| `algebra` | 群、环与同态 | 公理、子群、陪集、同态、同构、理想 |
| `boolean_algebra` | 布尔代数与逻辑化简 | 布尔公理、德摩根律、对偶原理 |
| `automata` | 自动机与状态转移 | 初态、终态、转移规则、可达性 |
| `formal_languages` | 形式语言与文法 | 字母表、语言、文法、正则表达式、自动机等价 |
| `invariants` | 不变量与算法正确性 | 初始化、保持、退出条件 |
| `termination` | 终止性与总正确性 | 良基度量、部分正确性与终止性 |
| `probability` | 离散概率与存在性 | 样本空间、独立性、期望、概率方法 |
| `asymptotic` | 渐近界与算法复杂度 | O、Ω、Θ 的常数与阈值 |
| `cardinality` | 有限集、可数性与基数 | 枚举、注入、双射、不可数性 |

## 三、证明方法覆盖

领域与方法分开管理。同一种证明方法可以用于多个领域，一个领域也可以采用多种方法。

| 方法 ID | 中文名称 | English |
| --- | --- | --- |
| `direct` | 直接证明 | Direct proof |
| `contrapositive` | 逆否证明 | Proof by contrapositive |
| `contradiction` | 反证法 | Proof by contradiction |
| `cases` | 分类讨论 | Proof by cases |
| `construction` | 构造性证明 | Constructive proof |
| `existence` | 非构造存在性 | Nonconstructive existence |
| `uniqueness` | 唯一性证明 | Uniqueness proof |
| `weak_induction` | 普通归纳法 | Weak induction |
| `strong_induction` | 强归纳法 | Strong induction |
| `structural_induction` | 结构归纳法 | Structural induction |
| `minimal_counterexample` | 最小反例法 | Minimal-counterexample method |
| `infinite_descent` | 无穷递降法 | Infinite descent |
| `bijection` | 双射证明 | Bijective proof |
| `double_counting` | 双重计数 | Double counting |
| `pigeonhole` | 抽屉原理 | Pigeonhole argument |
| `extremal` | 极值原理 | Extremal argument |
| `invariant` | 不变量证明 | Invariant proof |
| `probabilistic` | 概率方法 | Probabilistic method |
| `algebraic` | 代数恒等变形 | Algebraic identity proof |
| `equivalence_chain` | 等价链证明 | Equivalence-chain proof |
| `truth_table` | 真值表验证 | Truth-table verification |
| `counterexample` | 反例否证 | Disproof by counterexample |
| `exhaustive` | 有限穷举证明 | Proof by exhaustive enumeration |

## 四、中英文统一原则

中文和英文使用同一组领域 ID、证明方法 ID、逻辑要求与错误分类。英文采用自然数学英语，而非逐字翻译中文。

| 中文 | 英文 | 逻辑含义 |
| --- | --- | --- |
| 任取 | Let ... be arbitrary | 全称命题的任意对象 |
| 存在 | There exists | 必须有见证或存在性论证 |
| 若 P，则 Q | If P, then Q | P⇒Q |
| P 仅当 Q | P only if Q | P⇒Q；P if Q 则为 Q⇒P |
| 当且仅当 | If and only if | 两个方向 |
| 逆否证明 | Proof by contrapositive | 不能混同逆命题 |
| 反证法 | Proof by contradiction | 否定准确的待证结论 |
| 不妨设 | Without loss of generality | 必须有对称或等价依据 |
| 反对称 | Antisymmetric | 不等于 asymmetric |
| 同态／同构 | Homomorphism / Isomorphism | 同构还要求双射 |

## 五、权威来源与边界

- [MIT 6.1200J Mathematics for Computer Science (2024)](https://ocw.mit.edu/courses/6-1200j-mathematics-for-computer-science-spring-2024/pages/readings/)：离散数学、证明、归纳、算法不变量与状态机。
- [MIT 6.042J Mathematics for Computer Science (2015)](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-spring-2015/pages/readings/)：逻辑、集合、数论、计数、图论、概率。
- [Hammack, Book of Proof](https://richardhammack.github.io/BookOfProof/)：证明方法、集合、关系、函数、归纳与基数。
- [Stanford CS103 Proofwriting Checklist](https://web.stanford.edu/class/cs103/proofwriting_checklist)：变量作用域、假设/目标、自然语言证明写作。
- [CMU 15-251 Proof Guidelines](https://www.cs.cmu.edu/~arielpro/15251f17/docs/proof-checklist.pdf)：论证结构与证明表达。
- [AMS, Language, Logic, and Proof](https://www.ams.org/bookstore/pspdf/amstext-26-prev.pdf)：数学语言、符号和写作准确性。
- [高等教育出版社《离散数学》第3版](https://www.hep.com.cn/book/show/2d67dc4c-217a-41db-81b2-56bfe7428879)：中文本科课程术语和范围参考；目前依据公开出版社目录，不声称逐页审阅全书。
- [高等教育出版社《离散数学学习指导与习题解析》第3版](https://xuanshu.hep.com.cn/front/book/findBookDetails?bookId=66ca132674ce561611bda659)：中文习题范围参考，不复制其受版权保护的习题和解析。
- [MIT 18.781 Theory of Numbers](https://ocw.mit.edu/courses/18-781-theory-of-numbers-spring-2012/pages/lecture-notes/) 与 [MIT 18.703 Modern Algebra](https://ocw.mit.edu/courses/18-703-modern-algebra-spring-2013/pages/lecture-notes/)：仅用于离散数学中数论、群环等专题的补充。

这些来源是规范依据，不代表来源机构认证 DMate，也不代表 AI 生成证明已经通过数学验证。当前 CI 检查的是规则覆盖和代码接入；模型数学正确性还需通过中英文同题测试。

**范围声明：** 本规范面向本科离散数学及其紧密相关的算法、组合与代数专题，不声称覆盖所有数学学科。未单独列出的离散数学题型仍须遵守通用逻辑与证明语言规范，不得因缺少专门条目而拒绝处理。
