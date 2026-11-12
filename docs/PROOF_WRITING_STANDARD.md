# DMate 数学证明表达规范

版本：1.0

## 目标与适用范围

本规范统一 DMate 在聊天解题、完整解析、概念笔记分析、证明提示和学生证明批改中的数学证明表达。它统一逻辑责任、术语和书写质量，不规定所有证明必须采用同一种句式，也不覆盖课程教材或教师明确指定的记号约定。

**核心标准：每个非平凡结论都必须有可追溯的依据；每个量词、变量和逻辑方向都必须明确；最终证明应当是完整、清晰、可独立检查的数学论证。**

## 统一要求

1. **命题准确**：保留原题的定义域、假设、量词和结论，不把蕴含偷换成等价。
2. **变量明确**：首次出现时说明变量的范围、作用和引入依据。
3. **量词准确**：全称命题用“任取/对于任意”；存在命题给出见证或构造并验证。
4. **方法匹配**：根据命题逻辑结构选择直接证明、逆否证明、反证、分类讨论、双向证明、集合包含证明、存在唯一性证明或归纳法。
5. **推理可追溯**：每个关键步骤标明来自题设、定义、已证结论、定理或有效变形。
6. **自然语言组织**：证明正文使用完整句子，公式嵌入论证；除形式化逻辑题外，不把证明写成符号联结词的堆叠。
7. **术语与符号稳定**：同一对象保持同一名称和符号；优先服从课程教材约定；存在歧义的定义域约定必须说明。
8. **结论闭合**：最后明确回到原待证命题；若命题为假，给出核验过的反例。
9. **简洁而不跳步**：可以省略常规运算，但不能省略关键逻辑转换、定义使用、量词变化或情形覆盖。
10. **批改先诊断**：指出最早的实质性错误，区分逻辑错误、缺少依据、量词错误、情形遗漏、术语问题和纯表达问题；认可有效的不同证明方法。

## 证明方法的最低检查项

| 证明类型 | 必须核对的内容 |
| --- | --- |
| 直接证明 | 从题设出发，推出待证结论 |
| 逆否证明 | 明确写出逆否命题，不得误用逆命题 |
| 反证法 | 在原假设下否定准确的待证结论，并导出矛盾 |
| 当且仅当 | 两个方向都得到证明 |
| 集合包含/相等 | 任取元素证明包含；相等须覆盖两个方向 |
| 存在性 | 给出并验证一个满足条件的对象 |
| 唯一性 | 任取两个满足条件的对象，证明二者相等 |
| 分类讨论 | 情形覆盖全部可能性，每种情形均完成论证 |
| 数学归纳法 | 起点覆盖正确、归纳假设范围明确、归纳步骤不循环 |
| 反例 | 对象满足定义域条件且确实使结论失败 |

## 统一用语

| 含义 | 默认表达 |
| --- | --- |
| Universal | 任取、对于任意 |
| Existential | 存在、存在一个 |
| Hypothesis | 已知、假设、由题设 |
| Definition | 根据……的定义 |
| Implication | 若……则…… |
| Biconditional | 当且仅当 |
| Contrapositive | 逆否命题 |
| Contradiction | 反证法、导出矛盾 |
| Induction hypothesis | 归纳假设 |
| Inductive step | 归纳步骤 |

“显然”“易知”“同理”“由题意”等表达不能替代关键论证。“必要性”和“充分性”必须对应正确的逻辑方向。“逆命题”和“逆否命题”必须严格区分。

## 教学模式

- **提示引导**：指出命题结构和下一步，不提前泄露完整证明。
- **完整解析**：提供完整、可独立检查的证明；必要时先用简短文字说明证明路线。
- **答案诊断**：先定位学生证明的最早错误，再解释原因和修正方向；未经请求不直接覆盖学生原有思路。
- **概念笔记**：涉及定理证明时，保留定义条件、证明依据和结论边界。

## 依据与参考

本规范综合参考以下数学教学与写作材料：

- Stanford University, CS103, [Proofwriting Checklist](https://web.stanford.edu/class/cs103/proofwriting_checklist)：明确假设与目标、变量作用域、完整句子、避免符号化证明正文及避免“contradiction sandwich”。
- Massachusetts Institute of Technology, 6.042J, *Mathematics for Computer Science*, [Course Notes](https://s3.amazonaws.com/if-else-assets/MIT6_042JS10_notes.pdf)：逻辑推理依据、标准证明方法、证明路线、线性论证、适度使用符号及证明清晰度。
- American Mathematical Society, *Language, Logic, and Proof*, [Chapter 1 and Appendix: Writing Mathematics](https://www.ams.org/bookstore/pspdf/amstext-26-prev.pdf)：数学语言精确性、变量定义、完整句子、正确术语以及引用定义和定理。
- Richard Hammack, *Book of Proof*, [Third Edition](https://richardhammack.github.io/BookOfProof/)：直接证明、逆否证明、反证、双向证明、集合证明、反例、归纳法、关系与函数证明。

这些材料提供的是通行的证明写作原则，而不是一套必须逐字照搬的统一模板。DMate 的默认表达以中文本科离散数学教学为基准，并尊重用户课程中的明确约定。

## 版本 2：中英文等覆盖与来源核查（2026-11）

**语言平等原则。** 中英文以同一个 `proof_writing_extended.py` 规则表为事实来源，每条规则均有唯一 ID、中英文自然表达及参考资料 ID。中文和英文只在句式、教学语言、术语习惯上不同，不能在定义域、量词、逻辑条件、证明步骤或批改尺度上降低任一语言的要求。英文并非机械翻译中文；依英语数学写作规范采用 *Let ... be arbitrary*, *There exists*, *By definition*, *For the converse direction* 等自然句式。

### 分领域证明覆盖矩阵

| 规则 ID | 中文覆盖内容 | 英文对应 |
| --- | --- | --- |
| `logic_scope` | 逻辑形式与量词 | Logical form and quantifiers |
| `logical_implications` | 蕴含、等价与证明方向 | Implication, equivalence and proof direction |
| `induction_family` | 归纳、强归纳与最小反例 | Induction, strong induction and minimal counterexample |
| `structural_induction` | 结构归纳与递归对象 | Structural induction and recursively defined objects |
| `invariants` | 不变量与算法正确性 | Invariants and algorithm correctness |
| `termination` | 终止性与总正确性 | Termination and total correctness |
| `recursion` | 递归与递推证明 | Recursive algorithms and recurrences |
| `bijection` | 双射与组合计数 | Bijections and combinatorial counting |
| `double_counting` | 双重计数与恒等式 | Double counting and identities |
| `pigeonhole` | 抽屉原理与极值 | Pigeonhole principle and extremal arguments |
| `inclusion_exclusion` | 容斥与分类计数 | Inclusion–exclusion and case counting |
| `graph_theory` | 图论性质与同构 | Graph properties and isomorphism |
| `graph_planarity` | 平面性与图嵌入 | Planarity and graph embeddings |
| `relations_functions` | 关系、映射与商结构 | Relations, functions and quotient structures |
| `algebra` | 群、环与同态 | Groups, rings and homomorphisms |
| `automata` | 自动机与状态转移 | Automata and state transitions |
| `probability` | 概率计数与存在性 | Probability and existential arguments |
| `asymptotic` | 渐近界与复杂度 | Asymptotic bounds and complexity |

矩阵侧重**本科离散数学及相关算法证明**，并不声称已覆盖全部数学研究领域、任意公理体系或所有高等数学证明习惯。

### 中英文术语对应的语义约束

| 中文 | 标准英语 | 关键区别 |
| --- | --- | --- |
| 任取／对于任意 | Let ... be arbitrary / For every ... | 证明全称命题，不是只举一个例子 |
| 存在／存在一个 | There exists / There is some ... | 必须给出见证或存在性论证 |
| 若 P，则 Q | If P, then Q | 方向为 P⇒Q |
| P 仅当 Q | P only if Q | 方向仍为 P⇒Q；`P if Q` 表示 Q⇒P |
| 当且仅当 | If and only if | 必须证明两个方向 |
| 逆否证明 | Proof by contrapositive | 不能和逆命题混淆 |
| 反证法 | Proof by contradiction | 否定真正待证结论 |
| 不妨设 | Without loss of generality | 必须有对称性或等价理由 |
| 归纳假设／归纳步骤 | Induction hypothesis / Inductive step | 明确有效下标 |
| 循环不变量 | Loop invariant | 初始化、保持、退出时的作用 |
| 双射 | Bijection | 要证明单射和满射 |
| 同态／同构 | Homomorphism / Isomorphism | 同构除运算保持还需双射 |

“反对称”应对应 *antisymmetric*，“非对称”对应 *asymmetric*；出现这类易混术语时，应核对定义而非根据文字相似性判断。中文和英文均须尊重题目、课程或教师明确规定的记号和定义域。

### 来源的权威性与适用边界

| 参考来源 | 角色与可核验范围 |
| --- | --- |
| [Stanford CS103 Proofwriting Checklist](https://web.stanford.edu/class/cs103/proofwriting_checklist) | 官方课程的证明书写指导，尤其是变量作用域、假设与目标、句子与逻辑负担 |
| [CMU 15-251 Proof Guidelines](https://www.cs.cmu.edu/~arielpro/15251f17/docs/proof-checklist.pdf) | 官方课程的数学证明写作与论证流程指导 |
| [MIT 6.1200J (2024) Reading List](https://ocw.mit.edu/courses/6-1200j-mathematics-for-computer-science-spring-2024/pages/readings/) | 官方较新课程对证明、归纳、状态机、算法等主题的覆盖依据 |
| [MIT 6.042J (2015) Readings](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-spring-2015/pages/readings/) | 官方教材章节对图论、数论、计数、概率等证明领域的覆盖依据 |
| [Hammack, Book of Proof](https://richardhammack.github.io/BookOfProof/) | 经美国数学研究所开放教材项目认可，覆盖标准证明方法、集合/关系/函数及归纳 |
| [AMS: Language, Logic, and Proof](https://www.ams.org/bookstore/pspdf/amstext-26-prev.pdf) | 专业数学出版机构教材，特别适合数学语言、符号与写作准确性 |
| [高等教育出版社《离散数学》第3版](https://www.hep.com.cn/book/show/2d67dc4c-217a-41db-81b2-56bfe7428879) | 中文课程范围、术语及教材体系参考；目前核对的是出版社公开目录与介绍，不声称已逐页审阅全书 |
| [配套《离散数学学习指导与习题解析》第3版](https://xuanshu.hep.com.cn/front/book/findBookDetails?bookId=66ca132674ce561611bda659) | 中文大学习题类型与解答覆盖的公开目录参考；不直接重印习题和解析 |

这里的“权威”指来源机构及材料本身可靠，并非这些机构对 DMate 的实际模型回答、评分或产品功能做了认证。**来源丰富不等于 AI 证明必定正确**。现有单元测试核验的是两种语言的规则覆盖、来源 ID 完整性和代码接入；数学正确性还需要双语真实题目的独立检验，尤其应检查错误证明的识别能力。

本规范综合归纳公开的证明教学原则，未将课本的受版权保护长段落、习题及解析复制进 DMate，亦不因链接权威资料就宣称获得其商业再分发许可。英文详细版本见 [Proof Writing Standard (English)](PROOF_WRITING_STANDARD.en.md)。
