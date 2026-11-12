"""Bilingual, source-traceable discrete-mathematics proof coverage for DMate.

Each proof domain is defined once with equally scoped Chinese and English
instructions. This is a teaching standard, not a machine proof checker.
External references inform original guidance; no textbook prose is copied.
"""

PROOF_SOURCES = {
    "stanford_cs103": {
        "name": "Stanford CS103 — Proofwriting Checklist",
        "url": "https://web.stanford.edu/class/cs103/proofwriting_checklist",
        "role": "proof prose, variable scope, assumptions and goals",
    },
    "mit_2024": {
        "name": "MIT 6.1200J — Mathematics for Computer Science (2024)",
        "url": "https://ocw.mit.edu/courses/6-1200j-mathematics-for-computer-science-spring-2024/pages/readings/",
        "role": "discrete-mathematics methods, induction, state-machine invariants",
    },
    "mit_2015": {
        "name": "MIT 6.042J — Mathematics for Computer Science (2015)",
        "url": "https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-spring-2015/pages/readings/",
        "role": "proof techniques, number theory, graph theory, counting and probability",
    },
    "hammack": {
        "name": "Richard Hammack — Book of Proof (third edition)",
        "url": "https://richardhammack.github.io/BookOfProof/",
        "role": "direct and indirect proof, induction, relations, functions and cardinality",
    },
    "ams": {
        "name": "American Mathematical Society — Language, Logic, and Proof",
        "url": "https://www.ams.org/bookstore/pspdf/amstext-26-prev.pdf",
        "role": "precision, notation, mathematical writing and references",
    },
    "cmu_251": {
        "name": "Carnegie Mellon University 15-251 — Proof Guidelines",
        "url": "https://www.cs.cmu.edu/~arielpro/15251f17/docs/proof-checklist.pdf",
        "role": "logical flow, natural-language writing and verifiable justification",
    },
    "hep_discrete": {
        "name": "高等教育出版社 — 《离散数学》第3版（2024）",
        "url": "https://www.hep.com.cn/book/show/2d67dc4c-217a-41db-81b2-56bfe7428879",
        "role": "Chinese undergraduate scope and terminology (publisher catalog)",
    },
    "hep_exercises": {
        "name": "高等教育出版社 — 《离散数学学习指导与习题解析》第3版",
        "url": "https://xuanshu.hep.com.cn/front/book/findBookDetails?bookId=66ca132674ce561611bda659",
        "role": "Chinese undergraduate exercise coverage (publisher catalog)",
    },
    "mit_number_theory": {
        "name": "MIT 18.781 — Theory of Numbers (Spring 2012)",
        "url": "https://ocw.mit.edu/courses/18-781-theory-of-numbers-spring-2012/pages/lecture-notes/",
        "role": "divisibility, primes, gcd, Euclidean algorithm, congruences, CRT, Diophantine equations and descent",
    },
    "mit_algebra": {
        "name": "MIT 18.703 — Modern Algebra (Spring 2013)",
        "url": "https://ocw.mit.edu/courses/18-703-modern-algebra-spring-2013/pages/lecture-notes/",
        "role": "groups, subgroups, quotient groups, homomorphisms, rings, ideals, fields and polynomial rings",
    },
    "mit_probability": {
        "name": "MIT 6.1200J — Mathematics for Computer Science (Spring 2024), Expectation",
        "url": "https://ocw.mit.edu/courses/6-1200j-mathematics-for-computer-science-spring-2024/mit6_1200j_s24_lec22.pdf",
        "role": "probability, expectation, independence and discrete probabilistic arguments",
    },
}

# id, zh heading, en heading, zh requirement, en requirement, supporting sources.
PROOF_DOMAINS = (
    ("logic_scope", "逻辑形式与量词", "Logical form and quantifiers",
     "先明确命题与谓词的定义域、量词顺序、自由/约束变元的作用范围；否定全称或存在命题时，正确互换量词并否定谓词。不要交换量词后声称等价。",
     "State the domains and scopes of predicates, the order of quantifiers, and the roles of free and bound variables. When negating quantified claims, switch quantifiers and negate the predicate correctly; never silently exchange quantifier order.",
     ("stanford_cs103", "hammack", "ams")),
    ("logical_implications", "蕴含、等价与证明方向", "Implication, equivalence and proof direction",
     "准确区分 P⇒Q、Q⇒P 和 P⇔Q；证明当且仅当要完成两个方向；否定蕴含时使用 P 成立且 Q 不成立，而非仅否定 P。",
     "Distinguish P=>Q, Q=>P and P<=>Q. A biconditional requires both directions. To negate an implication, establish P together with not-Q; do not merely negate P.",
     ("stanford_cs103", "hammack", "mit_2015")),
    ("induction_family", "归纳、强归纳与最小反例", "Induction, strong induction and minimal counterexample",
     "给出正确且足够的起点；说明归纳假设允许哪些下标；从假设推出下一步，不能循环论证。强归纳或最小反例法须证明所有必需的更小情形。",
     "Give all necessary base cases, state exactly which earlier indices the inductive hypothesis covers, and derive the next case without circularity. Strong induction and minimal-counterexample arguments must justify the required smaller cases.",
     ("mit_2024", "mit_2015", "hammack")),
    ("structural_induction", "结构归纳与递归对象", "Structural induction and recursively defined objects",
     "对字符串、树、公式等递归定义对象，证明所有基本构造，并对每一种递归构造验证：子对象满足归纳性质时，新对象也满足。不能只对长度进行类比而忽略构造规则。",
     "For strings, trees, formulas or other recursively defined objects, cover every base constructor and every recursive constructor. Show that the property transfers from the required subobjects to the newly constructed object; do not ignore construction rules.",
     ("mit_2015", "mit_2024")),
    ("invariants", "不变量与算法正确性", "Invariants and algorithm correctness",
     "分别验证不变量初始化、每轮保持，以及退出时不变量与退出条件如何推出目标后置条件；不要把样例运行当作一般正确性证明。",
     "Prove initialization, preservation through every allowed transition, and how the invariant plus exit condition yields the postcondition. Example traces alone are not a general correctness proof.",
     ("mit_2024", "mit_2015")),
    ("termination", "终止性与总正确性", "Termination and total correctness",
     "终止证明需给出在良基集合中严格下降的度量，或其他有效终止论证；部分正确性与终止性合起来才证明总正确性。",
     "For termination, supply a measure that strictly decreases in a well-founded set, or another valid termination argument. Distinguish partial correctness from total correctness, which also requires termination.",
     ("mit_2024", "mit_2015")),
    ("recursion", "递归与递推证明", "Recursive algorithms and recurrences",
     "区分递归定义、递推关系和求解公式。明确初始条件、适用指标，并检验每次递归调用使用更小的有效实例；闭式公式须代回验证初值和递推式。",
     "Distinguish a recursive definition, a recurrence relation and a proposed closed form. State initial conditions and valid indices; ensure recursive calls use smaller valid instances. Check a closed form against both the base values and recurrence.",
     ("mit_2015", "mit_2024")),
    ("bijection", "双射与组合计数", "Bijections and combinatorial counting",
     "组合计数证明必须说明正在计数的对象与目标集合。使用双射时明确映射和逆映射，或分别证明单射及满射；不能仅凭“看起来一一对应”断言数量相同。",
     "Identify precisely the finite objects being counted. A bijective proof must specify the map and inverse, or prove both injectivity and surjectivity. Visual resemblance is not a proof of a bijection.",
     ("hammack", "mit_2015")),
    ("double_counting", "双重计数与恒等式", "Double counting and identities",
     "说明两种计数方式确实统计同一集合、每个对象出现的次数一致；若按权重或重数计数，须明确其意义，不能遗漏重复计数。",
     "Show that both counting arguments enumerate the same collection with matching multiplicities. If weights or multiplicities occur, define and account for them; do not silently count an object more than once.",
     ("hammack", "mit_2015")),
    ("pigeonhole", "抽屉原理与极值", "Pigeonhole principle and extremal arguments",
     "明确对象与抽屉的对应、数量界和极端对象的选取理由；应用极小/极大原则时，证明所需的存在性及边界情形。",
     "Specify the objects, boxes, cardinality bounds and the chosen extremal object. For minimum/maximum arguments, justify existence and handle boundary cases.",
     ("hammack", "mit_2015")),
    ("inclusion_exclusion", "容斥与分类计数", "Inclusion–exclusion and case counting",
     "明确全集、重叠部分和交集符号，保持容斥正负号正确；分类计数必须彼此不重且覆盖全部目标对象，或解释交叠如何修正。",
     "Define the universe, overlaps and intersections; use the correct inclusion–exclusion signs. Counting cases must be exhaustive and disjoint unless their overlaps are explicitly corrected.",
     ("hammack", "mit_2015")),
    ("graph_theory", "图论性质与同构", "Graph properties and isomorphism",
     "明确图是有向/无向、简单/多重或带权图，以及相关路径、环、度数定义。同构证明须给出顶点双射并验证邻接关系与适用的方向/权值条件；相同度数序列仅是必要线索，不足以证明同构。",
     "Specify whether the graph is directed, undirected, simple, a multigraph or weighted, and use the appropriate path, cycle and degree definitions. Isomorphism needs a vertex bijection preserving adjacency and relevant directions/weights; matching degree sequences alone is insufficient.",
     ("mit_2015", "hep_discrete", "hep_exercises")),
    ("graph_planarity", "平面性与图嵌入", "Planarity and graph embeddings",
     "图的某一画法有交叉不能证明该图非平面；使用欧拉公式须先满足其适用条件。需要否证平面性时提供有效的图论不变量或禁用结构等依据。",
     "Crossings in one drawing do not establish nonplanarity; Euler's formula requires its hypotheses. A nonplanarity proof needs a valid structural obstruction or other sound graph-theoretic argument.",
     ("mit_2015", "hep_discrete")),
    ("relations_functions", "关系、映射与商结构", "Relations, functions and quotient structures",
     "证明等价关系或偏序关系应逐项核对相应定义性质；证明单射、满射、双射时保持各自量词和定义域/陪域正确。对商集或等价类运算须证明定义与代表元选择无关。",
     "Check each required axiom for equivalence or partial order relations. For injectivity, surjectivity and bijectivity, preserve the correct quantifiers, domain and codomain. Operations on equivalence classes must be well-defined independently of representatives.",
     ("hammack", "mit_2015", "hep_discrete")),
    ("algebra", "群、环与同态", "Groups, rings and homomorphisms",
     "证明某结构满足群/环条件时核对所需公理，允许清楚引用已知母结构的结合律等性质。证明同态时逐项验证运算保持；证明同构还需证明双射，不能只凭结构外观相似。",
     "For group/ring structures, verify the applicable axioms; known associativity of an ambient structure may be invoked explicitly. A homomorphism must preserve each relevant operation; an isomorphism also requires bijectivity, not mere visual similarity.",
     ("hep_discrete", "hep_exercises", "mit_2015")),
    ("automata", "自动机与状态转移", "Automata and state transitions",
     "自动机或状态机证明须明确初始状态、转移规则、允许的输入及接受条件；证明接受语言或状态性质时可按输入长度归纳或使用可达性不变量，不能只检验少数输入。",
     "State the start states, transition relation, allowed inputs and acceptance conditions. Prove accepted-language or state properties by induction on input length or a reachability invariant; testing a few strings is not sufficient.",
     ("mit_2024", "mit_2015")),
    ("probability", "概率计数与存在性", "Probability and existential arguments",
     "明确样本空间、事件和概率假设；使用独立性、全概率、条件概率或期望时核对适用条件。概率方法证明存在性时，须解释概率界为何推出至少一个合格对象存在。",
     "Define the sample space, events and assumptions. Verify conditions before using independence, conditioning, total probability or expectation. In a probabilistic existence proof, justify why the probability bound implies at least one suitable object exists.",
     ("mit_2015", "mit_2024")),
    ("asymptotic", "渐近界与复杂度", "Asymptotic bounds and complexity",
     "大 O、Ω、Θ 证明须明确函数定义域，正确给出常数和充分大的阈值，并验证不等式；不要用有限数值测试冒充渐近证明。",
     "For big-O, big-Omega and big-Theta, state the function domain, choose valid constants and a sufficiently large threshold, and verify the required inequality. Finite numeric tests are not asymptotic proofs.",
     ("mit_2024", "mit_2015")),
    ("number_theory", "数论与整除性", "Number theory and divisibility",
     "证明整除、最大公因数、素数性质时明确整数范围和整除定义；使用带余除法、欧几里得算法或唯一分解时核对条件。无穷递降须给出严格下降的正整数或其他良基量。",
     "State the integer domains and divisibility definitions. Check the hypotheses of the division algorithm, Euclidean algorithm and unique factorization. Infinite descent must produce a strictly smaller positive integer or another well-founded measure.",
     ("mit_number_theory", "mit_2015", "hep_discrete")),
    ("congruences", "同余与中国剩余定理", "Congruences and the Chinese remainder theorem",
     "区分整数等式与模 n 同余；约去因子前验证其与模数互素等条件。中国剩余定理须核对模数两两互素的适用条件，并说明构造解及唯一性所在的模数范围。",
     "Distinguish integer equality from congruence modulo n. Before cancellation, verify coprimality or the appropriate divisibility condition. Check pairwise-coprime hypotheses for the Chinese remainder theorem and state the modulus under which the solution is unique.",
     ("mit_number_theory", "mit_2015")),
    ("cardinality", "有限集、可数性与基数", "Finite sets, countability and cardinality",
     "证明集合等势时给出双射；证明可数时给出枚举或注入到自然数的映射；证明不可数时使用对角线或其他有效论证，并说明映射的定义域和值域。",
     "For equipotence, construct a bijection. For countability, give an enumeration or injection into the natural numbers. For uncountability, use a valid diagonal or other argument and state the map's domain and codomain.",
     ("hammack",)),
    ("set_theory", "集合论与集合运算", "Set theory and set operations",
     "证明集合包含时任取源集合元素并证明其属于目标集合；证明相等时完成两个包含方向。使用幂集、笛卡尔积、差集、补集和基数时明确全集、定义域与运算约定，不能把元素属于与集合包含混淆。",
     "For set inclusion, take an arbitrary element of the source set and show it belongs to the target; for equality, prove both inclusions. State the universe and conventions for power sets, Cartesian products, differences, complements and cardinalities. Do not confuse membership with inclusion.",
     ("hammack", "mit_2015", "hep_discrete")),
    ("combinatorial_structures", "组合结构与计数恒等式", "Combinatorial structures and counting identities",
     "明确被计数对象及其参数；排列、组合、二项式系数、分拆或递推计数必须说明对象如何分类、构造或对应。组合恒等式可用双射、双重计数或代数推导，但须明确每种方法实际证明了什么。",
     "Define the objects and parameters being counted. For permutations, combinations, binomial coefficients, partitions or recursive counts, explain the classification, construction or correspondence. A counting identity may use a bijection, double counting or algebra, but state what each argument establishes.",
     ("mit_2015", "mit_2024", "hep_discrete")),
    ("trees", "树与森林", "Trees and forests",
     "使用树的等价刻画时明确有限、连通、无环、边数等前提；生成树证明须验证覆盖所有顶点且保持连通、无环。根树和有序树还须区分根、父子关系及子节点顺序。",
     "When using equivalent characterizations of trees, state finiteness, connectivity, acyclicity and edge-count hypotheses. A spanning-tree proof must establish that every vertex is covered and that the result is connected and acyclic. For rooted or ordered trees, distinguish roots, parent-child relations and child order.",
     ("mit_2015", "mit_2024", "hep_discrete")),
    ("graph_algorithms", "图算法与算法正确性", "Graph algorithms and correctness",
     "证明 BFS、DFS、最短路径、生成树、匹配或网络流算法时，明确输入图和权值条件；区分算法运行轨迹与一般正确性证明。使用循环不变量、割性质、交换论证或归纳时，验证其前提和每一步保持。",
     "For BFS, DFS, shortest-path, spanning-tree, matching or flow algorithms, state graph and weight assumptions. Distinguish a sample execution trace from a general correctness proof. When using invariants, cut properties, exchange arguments or induction, verify their hypotheses and preservation steps.",
     ("mit_2015", "mit_2024")),
    ("posets_lattices", "偏序集与格", "Partially ordered sets and lattices",
     "证明偏序时逐项验证自反、反对称、传递；证明哈斯图时只保留覆盖关系，不能把传递边当作覆盖边。证明格时对任意两个元素验证最小上界和最大下界存在且满足定义。",
     "Verify reflexivity, antisymmetry and transitivity separately when proving a partial order. A Hasse diagram contains cover relations, not transitive edges. To prove a poset is a lattice, establish that every pair has a least upper bound and greatest lower bound.",
     ("mit_2015", "hep_discrete")),
    ("boolean_algebra", "布尔代数与逻辑化简", "Boolean algebra and logical simplification",
     "使用交换、结合、分配、吸收、补元、德摩根律和对偶原理时，说明等式所依据的公理或已证恒等式；逻辑等价与布尔代数等式须区分语义依据和代数变形。",
     "When using commutativity, associativity, distributivity, absorption, complements, De Morgan's laws or duality, identify the relevant axiom or established identity. Distinguish semantic logical equivalence from algebraic manipulation in a Boolean algebra.",
     ("mit_2015", "mit_2024", "hep_discrete")),
    ("formal_languages", "形式语言与文法", "Formal languages and grammars",
     "证明语言运算、正则表达式、文法或自动机等价时，明确字母表、语言和生成/识别定义；语言包含须对任意字符串证明，自动机等价须证明两边接受同一语言，不能只测试有限个样例。",
     "For language operations, regular expressions, grammars or automata equivalence, define the alphabet, language and generation/acceptance semantics. Language inclusion requires an argument for arbitrary strings; automata equivalence requires equality of accepted languages, not a finite sample test.",
     ("mit_2024", "mit_2015")),
)

# Proof methods are separate from subject domains: a domain may require several methods.
PROOF_METHODS = (
    ("direct", "直接证明", "Direct proof", "从假设按有效推理推出结论。", "Derive the target from the hypotheses by valid steps."),
    ("contrapositive", "逆否证明", "Proof by contrapositive", "证明等价的逆否命题，不误用逆命题。", "Prove the equivalent contrapositive, not the converse."),
    ("contradiction", "反证法", "Proof by contradiction", "在原假设下否定准确的目标并导出矛盾。", "Negate the actual target under the original hypotheses and derive a contradiction."),
    ("cases", "分类讨论", "Proof by cases", "情形彼此清楚且覆盖全部可能性。", "Make cases clear and exhaustive."),
    ("construction", "构造性证明", "Constructive proof", "明确构造对象并逐项验证性质。", "Construct a witness explicitly and verify its properties."),
    ("existence", "非构造存在性", "Nonconstructive existence proof", "说明定理或逻辑依据如何保证对象存在。", "Explain which theorem or argument guarantees existence."),
    ("uniqueness", "唯一性证明", "Uniqueness proof", "任取两个满足条件的对象并证明相等。", "Take any two witnesses and prove they are equal."),
    ("weak_induction", "普通数学归纳法", "Weak induction", "明确起点、归纳假设和下一步。", "State the base case, induction hypothesis and successor step."),
    ("strong_induction", "强归纳法", "Strong induction", "说明可使用的所有较小指标。", "State exactly which earlier indices may be used."),
    ("structural_induction", "结构归纳法", "Structural induction", "覆盖每一种基本构造和递归构造。", "Cover every base constructor and recursive constructor."),
    ("minimal_counterexample", "最小反例法", "Minimal-counterexample method", "证明最小反例存在，并从其最小性推出矛盾。", "Establish a minimal counterexample and use its minimality to derive a contradiction."),
    ("infinite_descent", "无穷递降法", "Infinite descent", "构造严格下降的良基量，排除无限递降。", "Construct a strictly decreasing well-founded measure, ruling out infinite descent."),
    ("bijection", "双射证明", "Bijective proof", "给出映射并证明可逆或双射。", "Define the map and prove it is bijective or invertible."),
    ("double_counting", "双重计数", "Double counting", "从两种方式计数同一对象集合。", "Count the same collection in two justified ways."),
    ("pigeonhole", "抽屉原理证明", "Pigeonhole argument", "明确对象、抽屉及数量界。", "Specify objects, boxes and cardinality bounds."),
    ("extremal", "极值原理", "Extremal argument", "证明极值对象存在，再利用其极值性质。", "Establish an extremal object and exploit its extremal property."),
    ("invariant", "不变量证明", "Invariant proof", "证明初始化、保持和退出结论。", "Prove initialization, preservation and the exit implication."),
    ("probabilistic", "概率方法", "Probabilistic method", "由概率界严格推出存在或高概率性质。", "Derive existence or high-probability claims from valid probability bounds."),
    ("algebraic", "代数恒等变形证明", "Algebraic identity proof", "每步等式使用合法运算并核对定义域。", "Justify each identity transformation and verify domains."),
    ("equivalence_chain", "等价链证明", "Equivalence-chain proof", "逐步证明每个等价变形方向成立。", "Justify both directions of every equivalence step."),
    ("truth_table", "真值表验证", "Truth-table verification", "对有限命题变元的所有真值赋值逐行核验；说明变量顺序及行覆盖完整，不把抽样行当作证明。", "Check every truth assignment for the finite set of propositional variables. State the variable order and ensure all rows are covered; sampled rows are not a proof."),
    ("counterexample", "反例否证", "Disproof by counterexample", "反驳全称命题时，给出定义域内的具体对象，核验前提成立且结论失败；不要把反例当成对存在命题的否证。", "To refute a universal claim, give an object in the stated domain and verify that the hypotheses hold while the conclusion fails. A counterexample to a universal statement is not a refutation of an existential claim."),
    ("exhaustive", "有限穷举证明", "Proof by exhaustive enumeration", "只有对象集合确实有限且每种情况均被覆盖时才能使用；说明枚举范围和完整性，不能用有限样例推断无限情形。", "Use only when the domain is finite and every case is covered. State the enumeration range and why it is exhaustive; finite examples do not establish an infinite claim."),
)

# id, Chinese expression, English expression, semantic caution (Chinese / English).
PROOF_GLOSSARY = (
    ("universal", "任取／对于任意", "Let ... be arbitrary / For every ...",
     "用于全称命题；不是只举一个例子。", "For a universal claim, not merely a single example."),
    ("existential", "存在／存在一个", "There exists / There is some ...",
     "需给出见证或存在性理由。", "Provide a witness or a sound existence argument."),
    ("implication", "若 P，则 Q", "If P, then Q",
     "不能未经证明把单向蕴含升级为等价。", "Do not upgrade an implication into equivalence without proof."),
    ("only_if", "P 仅当 Q", "P only if Q",
     "含义为 P⇒Q；“P if Q”则是 Q⇒P。", "Means P=>Q; 'P if Q' means Q=>P."),
    ("biconditional", "当且仅当", "If and only if",
     "需要两个方向。", "Both directions are required."),
    ("contrapositive", "逆否命题／逆否证明", "Contrapositive / Proof by contrapositive",
     "不能误作逆命题。", "Do not confuse with the converse."),
    ("contradiction", "反证法／导出矛盾", "Proof by contradiction / This is a contradiction",
     "准确否定待证结论。", "Negate the actual target claim."),
    ("wlog", "不妨设", "Without loss of generality",
     "必须有对称性或等价理由。", "Requires a symmetry or equivalence justification."),
    ("induction", "归纳假设／归纳步骤", "Induction hypothesis / Inductive step",
     "标明允许的指标。", "State the allowed indices."),
    ("invariant", "循环不变量／状态不变量", "Loop invariant / State invariant",
     "初始化、保持、退出时的用途要分别说明。", "Prove initiation, maintenance and use at exit."),
    ("bijection", "双射／一一对应", "Bijection / One-to-one correspondence",
     "映射需可逆或证明单射及满射。", "Supply an inverse or prove injective and surjective."),
    ("homomorphism", "同态／同构", "Homomorphism / Isomorphism",
     "同构在保持运算之外还要求双射。", "An isomorphism also requires bijectivity."),
    ("conclusion", "因此……，命题得证", "Therefore ... , as required",
     "结论必须回扣原命题。", "The conclusion must match the original claim."),
)


def proof_coverage_prompt(language="zh-CN"):
    """Build the same checklist sections for Chinese and English."""
    english = str(language or "").strip().lower().replace("_", "-").startswith("en")
    heading = (
        "[Discrete-mathematics proof checks; apply only to relevant topics within that curriculum]"
        if english else "【离散数学分领域证明核对要求｜仅用于该课程范围内的相关题型】"
    )
    lines = [heading]
    for index, (_, title_zh, title_en, rule_zh, rule_en, _) in enumerate(PROOF_DOMAINS, 1):
        title, rule = (title_en, rule_en) if english else (title_zh, rule_zh)
        lines.append(f"{index}. {title}：{rule}" if not english else f"{index}. {title}: {rule}")
    method_heading = (
        "[Proof-method selection checklist; select methods from the proposition's structure]"
        if english else "【证明方法选择清单｜根据命题结构选择，不机械套用】"
    )
    lines.append(method_heading)
    for key, zh, en, caution_zh, caution_en in PROOF_METHODS:
        lines.append(f"{en}: {caution_en}" if english else f"{zh}：{caution_zh}")
    lines.append(
        "[Bilingual terminology cross-check; use the correct natural expression, never mechanical translation]"
        if english else "【中英文术语语义对照｜用自然的语言，不逐字硬译】"
    )
    for _, zh, en, caution_zh, caution_en in PROOF_GLOSSARY:
        lines.append(
            f"{en}: {caution_en}" if english else f"{zh}：{caution_zh}"
        )
    lines.append(
        "Use each source as a reference for principles, not as automatically verified authority for any particular generated proof. Keep course-specific conventions and recognize valid alternative proofs."
        if english else
        "这些权威资料用于建立规范，不意味着某次 AI 输出已经被权威机构验证。尊重课程记号与有效的不同证明方法。"
    )
    return "\n\n" + "\n".join(lines) + "\n"
