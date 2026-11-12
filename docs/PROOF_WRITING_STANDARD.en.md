# DMate Mathematical Proof-Writing Standard

Version: 2.0 — Chinese/English parity

## Purpose and scope

This is the English-language counterpart to [DMate 数学证明表达规范](PROOF_WRITING_STANDARD.md). Both language variants are generated from the same domain checklist and source registry in `proof_writing_extended.py`. English proofs must meet the same logical, mathematical and pedagogical standards as Chinese proofs, while using idiomatic English mathematical prose rather than translating Chinese sentence patterns word for word.

**Core requirement:** Every nontrivial conclusion must be justified; variable domains, quantifier scopes and logical directions must be explicit; a completed proof must be clear, sound and independently checkable.

## Shared principles

1. **Preserve the proposition.** Keep the original domain, hypotheses, quantifiers and conclusion. Never silently replace an implication with a biconditional.
2. **Introduce variables.** Each variable must have an identified origin, domain and role.
3. **Use quantifiers correctly.** For universal claims, choose an arbitrary object. For existence, supply a witness, construction or valid nonconstructive argument.
4. **Choose the appropriate method.** Direct proof, contrapositive, contradiction, equivalence, cases, induction, structural induction, construction and counterexample are alternatives, not a rigid template.
5. **Justify reasoning steps.** Tie each important inference to an assumption, definition, theorem or previous result; avoid handwaving.
6. **Write mathematical English.** Use complete sentences alongside well-formatted equations. Do not use strings of logical symbols as a substitute for prose unless formal logic is explicitly requested.
7. **Maintain consistent terms.** Preserve course-defined notation and distinguish necessary/sufficient, converse/contrapositive, antisymmetric/asymmetric, injective/surjective, and homomorphism/isomorphism.
8. **Conclude the original claim.** End by showing precisely what has been established. An incomplete proof must be labeled incomplete.
9. **Be concise without logical gaps.** Omit routine manipulations, not critical changes of scope, direction, assumptions or case coverage.
10. **Review the student's reasoning fairly.** Identify the earliest substantive error; distinguish genuine logical flaws from cosmetic differences; accept sound alternative methods.

## Domain coverage: one-to-one with Chinese

| Rule ID | English scope | 中文对应 |
| --- | --- | --- |
| `logic_scope` | Logical form and quantifiers | 逻辑形式与量词 |
| `logical_implications` | Implication, equivalence and proof direction | 蕴含、等价与证明方向 |
| `induction_family` | Induction, strong induction and minimal counterexample | 归纳、强归纳与最小反例 |
| `structural_induction` | Structural induction and recursively defined objects | 结构归纳与递归对象 |
| `invariants` | Invariants and algorithm correctness | 不变量与算法正确性 |
| `termination` | Termination and total correctness | 终止性与总正确性 |
| `recursion` | Recursive algorithms and recurrences | 递归与递推证明 |
| `bijection` | Bijections and combinatorial counting | 双射与组合计数 |
| `double_counting` | Double counting and identities | 双重计数与恒等式 |
| `pigeonhole` | Pigeonhole principle and extremal arguments | 抽屉原理与极值 |
| `inclusion_exclusion` | Inclusion–exclusion and case counting | 容斥与分类计数 |
| `graph_theory` | Graph properties and isomorphism | 图论性质与同构 |
| `graph_planarity` | Planarity and graph embeddings | 平面性与图嵌入 |
| `relations_functions` | Relations, functions and quotient structures | 关系、映射与商结构 |
| `algebra` | Groups, rings and homomorphisms | 群、环与同态 |
| `automata` | Automata and state transitions | 自动机与状态转移 |
| `probability` | Probability and existential arguments | 概率计数与存在性 |
| `asymptotic` | Asymptotic bounds and complexity | 渐近界与复杂度 |

The matrix targets **undergraduate discrete mathematics and nearby algorithmic proof topics**. It does not claim exhaustive coverage of every field of research mathematics or every formal proof calculus.

## Terminology and logical direction

| English expression | Chinese equivalent | Meaning to verify |
| --- | --- | --- |
| Let ... be arbitrary / For every ... | 任取／对于任意 | Universal claim; not a single example |
| There exists / There is some ... | 存在／存在一个 | Requires an existence argument |
| If P, then Q | 若 P，则 Q | P implies Q |
| P only if Q | P 仅当 Q | P implies Q; **P if Q** means Q implies P |
| If and only if | 当且仅当 | Both directions |
| Proof by contrapositive | 逆否证明 | Not the converse |
| Proof by contradiction | 反证法 | Negate the actual target |
| Without loss of generality | 不妨设 | Only with an explicit symmetry or equivalence rationale |
| Induction hypothesis / Inductive step | 归纳假设／归纳步骤 | State valid indices |
| Loop invariant | 循环不变量 | Prove initialization, preservation and use at exit |
| Bijection | 双射／一一对应 | Establish injectivity and surjectivity |
| Homomorphism / Isomorphism | 同态／同构 | Isomorphism additionally requires bijectivity |

Avoid unnatural translations such as "According to the meaning of the question" as a generic replacement for a justification. Use *By the given hypothesis*, *By definition*, *By the inductive hypothesis*, *It follows that*, or *For the reverse implication* only where the claimed basis is valid.

## Teaching behavior

- **Hint:** Reveal only useful next steps, not a full proof.
- **Complete solution:** Supply the entire, independently checkable argument.
- **Answer review:** Identify the earliest substantive error, explain the issue and its impact, and do not reject valid alternative proofs.
- **Concept notes:** Distinguish definitions, conditions, statements of theorems and actual proofs.

## Authority, evidence and licensing

| Primary source | Role and evidence boundary |
| --- | --- |
| [Stanford CS103 Proofwriting Checklist](https://web.stanford.edu/class/cs103/proofwriting_checklist) | Official university guidance on proof prose, assumptions/goals and variable scope |
| [CMU 15-251 Proof Guidelines](https://www.cs.cmu.edu/~arielpro/15251f17/docs/proof-checklist.pdf) | Official university guidance on proof style and logical flow |
| [MIT 6.1200J (2024) Readings](https://ocw.mit.edu/courses/6-1200j-mathematics-for-computer-science-spring-2024/pages/readings/) | Official course scope for mathematical proofs, induction and invariants |
| [MIT 6.042J (2015) Readings](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-spring-2015/pages/readings/) | Official discrete mathematics text and associated proof domains |
| [Hammack, Book of Proof](https://richardhammack.github.io/BookOfProof/) | Text approved by the American Institute of Mathematics' Open Textbook Initiative; systematic proof methods |
| [AMS, Language, Logic, and Proof](https://www.ams.org/bookstore/pspdf/amstext-26-prev.pdf) | Mathematical language, terminology and writing precision |
| [Higher Education Press, Discrete Mathematics (3rd ed.)](https://www.hep.com.cn/book/show/2d67dc4c-217a-41db-81b2-56bfe7428879) | Chinese undergraduate curricular scope and terminology; only the public publisher record has been verified here |
| [Companion exercise and solutions volume](https://xuanshu.hep.com.cn/front/book/findBookDetails?bookId=66ca132674ce561611bda659) | Public curriculum/exercise-scope reference; the full copyrighted book has not been audited |

Authority belongs to the referenced institutions and authors. **They have not endorsed DMate or verified any individual AI-generated proof.** CI tests verify parity of the instructions, source IDs and integration; semantic correctness of real English or Chinese model outputs still requires independent, bilingual evaluations. The guidance is an original synthesis of mathematical proof-writing principles; it does not reproduce the textbooks' protected solutions, long passages or exercises and does not imply a commercial redistribution license.
