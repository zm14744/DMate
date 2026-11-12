#!/usr/bin/env python3
"""Check authored offline answers against independent arithmetic/graph oracles.

The audited full stems are fixed below. A changed stem must be reviewed before
updating its parameters and oracle; this is not a claim of teacher review.
Defaults read the repository's final offline-content packs. During authoring,
repeat --questions/--concepts to merge external fragments without writing files.
Uses only the Python standard library, performs no network or model calls.
"""
import argparse
import ast
import copy
from fractions import Fraction
import itertools
import json
import math
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = {}
CONCEPTS = {}
STEMS = {
    'q_number_prime_01': '下列正整数中，哪一个是素数？',
    'q_number_rsa_02': '玩具RSA取p=5、q=11、e=3，消息m=7。求满足0<d<40的私有指数d、密文c，并核对解密结果。此例仅用于模运算教学，不是安全加密参数。',
    'q_number_linear_congruence_02': '求6x≡8(mod 14)的全部模14余数解，要求代表元在0至13之间。',
    'q_number_linear_congruence_05': '对同余方程8x≡b(mod12)，下列哪些b值会使方程可解？',
    'q_number_inverse_crt_02': '求x≡1(mod 4)、x≡2(mod 7)、x≡3(mod 9)的最小非负解及全部整数解。',
    'q_number_inverse_crt_03': '方程组x≡1(mod 4)、x≡3(mod 6)的全部整数解应写成哪一种形式？',
    'q_number_inverse_crt_07': '方程组x≡2(mod6)、x≡3(mod9)是否有整数解？说明理由。',
    'q_number_euler_fermat_03': '以下哪些陈述正确？',
    'q_algebra_ring_field_01': '在带单位元的环ℤ₆中，全部乘法可逆元素构成哪个集合？',
    'q_algebra_ring_field_02': '在域ℤ₇中，求3的乘法逆元、商4/3，并求方程x²=1的全部元素解。',
    'q_algebra_lattice_bool_02': '取12的全部正因子组成集合D={1,2,3,4,6,12}，按整除关系排序。求4与6的交、并，并判断元素2是否有补元，由此判断此格是否为布尔代数。',
    'q_algebra_lattice_bool_07': '对6的正因子格L={1,2,3,6}，偏序为整除，列出全部无序补元对，并说明为什么2不是自己的补元。',
    'q_count_perm_comb_02': '某项目有5名工程人员和4名设计人员，所有人均不同。选3人组成不分职务的小组，要求两类人员都至少有1人，求小组数。',
    'q_count_binomial_02': '求 $(2x-3)^6$ 中 $x^4$ 的系数。',
    'q_count_binomial_08': '求 $(1+x)^3(1-x)^4$ 中 $x^5$ 的系数。请说明各因子贡献的次数或给出等价的简化。',
    'q_count_inclusion_02': '100台设备中，属性A、B、C分别有40、35、30台；同时具有A和B的有12台，A和C的有10台，B和C的有9台，三者都有的有4台。两两交集数均包含三者都有的设备。求至少有一种属性、恰有一种属性、三种都没有的台数。',
    'q_count_generating_02': '一种物品有2单位装和3单位装两种包装，每种包装均可使用任意非负个，同规格包装不可区分且不计拿取顺序。恰好组成12单位有多少种方案？请写出生成函数及相应系数。',
    'q_count_generating_06': '求非负整数方程u+v+w=4的解数，其中u≤2、v≤3，w没有额外上界。请建立普通生成函数并计算目标系数。',
    'q_recurrence_nonhomogeneous_03': '求 $a_n=2a_{n-1}+2^n$（n≥1）、$a_0=0$ 的通项公式。说明为什么不能用 $C2^n$ 作为特解。',
    'q_recurrence_homogeneous_03': '求 $a_n=4a_{n-1}-4a_{n-2}$（n≥2）、$a_0=1,a_1=4$ 的通项公式，并说明仅写 $C2^n$ 为什么不够。',
    'q_recurrence_initial_08': '已知 $a_0=2$，且 $a_n=\\frac{n}{n+1}a_{n-1}+\\frac1{n+1}$（n≥1）。令 $b_n=(n+1)a_n$，求b的初值与递推，再求a_n。',
    'q_graph_adjacency_01': '无向简单图的顶点按(a,b,c)排序，边恰为ab、bc。写出邻接矩阵，并由行和求三个顶点的度数。',
    'q_graph_adjacency_03': '无向简单图K₃按(1,2,3)排序，邻接矩阵A=[[0,1,1],[1,0,1],[1,1,0]]。求(A²)₁₂与(A³)₁₁，并解释它们统计的游走。',
    'q_graph_matrix_02': '顶点顺序为(a,b,c)，三条边的选定方向依次为a→b、b→c、a→c。取弧尾−1、弧头+1，故B=[[-1,0,-1],[1,-1,0],[0,1,1]]。计算BBᵀ，并说明把a→c改成c→a后结果是否变化。',
    'q_graph_matrix_03': '无自环有向图只有弧a→b、b→c，顶点顺序为(a,b,c)。分别写出“存在长度至少1的游走”的可达矩阵R，以及“允许长度0的游走”的反身可达矩阵R*。',
    'q_graph_topological_02': '有向图顶点为{a,b,c,d,e}，弧集为{a→c,b→c,b→d,c→e,d→e}。列出全部拓扑序，顶点标号不同的序列视为不同。',
    'q_tree_mst_01': '无向简单三角形顶点为a,b,c，边权w(ab)=−3、w(ac)=1、w(bc)=4。它的最小生成树总权重为多少？',
    'q_tree_mst_02': '连通无向简单图的顶点为{a,b,c,d}，边权为ab:1、ac:4、ad:6、bc:2、bd:5、cd:3。按Kruskal算法求最小生成树，写出加入边的顺序、总权重，并判断最优树是否唯一。',
    'q_tree_mst_07': '四边形a−b−c−d−a的4条边权均为2，另有对角线ac，权为5。求最小生成树总权重和不同最优树的棵数，并解释对角线能否进入最优树。',
    'q_tree_matrix_tree_01': '三角形K₃的拉普拉斯矩阵为[[2,−1,−1],[−1,2,−1],[−1,−1,2]]。按矩阵树定理，它有多少棵生成树？',
    'q_tree_matrix_tree_02': '无向简单图顶点顺序为a,b,c,d，边集为{ab,bc,cd,da,ac}。写出其拉普拉斯矩阵，删除d对应的行列，用矩阵树定理计算生成树数。',
    'q_tree_matrix_tree_07': '无向简单图的边为{ab,bc,ca,cd,de,ec}，即两个三角形仅共享顶点c，没有其他边。删除c对应的拉普拉斯行列，利用分块矩阵求生成树数。',
}


def plain(text):
    return text.replace('−', '-').replace('－', '-')


def integers(text):
    return [int(value) for value in re.findall(r'-?\d+', plain(text))]


def matrices(text):
    return [ast.literal_eval(value) for value in
            re.findall(r'\[\s*\[[\s\S]*?\]\s*\]', plain(text))]


def multiply(a, b):
    return [[sum(x*y for x, y in zip(row, col)) for col in zip(*b)] for row in a]


def determinant(matrix):
    """Leibniz expansion; our cofactors have at most four rows."""
    n = len(matrix)
    total = 0
    for perm in itertools.permutations(range(n)):
        inversions = sum(perm[i] > perm[j] for i in range(n) for j in range(i+1, n))
        total += (-1)**inversions * math.prod(matrix[i][perm[i]] for i in range(n))
    return total


def laplacian(vertices, edges):
    position = {v: i for i, v in enumerate(vertices)}
    result = [[0]*len(vertices) for _ in vertices]
    for u, v, _ in edges:
        i, j = position[u], position[v]
        result[i][i] += 1
        result[j][j] += 1
        result[i][j] -= 1
        result[j][i] -= 1
    return result


def cofactor(matrix, removed):
    return [[value for j, value in enumerate(row) if j != removed]
            for i, row in enumerate(matrix) if i != removed]


def spanning_trees(vertices, edges):
    """Enumerate edge subsets independently of Kruskal and determinants."""
    result = []
    for chosen in itertools.combinations(edges, len(vertices)-1):
        parent = {v: v for v in vertices}
        def find(v):
            while parent[v] != v:
                v = parent[v]
            return v
        for u, v, _ in chosen:
            left, right = find(u), find(v)
            if left == right:
                break
            parent[left] = right
        else:
            if len({find(v) for v in vertices}) == 1:
                result.append((frozenset(u+v for u, v, _ in chosen),
                               sum(w for _, _, w in chosen)))
    return result


class OfflineContentMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = set(STEMS)-set(QUESTIONS)
        if missing:
            raise AssertionError('缺少数学回归所需题目；请先集成完整题库，或重复传入 --questions 指定片段：'
                                 + ', '.join(sorted(missing)))

    def question(self, qid):
        item = QUESTIONS[qid]
        self.assertEqual(item['statement'], STEMS[qid],
                         qid + ' 题干已变化，请重新复核参数与独立算法，不能直接沿用旧答案基准。')
        if CONCEPTS:
            self.assertTrue(all(cid in CONCEPTS for cid in item['knowledge_points']), qid)
        return item

    def answer(self, qid):
        return self.question(qid)['answer_text']

    def capture(self, pattern, text):
        match = re.search(pattern, plain(text))
        self.assertIsNotNone(match, '参考答案格式已变化，需复核数学字段：' + text)
        return match

    def choices(self, item, accepted):
        expected = {option['key'] for option in item['options'] if accepted(option['text'])}
        self.assertTrue(expected, item['id'] + ' 没有符合独立计算的选项')
        if item['type'] == '单项选择':
            self.assertEqual(len(expected), 1)
        self.assertEqual(set(item['answer']), expected, item['id'])
        self.assertEqual(len(item['answer']), len(expected), '答案不能重复')

    def test_prime_choice(self):
        q = self.question('q_number_prime_01')
        def is_prime(value):
            n = int(value)
            return n > 1 and all(n % d for d in range(2, math.isqrt(n)+1))
        self.choices(q, is_prime)

    def test_rsa_parameters_ciphertext_and_decryption(self):
        answer = self.answer('q_number_rsa_02')
        p, q, e, message = 5, 11, 3, 7
        modulus, phi = p*q, (p-1)*(q-1)
        private = pow(e, -1, phi)
        cipher = pow(message, e, modulus)
        recovered = pow(cipher, private, modulus)
        superscript = str.maketrans('0123456789', '⁰¹²³⁴⁵⁶⁷⁸⁹')
        expected = f'd={private}，c={cipher}，{cipher}{str(private).translate(superscript)}≡{recovered}(mod {modulus})。'
        self.assertEqual(answer, expected)
        self.assertEqual(recovered, message)

    def test_all_linear_congruence_solutions(self):
        answer = self.answer('q_number_linear_congruence_02')
        solutions = [x for x in range(14) if (6*x-8) % 14 == 0]
        self.assertEqual(integers(answer), solutions)

    def test_linear_congruence_choice(self):
        q = self.question('q_number_linear_congruence_05')
        self.choices(q, lambda text: any((8*x-int(text.split('=')[1])) % 12 == 0
                                         for x in range(12)))

    def test_crt_three_moduli(self):
        answer = self.answer('q_number_inverse_crt_02')
        period = math.lcm(4, 7, 9)
        solutions = [x for x in range(period) if x % 4 == 1 and x % 7 == 2 and x % 9 == 3]
        self.assertEqual(len(solutions), 1)
        self.assertEqual(integers(answer), [solutions[0], solutions[0], period])

    def test_crt_non_coprime_period_choice(self):
        q = self.question('q_number_inverse_crt_03')
        period = math.lcm(4, 6)
        solutions = [x for x in range(period) if x % 4 == 1 and x % 6 == 3]
        self.assertEqual(len(solutions), 1)
        expected = f'x={solutions[0]}+{period}k，k∈ℤ。'
        self.choices(q, lambda text: text == expected)

    def test_crt_incompatible(self):
        answer = self.answer('q_number_inverse_crt_07')
        self.assertFalse([x for x in range(math.lcm(6, 9)) if x % 6 == 2 and x % 9 == 3])
        g, difference = math.gcd(6, 9), 2-3
        self.assertNotEqual(difference % g, 0)
        self.assertEqual(plain(answer), f'无解，因为gcd(6,9)={g}不整除余数差2-3={difference}。')

    def test_euler_fermat_choices(self):
        q = self.question('q_number_euler_fermat_03')
        # Freeze each proposition so a newly worded option cannot silently
        # inherit the truth value of an old option key.
        truths = {
            '3⁴≡1(mod 10)。': pow(3, 4, 10) == 1,
            '2⁴≡1(mod 10)。': pow(2, 4, 10) == 1,
            '对每个整数a，都有a⁷≡a(mod 7)。': all(pow(a, 7, 7) == a for a in range(7)),
            'φ(12)=11。': sum(math.gcd(a, 12) == 1 for a in range(12)) == 11,
        }
        self.assertEqual({o['text'] for o in q['options']}, set(truths))
        self.choices(q, lambda text: truths[text])

    def test_ring_units_choice(self):
        q = self.question('q_algebra_ring_field_01')
        units = {a for a in range(6) if any(a*b % 6 == 1 for b in range(6))}
        self.choices(q, lambda text: set(integers(text)) == units)

    def test_field_inverse_division_and_roots(self):
        answer = self.answer('q_algebra_ring_field_02')
        inverse = next(b for b in range(7) if 3*b % 7 == 1)
        quotient = 4*inverse % 7
        roots = [x for x in range(7) if x*x % 7 == 1]
        expected = f'3⁻¹={inverse}；4/3={quotient}；x²=1的解为{roots[0]}和{roots[1]}。'
        self.assertEqual(answer, expected)

    def test_divisor_lattice_missing_complement(self):
        answer = self.answer('q_algebra_lattice_bool_02')
        divisors = [d for d in range(1, 13) if 12 % d == 0]
        complements = [d for d in divisors if math.gcd(2, d) == 1 and math.lcm(2, d) == 12]
        self.assertEqual(complements, [])
        expected = f'4∧6={math.gcd(4,6)}，4∨6={math.lcm(4,6)}；2没有补元，所以该格不是布尔代数。'
        self.assertEqual(answer, expected)

    def test_all_complement_pairs(self):
        answer = self.answer('q_algebra_lattice_bool_07')
        divisors = [d for d in range(1, 7) if 6 % d == 0]
        expected = {(a, b) for a, b in itertools.combinations(divisors, 2)
                    if math.gcd(a, b) == 1 and math.lcm(a, b) == 6}
        actual = {tuple(integers(pair)) for pair in re.findall(r'\{[\d,]+\}', answer)}
        self.assertEqual(actual, expected)
        self.assertIn('2与自己之交是2而非最小元1', answer)

    def test_committee_count(self):
        answer = self.answer('q_count_perm_comb_02')
        # Enumerate subsets rather than use the authored combination formula.
        expected = sum(any(x < 5 for x in group) and any(x >= 5 for x in group)
                       for group in itertools.combinations(range(9), 3))
        actual = int(self.capture(r'=(\d+)\$?\s*组', answer)[1])
        self.assertEqual(actual, expected)

    def test_binomial_coefficient(self):
        answer = self.answer('q_count_binomial_02')
        # Multiply six copies directly, independently of the binomial formula.
        coefficients = [1]
        for _ in range(6):
            result = [0]*(len(coefficients)+1)
            for k, value in enumerate(coefficients):
                result[k] -= 3*value
                result[k+1] += 2*value
            coefficients = result
        self.assertEqual(answer, str(coefficients[4])+'。')

    def test_signed_product_coefficient(self):
        answer = self.answer('q_count_binomial_08')
        coefficients = [1]
        for sign in (1, 1, 1, -1, -1, -1, -1):
            result = [0]*(len(coefficients)+1)
            for k, value in enumerate(coefficients):
                result[k] += value
                result[k+1] += sign*value
            coefficients = result
        self.assertEqual(plain(answer), str(coefficients[5])+'。')

    def test_exact_membership_count(self):
        answer = self.answer('q_count_inclusion_02')
        single = [40, 35, 30]
        pairs = [12, 10, 9]
        triple, total = 4, 100
        union = sum(single)-sum(pairs)+triple
        exact_one = sum(single)-2*sum(pairs)+3*triple
        self.assertEqual(answer, f'至少一种{union}台；恰好一种{exact_one}台；三种都没有{total-union}台。')

    def test_generating_coin_coefficient(self):
        answer = self.answer('q_count_generating_02')
        expected = sum(2*u+3*v == 12 for u in range(7) for v in range(5))
        actual = int(self.capture(r'所求系数为(\d+)', answer)[1])
        self.assertEqual(actual, expected)
        self.assertIn('1/((1-x^2)(1-x^3))', answer)

    def test_generating_bounded_coefficient(self):
        answer = self.answer('q_count_generating_06')
        expected = sum(u+v+w == 4 for u in range(3) for v in range(4) for w in range(5))
        actual = int(self.capture(r'系数为(\d+)', answer)[1])
        self.assertEqual(actual, expected)
        self.assertIn('(1+x+x^2)(1+x+x^2+x^3)/(1-x)', answer)

    def test_resonant_recurrence_formula(self):
        answer = self.answer('q_recurrence_nonhomogeneous_03')
        base = int(self.capture(r'\$a_n=n(\d+)\^n\$', answer)[1])
        # The answer's own base is evaluated, not a second hardcoded answer.
        expected = 0
        for n in range(16):
            if n:
                expected = 2*expected+2**n
            self.assertEqual(n*base**n, expected, 'n='+str(n))

    def test_repeated_root_formula(self):
        answer = self.answer('q_recurrence_homogeneous_03')
        match = self.capture(r'\$a_n=\(n\+(\d+)\)(\d+)\^n\$', answer)
        offset, base = map(int, match.groups())
        expected = [1, 4]
        for n in range(2, 16):
            expected.append(4*expected[-1]-4*expected[-2])
        self.assertEqual([(n+offset)*base**n for n in range(16)], expected)

    def test_transformed_initial_condition(self):
        answer = self.answer('q_recurrence_initial_08')
        match = self.capture(r'\$a_n=\(n\+(\d+)\)/\(n\+(\d+)\)\$', answer)
        numerator, denominator = map(int, match.groups())
        self.assertEqual(int(self.capture(r'\$b_0=(\d+)\$', answer)[1]), 2)
        expected = Fraction(2)
        for n in range(16):
            if n:
                expected = Fraction(n, n+1)*expected+Fraction(1, n+1)
            self.assertEqual(Fraction(n+numerator, n+denominator), expected)

    def test_adjacency_and_degrees(self):
        answer = self.answer('q_graph_adjacency_01')
        vertices, edges = 'abc', [('a', 'b'), ('b', 'c')]
        expected = [[int((u, v) in edges or (v, u) in edges) for v in vertices] for u in vertices]
        self.assertEqual(matrices(answer), [expected])
        actual_degrees = integers(self.capture(r'度数依次为([^。]+)', answer)[1])
        self.assertEqual(actual_degrees, list(map(sum, expected)))

    def test_matrix_powers_count_walks(self):
        q = self.question('q_graph_adjacency_03')
        adjacency = matrices(q['statement'])[0]
        squared = multiply(adjacency, adjacency)
        cubed = multiply(squared, adjacency)
        actual = [int(v) for v in re.findall(r'=(\d+)', q['answer_text'])]
        self.assertEqual(actual, [squared[0][1], cubed[0][0]])

    def test_oriented_incidence_laplacian(self):
        q = self.question('q_graph_matrix_02')
        incidence = matrices(q['statement'])[0]
        expected = multiply(incidence, list(map(list, zip(*incidence))))
        self.assertEqual(matrices(q['answer_text']), [expected])
        flipped = [row[:2]+[-row[2]] for row in incidence]
        self.assertEqual(multiply(flipped, list(map(list, zip(*flipped)))), expected)
        self.assertIn('结果不变', q['answer_text'])

    def test_reachability_conventions(self):
        answer = self.answer('q_graph_matrix_03')
        reach = [[0, 1, 0], [0, 0, 1], [0, 0, 0]]
        for k in range(3):
            for i in range(3):
                for j in range(3):
                    reach[i][j] = int(reach[i][j] or (reach[i][k] and reach[k][j]))
        reflexive = [[int(i == j or reach[i][j]) for j in range(3)] for i in range(3)]
        self.assertEqual(matrices(answer), [reach, reflexive])

    def test_all_topological_orders(self):
        answer = self.answer('q_graph_topological_02')
        edges = [('a', 'c'), ('b', 'c'), ('b', 'd'), ('c', 'e'), ('d', 'e')]
        expected = {order for order in itertools.permutations('abcde')
                    if all(order.index(u) < order.index(v) for u, v in edges)}
        match = self.capture(r'共有(\d+)个：([^。]+)', answer)
        actual = [tuple(sequence.split(',')) for sequence in match[2].split('；')]
        self.assertEqual(int(match[1]), len(expected))
        self.assertEqual(len(actual), len(expected), '不能重复列拓扑序')
        self.assertEqual(set(actual), expected)

    def test_negative_weight_mst_choice(self):
        q = self.question('q_tree_mst_01')
        trees = spanning_trees('abc', [('a', 'b', -3), ('a', 'c', 1), ('b', 'c', 4)])
        minimum = min(weight for _, weight in trees)
        self.choices(q, lambda text: int(plain(text)) == minimum)

    def test_kruskal_order_and_unique_mst(self):
        answer = self.answer('q_tree_mst_02')
        edges = [('a', 'b', 1), ('a', 'c', 4), ('a', 'd', 6),
                 ('b', 'c', 2), ('b', 'd', 5), ('c', 'd', 3)]
        trees = spanning_trees('abcd', edges)
        minimum = min(weight for _, weight in trees)
        optimal = [chosen for chosen, weight in trees if weight == minimum]
        actual_order = self.capture(r'依次考虑([^。]+)', answer)[1].split('、')
        self.assertEqual(actual_order, [u+v for u, v, _ in sorted(edges, key=lambda edge: edge[2])])
        actual_tree = frozenset(self.capture(r'前三条([^，。]+)不成圈', answer)[1].split('、'))
        self.assertEqual(optimal, [actual_tree])
        total = self.capture(r'得到总权重([^。]+)', answer)[1]
        self.assertEqual(int(total.rsplit('=', 1)[1]), minimum)
        self.assertIn('最小生成树唯一', answer)

    def test_mst_weight_and_all_optimal_trees(self):
        answer = self.answer('q_tree_mst_07')
        edges = [('a', 'b', 2), ('b', 'c', 2), ('c', 'd', 2), ('d', 'a', 2), ('a', 'c', 5)]
        trees = spanning_trees('abcd', edges)
        minimum = min(weight for _, weight in trees)
        count = sum(weight == minimum for _, weight in trees)
        match = self.capture(r'最优权重为(\d+)，恰有(\d+)棵', answer)
        self.assertEqual(tuple(map(int, match.groups())), (minimum, count))

    def test_triangle_matrix_tree_choice(self):
        q = self.question('q_tree_matrix_tree_01')
        matrix = matrices(q['statement'])[0]
        expected = determinant(cofactor(matrix, 2))
        enumerated = spanning_trees('abc', [('a', 'b', 1), ('b', 'c', 1), ('a', 'c', 1)])
        self.assertEqual(expected, len(enumerated))
        self.choices(q, lambda text: int(text) == expected)

    def test_matrix_tree_diagonal_graph(self):
        answer = self.answer('q_tree_matrix_tree_02')
        edges = [('a', 'b', 1), ('b', 'c', 1), ('c', 'd', 1), ('d', 'a', 1), ('a', 'c', 1)]
        expected = laplacian('abcd', edges)
        minor = cofactor(expected, 3)
        count = len(spanning_trees('abcd', edges))
        self.assertEqual(matrices(answer), [expected, minor])
        self.assertEqual(determinant(minor), count)
        self.assertEqual(int(self.capture(r'共有(\d+)棵生成树', answer)[1]), count)

    def test_matrix_tree_shared_vertex(self):
        answer = self.answer('q_tree_matrix_tree_07')
        edges = [('a', 'b', 1), ('b', 'c', 1), ('c', 'a', 1),
                 ('c', 'd', 1), ('d', 'e', 1), ('e', 'c', 1)]
        minor = cofactor(laplacian('abcde', edges), 2)
        count = len(spanning_trees('abcde', edges))
        self.assertEqual(matrices(answer), [minor])
        self.assertEqual(determinant(minor), count)
        self.assertEqual(int(self.capture(r'图有(\d+)棵生成树', answer)[1]), count)

    def test_wrong_answers_and_changed_stems_are_rejected(self):
        """Mutate copies in memory; never write to the actual content packs."""
        rsa = QUESTIONS['q_number_rsa_02']['answer_text']
        mutants = [
            ('q_number_prime_01', 'answer', ['A'], 'test_prime_choice'),
            ('q_number_rsa_02', 'answer_text', rsa.replace('d=27', 'd=2'), 'test_rsa_parameters_ciphertext_and_decryption'),
            ('q_number_rsa_02', 'answer_text', rsa.replace('c=13', 'c=99'), 'test_rsa_parameters_ciphertext_and_decryption'),
            ('q_number_rsa_02', 'answer_text', rsa.replace('≡7(', '≡9('), 'test_rsa_parameters_ciphertext_and_decryption'),
            ('q_number_rsa_02', 'statement', STEMS['q_number_rsa_02'].replace('m=7', 'm=8'), 'test_rsa_parameters_ciphertext_and_decryption'),
            ('q_graph_adjacency_01', 'answer_text', QUESTIONS['q_graph_adjacency_01']['answer_text'].replace('[[0,1,0]', '[[0,0,0]'), 'test_adjacency_and_degrees'),
            ('q_tree_matrix_tree_02', 'answer_text', QUESTIONS['q_tree_matrix_tree_02']['answer_text'].replace('共有8棵', '共有7棵'), 'test_matrix_tree_diagonal_graph'),
        ]
        for qid, field, bad, method in mutants:
            with self.subTest(question=qid, field=field, mutant=bad):
                original = QUESTIONS[qid]
                self.assertNotEqual(original[field], bad, 'mutation必须确实改变字段')
                QUESTIONS[qid] = {**copy.deepcopy(original), field: bad}
                try:
                    with self.assertRaises(AssertionError):
                        getattr(self, method)()
                finally:
                    QUESTIONS[qid] = original


def read_rows(paths, key):
    rows = {}
    for path in paths:
        pack = json.loads(path.read_text(encoding='utf-8'))
        for item in pack[key] if isinstance(pack, dict) else pack:
            if item['id'] in rows:
                raise ValueError('重复ID：'+item['id'])
            rows[item['id']] = item
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--questions', action='append', type=Path,
                        help='题库包或含questions的片段，可重复传入并在内存中合并')
    parser.add_argument('--concepts', action='append', type=Path,
                        help='概念包或含concepts的片段，可重复传入')
    args, unittest_args = parser.parse_known_args()
    question_paths = args.questions or [ROOT/'offline-content/questions.zh-CN.json']
    QUESTIONS.update(read_rows(question_paths, 'questions'))
    if args.concepts:
        CONCEPTS.update(read_rows(args.concepts, 'concepts'))
    elif args.questions:
        # Authoring fragments already contain both arrays; shipping question
        # packs do not, and should use the adjacent concept pack explicitly.
        combined = [path for path in question_paths if 'concepts' in json.loads(path.read_text())]
        if len(combined) == len(question_paths):
            CONCEPTS.update(read_rows(combined, 'concepts'))
    else:
        CONCEPTS.update(read_rows([ROOT/'offline-content/concepts.zh-CN.json'], 'concepts'))
    unittest.main(argv=[__file__, *unittest_args], verbosity=2)


if __name__ == '__main__':
    main()
