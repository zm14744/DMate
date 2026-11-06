(function (root) {
    'use strict';
    const knowledgeLanguage = root.DMateKnowledgeLanguage
        || (typeof module !== 'undefined' && module.exports ? require('./language-knowledge.js') : null);

    // Specific mathematical phrases come first. Consuming only their matched
    // spans prevents, for example, generating functions becoming function study.
    // These are study suggestions, not assessments of ability or correctness.
    const rules = [
        ['生成函数', /生成函数|母函数|\bgenerating functions?\b/gi,
            '用题目中的前几个计数值写出生成函数的前几项，并说明系数代表什么。',
            '展开所得到的式子，核对各项系数与手工计数或已知初值是否一致。'],
        ['非齐次递推', /非齐次(?:线性)?递推(?:关系)?|线性非齐次递推(?:关系)?/g,
            '把递推式中的齐次部分和额外项分开，再用初值算出前三项。',
            '将候选通项代回原递推式和初始条件；只满足齐次部分还不能作为答案。'],
        ['线性齐次递推', /(?:线性齐次|齐次线性)递推(?:关系)?|特征方程(?:法)?/g,
            '从递推式写出特征方程，再用初始条件确定通项中的常数。',
            '把通项代回递推式，并核对每个给定初值；重根时检查是否漏了相应的多项式因子。'],
        ['初始条件', /^初始条件$|递推(?:关系)?的初始条件/g,
            '写出递推式从哪个下标开始适用，再逐项列出所需初值。',
            '从初值算出前几项，与题目中的起始情况逐一核对，检查是否缺少初值或错移了下标。'],
        ['递推关系建模', /递推关系(?:建模)?|递归关系|递推式|递推数列|递推方程|\brecurrence relations?\b/gi,
            '先说明数列每一项表示什么，写出起始情况，再按最后一步分类得到递推式。',
            '手算最小的几个情况，核对初值、下标和分类是否重复或遗漏。'],
        ['欧拉定理与费马小定理', /欧拉定理|费马小定理|\bEuler['’]?s theorem\b|\bFermat['’]?s little theorem\b/gi,
            '选一个模幂例子，先检查底数与模数是否互素，再尝试缩减指数。',
            '核对所用定理的互素或素数条件，并用较小指数的直接计算验证余数。'],
        ['RSA公钥密码', /RSA公钥密码|RSA(?:算法|加密|解密|密码)|\bRSA cryptography\b/gi,
            '用很小的教学用素数计算一次模数、指数与密钥，再手算一轮加密和解密。',
            '检查指数的互素条件与模逆关系，核对解密是否还原原消息；教学用小参数不能用于真实加密。'],
        ['模逆与中国剩余定理', /模逆(?:元)?|乘法逆元|中国剩余定理|孙子定理|\bChinese remainder theorem\b|\bmodular inverse\b/gi,
            '对一个模逆问题先求最大公因数；对同余方程组先检查各模数之间的关系。',
            '把候选逆元代入乘积取模，或把候选解逐个代回原同余式；不能直接套用互素条件不满足的版本。'],
        ['线性同余方程', /线性同余(?:方程)?|一次同余(?:方程)?|\blinear congruences?\b/gi,
            '把方程写成 ax 与 b 模 m 同余，先计算 a 与 m 的最大公因数。',
            '检查最大公因数是否整除 b，再把求出的各个剩余类代回原方程。'],
        ['最大公因数与欧几里得算法', /最大公(?:因|约)数|欧几里得算法|辗转相除法|贝祖(?:定理|等式)|\bEuclidean algorithm\b|\bgcd\b/gi,
            '用辗转相除法完成一个最大公因数计算，保留每一步的商和余数。',
            '检查每步余数范围以及最后一个非零余数；需要整数系数时再回代验证贝祖等式。'],
        ['同余与模运算', /同余(?:与模运算)?|模运算|模算术|\bmodular arithmetic\b/gi,
            '把一个同余关系改写成整除关系，再独立计算两边的余数。',
            '核对模数是否一致；进行约分前检查约去的数在该模数下是否可逆。'],
        ['整除与素数', /整除与素数|整除性|整除关系|素因数分解|质因数分解|素数判定|素数(?:与|和)合数|\bprime factorization\b/gi,
            '把题目中的整除条件改写成整数倍关系，或对给定整数做素因数分解。',
            '核对整数倍中的系数确为整数，分解时将各个素因子乘回原数。'],
        ['数学归纳法', /强归纳法|数学归纳法|归纳证明|归纳假设|归纳步骤|\bmathematical induction\b|\bstrong induction\b/gi,
            '只写出归纳起点、归纳假设和要证明的下一步，并标出使用归纳假设的位置。',
            '核对起点覆盖了题目要求，假设只用于已经允许的下标，下一步没有直接假设待证结论。'],
        ['直接证明与反证法', /直接证明(?:与反证法)?|反证法|逆否证(?:明|法)|数学证明|证明方法|\bproof by contradiction\b|\bcontrapositive\b/gi,
            '把已知条件和待证结论分别写下，再选择直接推导、逆否证明或反证中的一种。',
            '逐步标出所用定义或定理；反证时检查否定的是否正是待证结论，避免循环论证。'],
        ['量词推理与否定', /量词(?:推理与否定|否定|的否定)|否定.{0,6}量词|量词.{0,6}否定|量词(?:顺序|交换)|前束范式|\bquantifier negation\b/gi,
            '先写明个体域，再把一句含量词的命题完整否定一次。',
            '核对每个全称与存在量词是否互换、内部谓词是否否定，并检查变量的辖域。'],
        ['量词', /量词|全称命题|存在命题|全称量词|存在量词|谓词与个体域|谓词逻辑|变元与辖域|自由变元|约束变元|\bquantifiers?\b/gi,
            '选一句含“每个”或“存在”的陈述，明确个体域后写成量词表达式。',
            '用一个小的个体域逐项验证；有多个量词时，检查交换顺序是否改变含义。'],
        ['范式', /^范式$|主析取范式|主合取范式|析取范式|合取范式|命题范式|\bdisjunctive normal form\b|\bconjunctive normal form\b/gi,
            '先列出命题的真值表，再从取真或取假的行构造所需范式。',
            '对照真值表逐行检查结果；主范式中的每一项应包含全部命题变元。'],
        ['逻辑等价', /逻辑等价|逻辑等值|等值演算|德摩根(?:定律|律)|\blogical equivalence\b/gi,
            '对一个等价变形写出每一步所用的等值律，或独立列出两边的真值表。',
            '核对两边在所有赋值下真值一致，特别检查括号、否定号和蕴含方向。'],
        ['真值表', /真值表|逻辑联结词|命题与真值|命题逻辑|\btruth tables?\b|\bpropositional logic\b/gi,
            '选一个含蕴含的复合命题，先找出使它为假的赋值，再补全真值表。',
            '核对每个变元组合都出现一次，并检查是否把原命题、逆命题与逆否命题混为一谈。'],
        ['命题推理', /命题推理|推理规则|推理有效性|有效推理|\brules? of inference\b/gi,
            '把前提和结论分开，尝试寻找“全部前提为真而结论为假”的赋值。',
            '找到这种赋值即可否定有效性；找不到时仍需完整真值表或合规推理步骤作依据。'],
        ['单射满射双射', /单射满射双射|单射|满射|双射|一一映射|\binjective\b|\bsurjective\b|\bbijective\b/gi,
            '写清定义域和陪域，检查是否有两个不同输入对应同一输出，以及是否有陪域元素没有原像。',
            '用定义分别判断单射和满射；只有两项都满足才能判断为双射，且判断依赖陪域。'],
        ['复合函数', /复合函数|函数复合|复合映射|映射复合|\bfunction composition\b/gi,
            '选一个合法输入，按从内到外的顺序算出一次复合函数的值。',
            '核对内层输出是否属于外层定义域，再对照复合顺序；一般不能交换两个函数。'],
        ['逆函数', /逆函数|逆映射|\binverse functions?\b/gi,
            '写清原函数的定义域和陪域，先判断它是否具有逆函数。',
            '对候选逆函数分别验证两个方向的复合为恒等映射，并核对适用的定义域。'],
        ['函数与映射', /函数与映射|函数映射|映射的定义|(?:函数|映射)(?:的)?(?:定义|性质|习题|练习|题目)|(?:离散数学|数学)(?:中|中的)?(?:函数|映射)|(?:什么是|解释(?:一下)?|(?:怎么|如何)理解)(?:函数|映射)(?!按钮|菜单|界面|模块|接口|代码|调用|参数|返回值)|(?:函数|映射)是什么|定义域|陪域|值域/gi,
            '写清定义域和陪域，再逐个检查每个输入对应的输出。',
            '核对是否每个输入恰有一个输出，并区分实际取得的值域与预先指定的陪域。'],
        ['等价关系与划分', /等价关系(?:与划分)?|等价类|集合划分|商集|\bequivalence relations?\b/gi,
            '对一个小集合上的关系，先验证自反、对称和传递，再写出一个元素的等价类。',
            '核对各等价类是否非空、不相交且覆盖原集合；未满足三项性质时不要直接按等价类处理。'],
        ['偏序关系', /偏序(?:关系|集)?|哈斯图|全序(?:关系|集)?|极大元|极小元|上确界|下确界|\bpartial orders?\b|\bHasse diagrams?\b/gi,
            '对一个小偏序集画出哈斯图，选一个元素判断它是否为极大元或极小元。',
            '核对自反、反对称与传递，并区分“没有更大的元素”和“大于等于所有元素”。'],
        ['关系闭包', /关系闭包|自反闭包|对称闭包|传递闭包|\btransitive closure\b/gi,
            '从原关系出发，只补上满足所求闭包性质所必需的有序对。',
            '核对原关系仍被包含、目标性质已经满足，并说明每个新增有序对由哪条规则或哪段关系链推出。'],
        ['关系运算', /关系运算|关系(?:的)?复合|复合关系|逆关系|关系(?:的)?幂|\bcomposition of relations\b/gi,
            '先写出关系运算的定义，再从一个有序对出发寻找它是否属于结果关系的依据。',
            '复合时核对中间元素是否存在以及两个关系的先后约定；求逆时检查是否交换了每对元素的顺序。'],
        ['笛卡尔积与关系', /笛卡尔积(?:与关系)?|直积集合|\bCartesian products?\b/gi,
            '用两个小集合列出笛卡尔积中的全部有序对，再交换集合顺序比较。',
            '逐对核对第一、第二分量的所属集合，并用两个集合大小的乘积检查是否漏列或重复。'],
        ['关系性质', /关系性质|二元关系|二项关系|自反性|反自反性|对称性|反对称性|传递性|关系(?:的)?(?:自反|对称|传递|反对称)|(?:离散数学|数学)(?:中|中的|里|里的)?[，,：:\s]*(?:什么是|解释(?:一下)?|(?:怎么|如何)理解)关系|(?:什么是|解释(?:一下)?|(?:怎么|如何)理解)(?:离散数学|数学)(?:中|中的|里|里的)?的?关系|\bbinary relations?\b/gi,
            '选一个关系性质，先写出它的定义，再逐项验证或寻找一个反例。',
            '反例必须属于给定集合并满足定义中的前提；区分“不对称”和“反对称”。'],
        ['幂集与子集', /幂集(?:与子集)?|子集|\bpower sets?\b|\bsubsets?\b/gi,
            '选一个小的有限集合，按子集大小列出它的全部子集，并把这些子集组成幂集。',
            '核对每个候选的元素都属于原集合，没有重复，且包含空集和原集合；原集合有 n 个元素时应有 2 的 n 次方个子集。若题目要求真子集，再排除原集合。'],
        ['集合运算', /集合运算|集合恒等式|集合(?:的)?(?:并|交|差|补)|并集|交集|差集|补集|集合(?:的)?(?:定义|性质|习题|练习|题目)|(?:什么是|解释(?:一下)?|(?:怎么|如何)理解)集合(?!按钮|菜单|界面|模块|接口|代码)|集合是什么|\bset operations?\b/gi,
            '取一个任意元素，把它属于结果集合的条件改写成关于原集合的逻辑条件。',
            '核对交、并、差、补对应的条件，使用补集时明确全集，再用小集合枚举验证。'],
        ['容斥原理', /容斥原理|容斥公式|\binclusion[- ]exclusion\b/gi,
            '先画出涉及集合的交叠区域，再写出每层交集在计数式中的符号。',
            '挑一个同时属于多个集合的元素，检查它在完整公式中是否恰好被计数一次。'],
        ['鸽巢原理', /鸽巢原理|抽屉原理|\bpigeonhole principle\b/gi,
            '明确题目中的对象和抽屉分别是什么，再写出对象数量超过容量的地方。',
            '核对每个对象恰好归入一个抽屉，并区分“至少存在”的结论与具体构造。'],
        ['排列与组合', /排列与组合|排列组合|排列数|组合数|全排列|重复排列|重复组合|二项式定理|二项式系数|\bpermutations?\b|\bcombinations?\b/gi,
            '在选公式前，先写清是否区分顺序、是否允许重复，再列出一个小规模例子。',
            '将枚举数量与公式结果比较，检查同一个结果是否因为不同选取顺序被重复计算。'],
        ['基本计数原理', /基本计数原理|加法原理|乘法原理|计数原理|组合计数|怎么计数|如何计数|计数(?:练习|习题|题目)|\bcounting principles?\b/gi,
            '把计数过程分成互斥的分类或依次完成的步骤，写出每部分的选择数。',
            '分类相加时核对不重不漏，分步相乘时检查后一步选择数是否依赖前一步。'],
        ['最小生成树', /最小生成树|最小支撑树|\bminimum spanning trees?\b|\bKruskal\b|\bPrim\b/gi,
            '在给定带权图上逐步选边构造一棵生成树，并记录每一步为何选这条边。',
            '核对覆盖全部顶点、连通且无环，并检查选边规则；总权值最小与两点间最短路径是不同目标。'],
        ['矩阵树定理', /矩阵树定理|基尔霍夫定理|\bmatrix[- ]tree theorem\b/gi,
            '按题目图类型构造相应拉普拉斯矩阵，再计算一个适用的余子式。',
            '先核对邻接与度数约定；对小图可枚举生成树，比较枚举数量与行列式结果。'],
        ['欧拉图', /欧拉图|欧拉(?:回路|通路|路径)|一笔画|\bEuler(?:ian)? (?:graphs?|circuits?|paths?|trails?)\b/gi,
            '先区分有向图和无向图，写出各顶点的度或入度、出度，再尝试走出一条遍历边的路线。',
            '逐边核对是否每条边恰走一次，回路还须回到起点；使用判定条件时别漏掉相应的连通条件。'],
        ['哈密顿图', /哈密顿(?:图|回路|通路|路径)|汉密尔顿(?:图|回路|通路|路径)|\bHamilton(?:ian)? (?:graphs?|cycles?|paths?)\b/gi,
            '写出一条候选顶点序列，尝试让每个顶点恰好出现一次。',
            '检查相邻顶点间确有允许方向的边；要求回路时还需检查首尾相连，不要套用欧拉图的度数判定。'],
        ['图同构', /图同构|同构图|\bgraph isomorphisms?\b/gi,
            '先比较顶点数、边数和度数，再尝试写出一个完整的顶点对应。',
            '对照每一对顶点检查邻接关系是否被保持；仅有相同度数序列不能证明同构。'],
        ['图的矩阵表示', /图的矩阵表示|邻接矩阵|关联矩阵|可达矩阵|\badjacency matr(?:ix|ices)\b/gi,
            '固定顶点顺序，按所用矩阵的定义写出一行，再从这一行还原对应的图信息。',
            '对照原图核对端点、方向以及自环或重边的约定；使用关联矩阵时还需固定边的顺序。'],
        ['最短路', /最短路(?:径)?|\bshortest paths?\b|\bDijkstra\b|\bBellman[- ]Ford\b/gi,
            '明确起点、终点和边权，用所选算法记录一次距离更新及其来源。',
            '核对方向和候选路线的总权值；使用 Dijkstra 算法前检查是否存在负权边。'],
        ['图着色', /图着色|顶点着色|边着色|色数|\bgraph colo[u]?ring\b/gi,
            '先给小图构造一个合法着色，再尝试减少一种颜色。',
            '按顶点着色或边着色的约束检查相邻对象；构造只给出上界，最少颜色还需要下界依据。'],
        ['图匹配', /图匹配|二部图匹配|二分图匹配|最大匹配|完美匹配|增广路|\bgraph matching\b/gi,
            '选出一组两两不共端点的边，再尝试寻找能增加匹配边数的增广路。',
            '核对每个顶点是否至多属于一条已选边；区分无法直接添边的极大匹配与边数最多的最大匹配。'],
        ['二部图', /二部图|二分图|\bbipartite graphs?\b/gi,
            '从一个顶点开始交替染两种颜色，再检查每个尚未访问的连通分量。',
            '核对每条边是否连接不同颜色；出现冲突时寻找导致冲突的奇环。'],
        ['平面图', /平面图|平面性|多面体欧拉公式|\bplanar graphs?\b/gi,
            '对一个已有平面嵌入的连通图数出顶点、边和面，包含外部面。',
            '检查顶点数减边数加面数是否等于二；公式成立本身不能证明一个任意图是平面图。'],
        ['支配集/覆盖集/独立集', /支配集|顶点覆盖|边覆盖|独立集|独立数|\bvertex cover\b|\bindependent sets?\b/gi,
            '先明确题目要求覆盖的是顶点还是边，或要求选中顶点彼此不相邻，再给出一个候选集合。',
            '按定义逐个检查覆盖或不相邻条件；可行集合只给出一个界，最优性还需要额外依据。'],
        ['拓扑排序', /拓扑排序|拓扑序|有向无环图|\btopological sort\b/gi,
            '从入度为零的顶点开始逐个移除，记录得到的顶点顺序。',
            '核对每条有向边都从序列前方指向后方；若仍有顶点却无法继续，检查是否存在有向环。'],
        ['树的基本性质', /树的基本性质|生成树|根树|二叉树|树的遍历|树的性质|无根树|\bspanning trees?\b|\bbinary trees?\b/gi,
            '在一个小图上检查连通性和是否含环，再数顶点与边。',
            '无向树应连通且无环，并满足边数等于顶点数减一；不能只凭边数就断定为树。'],
        ['路径与连通性', /路径与连通性|图的连通性|连通分量|强连通|弱连通|割点|割边|桥边|\bconnected components?\b/gi,
            '选两个顶点，写出它们之间的一条路径；若不存在，尝试划出它们所在的连通部分。',
            '逐边检查路径有效，有向图要遵守方向，并区分双向可达与忽略方向后的连通。'],
        ['图的基本概念', /图的基本概念|图论|无向图|有向图|简单图|多重图|带权图|顶点(?:的)?度数|入度|出度|\bgraph theory\b/gi,
            '选一个顶点，分别列出它的邻点和关联的边；有向图再分清入边、出边。',
            '回到图中逐条核对端点和方向，遇到自环或重边时按定义计数，避免把邻点数直接当成度数。'],
        ['群与子群', /群与子群|子群|循环群|置换群|阿贝尔群|交换群|群公理|群论|拉格朗日定理|群(?:的)?(?:定义|性质)|\bsubgroups?\b|\bgroup theory\b/gi,
            '针对给定集合和运算，分别检查封闭性、单位元和每个元素的逆元。',
            '还要核对结合律；判断子群时写明所用判定法和非空条件，不能只检查元素属于原群。'],
        ['同态与同构', /同态与同构|群同态|群同构|环同态|环同构|代数同构|同态映射|同态|\bhomomorphisms?\b/gi,
            '写出映射保持运算的等式，再用给定的运算和映射逐项验证。',
            '核对等式两边分别在哪个代数系统计算；要求同构时还必须证明映射是双射。'],
        ['环与域', /环与域|交换环|整环|有限域|域的定义|环的定义|环公理|域公理|\bfinite fields?\b/gi,
            '把两种运算分开，逐条核对题目所用的环或域定义。',
            '特别检查分配律；判断域时检验每个非零元素的乘法逆元，并注明采用的单位元约定。'],
        ['格与布尔代数', /格与布尔代数|布尔代数|布尔格|分配格|有补格|格的定义|\bBoolean algebra\b/gi,
            '对给定偏序中的一对元素，找出它们的上确界与下确界。',
            '核对所选元素确为最小上界与最大下界；判断布尔代数还需逐项检查有界、分配和补的条件。'],
        ['代数系统', /代数系统|代数结构|二元运算|运算封闭性|\balgebraic structures?\b/gi,
            '先写出集合和运算，再用定义检验封闭性并尝试寻找单位元。',
            '核对运算结果仍在集合内；交换律、结合律和逆元需要分别检查，不能由少数例子直接断定。']
    ];

    const fallback = {
        action: '先不看资料，用自己的话写出一个定义，并举一个满足定义的例子。',
        check: '对照原文逐项核对条件，再尝试构造一个缺少其中一项条件的反例。'
    };

    // Complete English suggestions are selected by the same canonical topic.
    // This keeps the evidence/priorities unchanged and never rewrites notes.
    const englishAdvice = {
        '生成函数': ['Write the first few terms of a generating function from the given counts and explain what each coefficient represents.', 'Expand your expression and compare its coefficients with direct counting or the given initial values.'],
        '非齐次递推': ['Separate the homogeneous part from the extra term, then use the initial values to calculate the first three terms.', 'Substitute a candidate formula into both the original recurrence and the initial conditions. Satisfying only the homogeneous part is not enough.'],
        '线性齐次递推': ['Form the characteristic equation and use the initial conditions to determine the constants in the general term.', 'Substitute the result into the recurrence and check every initial value. For repeated roots, include the required polynomial factors.'],
        '初始条件': ['State the first index at which the recurrence applies and list all the initial values it needs.', 'Calculate the first few terms and compare them with the starting cases. Check for missing values and shifted indices.'],
        '递推关系建模': ['Define what each term counts, state the starting cases, and derive a recurrence by classifying the final step.', 'Work out the smallest cases by hand. Check the initial values, indices, and whether the cases overlap or omit possibilities.'],
        '欧拉定理与费马小定理': ['Choose a modular exponentiation example. Check whether the base and modulus are coprime before reducing the exponent.', 'Check the coprimality or prime-modulus assumptions of the theorem, then verify the remainder with a small direct calculation.'],
        'RSA公钥密码': ['Use small teaching examples to calculate an RSA modulus, exponents and keys, then carry out one encryption and decryption by hand.', 'Check the coprimality and modular-inverse conditions and verify that decryption recovers the message. Small teaching parameters are unsuitable for real encryption.'],
        '模逆与中国剩余定理': ['For a modular inverse, first compute the greatest common divisor. For a system of congruences, first examine how the moduli are related.', 'Check a proposed inverse by multiplication modulo the modulus, or substitute a proposed solution into every congruence. Do not apply a coprime-moduli version when its assumptions fail.'],
        '线性同余方程': ['Write the equation as ax congruent to b modulo m and first calculate gcd(a, m).', 'Check whether this greatest common divisor divides b, then substitute every resulting residue class into the original equation.'],
        '最大公因数与欧几里得算法': ['Compute a greatest common divisor with the Euclidean algorithm, keeping each quotient and remainder.', 'Check each remainder and the final nonzero remainder. If integer coefficients are needed, back-substitute and verify the Bézout identity.'],
        '同余与模运算': ['Rewrite a congruence as a divisibility statement, then independently calculate the remainders on both sides.', 'Check that the modulus is the same. Before canceling a factor, verify that it is invertible modulo that modulus.'],
        '整除与素数': ['Rewrite the divisibility condition as an integer-multiple relation, or find the prime factorization of the given integer.', 'Check that the multiplier is an integer, and multiply the prime factors back together to recover the original number.'],
        '数学归纳法': ['Write only the base case, induction hypothesis and next step to prove, and mark where you use the hypothesis.', 'Check that the base cases cover the required range, the hypothesis is used only at allowed indices, and the next step does not assume the conclusion.'],
        '直接证明与反证法': ['Separate the assumptions from the conclusion, then choose a direct proof, a contrapositive proof or a proof by contradiction.', 'Name the definition or theorem used at each step. In a contradiction proof, negate the actual conclusion and avoid circular reasoning.'],
        '量词推理与否定': ['State the domain, then fully negate one statement containing quantifiers.', 'Check that universal and existential quantifiers are exchanged, the inner predicate is negated, and variable scopes are correct.'],
        '量词': ['Choose a statement containing “every” or “there exists,” state its domain, and write it using quantifiers.', 'Verify it on a small domain. With several quantifiers, check whether changing their order changes the meaning.'],
        '范式': ['Build the truth table, then construct the required normal form from the true or false rows.', 'Check the result against every row. Each term in a canonical normal form should contain all the propositional variables.'],
        '逻辑等价': ['Name the equivalence law used at each transformation, or independently build truth tables for both sides.', 'Check that both sides have the same truth value for every assignment. Pay special attention to parentheses, negation and the direction of implication.'],
        '真值表': ['Choose a compound proposition with an implication. Identify the assignments that make it false, then complete its truth table.', 'Check that every variable assignment appears exactly once, and distinguish the original statement, its converse and its contrapositive.'],
        '命题推理': ['Separate the premises from the conclusion and look for an assignment where all premises are true but the conclusion is false.', 'Such an assignment disproves validity. If you do not find one, you still need a complete truth table or valid inference steps.'],
        '单射满射双射': ['State the domain and codomain. Check whether two different inputs share an output and whether any codomain element has no preimage.', 'Use the definitions to test injectivity and surjectivity separately. A bijection needs both, and the answer depends on the codomain.'],
        '复合函数': ['Choose a valid input and evaluate a composition from the inner function to the outer function.', 'Check that the inner output belongs to the outer domain and that the order is correct. Functions cannot generally be interchanged.'],
        '逆函数': ['State the domain and codomain of the original function and first decide whether it has an inverse.', 'Check that both compositions with a proposed inverse are identity maps, using the correct domains.'],
        '函数与映射': ['State the domain and codomain, then examine the output assigned to each input.', 'Check that each input has exactly one output, and distinguish the actual image from the specified codomain.'],
        '等价关系与划分': ['On a small set, verify reflexivity, symmetry and transitivity before finding the equivalence class of one element.', 'Check that the classes are nonempty, disjoint and cover the original set. Do not treat a relation as an equivalence relation before verifying all three properties.'],
        '偏序关系': ['Draw a Hasse diagram for a small partially ordered set and decide whether a chosen element is maximal or minimal.', 'Check reflexivity, antisymmetry and transitivity. Distinguish “no larger element” from “greater than or equal to every element.”'],
        '关系闭包': ['Starting from the original relation, add only the ordered pairs needed for the required closure property.', 'Check that the original relation is contained, the target property holds, and each added pair follows from a rule or a chain of related elements.'],
        '关系运算': ['Write the definition of the relation operation, then justify whether a chosen ordered pair belongs to the result.', 'For composition, check the intermediate element and the order convention. For an inverse relation, check that each pair has been reversed.'],
        '笛卡尔积与关系': ['List every ordered pair in the Cartesian product of two small sets, then reverse the set order and compare.', 'Check which set each component belongs to. Use the product of the set sizes to check for missing or repeated pairs.'],
        '关系性质': ['Choose a property of a relation, state its definition, and verify it or find a counterexample.', 'A counterexample must lie in the given set and satisfy the premise of the definition. Distinguish “not symmetric” from “antisymmetric.”'],
        '幂集与子集': ['List all subsets of a small finite set by their sizes, then collect them into the power set.', 'Check membership and duplicates, including the empty set and the whole set. A set with n elements has 2 to the power n subsets. Exclude the whole set if proper subsets are required.'],
        '集合运算': ['Take an arbitrary element and express membership in the result as logical conditions on membership in the original sets.', 'Check the conditions for intersection, union, difference and complement. Specify the universal set for complements, then verify with small examples.'],
        '容斥原理': ['Draw the overlapping regions of the sets and write the sign for each level of intersection in the counting formula.', 'Choose an element belonging to several sets and check that the complete formula counts it exactly once.'],
        '鸽巢原理': ['Identify the objects and the boxes, then state where the number of objects exceeds the available capacity.', 'Check that each object enters exactly one box. Distinguish an existence guarantee from an explicit construction.'],
        '排列与组合': ['Before choosing a formula, state whether order matters and repetition is allowed, then list a small example.', 'Compare enumeration with the formula and check whether different selection orders count the same outcome more than once.'],
        '基本计数原理': ['Split the count into mutually exclusive cases or successive steps, and state the number of choices in each part.', 'For addition, check that the cases are disjoint and exhaustive. For multiplication, check whether later choices depend on earlier ones.'],
        '最小生成树': ['Construct a spanning tree of the weighted graph one edge at a time and record why each edge is chosen.', 'Check that it spans all vertices, is connected and has no cycle, then verify the edge-selection rule. Minimizing total tree weight differs from finding a shortest path.'],
        '矩阵树定理': ['Construct the appropriate Laplacian matrix for the type of graph and calculate an applicable cofactor.', 'Check the adjacency and degree conventions first. On a small graph, enumerate spanning trees and compare the count with the determinant.'],
        '欧拉图': ['First distinguish directed and undirected graphs. List degrees or in-degrees and out-degrees, then try to trace a route through the edges.', 'Check that each edge is used exactly once, and that a circuit returns to its start. Include the required connectivity condition when applying a criterion.'],
        '哈密顿图': ['Write a candidate vertex sequence that visits every vertex exactly once.', 'Check that consecutive vertices are joined by edges in an allowed direction. For a cycle, also check the closing edge. Eulerian degree criteria do not decide Hamiltonicity.'],
        '图同构': ['Compare vertex counts, edge counts and degrees, then try to give a complete correspondence between the vertices.', 'Check that the correspondence preserves adjacency for every pair. Equal degree sequences alone do not prove isomorphism.'],
        '图的矩阵表示': ['Fix a vertex order, write one row according to the matrix definition, and reconstruct the corresponding graph information from it.', 'Check endpoints, directions, loops and parallel-edge conventions against the graph. For an incidence matrix, also fix an edge order.'],
        '最短路': ['State the start, destination and edge weights, then record one distance update and its source using the chosen algorithm.', 'Check edge directions and total route weights. Before using Dijkstra’s algorithm, check for negative-weight edges.'],
        '图着色': ['Construct a valid coloring of a small graph, then try to use one fewer color.', 'Check the appropriate adjacency constraints for vertex or edge coloring. A construction gives an upper bound; proving the minimum also needs a lower bound.'],
        '图匹配': ['Choose edges with no shared endpoints, then look for an augmenting path that increases the matching size.', 'Check that each vertex belongs to at most one selected edge. Distinguish a maximal matching from a maximum matching.'],
        '二部图': ['Starting from one vertex, assign two colors alternately, then repeat for every unvisited component.', 'Check that each edge joins different colors. If a conflict occurs, find an odd cycle that explains it.'],
        '平面图': ['For a connected graph with an existing planar embedding, count the vertices, edges and faces, including the outer face.', 'Check that vertices minus edges plus faces equals two. Satisfying this equation alone does not prove that an arbitrary graph is planar.'],
        '支配集/覆盖集/独立集': ['Clarify whether vertices or edges must be covered, or whether selected vertices must be pairwise nonadjacent, then propose a set.', 'Check each condition from the definition. A feasible set gives only a bound; optimality needs additional justification.'],
        '拓扑排序': ['Repeatedly remove a vertex of in-degree zero and record the resulting order.', 'Check that every directed edge goes forward in the order. If vertices remain but no step is possible, look for a directed cycle.'],
        '树的基本性质': ['Check whether a small graph is connected and acyclic, then count its vertices and edges.', 'An undirected tree is connected and acyclic and has one fewer edge than vertices. Edge count alone does not establish that a graph is a tree.'],
        '路径与连通性': ['Choose two vertices and write a path between them. If none exists, try to separate their connected parts.', 'Verify every edge of the path. In a directed graph, respect directions and distinguish mutual reachability from connectivity after ignoring directions.'],
        '图的基本概念': ['Choose a vertex and separately list its neighbors and incident edges. In a directed graph, distinguish incoming and outgoing edges.', 'Check endpoints and directions against the graph. Apply the definitions to loops and parallel edges instead of assuming the number of neighbors is the degree.'],
        '群与子群': ['For the given set and operation, check closure, an identity element and an inverse for every element.', 'Also verify associativity. For a subgroup, state the criterion and nonemptiness condition; membership in the original group alone is insufficient.'],
        '同态与同构': ['Write the equation expressing preservation of the operation, then verify it using the specified map and operations.', 'Check which algebraic system each side is calculated in. An isomorphism must also be proved bijective.'],
        '环与域': ['Separate the two operations and check the exact definition of a ring or field being used.', 'Pay particular attention to distributivity. For a field, check multiplicative inverses of nonzero elements and state the identity-element convention.'],
        '格与布尔代数': ['For two elements of the given partially ordered set, find their least upper bound and greatest lower bound.', 'Verify leastness and greatestness. A Boolean algebra also requires the relevant bounds, distributivity and complements.'],
        '代数系统': ['State the set and operation, check closure from the definition, and try to find an identity element.', 'Check that outputs remain in the set. Commutativity, associativity and inverses must be tested separately; a few examples cannot establish them.']
    };
    const englishFallback = {
        action: 'Without looking at your materials, state a definition in your own words and give an example that satisfies it.',
        check: 'Compare every condition with the source, then try to construct a counterexample that omits one condition.'
    };

    function topics(value) {
        if (Array.isArray(value)) return [...new Set(value.flatMap(topics))];
        if (typeof value !== 'string' || !value.trim()) return [];
        // Keep code snippets from becoming evidence of mathematics study.
        // Product-operation filtering belongs to the caller; do not classify
        // isolated words such as 图、关系、函数、运算 in the first place.
        let remaining = value.trim().replace(/```[\s\S]*?```|`[^`\n]*`/g, ' ')
            .replace(/(?:平面图|多面体)(?:中|中的|的|里|里的)?\s*[：:]?\s*欧拉(?:定理|公式)/g, '平面图');
        const programming = /\b(?:javascript|typescript|python|java|php|golang|js|ts)\b|编程|函数(?:调用|参数|返回值|按钮|代码)/i.test(remaining);
        const mathematicalFunction = /定义域|陪域|值域|离散数学|数学函数|函数与映射/.test(remaining);
        const found = [];
        for (const rule of rules) {
            if (rule[0] === '函数与映射' && programming && !mathematicalFunction) continue;
            let matched = false;
            remaining = remaining.replace(rule[1], match => {
                matched = true;
                return ' '.repeat(match.length);
            });
            // The English display name is also valid study evidence. Only
            // recognized mathematical phrases are matched, not generic words
            // such as "function" that also occur in product/programming text.
            const englishName = knowledgeLanguage?.labels[rule[0]];
            if (englishName) {
                const pattern = new RegExp('\\b' + englishName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b', 'gi');
                remaining = remaining.replace(pattern, match => {
                    matched = true;
                    return ' '.repeat(match.length);
                });
            }
            if (matched) found.push(rule[0]);
        }
        return found;
    }

    function advice(topic, language) {
        const value = typeof topic === 'string' ? topic.trim() : '';
        const name = rules.some(rule => rule[0] === value) ? value : topics(value)[0];
        const selected = language || root.DMateI18n?.getLanguage?.() || 'zh-CN';
        if (selected.startsWith('en')) {
            const pair = englishAdvice[name];
            return pair ? { action: pair[0], check: pair[1] } : { ...englishFallback };
        }
        const rule = rules.find(candidate => candidate[0] === name);
        return rule ? { action: rule[2], check: rule[3] } : { ...fallback };
    }

    const api = { topics, advice };
    root.DMateLearningReviewGuidance = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
