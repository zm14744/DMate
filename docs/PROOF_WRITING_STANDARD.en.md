# DMate Discrete Mathematics Proof-Writing Standard

Version: 3.0 — Discrete mathematics only

## Purpose and scope

This standard governs DMate's discrete-mathematics tutoring, proof hints, complete solutions, exercise answers, concept notes and proof review. It does not turn DMate into a general higher-mathematics platform.

**Included scope:** mathematical logic, sets, relations and functions, number theory, combinatorics, induction and recursion, graph theory and trees, posets and lattices, discrete algebraic structures, Boolean algebra, automata and formal languages, discrete probability, algorithm correctness and complexity.

**Not separate DMate proof modules:** real analysis, epsilon-delta limits, continuity and calculus, general topology, linear-algebra coursework, differential equations, complex analysis and continuous optimization. General logical principles still apply to any mathematical argument, but these subjects do not receive dedicated DMate proof checklists.

## 1. Shared proof-language requirements

1. **Preserve the proposition:** retain the original domain, assumptions, quantifiers and conclusion; never silently strengthen an implication into an equivalence.
2. **Define variables:** state each new variable's domain, origin and role.
3. **Respect quantifiers:** use an arbitrary object for universal claims; provide a witness, construction or valid existence argument for existential claims.
4. **Justify inferences:** every substantive conclusion must follow from a hypothesis, definition, established result, theorem or valid transformation.
5. **Write natural mathematical English:** use complete sentences to connect equations. Do not replace prose with a chain of logical symbols unless formal logic is requested.
6. **Use stable terminology:** respect the user's textbook and instructor conventions; distinguish necessary/sufficient, converse/contrapositive, antisymmetric/asymmetric, injective/surjective and homomorphism/isomorphism.
7. **Be concise without gaps:** routine algebra may be compressed, but quantifier changes, definitions, logical directions and case coverage may not.
8. **Close the argument:** return explicitly to the original claim; if the proof is incomplete, say so, or provide a verified counterexample when the statement is false.
9. **Review fairly:** locate the earliest substantive error and accept valid alternative proofs rather than marking stylistic differences as mathematical errors.

## 2. Discrete-mathematics domain coverage

The same rule registry supplies Chinese and English guidance with identical stable IDs.

| Domain ID | English coverage | Main checks |
| --- | --- | --- |
| `logic_scope` | Logical form and quantifiers | Propositions, predicates, free/bound variables, quantifier order and negation |
| `logical_implications` | Implication, equivalence and proof direction | Converse, contrapositive, necessary and sufficient conditions |
| `set_theory` | Set theory and set operations | Membership, inclusion, equality, power sets, products and cardinality |
| `relations_functions` | Relations, functions and quotient structures | Equivalence, partial orders, injectivity, surjectivity, bijections and well-definedness |
| `number_theory` | Number theory and divisibility | Divisibility, primes, gcd and Euclidean algorithm |
| `congruences` | Congruences and the Chinese remainder theorem | Modular arithmetic, cancellation conditions and CRT hypotheses |
| `induction_family` | Induction, strong induction and minimal counterexample | Base cases, hypothesis range and inductive step |
| `structural_induction` | Structural induction and recursive objects | Every base and recursive constructor |
| `recursion` | Recursive definitions and recurrences | Initial conditions, recurrence and decreasing instance size |
| `combinatorial_structures` | Combinatorial structures and counting identities | Permutations, combinations, binomial coefficients and constructions |
| `bijection` | Bijections and combinatorial counting | Map, inverse, injectivity and surjectivity |
| `double_counting` | Double counting | Same collection and matching multiplicities |
| `pigeonhole` | Pigeonhole principle and extremal arguments | Object/box assignment and cardinality bounds |
| `inclusion_exclusion` | Inclusion–exclusion and case counting | Intersections, signs, disjointness and coverage |
| `graph_theory` | Graph properties and isomorphism | Degree, paths, connectivity, cycles and isomorphism |
| `graph_planarity` | Planarity and graph embeddings | Euler hypotheses and structural obstructions |
| `trees` | Trees and forests | Connectivity, acyclicity, spanning and rooted trees |
| `graph_algorithms` | Graph algorithms and correctness | BFS, DFS, shortest paths, spanning trees, matching and flow |
| `posets_lattices` | Posets and lattices | Reflexivity, antisymmetry, transitivity, covers, joins and meets |
| `algebra` | Groups, rings and homomorphisms | Axioms, subgroups, cosets, homomorphisms, isomorphisms and ideals |
| `boolean_algebra` | Boolean algebra and logical simplification | Boolean axioms, De Morgan's laws and duality |
| `automata` | Automata and state transitions | Initial/final states, transitions and reachability |
| `formal_languages` | Formal languages and grammars | Alphabet, languages, grammars, regular expressions and automata equivalence |
| `invariants` | Invariants and algorithm correctness | Initialization, preservation and exit condition |
| `termination` | Termination and total correctness | Well-founded measures, partial correctness and termination |
| `probability` | Discrete probability and existence | Sample spaces, independence, expectation and probabilistic method |
| `asymptotic` | Asymptotic bounds and algorithm complexity | Constants and thresholds for O, Ω and Θ |
| `cardinality` | Finite sets, countability and cardinality | Enumeration, injections, bijections and uncountability |

## 3. Proof-method coverage

Domains and methods are separate: one method can apply in several domains, and one domain may require multiple methods.

| Method ID | English method | 中文名称 |
| --- | --- | --- |
| `direct` | Direct proof | 直接证明 |
| `contrapositive` | Proof by contrapositive | 逆否证明 |
| `contradiction` | Proof by contradiction | 反证法 |
| `cases` | Proof by cases | 分类讨论 |
| `construction` | Constructive proof | 构造性证明 |
| `existence` | Nonconstructive existence | 非构造存在性 |
| `uniqueness` | Uniqueness proof | 唯一性证明 |
| `weak_induction` | Weak induction | 普通归纳法 |
| `strong_induction` | Strong induction | 强归纳法 |
| `structural_induction` | Structural induction | 结构归纳法 |
| `minimal_counterexample` | Minimal-counterexample method | 最小反例法 |
| `infinite_descent` | Infinite descent | 无穷递降法 |
| `bijection` | Bijective proof | 双射证明 |
| `double_counting` | Double counting | 双重计数 |
| `pigeonhole` | Pigeonhole argument | 抽屉原理 |
| `extremal` | Extremal argument | 极值原理 |
| `invariant` | Invariant proof | 不变量证明 |
| `probabilistic` | Probabilistic method | 概率方法 |
| `algebraic` | Algebraic identity proof | 代数恒等变形 |
| `equivalence_chain` | Equivalence-chain proof | 等价链证明 |
| `truth_table` | Truth-table verification | 真值表验证 |
| `counterexample` | Disproof by counterexample | 反例否证 |
| `exhaustive` | Proof by exhaustive enumeration | 有限穷举证明 |

## 4. Chinese/English parity

Both languages use the same domain IDs, method IDs, logical requirements and error categories. English should use idiomatic mathematical prose rather than literal translation.

| English | 中文 | Logical meaning |
| --- | --- | --- |
| Let ... be arbitrary | 任取 | Arbitrary object for a universal claim |
| There exists | 存在 | Requires a witness or existence argument |
| If P, then Q | 若 P，则 Q | P=>Q |
| P only if Q | P 仅当 Q | P=>Q; P if Q means Q=>P |
| If and only if | 当且仅当 | Both directions |
| Proof by contrapositive | 逆否证明 | Not the converse |
| Proof by contradiction | 反证法 | Negate the actual target |
| Without loss of generality | 不妨设 | Requires symmetry or equivalence |
| Antisymmetric | 反对称 | Not the same as asymmetric |
| Homomorphism / Isomorphism | 同态／同构 | Isomorphism also requires bijectivity |

## 5. Authoritative sources and boundaries

- [MIT 6.1200J Mathematics for Computer Science (2024)](https://ocw.mit.edu/courses/6-1200j-mathematics-for-computer-science-spring-2024/pages/readings/): discrete mathematics, proofs, induction, algorithm invariants and state machines.
- [MIT 6.042J Mathematics for Computer Science (2015)](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-spring-2015/pages/readings/): logic, sets, number theory, counting, graph theory and probability.
- [Hammack, Book of Proof](https://richardhammack.github.io/BookOfProof/): proof methods, sets, relations, functions, induction and cardinality.
- [Stanford CS103 Proofwriting Checklist](https://web.stanford.edu/class/cs103/proofwriting_checklist): variable scope, assumptions/goals and natural-language proof writing.
- [CMU 15-251 Proof Guidelines](https://www.cs.cmu.edu/~arielpro/15251f17/docs/proof-checklist.pdf): proof structure and expression.
- [AMS, Language, Logic, and Proof](https://www.ams.org/bookstore/pspdf/amstext-26-prev.pdf): mathematical language, notation and writing precision.
- [Higher Education Press, Discrete Mathematics (3rd ed.)](https://www.hep.com.cn/book/show/2d67dc4c-217a-41db-81b2-56bfe7428879): Chinese undergraduate terminology and scope; only the public publisher record is used here.
- [Higher Education Press companion exercise guide](https://xuanshu.hep.com.cn/front/book/findBookDetails?bookId=66ca132674ce561611bda659): Chinese exercise-scope reference; copyrighted exercises and solutions are not copied.
- [MIT 18.781 Theory of Numbers](https://ocw.mit.edu/courses/18-781-theory-of-numbers-spring-2012/pages/lecture-notes/) and [MIT 18.703 Modern Algebra](https://ocw.mit.edu/courses/18-703-modern-algebra-spring-2013/pages/lecture-notes/): supplementary sources only for number theory and discrete algebraic structures.

These sources inform the standard; they do not certify DMate or any AI-generated proof. CI verifies coverage and integration, while mathematical correctness still requires bilingual tests on real problems.

**Scope statement:** This standard targets undergraduate discrete mathematics and closely related algorithms, combinatorics and algebra. It does not claim to cover all mathematics. A discrete-mathematics topic not listed explicitly must still be handled using the general rules of logic, definitions and valid inference; lack of a dedicated row is not a reason to reject a valid proof.
