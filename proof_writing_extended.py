"""Bilingual, source-traceable proof coverage for DMate.

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
    "mit_real_analysis": {
        "name": "MIT 18.100B — Real Analysis (Spring 2025)",
        "url": "https://ocw.mit.edu/courses/18-100b-real-analysis-spring-2025/pages/lecture-notes/",
        "role": "proof writing, epsilon-delta, sequences, series, continuity, derivatives, integrals, uniform convergence and ODEs",
    },
    "mit_number_theory": {
        "name": "MIT 18.781 — Theory of Numbers (Spring 2012)",
        "url": "https://ocw.mit.edu/courses/18-781-theory-of-numbers-spring-2012/pages/lecture-notes/",
        "role": "divisibility, primes, gcd, Euclidean algorithm, congruences, CRT, Diophantine equations and descent",
    },
    "mit_linear_algebra": {
        "name": "MIT 18.06 — Linear Algebra",
        "url": "https://ocw.mit.edu/courses/18-06-linear-algebra-spring-2010/",
        "role": "linear independence, bases, dimension, linear transformations, determinants and eigenvalues",
    },
    "mit_algebra": {
        "name": "MIT 18.703 — Modern Algebra (Spring 2013)",
        "url": "https://ocw.mit.edu/courses/18-703-modern-algebra-spring-2013/pages/lecture-notes/",
        "role": "groups, subgroups, quotient groups, homomorphisms, rings, ideals, fields and polynomial rings",
    },
    "mit_metric": {
        "name": "MIT 18.S190 — Introduction to Metric Spaces (January 2023)",
        "url": "https://ocw.mit.edu/courses/18-s190-introduction-to-metric-spaces-january-iap-2023/pages/lecture-notes/",
        "role": "metric spaces, continuity, completeness, compactness and connectedness",
    },
    "mit_probability": {
        "name": "MIT 6.1200J — Mathematics for Computer Science (Spring 2024), Expectation",
        "url": "https://ocw.mit.edu/courses/6-1200j-mathematics-for-computer-science-spring-2024/mit6_1200j_s24_lec22.pdf",
        "role": "probability, expectation, independence and discrete probabilistic arguments",
    },
    "mit_optimization": {
        "name": "MIT 6.7220J/15.084 — Nonlinear Optimization (Spring 2025)",
        "url": "https://ocw.mit.edu/courses/6-7220j-nonlinear-optimization-spring-2025/",
        "role": "convexity, optimality, derivatives and optimization proofs",
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
    ("inequalities", "不等式与极值估计", "Inequalities and extremal estimates",
     "每次乘除不等式前核对因子正负；平方、开方、取倒数或取对数须核对定义域与单调性。说明等号成立条件；不能只验证数值例子。",
     "Check signs before multiplying or dividing inequalities. Squaring, taking roots, reciprocals or logarithms requires domain and monotonicity conditions. State equality conditions; numerical examples are not proofs.",
     ("mit_real_analysis", "mit_2015")),
    ("real_completeness", "实数完备性与上确界", "Completeness of the real numbers and suprema",
     "使用上确界、下确界或完备性时先证明集合非空且有相应界；区分上界与最大元，并按 ε 逼近性质证明上确界结论。",
     "Before invoking completeness or a supremum/infimum, establish nonemptiness and the relevant boundedness. Distinguish an upper bound from a maximum and use the epsilon-approximation property where needed.",
     ("mit_real_analysis", "mit_2015")),
    ("sequences_series", "数列、级数与收敛", "Sequences, series and convergence",
     "明确收敛对象、极限和指标；使用 Cauchy 判别、比较判别、单调有界定理或幂级数性质时核对全部条件。点态收敛与一致收敛不得混淆。",
     "Identify the sequence or series, its limit and index range. Verify all hypotheses of Cauchy, comparison, monotone convergence and power-series tests. Do not confuse pointwise with uniform convergence.",
     ("mit_real_analysis", "mit_2015")),
    ("epsilon_delta", "ε-δ 与极限证明", "Epsilon-delta limit proofs",
     "按量词顺序先任取 ε>0，再构造只依赖 ε（及固定参数）的 δ>0；最后证明 0<|x-a|<δ 确实推出目标估计。δ 不得依赖正在趋近的变量 x。",
     "Respect the quantifier order: choose an arbitrary epsilon > 0, then construct a delta > 0 depending only on epsilon and fixed parameters. Verify that 0 < |x-a| < delta implies the required estimate. Delta must not depend on the varying x.",
     ("mit_real_analysis", "ams")),
    ("continuity", "连续性与一致连续性", "Continuity and uniform continuity",
     "分别识别点态连续与一致连续的量词顺序；使用序列刻画时说明其适用的度量/拓扑环境。紧致性推出一致连续等结论须先验证空间条件。",
     "Distinguish pointwise and uniform continuity by their quantifier order. State the metric or topological setting when using sequential characterizations. Verify compactness hypotheses before invoking results such as uniform continuity on compact spaces.",
     ("mit_real_analysis", "mit_metric")),
    ("differentiation", "微分、中值定理与 Taylor 展开", "Differentiation, mean value theorems and Taylor expansion",
     "使用 Rolle 定理、拉格朗日中值定理或 Taylor 定理前核对区间连续性、内部可导性和余项条件；L'Hôpital 法则须核对不定式及其适用假设。",
     "Check continuity, differentiability and remainder hypotheses before applying Rolle's theorem, the mean value theorem or Taylor's theorem. L'Hopital's rule requires a valid indeterminate form and its stated hypotheses.",
     ("mit_real_analysis",)),
    ("integration", "Riemann 积分与微积分基本定理", "Riemann integration and the fundamental theorem of calculus",
     "使用可积性、积分中值定理或微积分基本定理时核对函数与区间条件；交换极限、积分或求导顺序时必须证明一致收敛、支配条件或相应定理假设。",
     "Verify function and interval hypotheses for integrability, the integral mean value theorem and the fundamental theorem of calculus. Interchanging limits, integrals or derivatives requires uniform convergence, domination or the relevant theorem's hypotheses.",
     ("mit_real_analysis",)),
    ("metric_topology", "度量空间与拓扑证明", "Metric spaces and topology",
     "明确度量、开集、闭集、邻域、紧致、连通等定义；开覆盖证明须构造覆盖并论证有限子覆盖。不能把实数直线上的结论无条件推广到任意度量或拓扑空间。",
     "State the definitions of metric, open and closed sets, neighborhoods, compactness and connectedness. An open-cover proof must construct the cover and justify a finite subcover. Do not transfer real-line results to arbitrary metric or topological spaces without hypotheses.",
     ("mit_metric", "mit_real_analysis")),
    ("linear_algebra", "线性空间、基与维数", "Vector spaces, bases and dimension",
     "证明子空间须验证非空及线性封闭；证明线性无关、张成、基和维数时严格使用相应定义。秩-零度定理须明确线性映射的定义域、陪域及有限维条件。",
     "Verify nonemptiness and closure for subspaces. Use the exact definitions of linear independence, span, basis and dimension. State the domain, codomain and finite-dimensional hypotheses for rank-nullity.",
     ("mit_linear_algebra", "hep_discrete")),
    ("matrices_eigen", "矩阵、线性变换与特征值", "Matrices, linear maps and eigenvalues",
     "矩阵等式证明应核对维数和乘法顺序；相似、可对角化、特征空间和谱定理结论须核对域、维数及对称/正规等必要条件，不能把数值计算代替一般证明。",
     "Check dimensions and multiplication order in matrix identities. Similarity, diagonalizability, eigenspaces and spectral theorems require their field, dimension, symmetry or normality hypotheses. Numerical computation alone is not a general proof.",
     ("mit_linear_algebra", "mit_2015")),
    ("polynomial_algebra", "多项式与代数方程", "Polynomials and algebraic equations",
     "使用多项式整除、因式定理、根的重数或不可约性时说明系数环/域；多项式除法、唯一分解和根数界须核对底层代数结构。",
     "State the coefficient ring or field when using divisibility, the factor theorem, root multiplicity or irreducibility. Polynomial division, unique factorization and root bounds depend on the underlying algebraic structure.",
     ("mit_algebra", "mit_number_theory")),
    ("geometry", "欧氏几何与几何变换", "Euclidean geometry and geometric transformations",
     "几何证明须明确使用的公理、定义、角度/长度关系和构造条件；相似、全等、平行、垂直和圆幂等结论要核对对应判定条件。图形仅用于辅助，不以视觉直观替代论证。",
     "State the geometric axioms, definitions, angle/length relations and construction assumptions. Verify the criteria for similarity, congruence, parallelism, perpendicularity and power-of-a-point arguments. A diagram is auxiliary, not a substitute for proof.",
     ("ams", "hep_discrete")),
    ("optimization", "凸性与最优化证明", "Convexity and optimization proofs",
     "证明凸性须回到定义或等价判据；证明极小点/极大点或最优性条件时核对可行域、可微性、凸性和约束资格条件。KKT 条件不能脱离假设当作充分必要条件。",
     "Prove convexity from its definition or a valid equivalent criterion. For optimality, verify feasibility, differentiability, convexity and constraint qualifications. KKT conditions are not automatically necessary and sufficient without their hypotheses.",
     ("mit_optimization", "mit_real_analysis")),
    ("ode", "微分方程存在性与唯一性", "Existence and uniqueness for differential equations",
     "使用 Picard-Lindelöf 等存在唯一性定理时明确初值问题、定义域、连续性及 Lipschitz 条件；局部解与全局解必须区分，不能由数值轨迹推出唯一性。",
     "State the initial-value problem and verify continuity and Lipschitz hypotheses before applying Picard-Lindelof. Distinguish local from global existence; numerical trajectories do not prove uniqueness.",
     ("mit_real_analysis",)),
    ("cardinality", "有限集、可数性与基数", "Finite sets, countability and cardinality",
     "证明集合等势时给出双射；证明可数时给出枚举或注入到自然数的映射；证明不可数时使用对角线或其他有效论证，并说明映射的定义域和值域。",
     "For equipotence, construct a bijection. For countability, give an enumeration or injection into the natural numbers. For uncountability, use a valid diagonal or other argument and state the map's domain and codomain.",
     ("hammack", "mit_real_analysis")),
    ("multivariable_calculus", "多元微积分与向量分析", "Multivariable calculus and vector analysis",
     "多元极限须处理路径依赖并区分逐路径验证与完整证明；链式法则、隐函数/反函数定理、Green/Stokes/Gauss 定理须核对可微性、区域边界、方向和正则性条件。",
     "A multivariable limit proof must address path dependence; checking selected paths alone cannot establish a limit. Verify differentiability, boundary regularity, orientation and domain hypotheses for chain rule, implicit/inverse function theorems and Green/Stokes/divergence theorems.",
     ("mit_real_analysis", "mit_metric")),
    ("complex_analysis", "复分析基础证明", "Introductory complex analysis",
     "复可微、解析、Cauchy 积分定理/公式、幂级数和留数结论须核对区域连通性、解析性及曲线条件；不能直接把实变量微积分结论照搬到复平面。",
     "Check domain connectivity, analyticity and contour hypotheses for complex differentiability, Cauchy's theorem/formula, power series and residues. Real-variable calculus results cannot be transferred to the complex plane without justification.",
     ("ams", "mit_real_analysis")),
    ("convexity_optimization", "凸分析与对偶性", "Convex analysis and duality",
     "对偶性和最优性证明应明确原问题与对偶问题、弱/强对偶的条件及可行性；不能把弱对偶直接升级为强对偶，也不能忽略 Slater 等约束资格条件。",
     "State the primal and dual problems and the hypotheses for weak and strong duality. Do not infer strong duality from weak duality or omit constraint qualifications such as Slater's condition.",
     ("mit_optimization",)),
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
    ("epsilon_delta", "ε-δ 证明", "Epsilon-delta proof", "遵守量词顺序并构造合法 δ。", "Respect quantifier order and construct a valid delta."),
    ("sequential", "序列刻画证明", "Sequential-characterization proof", "确认所在空间中序列刻画定理的适用条件。", "Verify that the sequential characterization applies in the given space."),
    ("open_cover", "开覆盖证明", "Open-cover proof", "构造开覆盖并使用有限子覆盖性质。", "Construct an open cover and use the finite-subcover property."),
    ("algebraic", "代数恒等变形证明", "Algebraic identity proof", "每步等式使用合法运算并核对定义域。", "Justify each identity transformation and verify domains."),
    ("equivalence_chain", "等价链证明", "Equivalence-chain proof", "逐步证明每个等价变形方向成立。", "Justify both directions of every equivalence step."),
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
        "[Domain-specific proof checks; apply only when relevant to the user's task]"
        if english else "【分领域证明核对要求｜只在相关题型中应用】"
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
