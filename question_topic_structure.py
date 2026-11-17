"""Conservative mathematical task features mapped to the existing topic IDs.

These recognizers describe families of questions, not example answers. They do
not read the course graph's prerequisite links and do not choose optional proof
methods. Semantic classification can review tasks beyond this local coverage.
"""
from __future__ import annotations

import re
import unicodedata
from fractions import Fraction


_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉₊₋ₙᵢⱼₖ", "0123456789+-nijk")
_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ", "0123456789+-n")
_QUANTITY = r"(?:\d+|[一二三四五六七八九十百千万两]+)"


def _linear_recurrence_kind(rhs, symbol):
    """Recognize an explicit affine sum; leave algebraic simplification unknown."""
    parts, start, depth = [], 0, 0
    for index, char in enumerate(rhs):
        if char in "({[":
            depth += 1
        elif char in ")}]":
            depth -= 1
        elif char in "+-" and depth == 0 and index > start:
            parts.append(rhs[start:index])
            start = index
    parts.append(rhs[start:])
    previous = re.escape(symbol) + r"_?\{?n-\d+\}?"
    coefficient_term = re.compile(r"[+-]?(?:\d+(?:\.\d+)?\*?)?" + previous)
    forcing, has_previous = [], False
    for part in parts:
        if coefficient_term.fullmatch(part):
            has_previous = True
        elif re.search(previous, part):
            # Products, variable coefficients and powers need symbolic review.
            return None
        else:
            forcing.append(part)
    if not has_previous:
        return None
    if not forcing:
        return "recurrence_homogeneous"
    if all(re.fullmatch(r"[+-]?\d+(?:\.\d+)?", part) for part in forcing):
        if len(forcing) > 32 or any(len(part) > 64 for part in forcing):
            return None
        return "recurrence_homogeneous" if sum(Fraction(part) for part in forcing) == 0 else "recurrence_nonhomogeneous"
    if len(forcing) == 1 and re.fullmatch(r"[+-]?(?:\d+\*?)?n(?:\^\{?\d+\}?)?", forcing[0]):
        return "recurrence_nonhomogeneous"
    return None


def mathematical_text(text):
    """Retain subscript and power meaning before compatibility normalization."""
    value = re.sub(r"([A-Za-z])([₀₁₂₃₄₅₆₇₈₉₊₋ₙᵢⱼₖ]+)",
                   lambda match: match[1] + "_{" + match[2].translate(_SUBSCRIPTS) + "}", str(text or ""))
    value = re.sub(r"([A-Za-z])([⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ]+)",
                   lambda match: match[1] + "^{" + match[2].translate(_SUPERSCRIPTS) + "}", value)
    value = unicodedata.normalize("NFKC", value).lower()
    value = value.replace("−", "-").replace("–", "-")
    value = re.sub(r"([aft])_\((n(?:[-+]\d+)?)\)", r"\1_{\2}", value)
    for old, new in ((r"\forall", "∀"), (r"\exists", "∃"), (r"\land", "∧"),
                     (r"\lor", "∨"), (r"\neg", "¬"), (r"\lnot", "¬"),
                     (r"\implies", "⇒"), (r"\equiv", "≡"), (r"\pmod", "mod"),
                     (r"\bmod", "mod"), (r"\mathbb", ""), (r"\left", ""), (r"\right", "")):
        value = value.replace(old, new)
    return re.sub(r"\s+", "", value).replace("−", "-").replace("–", "-")


def _binary_table_shape(value):
    """Read a bounded rectangular 0/1 literal without executing expressions."""
    literal = re.search(r"\[\[[01](?:,[01])*\](?:,\[[01](?:,[01])*\])*\]", value)
    if not literal or len(literal[0]) > 8192:
        return None
    rows = re.findall(r"\[([01](?:,[01])*)\]", literal[0])
    columns = len(rows[0].split(","))
    if len(rows) < 2 or columns < 2 or len(rows) > 64 or columns > 64 \
            or any(len(row.split(",")) != columns for row in rows):
        return None
    return len(rows), columns


def _directed_transitivity(value):
    """The same three vertices must occur in all three directed predicates."""
    if re.search(r"([a-z])(?:能|可)?直接(?:到|连向|通向)([a-z]).{0,8}"
                 r"\2(?:能|可)?直接(?:到|连向|通向)([a-z]).{0,16}"
                 r"\1(?:也|就|必须|应当)?(?:能|可)?直接(?:到|连向|通向)\3", value):
        return True
    if re.search(r"([a-z])→([a-z]).{0,8}\2→([a-z]).{0,16}"
                 r"(?:⇒|推出|保证|then|implies).{0,8}\1→\3", value):
        return True
    return bool(re.search(r"\(([a-z]),([a-z])\).{0,15}\(\2,([a-z])\).{0,25}"
                          r"(?:⇒|推出|保证|也在|都在|包含|in|then|implies).{0,12}\(\1,\3\)", value))


def structural_topic_ids(text):
    """Recognize explicit mathematical tasks without requiring their topic names."""
    value = mathematical_text(text)
    topics = set()
    has = lambda pattern: bool(re.search(pattern, value, re.I))

    # A finite choice can be described by people/items rather than C(n,k).
    choice = has(_QUANTITY + r"(?:名|位|个|件|本|种|人|枚|只|辆|门|球|学生|同学)"
                 r"[^。；;!?]{0,28}?(?:选(?:出|取)?|挑(?:出|选)?|取(?:出)?|抽(?:出|取)?)"
                 + _QUANTITY + r"(?:名|位|个|件|本|种|人|枚|只|辆|门|球)?|(?:choose|select|pick)\d+(?:of|from|outof)\d+")
    counting_goal = has(r"多少(?:种|个|套)|几种|不同(?:选法|取法|排法|结果|方式|方案)|共有.{0,12}种|种(?:选法|取法|排法)|howmany|numberofways|countthe")
    if choice and counting_goal:
        topics.add("count_perm_comb")
        if has(r"再(?:从|选|指定|安排)|随后|接着|分别担任|指定.{0,12}(?:长|职务)|先.{0,30}再|captain|leader|president"):
            topics.add("count_basic")
    if counting_goal and has(r"排成|排成一列|不同座次|围成一圈|担任.{0,12}(?:职务|职位)|安排.{0,12}(?:座位|岗位)"):
        topics.add("count_perm_comb")
    if counting_goal and len(re.findall(r"\d+", value)) >= 3 and has(r"students?|学生|班级|人数") \
            and has(r"both|同时|两者都") and has(r"neither|atleastone|doublecount|至少一种|都不"):
        topics.add("count_inclusion")

    # Truth-functional comparison and quantified translation are different tasks.
    logic_formula = has(r"[∧∨¬↔⇒⇔]|[pqr](?:→|->)[pqr]") and has(r"(?<![a-z])[pqr](?![a-z(])")
    if logic_formula:
        topics.add("logic_connectives")
        if has(r"(?:真假|真值|真假值).{0,18}(?:相同|一致)|(?:相同|一致).{0,18}(?:真假|真值)|同真同假|等价|等值|↔|⇔|same(?:truth)?value|equivalent|改写|化为"):
            topics.add("logic_equivalence")
        if has(r"[pqr](?:为|是)真|[pqr](?:为|是)假|[pqr]is(?:true|false)"):
            topics.add("logic_truth")
        if has(r"改写|化为|变为|写成") and has(r"(?:合取|析取).{0,35}(?:文字|子句)|(?:文字|子句).{0,35}(?:合取|析取)"):
            topics.add("logic_normal_form")
    quantified = has(r"∀|∃") or (has(r"每个|任意|所有|任何") and has(r"存在|至少一个|都.{0,5}一个"))
    formal_logic_goal = has(r"符号(?:表达式|化|形式|表示)|写成.{0,8}(?:公式|符号)|否定号|量词|谓词")
    if quantified and formal_logic_goal:
        topics.add("predicate_quantifier")
        if has(r"否定|否定号|等价|推出|推理"):
            topics.add("predicate_reasoning")
    if quantified and has(r"(?:符号|量词|∀|∃).{0,20}(?:最前|前面)|(?:最前|前面).{0,20}(?:符号|量词|∀|∃)|prenex"):
        topics.update(("predicate_quantifier", "predicate_reasoning", "predicate_prenex"))
        if has(r"变元|variable|变量"):
            topics.add("predicate_variable")
    if quantified and has(r"自由|约束|辖域|occurrence|outsideassignment|controlledbyaquantifying"):
        topics.add("predicate_variable")
    if quantified and has(r"论域|个体域|rangeover|allowedobjects|domain") and has(r"选择|改变|比较|changes|truewhen|范围|对象"):
        topics.add("predicate_domain")

    # Required proof steps identify the proof method independently of theorem.
    if has(r"直接从|直接证明|directproof") and has(r"证明|prove|show"):
        topics.add("proof_direct_contradiction")
    if has(r"n=1") and has(r"n=k") and has(r"n=k\+1") and has(r"假定|假设|assume"):
        topics.add("proof_induction")
    if has(r"(?:所有|每个|every|all).{0,35}(?:m|k).{0,25}(?:<n|小于n)") and has(r"假定|假设|assume|known|earlierstatements"):
        topics.add("proof_strong_induction")
    if has(r"奇整数|偶整数|奇数|偶数|prime|primes|整除|素数|质数") and has(r"证明|prove|show"):
        topics.add("number_prime")

    # Formula definitions of reflexivity/symmetry/transitivity and their classes.
    relational = unicodedata.normalize("NFKC", str(text)).lower()
    relation_has = lambda pattern: bool(re.search(pattern, relational, re.I))
    reflexive = relation_has(r"(?<![a-z])([a-z])\s*r\s*\1(?![a-z])")
    symmetric = relation_has(r"(?<![a-z])([a-z])\s*r\s*([a-z])(?![a-z]).{0,24}(?:推出|蕴含|⇒|→|有|得).{0,6}\2\s*r\s*\1(?![a-z])")
    transitive = relation_has(r"(?<![a-z])([a-z])\s*r\s*([a-z])(?![a-z]).{0,12}\2\s*r\s*([a-z])(?![a-z]).{0,24}(?:推出|蕴含|⇒|→|有|得).{0,6}\1\s*r\s*\3(?![a-z])")
    if reflexive or symmetric or transitive:
        topics.add("relation_property")
    if reflexive and symmetric and transitive and has(r"等价类|形成.{0,12}集合|分别满足r|分类|划分|满足r.{0,20}集合"):
        topics.add("relation_equivalence")
    if has(r"s∘r|r∘s|r⁻¹|r\^-1|r\^\{-1\}") and has(r"配对|有序对|orderedpair|关系|subsets"):
        topics.add("relation_operation")
    if has(r"添加配对|加入.{0,10}配对|添加.{0,5}有序对") and has(r"\(a,b\).{0,15}\(b,c\).{0,20}\(a,c\)"):
        topics.update(("relation_closure", "relation_property"))

    # Ask uniqueness and coverage of a mapping, even without saying injective.
    function = has(r"[fgh]:.{0,20}(?:→|\\to|\\rightarrow)|[fgh]\([a-z]\)=|从.{0,24}(?:映到|映入|映至)")
    uniqueness = has(r"不同.{0,8}(?:输入|原像|自变量).{0,16}相同.{0,8}(?:输出|像|函数值)|"
                     r"相同.{0,8}(?:输出|像|函数值).{0,14}不同.{0,8}(?:输入|原像)|唯一原像|"
                     r"f\([a-z]\)=f\([a-z]\).{0,15}[a-z]=[a-z]|distinctinputs.{0,18}sameoutput|one-to-one")
    coverage = has(r"(?:每个|每一个|所有|任意).{0,20}(?:输出|像|原像|取到)|"
                   r"(?:非负整数|陪域|目标集合).{0,18}(?:每个|每一个).{0,15}(?:输出|像|取到)|every.{0,20}target.{0,20}(?:reached|reach)")
    function = function or has(r"(?:φ|ϕ).{0,10}(?:send|map)|机器.{0,10}(?:输入|输出)|machinesends")
    if function:
        if has(r"[fgh]:|从.{0,24}(?:映到|映入|映至)|输入|输出|定义域|陪域|值域|inputs?|outputs?|domain|targetset"):
            topics.add("function_mapping")
        if uniqueness or coverage or has(r"单射|满射|双射|一一对应"):
            topics.add("function_injection")
    if has(r"对应表|每个.{0,16}元素.{0,16}唯一指定.{0,10}输出"):
        topics.add("function_mapping")
    if has(r"[fgh]\([fgh]\([a-z]\)\)"):
        topics.add("function_composition")
    if has(r"恢复.{0,10}输入|recovers?.{0,8}(?:x|input)|recover.{0,10}fromeveryoutput"):
        topics.add("function_inverse")
        if has(r"[fgh]\([^)]*\)=x|[fgh]\([^)]*\).{0,6}=y"):
            topics.add("function_composition")

    if has(r"(?:同时|都).{0,10}整除.{0,45}最大(?:的)?(?:正)?整数|最大(?:的)?(?:正)?整数.{0,35}(?:同时|都).{0,8}整除|"
           r"(?:公因子|公约数|公因数).{0,12}(?:最大|最高)"):
        topics.add("number_gcd")
    integer_divisibility = has(r"(?:[a-z](?:-[a-z])?|\d+)(?:能|可)?被\d+整除|"
                              r"(?<![a-z])[a-z](?:整除|\|)[a-z](?![a-z])")
    numeric_divisor_goal = has(r"求|计算|找出|find|compute") and has(r"最大公因数|最大公约数|公因子|公因数|同时.{0,8}整除") \
        and len(re.findall(r"\d+", value)) >= 2
    if integer_divisibility or numeric_divisor_goal:
        topics.add("number_prime")
    linear_unknown = has(r"\d+[xyz](?:≡|除以)|\d+[xyz].{0,5}(?:mod|模)|dividing\d+[xyz]by\d+")
    remainder = has(r"≡|除以.{0,12}(?:余数|余\d+)|mod|模|remainder")
    if linear_unknown and remainder and has(r"求|解|所有|全部|整数|find|integer|solve"):
        topics.update(("number_congruence", "number_linear_congruence"))
    # A declared scalar can be the coefficient of an unknown, e.g. t=7 and
    # tu ≡ 1 mod m. Resolve that role from the declaration and constraint;
    # never infer it merely from an isolated two-letter word.
    declared = {match[1] for match in re.finditer(r"(?<![a-z])([a-z])=[+-]?\d+(?![a-z])", value)}
    if declared and remainder and has(r"求|找|解|find|solve|integer|整数"):
        for coefficient in declared:
            products = re.finditer(r"(?<![a-z])(?:" + re.escape(coefficient) + r"\*?([a-z])|([a-z])\*?"
                                   + re.escape(coefficient) + r")(?![a-z])(?=.{0,24}(?:≡|除以|mod|模|remainder))", value)
            if any((match[1] or match[2]) not in declared and (match[1] or match[2]) != coefficient for match in products):
                topics.update(("number_congruence", "number_linear_congruence"))
                break
    if has(r"modulo\d+|remainderclass|每\d+件一组余\d+件"):
        topics.add("number_congruence")
    if len(re.findall(r"每\d+件一组余\d+件", value)) >= 2:
        topics.add("number_inverse_crt")
    if has(r"a\^\{?\d+\}?≡1") and has(r"mod|模") and has(r"anyinteger|任意整数|任何整数|所有整数"):
        topics.add("number_euler_fermat")

    # Every edge once vs every vertex once are separate graph problems.
    edge_once = has(r"每(?:一)?条(?:边|道路|路段|线段).{0,12}(?:恰好|正好|只)?(?:走|经过|通过|画|使用).{0,6}(?:一|1)次|"
                    r"(?:一次|一笔).{0,10}(?:走遍|经过|画完).{0,10}(?:所有|全部)?(?:边|道路|线段)")
    if edge_once:
        topics.add("graph_euler")
    if has(r"每(?:一)?个(?:顶点|站点|城市|地点).{0,12}(?:恰好|正好|只)?(?:走|经过|访问).{0,6}(?:一|1)次|(?:each|every)vertexexactlyonce"):
        topics.add("graph_hamilton")
    connected = has(r"连通|任意两.{0,8}(?:能|可).{0,8}(?:到达|抵达|相通|达)|(?:所有|全部).{0,10}(?:互通|相通)")
    acyclic = has(r"无环|无圈|不含.{0,3}(?:环|圈)|不存在.{0,5}(?:简单环|圈)|没有简单圈")
    if connected and acyclic:
        topics.add("tree_basic")
        if has(r"为根|根后|根节点|父亲|父节点"):
            topics.add("tree_rooted")
    weighted_minimum = has(r"权值|边权|费用|成本|代价") and has(r"总.{0,10}(?:最小|最低|最少)|之和最小")
    explicit_cost = has(r"费用|成本|代价") and not has(r"[=:]-\d+")
    if connected and weighted_minimum and (acyclic or explicit_cost or has(r"生成树|(?:正|非负).{0,5}(?:权|费用)|权.{0,8}(?:正|非负)")):
        topics.update(("tree_mst", "tree_spanning", "graph_weighted"))
    if has(r"耗时|时间为|cost|travel\s*time") and has(r"最少.{0,8}(?:路线|时间)|耗时最少|minimumtime|shortest"):
        topics.update(("graph_shortest", "graph_weighted"))
    if has(r"workers?|工人|职工") and has(r"jobs?|工作|任务") and has(r"(?:no|without).{0,16}(?:twice|repeat)|不重复|不同.{0,6}工作|distinctjobs"):
        topics.update(("graph_bipartite", "graph_matching"))
    if has(r"完成后才能|先后要求|prerequisite|mustprecede") and has(r"顺序|order|次序"):
        topics.add("graph_topological")
    if has(r"0-1表|表中1表示.{0,12}相连|矩阵.{0,12}对应.{0,12}相连"):
        topics.update(("graph_adjacency", "graph_matrix"))
    table_shape = _binary_table_shape(value)
    directed_entry = has(r"第?([a-z])行(?:[、，,和与])?(?:第)?([a-z])列.{0,12}(?:为|是|等于)1.{0,12}"
                         r"(?:表示|意味着|对应)\1(?:能|可)?(?:直接)?(?:连向|连接到|连到|到达|到|指向)\2|"
                         r"row([a-z])(?:,|and)?column([a-z]).{0,12}(?:is|equals?)1.{0,12}"
                         r"(?:means|iff|represents)\1(?:is)?(?:directly)?(?:connectedto|connectsto|joinedto|reaches)\2")
    if table_shape and directed_entry:
        topics.add("graph_matrix")
        if table_shape[0] == table_shape[1]:
            topics.add("graph_adjacency")
        matrix_product = has(r"[a-z]\^\{?\d+\}?|自身相乘|普通整数乘加|矩阵乘法|matrixmultiplication|integerproducts")
        positive_boolean = has(r"(?:正数|正值|大于0|>0).{0,10}(?:改|变|置|设|替换).{0,5}1|"
                               r"(?:replace|set|change).{0,12}positive.{0,12}(?:ones|1)")
        walk_meaning = has(r"路线|通路|路径|可达|到达|walk|route|reachability")
        if matrix_product and positive_boolean and walk_meaning:
            topics.add("graph_connectivity")
    transitive_task = _directed_transitivity(value)
    if transitive_task:
        topics.add("relation_property")
        monotone_extension = has(r"(?:0|零).{0,5}(?:改|变|置|替换).{0,5}(?:1|一)|添加|加入|补充|add|change.{0,5}0.{0,5}1")
        least_extension = has(r"只许|只允许|只能|最少|至少|不许删除|minimum|least|only|withoutremov")
        if monotone_extension and least_extension:
            topics.add("relation_closure")
    if has(r"相连当且仅当.{0,12}相连|adjacentifandonlyif") and has(r"一一对应|bijection|对应"):
        topics.add("graph_isomorphism")

    # Recognize recurrence notation before Unicode subscripts lose their role.
    term = r"[aft]_?\{?n(?:-\d+)?\}?"
    equation = re.search(r"([aft])_?\{?n\}?=([a-z0-9_{}+*/^().-]+)", value)
    supplied_recurrence = False
    if equation and re.search(term.replace("[aft]", re.escape(equation[1])) + r"", equation[2]):
        supplied_recurrence = True
        rhs = re.sub(r"for[a-z]$", "", equation[2])
        kind = _linear_recurrence_kind(rhs, equation[1])
        if kind:
            topics.add(kind)
    binary_string = has(r"二进制.{0,8}串|01串|0[、,和与或-]?1字符串|0[、,和与或-]?1.{0,5}串")
    forbidden_adjacency = has(r"(?:没有|不能|不含|不出现|禁止|不允许).{0,18}(?:相邻|连续)|(?:相邻|连续).{0,12}(?:不|没有)")
    model_goal = has(r"建立|建模|(?:求|写出|建立|推导).{0,8}(?:递推式|递归式)(?!的?(?:通项|解))|用.{0,20}(?:前面|较短|之前|前几|前一).{0,18}(?:数量|表示|项)|根据末尾|按末尾")
    if (binary_string and forbidden_adjacency and model_goal) or (model_goal and has(r"数列|数量|个数|串|方案")):
        topics.add("recurrence_model")
        if binary_string:
            topics.add("count_basic")
    initials = has(r"[aft]_?\{?[01]\}?=|最初.{0,6}(?:值|项)|初始|初值|起始.{0,6}值|空串")
    if initials and (supplied_recurrence or "recurrence_model" in topics):
        topics.add("recurrence_initial")
    if has(r"形式幂级数|formalseries|Σ.{0,20}[aft]_?\{?n\}?[a-z]|∑.{0,20}[aft]_?\{?n\}?[a-z]") and has(r"系数|coefficient|求和|sumover"):
        topics.add("count_generating")
    if has(r"\(1\+[a-z]\)\^\{?\d+\}?") and has(r"系数|coefficient|展开"):
        topics.add("count_binomial")

    # A binary operation with the group axioms is algebra, even if defined mod m.
    operation = has(r"[abc]\s*[∘*·]\s*[abc]|二元运算|规定.{0,12}(?:运算|[abc]\*)")
    associative = has(r"结合律|\(a\*b\)\*c=a\*\(b\*c\)")
    identity = has(r"单位元|e\*a=a\*e=a|e∘a=a∘e=a")
    inverses = has(r"逆元|a\*b=b\*a=e|a∘b=b∘a=e")
    if operation and (associative or identity or inverses):
        topics.add("algebra_system")
        if associative and identity and inverses:
            topics.add("algebra_group")
    finite_operation_table = has(r"operationtable|cayleytable|运算表") \
        and has(r"write|complete|construct|give|写出|补全|构造|列出") \
        and has(r"(?:on|在|集合|于)[a-z]?=\{[^{}]+\}|[a-z]=\{[^{}]+\}") \
        and not has(r"may(?:write|complete)|couldwrite|optionaloperationtable|ifyou(?:wish|want)|(?:可选|可以).{0,15}运算表")
    if finite_operation_table:
        topics.add("algebra_system")
    if has(r"加法|addition") and has(r"乘法|multiplication") and has(r"分配|distribut|非零.{0,20}(?:逆元|除数)"):
        topics.add("algebra_ring_field")
    if has(r"(?:φ|ϕ|f)\(a\+b\)=(?:φ|ϕ|f)\(a\)\+(?:φ|ϕ|f)\(b\)"):
        topics.add("algebra_homomorphism")
    if has(r"上界|下界|upperbound|lowerbound") and has(r"补集|complement") and has(r"全部子集|幂集|powerset|交|并"):
        topics.add("algebra_lattice_bool")
    return topics
