import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path


MODE_LABELS = {
    "hint": "提示引导",
    "full_solution": "完整解析",
    "concept": "概念讲解",
    "exercise": "练习出题",
    "check_answer": "答案诊断",
}


KNOWLEDGE_GRAPH_PATH = Path(__file__).with_name("knowledge_graph.json")


def _load_knowledge_graph():
    try:
        with KNOWLEDGE_GRAPH_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception as exc:
        print(f"知识图谱加载失败：{repr(exc)}")
        return {"nodes": []}

    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        print("知识图谱格式异常：缺少 nodes 列表")
        return {"nodes": []}

    return data


_KNOWLEDGE_GRAPH = _load_knowledge_graph()
_KNOWLEDGE_INDEX = {
    node.get("name"): node
    for node in _KNOWLEDGE_GRAPH.get("nodes", [])
    if isinstance(node, dict) and isinstance(node.get("name"), str)
}


def _direct_prerequisites(points, limit=4):
    result = []

    for point in points or []:
        node = _KNOWLEDGE_INDEX.get(point)
        if not node:
            continue

        prerequisites = node.get("prerequisites") or []
        for name in prerequisites:
            if isinstance(name, str) and name not in result and name not in points:
                result.append(name)
                if len(result) >= limit:
                    return result

    return result


def _longest_prerequisite_path(point, visited=None):
    if point not in _KNOWLEDGE_INDEX:
        return [point] if point else []

    visited = set(visited or ())
    if point in visited:
        return [point]
    visited.add(point)

    prerequisites = _KNOWLEDGE_INDEX[point].get("prerequisites") or []
    candidate_paths = []

    for prerequisite in prerequisites:
        if not isinstance(prerequisite, str):
            continue
        candidate_paths.append(
            _longest_prerequisite_path(prerequisite, visited.copy())
        )

    if not candidate_paths:
        return [point]

    best = max(candidate_paths, key=len)
    return best + [point]


def _knowledge_path(points, limit=5):
    best = []

    for point in points or []:
        path = _longest_prerequisite_path(point)
        if len(path) > len(best):
            best = path

    if len(best) > limit:
        best = best[-limit:]

    return best


def _enrich_with_graph(result):
    result = dict(result or {})
    points = result.get("knowledge_points") or []
    result["prerequisite_points"] = _direct_prerequisites(points)
    result["knowledge_path"] = _knowledge_path(points)
    return result



# 第 7 步先采用轻量、可解释的规则分类。
# 这里不额外调用大模型，因此不会增加一次 API 请求，也便于后续把这些标签
# 稳定地接到知识图谱、错题本和学习记录上。
CATEGORY_RULES = {
    "命题逻辑": {
        "keywords": [
            "命题", "真值表", "真值", "逻辑联结词", "否定", "合取", "析取",
            "蕴含", "逻辑等价", "等值", "主析取", "主合取", "析取范式",
            "合取范式", "永真", "永假", "推理规则", "逻辑推理", "可满足性", "消解",
        ],
        "points": {
            "命题与真值": ["命题", "真值", "永真", "永假"],
            "逻辑联结词": ["逻辑联结词", "否定", "合取", "析取", "蕴含"],
            "真值表": ["真值表"],
            "逻辑等价": ["逻辑等价", "等值", "等价式"],
            "范式": ["析取范式", "合取范式", "主析取", "主合取", "范式"],
            "命题推理": ["推理规则", "逻辑推理", "前提", "结论", "消解"],
        },
    },
    "谓词逻辑": {
        "keywords": [
            "谓词", "量词", "全称量词", "存在量词", "辖域", "自由变元",
            "约束变元", "个体域", "谓词公式", "量词否定", "一阶逻辑", "前束范式",
        ],
        "points": {
            "谓词与个体域": ["谓词", "个体域", "一阶逻辑"],
            "量词": ["量词", "全称量词", "存在量词"],
            "变元与辖域": ["辖域", "自由变元", "约束变元"],
            "量词推理与否定": ["量词否定", "谓词公式", "一阶逻辑推理", "置换规则"],
            "前束范式": ["前束范式", "prenex"],
        },
    },
    "证明与归纳": {
        "keywords": [
            "直接证明", "直接证法", "反证法", "反证", "归纳法", "数学归纳法",
            "强归纳法", "完全归纳法", "结构归纳",
        ],
        "points": {
            "直接证明与反证法": ["直接证明", "直接证法", "反证法", "反证"],
            "数学归纳法": ["数学归纳法", "归纳法", "归纳假设"],
            "强归纳法": ["强归纳法", "完全归纳法", "结构归纳"],
        },
    },
    "集合与关系": {
        "keywords": [
            "集合", "子集", "幂集", "笛卡尔积", "关系", "二元关系", "自反",
            "反自反", "对称", "反对称", "传递", "等价关系", "等价类", "划分",
            "偏序", "全序", "哈斯图", "闭包", "关系矩阵", "关系运算", "关系的运算",
            "逆关系", "复合关系", "合成关系", "关系的幂",
        ],
        "points": {
            "集合运算": ["集合", "子集", "幂集", "并集", "交集", "差集", "补集"],
            "笛卡尔积与关系": ["笛卡尔积", "二元关系", "关系矩阵"],
            "关系运算": ["关系运算", "关系的运算", "逆关系", "复合关系", "合成关系", "关系的幂"],
            "关系性质": ["自反", "反自反", "对称", "反对称", "传递"],
            "等价关系与划分": ["等价关系", "等价类", "划分"],
            "偏序关系": ["偏序", "全序", "哈斯图"],
            "关系闭包": ["自反闭包", "对称闭包", "传递闭包", "闭包"],
        },
    },
    "函数": {
        "keywords": [
            "函数", "映射", "单射", "满射", "双射", "复合函数", "复合映射",
            "逆函数", "原像", "像", "定义域", "值域",
        ],
        "points": {
            "函数与映射": ["函数", "映射", "定义域", "值域", "原像"],
            "单射满射双射": ["单射", "满射", "双射"],
            "复合函数": ["复合函数", "复合映射"],
            "逆函数": ["逆函数", "反函数"],
        },
    },
    "初等数论": {
        "keywords": [
            "数论",
            "整除", "素数", "质数", "合数", "因数", "约数", "最大公因数", "最大公约数",
            "最小公倍数", "欧几里得算法", "辗转相除", "同余", "模运算", "mod",
            "线性同余", "一次同余", "模逆元", "模逆", "中国剩余定理", "孙子定理",
            "crt", "欧拉函数", "欧拉定理", "费马小定理", "rsa", "公钥密码",
        ],
        "points": {
            "整除与素数": ["整除", "素数", "质数", "合数", "因数", "约数"],
            "最大公因数与欧几里得算法": ["最大公因数", "最大公约数", "最小公倍数", "欧几里得算法", "辗转相除", "gcd", "lcm"],
            "同余与模运算": ["同余", "模运算", "mod"],
            "线性同余方程": ["线性同余", "一次同余", "同余方程"],
            "模逆与中国剩余定理": ["模逆元", "模逆", "中国剩余定理", "孙子定理", "crt"],
            "欧拉定理与费马小定理": ["欧拉函数", "欧拉定理", "费马小定理"],
            "RSA公钥密码": ["rsa", "公钥密码"],
        },
    },
    "计数与组合": {
        "keywords": [
            "排列", "组合", "排列数", "组合数", "二项式", "二项式定理", "鸽巢",
            "鸽巢原理", "抽屉原理", "容斥", "容斥原理", "计数", "加法原理",
            "乘法原理", "多重集合", "生成函数",
        ],
        "points": {
            "基本计数原理": ["计数", "加法原理", "乘法原理"],
            "排列与组合": ["排列", "组合", "排列数", "组合数"],
            "二项式定理": ["二项式", "二项式定理"],
            "鸽巢原理": ["鸽巢", "鸽巢原理", "抽屉原理"],
            "容斥原理": ["容斥", "容斥原理"],
            "生成函数": ["生成函数"],
        },
    },
    "递推关系": {
        "keywords": [
            "递推", "递推关系", "递归关系", "特征方程", "齐次递推",
            "特征根", "非齐次递推", "初始条件", "递推式",
        ],
        "points": {
            "递推关系建模": ["递推", "递推关系", "递归关系", "递推式"],
            "线性齐次递推": ["齐次递推", "特征方程", "特征根"],
            "非齐次递推": ["非齐次递推"],
            "初始条件": ["初始条件"],
        },
    },
    "图论": {
        "keywords": [
            "图论", "无向图", "有向图", "顶点", "边集", "邻接", "邻接矩阵", "邻接表",
            "关联矩阵", "度矩阵", "度数", "度序列", "路径", "回路", "圈", "连通", "连通分量",
            "欧拉", "哈密顿", "最短路", "dijkstra", "着色", "平面图", "匹配",
            "二部图", "二分图", "二着色", "拓扑排序", "拓扑序", "拓扑序列", "有向无环图", "dag",
            "拉普拉斯矩阵", "laplacian", "树", "生成树", "最小生成树", "带权图", "权值",
            "矩阵树定理", "matrix-tree", "matrix tree", "kirchhoff", "基尔霍夫",
            "kruskal", "prim", "根树", "二叉树", "叶子", "割点", "割边", "桥", "生成森林",
            "支配集", "覆盖集", "独立集", "简单图", "图化", "可图化", "简单图化", "可简单图化",
            "havel", "hakimi", "havel-hakimi", "握手定理", "度数列", "图序列", "实现度序列",
        ],
        "points": {
            "图的基本概念": ["无向图", "有向图", "顶点", "边集", "度数", "度序列", "度数列", "图论", "邻接表", "简单图", "图化", "可图化", "简单图化", "可简单图化", "havel", "hakimi", "havel-hakimi", "握手定理", "实现度序列"],
            "图同构": ["图同构", "同构图", "顶点对应", "顶点映射", "保持邻接"],
            "邻接矩阵": ["邻接矩阵", "a^2", "tr(a^2)", "tr(a²)"],
            "图的矩阵表示": ["关联矩阵", "拉普拉斯矩阵", "laplacian", "度矩阵"],
            "路径与连通性": ["路径", "通路", "回路", "圈", "连通", "连通分量"],
            "割点与割边": ["割点", "割边", "桥"],
            "带权图": ["带权图", "加权图", "权值", "边权"],
            "欧拉图": ["欧拉", "欧拉路", "欧拉通路", "欧拉回路"],
            "哈密顿图": ["哈密顿", "哈密顿路", "哈密顿通路", "哈密顿回路"],
            "最短路": ["最短路", "最短路径", "dijkstra"],
            "图着色": ["着色", "色数"],
            "平面图": ["平面图", "欧拉公式"],
            "二部图": ["二部图", "二分图", "二着色"],
            "拓扑排序": ["拓扑排序", "拓扑序", "拓扑序列", "有向无环图", "dag"],
            "支配集、覆盖集与独立集": ["支配集", "覆盖集", "点覆盖", "边覆盖", "独立集"],
            "图匹配": ["匹配", "完美匹配", "二部图匹配"],
            "树的基本性质": ["树", "无向树", "叶子"],
            "根树": ["根树", "有根树", "二叉树"],
            "生成树": ["生成树", "生成森林"],
            "最小生成树": ["最小生成树", "kruskal", "prim"],
            "矩阵树定理": ["矩阵树定理", "matrix-tree", "matrix tree", "kirchhoff", "基尔霍夫"],
        },
    },
    "代数结构": {
        "keywords": [
            "代数系统", "代数结构", "半群", "幺半群", "群", "子群", "循环群",
            "陪集", "拉格朗日定理", "同态", "同构", "二元运算", "封闭性", "结合律", "交换律",
            "单位元", "幺元", "环", "域", "格", "布尔代数",
        ],
        "points": {
            "代数系统": ["代数系统", "代数结构", "半群", "幺半群", "二元运算", "封闭性", "结合律", "交换律", "单位元", "幺元"],
            "群与子群": ["群", "子群", "循环群", "陪集", "拉格朗日定理"],
            "同态与同构": ["同态", "同构"],
            "环与域": ["环", "域"],
            "格与布尔代数": ["格", "布尔代数"],
        },
    },
}


NO_SOLUTION_PATTERNS = [
    "不要给我答案", "别给我答案", "不要直接给答案", "别直接给答案",
    "不要完整解析", "不用完整解析", "只给提示", "只提示", "给我提示", "提示一下",
]

FULL_SOLUTION_PATTERNS = [
    "给我答案", "直接给答案", "直接答案", "完整解析", "完整解答", "详细解答",
    "完整过程", "直接解出来", "直接做出来", "告诉我最终答案", "最终答案", "把答案给我",
]

CHECK_PATTERNS = [
    "我的答案", "我算", "我做", "我写", "我觉得", "我认为", "对不对", "正确吗",
    "有没有错", "哪里错", "帮我检查", "检查一下", "为什么错", "我这样做", "我这样算",
    "错题复测回答", "复测回答",
]

CONCEPT_PATTERNS = [
    "什么是", "是什么意思", "定义", "概念", "含义", "区别", "解释一下", "怎么理解",
]

PROBLEM_PATTERNS = [
    "求", "计算", "证明", "判断", "已知", "设", "列出", "写出", "求解", "试求",
]


_INTERNAL_IMAGE_MARKERS = (
    "[图片识题]",
    "【题目文字】",
    "【图形信息】",
    # 兼容旧版本会话记录
    "【题干与公式识别】",
    "【图形结构识别】",
)


FOCUS_POINT_ALIASES = {
    "图同构": ["图同构", "同构图", "顶点对应", "顶点映射", "保持邻接", "邻接关系"],
    "邻接矩阵": ["aij", "a_{ij}", "a_ij", "邻接矩阵", "矩阵a", "矩阵 a", "大括号"],
    "图的矩阵表示": ["拉普拉斯", "laplacian", "关联矩阵", "度矩阵", "矩阵表示"],
    "路径与连通性": ["通路", "路径", "回路", "长度为", "连通", "连通分量"],
    "割点与割边": ["割点", "割边", "桥"],
    "带权图": ["带权", "加权", "权值", "边权"],
    "欧拉图": ["欧拉", "欧拉通路", "欧拉回路", "奇度", "偶度", "度数"],
    "哈密顿图": ["哈密顿", "哈密顿通路", "哈密顿回路"],
    "生成树": ["生成树", "树的数量", "生成森林"],
    "最小生成树": ["最小生成树", "kruskal", "prim", "最小权"],
    "矩阵树定理": ["矩阵树", "matrix-tree", "kirchhoff", "基尔霍夫", "余子式"],
    "最短路": ["最短路", "最短路径", "dijkstra"],
    "二部图": ["二部图", "二分图", "二着色"],
    "拓扑排序": ["拓扑排序", "拓扑序", "拓扑序列", "有向无环图", "dag"],
    "根树": ["根树", "有根树", "二叉树"],
    "关系运算": ["关系运算", "逆关系", "复合关系", "关系的幂"],
    "关系性质": ["自反", "反自反", "对称", "反对称", "传递"],
    "等价关系与划分": ["等价关系", "等价类", "划分"],
    "偏序关系": ["偏序", "全序", "哈斯图", "极大元", "极小元"],
    "关系闭包": ["闭包", "自反闭包", "对称闭包", "传递闭包"],
    "函数与映射": ["函数", "映射", "定义域", "值域", "原像"],
    "真值表": ["真值表", "真值"],
    "逻辑等价": ["逻辑等价", "等值", "等价式"],
    "范式": ["范式", "主析取", "主合取", "析取范式", "合取范式"],
    "前束范式": ["前束范式", "prenex"],
    "量词": ["量词", "全称", "存在", "∀", "∃"],
    "直接证明与反证法": ["直接证明", "反证法", "反证"],
    "数学归纳法": ["数学归纳法", "归纳假设"],
    "强归纳法": ["强归纳法", "完全归纳法"],
    "整除与素数": ["整除", "素数", "质数"],
    "最大公因数与欧几里得算法": ["最大公因数", "最大公约数", "gcd", "欧几里得", "辗转相除"],
    "同余与模运算": ["同余", "模运算", "mod"],
    "线性同余方程": ["线性同余", "一次同余", "同余方程"],
    "模逆与中国剩余定理": ["模逆元", "模逆", "中国剩余定理", "孙子定理", "crt"],
    "欧拉定理与费马小定理": ["欧拉定理", "费马小定理", "欧拉函数"],
    "排列与组合": ["排列", "组合", "排列数", "组合数", "c(n", "a(n"],
    "鸽巢原理": ["鸽巢", "抽屉"],
    "容斥原理": ["容斥"],
    "生成函数": ["生成函数"],
    "线性齐次递推": ["齐次递推", "特征方程", "特征根"],
    "非齐次递推": ["非齐次递推", "特解"],
    "群与子群": ["子群", "循环群", "陪集", "拉格朗日"],
    "同态与同构": ["同态", "同构", "核", "像"],
}



def _focus_normalize(text):
    value = str(text or "").lower()
    value = value.replace("（", "(").replace("）", ")")
    value = value.replace("²", "^2")
    value = value.replace("\\_", "_")
    value = re.sub(r"\\text\{([^{}]*)\}", r"\1", value)
    value = re.sub(r"[\s`$*\\]+", "", value)
    return value


def _point_keywords(category, point):
    keywords = [point]
    rule = CATEGORY_RULES.get(category) or {}
    point_rules = rule.get("points") or {}
    keywords.extend(point_rules.get(point) or [])
    keywords.extend(FOCUS_POINT_ALIASES.get(point) or [])

    result = []
    for keyword in keywords:
        if not isinstance(keyword, str) or not keyword.strip():
            continue
        normalized = _focus_normalize(keyword)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _score_focus_text(text, category, points, weight=1):
    normalized = _focus_normalize(text)
    scores = {point: 0 for point in points or []}

    if not normalized:
        return scores

    for point in scores:
        for keyword in _point_keywords(category, point):
            if keyword and keyword in normalized:
                # 越具体的词权重越高；短符号如 aij 也至少给到有效分。
                keyword_score = 3 if len(keyword) >= 4 else 2
                if keyword == _focus_normalize(point):
                    keyword_score += 2
                scores[point] += keyword_score * weight

    return scores


def _infer_focus_points(messages, category, points, question_text, mode, question_score):
    """识别“本题难点”。

    这里的 focus_points 继续沿用旧字段名以兼容前端和本地学习记录，
    但语义已经改为“题目本身最核心/较难的 1~2 个知识点”。

    重要原则：
    - 只根据题目文本、已识别知识点和知识图谱层级判断；
    - 不读取最近助手回复，也不根据学生的跟进语句猜测“学生卡在哪里”；
    - 信号不足时宁可少给，不制造虚假的个体学习判断。
    """
    del messages, mode, question_score  # 保留旧调用签名，避免牵动其它模块。

    candidates = [
        point
        for point in (points or [])
        if isinstance(point, str) and point
    ]

    if not candidates:
        return []

    if len(candidates) == 1:
        return candidates[:1]

    text_scores = _score_focus_text(
        question_text,
        category,
        candidates,
        weight=1,
    )

    # 知识图谱层级只用于“同等题面信号”下的排序：
    # 前置链更长的知识点通常更综合，但不会压过题面明确点名的知识点。
    ranked = []
    for point in candidates:
        path = _longest_prerequisite_path(point)
        depth = max(0, len(path) - 1)
        ranked.append((
            point,
            int(text_scores.get(point, 0)),
            depth,
        ))

    ranked.sort(
        key=lambda item: (-item[1], -item[2], item[0])
    )

    top_point, top_score, top_depth = ranked[0]

    # 题面完全没有把多个知识点区分开时，用知识图谱层级给一个保守结果。
    if top_score <= 0:
        if top_depth <= 0:
            return []
        return [top_point]

    result = [top_point]

    # 第二难点只有在题面也有明确证据、且与第一难点接近时才保留。
    if len(ranked) >= 2:
        second_point, second_score, second_depth = ranked[1]
        close_enough = (
            second_score > 0
            and second_score * 10 >= top_score * 7
            and second_depth >= max(0, top_depth - 1)
        )
        if close_enough:
            result.append(second_point)

    return result[:2]


def _normalize(text):
    value = str(text or "").strip().lower()
    value = value.replace("（", "(").replace("）", ")")
    value = value.replace("²", "^2")
    value = re.sub(r"\s+", " ", value)
    return value


def _contains_any(text, patterns):
    return any(pattern.lower() in text for pattern in patterns)


# 仅用于“用户短指令”的本地模糊识别。
# 不调用 AI，不改原始题面，不参与 MathJax / OCR 文本本身的展示。
# 目标是容忍常见输入法错字、同音字、漏字，并保持毫秒级处理。
_REQUEST_EXACT_ALIASES = {
    # 出题动作 / 量词
    "出一到题": "出一道题", "出一倒题": "出一道题", "出一到": "出一道", "出一倒": "出一道",
    "来一到题": "来一道题", "来一到": "来一道", "给我一到题": "给我一道题", "给我一到": "给我一道",
    "再来一到": "再来一道", "再出一到": "再出一道",
    "练西题": "练习题", "练系题": "练习题", "题木": "题目",
    # 难度
    "减单": "简单", "简丹": "简单", "简但": "简单", "建单": "简单",
    "困南": "困难", "困男": "困难", "捆难": "困难", "坤难": "困难",
    "中登": "中等", "中灯": "中等", "中邓": "中等",
    "不南": "不难", "不男": "不难", "很南": "很难", "很男": "很难",
    "太南": "太难", "太男": "太难", "高南": "高难",
    "容一": "容易", "荣易": "容易",
    "基处": "基础", "基楚": "基础", "初几": "初级", "初及": "初级", "入们": "入门",
    # 离散数学常见模块 / 知识点
    "树论": "数论", "术论": "数论", "数伦": "数论", "数轮": "数论",
    "涂论": "图论", "图伦": "图论", "图轮": "图论",
    "群伦": "群论", "群轮": "群论", "格伦": "格论", "格轮": "格论",
    "集和": "集合", "急合": "集合", "关西": "关系",
    "含数": "函数", "函术": "函数", "函树": "函数", "应射": "映射", "映设": "映射",
    "递退": "递推", "计树": "计数", "组和": "组合", "代树": "代数",
    "临接矩阵": "邻接矩阵", "邻接举阵": "邻接矩阵", "邻接矩正": "邻接矩阵",
    "临接矩正": "邻接矩阵", "临接举阵": "邻接矩阵",
    "同于": "同余", "同鱼": "同余", "魔运算": "模运算", "摸运算": "模运算",
    "欧啦": "欧拉", "哈密吨": "哈密顿",
    "非马小定理": "费马小定理", "费码小定理": "费马小定理",
    "中国剩于定理": "中国剩余定理", "中国剩鱼定理": "中国剩余定理",
    "贝组": "贝祖", "陪蜀": "裴蜀", "欧几里德": "欧几里得",
    "真直表": "真值表", "真职表": "真值表", "前束范事": "前束范式", "前束范试": "前束范式",
    "拓朴排序": "拓扑排序", "拓普排序": "拓扑排序",
    "二步图": "二部图", "二不图": "二部图", "二部涂": "二部图",
    "最小生成数": "最小生成树", "最小生城树": "最小生成树",
    "图同够": "图同构", "图同购": "图同构", "最短璐": "最短路", "最短录": "最短路",
    "欧拉通璐": "欧拉通路", "欧拉回璐": "欧拉回路", "哈密顿回璐": "哈密顿回路",
    "哈密炖": "哈密顿", "哈蜜顿": "哈密顿",
    "关系巨阵": "关系矩阵", "关西矩阵": "关系矩阵", "关系的密": "关系的幂",
    "自反幸": "自反性", "对陈性": "对称性", "传弟性": "传递性", "反对陈": "反对称",
    "等价关西": "等价关系", "偏需关系": "偏序关系", "哈斯涂": "哈斯图",
    "笛卡儿积": "笛卡尔积", "迪卡尔积": "笛卡尔积",
    "排列组和": "排列组合", "排列祖合": "排列组合", "鸽朝原理": "鸽巢原理",
    "容斥园理": "容斥原理", "容拆原理": "容斥原理", "生成涵数": "生成函数",
    "递推关西": "递推关系", "递归关西": "递归关系", "特征防程": "特征方程",
    "布尔带数": "布尔代数", "代数结够": "代数结构",
    "提目": "题目", "题慕": "题目", "练西": "练习", "练系": "练习",
    "南度": "难度", "男度": "难度", "不太南": "不太难", "不太男": "不太难",
    "不要太南": "不要太难", "不要太男": "不要太难", "非常南": "非常难", "特别南": "特别难",
}

# 用于泛化的一字误差修复。短词只在强语境下修复，避免把正常句子误改。
_REQUEST_FUZZY_TERMS = (
    # 只对较长的高价值模块/知识点做“任意一字误差”泛化修复。
    # 数量刻意受控：扩大覆盖面，但保持每次本地解析在毫秒级；
    # 2~3 字短词若泛化过度很容易误改正常句子，继续走上面的高置信别名。
    "命题逻辑", "谓词逻辑", "逻辑联结词", "前束范式", "数学归纳法",
    "代数结构", "布尔代数", "笛卡尔积", "等价关系", "偏序关系",
    "关系矩阵", "关系运算", "关系闭包", "函数与映射", "复合函数",
    "邻接矩阵", "路径与连通性", "最小生成树", "拓扑排序", "哈密顿图",
    "欧拉通路", "欧拉回路", "哈密顿回路", "图的基本概念", "树的基本性质",
    "最大公约数", "最大公因数", "欧几里得算法", "线性同余方程", "模运算",
    "中国剩余定理", "费马小定理", "欧拉定理", "排列组合", "二项式定理",
    "鸽巢原理", "容斥原理", "递推关系", "特征方程", "生成函数",
)

_REQUEST_CONTEXT_MARKERS = (
    "题", "练习", "出", "生成", "来", "给", "刷", "考", "难度", "知识点",
    "讲", "解释", "复测", "再来", "换",
)


def _bounded_edit_distance(left, right, limit=1):
    """小字符串的限界 Levenshtein；超过 limit 立即返回 limit+1。"""
    if left == right:
        return 0
    if abs(len(left) - len(right)) > limit:
        return limit + 1

    # 输入法/手机键盘里相邻两个字颠倒也很常见；把一次相邻交换视为一处模糊误差。
    # 这里只在等长字符串上做 O(n) 快速检查，不引入额外依赖。
    if limit >= 1 and len(left) == len(right):
        diffs = [index for index, (a, b) in enumerate(zip(left, right)) if a != b]
        if (
            len(diffs) == 2
            and diffs[1] == diffs[0] + 1
            and left[diffs[0]] == right[diffs[1]]
            and left[diffs[1]] == right[diffs[0]]
        ):
            return 1

    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        row_min = current[0]
        for j, b in enumerate(right, 1):
            cost = 0 if a == b else 1
            distance = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + cost,
            )
            current.append(distance)
            row_min = min(row_min, distance)
        if row_min > limit:
            return limit + 1
        previous = current
    return previous[-1]


def _fuzzy_replace_once(value, term):
    """只替换一个高置信的一字误差片段。"""
    if term in value:
        return value
    term_len = len(term)
    if term_len < 4:
        return value

    strong_context = any(marker in value for marker in _REQUEST_CONTEXT_MARKERS)
    if not strong_context:
        return value

    best = None
    for width in range(max(2, term_len - 1), term_len + 2):
        if width > len(value):
            continue
        for start in range(0, len(value) - width + 1):
            piece = value[start:start + width]
            # 数字、LaTeX、ASCII 变量不参加中文词纠错。
            if re.search(r"[0-9A-Za-z_\\{}$^]", piece):
                continue
            distance = _bounded_edit_distance(piece, term, 1)
            if distance > 1:
                continue
            # 至少保留一半字符，避免把无关片段误纠成知识点。
            common = sum(1 for ch in set(piece) if ch in term)
            if common < max(2, term_len // 2):
                continue
            candidate = (distance, abs(width - term_len), start, start + width)
            if best is None or candidate < best:
                best = candidate

    if best is None:
        return value
    _, _, start, end = best
    return value[:start] + term + value[end:]


def normalize_user_request_text(text):
    """
    轻量规范化用户短指令。

    - 只对 <= 180 字的短输入启用模糊纠错；
    - 不调用模型，因此不会引入网络延迟；
    - 不修改页面展示的原始文本，只供意图/难度/知识点识别使用。
    """
    value = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    value = value.replace("，", ",").replace("。", ".").replace("？", "?").replace("！", "!")
    value = re.sub(r"\s+", "", value)
    if not value or len(value) > 180:
        return value

    for wrong, correct in sorted(
        _REQUEST_EXACT_ALIASES.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if wrong in value:
            value = value.replace(wrong, correct)

    # 量词“道”是中文输入里最常见的同音误字之一。只在后面很快出现“题/练习”时纠正，
    # 避免把普通句子里的“到/倒”全局改坏：两到图论题 -> 两道图论题。
    value = re.sub(
        r"([一二两三四五六七八九十百\d]+)[到倒](?=.{0,16}(?:题|练习))",
        r"\1道",
        value,
    )
    # 常见程度词 + “南/男”基本都是“难”的输入法误字；同样只在短指令里处理。
    value = re.sub(
        r"(非常|特别|比较|有点|有一点|稍微|稍稍|太|很|不太|不怎么|不是很|不要太|别太)[南男]",
        r"\1难",
        value,
    )

    # 输入法误字：“出一道很难得题目”中的“得”应作结构助词“的”。
    # 限定为难度修饰语紧邻“题/题目”，不能把普通的“难得”一词全局改掉。
    value = re.sub(
        r"(很难|非常难|特别难|困难|高难)得(?=题目|题)",
        r"\1的",
        value,
    )

    # 先长词后短词，避免“初级数论”被先拆成“数论”。
    for term in sorted(_REQUEST_FUZZY_TERMS, key=len, reverse=True):
        value = _fuzzy_replace_once(value, term)

    return value


def _looks_like_exercise_request_text(text):
    """识别自然语言中的出题/继续练习请求，并过滤否定、复盘和功能讨论。"""
    value = normalize_user_request_text(text)

    if not value or len(value) > 180:
        return False

    # 明确拒绝出题：不允许被后面的“出题/难题”关键词反向误触发。
    if re.search(
        r"(?:不想(?:让你)?|不要|别|不用|无需|禁止|先别|暂时别|以后别|别再|不要再)"
        r"(?:给我|帮我)?(?:再)?(?:出|生成|来|给|整|弄|安排|准备|考我|刷)"
        r".{0,10}(?:题目|题|练习)?",
        value,
    ):
        return False

    # “出题功能有 bug / 我在讨论如何生成题目”属于元讨论，不是生成命令。
    if re.search(
        r"(?:讨论|解释|分析|研究|功能|bug|代码|逻辑|识别|接口|模式|机制)"
        r".{0,14}(?:出题|生成题|题目生成|生成练习)"
        r"|(?:出题|生成题|题目生成|生成练习).{0,14}"
        r"(?:功能|bug|代码|逻辑|识别|接口|模式|机制)",
        value,
        flags=re.IGNORECASE,
    ):
        return False

    # “解释为什么出难题慢 / 出题为什么这么久”是对生成能力的提问，
    # 即使包含“出一道题”字样也不是新出题请求。
    if re.search(
        r"^(?:请|麻烦|我想|我要|给我|帮我|你能|能不能|可以)?"
        r"(?:解释|说明|分析|讨论|研究|讲讲|告诉我|为什么|怎么|如何|为何)"
        r".{0,80}(?:出题|出.{0,18}题|生成.{0,18}题|题目|难题)",
        value,
    ):
        return False
    if re.search(
        r"^(?:出题|生成题|题目生成).{0,25}(?:为什么|怎么|如何|太慢|很慢|慢|耗时|错误|异常)",
        value,
    ):
        return False

    # “给我解释/检查/解答这道题”包含“给我 + 一道题”，但明显是在处理已有题目，
    # 不能被后面的宽泛生成规则误判为“再出一道”。
    if re.search(
        r"(?:给我|帮我)(?:解释|讲解|分析|检查|批改|解答|解决|看看|看下|提示|说下思路|给思路|给答案)"
        r".{0,18}(?:这|该|上面|刚才)?(?:一?道|个)?(?:题目|题|练习)",
        value,
    ):
        return False

    # 先识别“换一个简单的 / 刚才太难了，再来个简单的”这类明确新动作。
    replacement_or_level = bool(re.search(
        r"(?:^|[，,。；;！!？?])(?:请|麻烦)?(?:给我|帮我)?"
        r"(?:再|重新)?(?:换|来|出|给|整|弄)"
        r"(?:个|道|一道|一个)?"
        r"(?:简单|基础|入门|容易|轻松|中等|适中|普通|一般|困难|高难|难|挑战|复杂)"
        r"(?:难度)?(?:点|一点|一些|点儿|的)?(?:题|练习)?(?:吧)?$",
        value,
    ))
    if replacement_or_level:
        return True

    # 单纯复盘上一道生成题，不应触发“再生成一道”。
    if re.search(
        r"(?:刚才|之前|上次|前面|你刚).{0,14}"
        r"(?:出(?:的)?|生成(?:的)?|给(?:我)?(?:的)?)"
        r".{0,8}(?:题目|题|练习)",
        value,
    ):
        return False

    if re.match(r"^(?:为什么|怎么|如何).{0,40}(?:出(?:的)?|生成(?:的)?|给(?:我)?).{0,10}(?:题目|题|练习)", value):
        return False

    # “再来一道同知识点 / 照上一题再来一道”允许省略末尾“题”字。
    # 仍须显式包含续题动词与参照语义，不会把单纯讨论“同知识点”当新请求。
    if re.fullmatch(
        r"(?:请|麻烦)?(?:给我|帮我)?(?:再|重新)?(?:来|出|换)(?:一?道|一?个)?"
        r"(?:相同|同样|同一|同)?(?:知识点|考点|类型|题型)(?:的)?(?:复测|练习|题)?(?:吧)?",
        value,
    ) or re.fullmatch(
        r"(?:请|麻烦)?(?:给我|帮我)?(?:按照|照着|参考|根据)?"
        r"(?:上一题|上一道题|刚才那题)(?:的)?(?:知识点|考点|类型|题型)?"
        r"(?:再)?(?:来|出)(?:一?道|一?个)?(?:题|练习)?(?:吧)?",
        value,
    ):
        return True

    # 常见省略“题”字的自然命令。
    if re.fullmatch(r"(?:请|麻烦)?(?:来)?考我(?:一下|下|几道?|一题|一道)?(?:吧)?", value):
        return True
    if re.fullmatch(
        r"(?:请|麻烦)?(?:陪我|让我|我想|想)?刷(?:几|一|两|二|\d+)?道?"
        r"(?:谓词逻辑|命题逻辑|逻辑|数论|计数|组合|递推|图论|图|集合|关系|函数|映射|代数|群|树|欧拉|哈密顿|邻接矩阵)?"
        r"(?:题|练习)?(?:吧)?",
        value,
    ):
        return True
    if re.fullmatch(
        r"(?:请|麻烦)?(?:给我|帮我)?(?:随机|随便|再|重新)?(?:来|出|整|弄)?"
        r"(?:一个|一道|一题)(?:题)?(?:吧)?",
        value,
    ):
        return True

    # “来个简单的 / 给个难的 / 出个中等难度的”。
    if re.fullmatch(
        r"(?:请|麻烦)?(?:给我|帮我)?(?:再|重新)?(?:换|来|出|给|整|弄)"
        r"(?:个|道|一道|一个)?"
        r"(?:简单|基础|入门|容易|轻松|中等|适中|普通|一般|困难|高难|难|挑战|复杂)"
        r"(?:难度)?(?:点|一点|一些|点儿|的)?(?:题|练习)?(?:吧)?",
        value,
    ):
        return True

    # “我想练点图论 / 想刷点关系题”。
    if re.fullmatch(
        r"(?:我)?(?:想|想要|要)?(?:练|刷|考)(?:一下|点|些|几道?)?"
        r"(?:谓词逻辑|命题逻辑|逻辑|数论|计数|组合|递推|图论|图|集合|关系|函数|映射|代数|群|树|"
        r"欧拉|哈密顿|邻接矩阵|图同构|最短路|最小生成树|二部图|拓扑排序|关系矩阵|关系运算|"
        r"同余|模运算|中国剩余定理|欧几里得算法|费马小定理|真值表|前束范式|单射|满射|双射|生成函数)"
        r"(?:题|练习)?(?:吧)?",
        value,
    ):
        return True

    # 更宽泛但仍然本地的生成命令：前面的否定/元讨论已经被过滤，
    # 因此可以安全覆盖“给我一个非常难的哈密顿图题”“安排两道同余练习”等自然说法。
    if re.search(
        r"(?:^|[,;!?])(?:请|麻烦)?(?:给我|帮我|让我|我要|我想要|想要|想)?"
        r"(?:再|重新|随机|随便|继续)?(?:来|出|生成|安排|准备|整|弄|抽|刷|练|考我)"
        r".{0,36}(?:题目|题|练习)(?:吧|呢|呗)?$",
        value,
    ):
        return True

    # “给我一个很难的哈密顿图题”省略了“出/来”，仍是清晰的生成请求；
    # 但“给我解释这道题/帮我检查这题”属于解题动作，明确排除。
    if re.fullmatch(
        r"(?:请|麻烦)?(?:给我|给|帮我)(?:再)?(?:一?个|一?道|几道?|几题)?"
        r"(?!(?:解释|讲解|分析|检查|批改|解答|解决|看看|提示|思路|答案))"
        r".{0,32}(?:题目|题|练习)(?:吧|呢|呗)?",
        value,
    ):
        return True

    # 省略“题”字但明确在要求一个难度档位的下一道练习。
    if re.search(
        r"(?:^|[,;!?])(?:请|麻烦)?(?:给我|帮我)?(?:再|重新)?(?:换|来|出|给|整|弄)"
        r"(?:一?个|一?道|个|道)?"
        r".{0,14}(?:简单|容易|轻松|不难|中等|适中|普通|一般|有点难度|稍微难|稍有挑战|困难|很难|高难|挑战|烧脑)"
        r"(?:一?点|一点儿|一些|些)?(?:的)?(?:吧|呢|呗)?$",
        value,
    ):
        return True

    # 带“题/练习”的普通生成表达。避免把“出的题/生成的题”当命令。
    if re.search(
        r"(?:请|麻烦|能否|能不能|可以|可不可以|帮我|给我|让我|我要|我想要|我想|想要|想|再|重新|随机|随便|继续|现在)?"
        r"(?:给我|帮我)?(?:再|重新|随机|随便|继续)?"
        r"(?:来|出(?!的)|生成(?!的)|安排|准备|整|弄|抽)"
        r".{0,12}(?:题目|题|练习)",
        value,
    ):
        return True

    if re.search(r"(?:给我|帮我).{0,10}(?:一道|一题|一个题|几道题|几题|题目|练习)", value):
        return True

    if re.search(
        r"(?:想|要|想要|可以|能不能|帮我|让我).{0,10}(?:做|练|刷|考)"
        r".{0,16}(?:题目|题|练习)",
        value,
    ):
        return True

    return bool(re.fullmatch(
        r"(?:请|麻烦)?(?:给我|帮我)?(?:下一道题|下一题|下一道|下一个题|"
        r"再来一道|再来一题|再来一个|再来个|再来一个题|"
        r"换一道题|换一个题|换个题|换一个|换一道|换一题)(?:吧|。|！|!)?",
        value,
    ))

def looks_like_exercise_request(text):
    """对外统一的出题请求判定，供 app.py 与 teaching.py 共用。"""
    return _looks_like_exercise_request_text(text)


def _looks_like_generated_exercise_text(text):
    value = str(text or "").strip()

    if not value:
        return False

    if re.search(
        r"(?:"
        r"【(?:题目|练习题)】"
        r"|(?:^|\n)\s*#{1,4}\s*(?:题目|练习题)\s*(?:\n|$)"
        r"|(?:^|\n)\s*\*\*(?:题目|练习题)[:：]?\*\*\s*(?:\n|$)"
        r"|(?:^|\n)\s*(?:题目|练习题)\s*[:：]?\s*(?:\n|$)"
        r")",
        value,
        flags=re.MULTILINE
    ):
        return True

    parenthesized = re.findall(
        r"(?:^|\n)\s*[（(]\s*\d{1,2}\s*[)）]\s*\S+",
        value,
        flags=re.MULTILINE
    )

    numbered = re.findall(
        r"(?:^|\n)\s*\d{1,2}\s*[、.．]\s*\S+",
        value,
        flags=re.MULTILINE
    )

    return bool(
        re.search(
            r"(?:设|已知|给定|请回答|回答以下|回答下列|求|判断|写出|计算|证明)",
            value
        )
        and (
            len(parenthesized) >= 2
            or len(numbered) >= 2
        )
    )


def _detect_mode(latest_text):
    text = _normalize(latest_text)

    # “完整解析，不要只给提示”同时含有“完整解析”和“只给提示”。
    # 这里先识别“明确拒绝仅提示”的表达，避免被 NO_SOLUTION_PATTERNS
    # 中的“只给提示”子串误伤。
    rejects_hint_only = bool(
        re.search(
            r"(?:不要|别|不用|无需)(?:再)?(?:只|仅)(?:给)?提示",
            text,
        )
    )
    if rejects_hint_only and _contains_any(text, FULL_SOLUTION_PATTERNS):
        return "full_solution"

    # 否定式要求优先级必须高于“给我答案”等子串，避免
    # “不要给我答案”被误判为完整解析。
    if _contains_any(text, NO_SOLUTION_PATTERNS):
        return "hint"
    if _contains_any(text, FULL_SOLUTION_PATTERNS):
        return "full_solution"
    # “检查我这道练习题的答案”同时含有“练习题”和“检查”，
    # 答案诊断应优先于出题请求；错题复测回答也依赖这个优先级。
    if _contains_any(text, CHECK_PATTERNS):
        return "check_answer"
    # 出题模式只接受经过“否定/元讨论过滤”的完整判定。
    # 不能再用“出题/练习题”裸子串兜底，否则
    # “不要再给我出题了 / 出题功能为什么有 bug”会被反向误判成出题请求。
    if looks_like_exercise_request(latest_text):
        return "exercise"
    if any(marker.lower() in text for marker in _INTERNAL_IMAGE_MARKERS):
        return "hint"
    if _contains_any(text, CONCEPT_PATTERNS) and not _contains_any(text, PROBLEM_PATTERNS):
        return "concept"
    return "hint"


def _detect_question_type(text, mode):
    normalized = _normalize(text)

    if mode == "exercise":
        return "出题请求"
    if mode == "concept":
        return "概念题"
    if mode == "check_answer":
        return "答案检查"
    if any(label in normalized for label in ("单选题", "多选题", "选择题")) or re.search(r"(?:请选择|选择正确|选择错误)", normalized):
        return "选择题"
    if "填空题" in normalized or re.search(r"(?:请)?填空|填入(?:适当|正确)?", normalized):
        return "填空题"
    if "证明" in normalized:
        return "证明题"
    if re.search(r"(?:画出|作图|绘制|画一|画一个|画一棵|画该|画这个)", normalized):
        return "作图题"
    if "构造" in normalized:
        return "构造题"
    if "判断" in normalized or "是否" in normalized:
        return "判断题"
    if re.match(r"^解(?!释)", normalized) or any(keyword in normalized for keyword in (
        "计算", "求", "写出", "列出", "化为", "转换为", "det(", "行列式", "矩阵", "最短路", "生成树"
    )):
        return "计算题"
    # “综合题”容易让用户误以为系统识别失败。没有明确题型信号时，
    # 使用中性的“一般题”，真正多小问/多任务的题仍可由难度与知识点体现综合度。
    return "一般题"


def _symmetry_counting_task(normalized):
    """Identify orbit-counting problems by structure, not one isolated word.

    Examples: bead necklaces modulo rotations/reflections, bracelets,
    circular colourings modulo symmetry. No AI call and no math-text edits.
    """
    value = str(normalized or "")
    subject = re.search(
        r"项链|手链|珠串|珠子|串珠|环形|环状|圆环|圆周|圆桌|手镯|"
        r"涂色|着色|染色|necklace|bracelet|colouring|coloring", value,
        flags=re.IGNORECASE,
    )
    symmetry = re.search(
        r"旋转|翻转|翻面|翻折|反射|镜像|对称|二面体|"
        r"burnside|polya|pólya|波利亚|伯恩赛德|本质不同|等价", value,
        flags=re.IGNORECASE,
    )
    count = re.search(
        r"求|多少|几种|计数|数目|种数|共有|不同|方案|排法|着色数|涂色数", value,
    )
    return bool(subject and symmetry and count)


def _constrained_binary_counting(text):
    """同时支持「二进制串不含连续...」和「不含连续...的二进制串」。"""
    normalized = _normalize(text)
    return bool(
        re.search(r"二进制串|01串|[01]串", normalized)
        and re.search(r"(?:不含|不包含|不出现|禁止|不能出现|避免).{0,25}(?:连续|相邻|子串|模式)", normalized)
    )


def _estimate_difficulty(text, knowledge_points=None, question_type="一般题"):
    """
    轻量三档难度评级。

    只返回：简单 / 中等 / 困难。
    不调用额外模型，也不参与回答提示词，避免难度功能改变原有教学行为。
    """
    value = str(text or "")
    normalized = _normalize(value)
    points = [
        str(item).strip()
        for item in (knowledge_points or [])
        if str(item).strip()
    ]

    score = 0

    # 多小问通常意味着需要组合多个步骤。
    parenthesized = re.findall(r"(?:^|\n)\s*[（(]\s*\d{1,2}\s*[）)]", value)
    numbered = re.findall(r"(?:^|\n)\s*\d{1,2}[.．、]", value)
    subquestion_count = max(len(parenthesized), len(numbered))
    if subquestion_count >= 4:
        score += 2
    elif subquestion_count >= 2:
        score += 1

    # 证明、构造、枚举全部结果一类题通常步骤更多。
    if question_type == "证明题" or any(
        keyword in normalized
        for keyword in (
            "证明", "推导", "构造", "求证", "反证",
            "所有通路", "所有回路", "所有路径", "所有方案",
        )
    ):
        score += 2

    # 常见需要连续算法/结构判断的任务。
    multi_step_keywords = (
        "同构", "欧拉通路", "欧拉回路", "哈密顿",
        "最短路", "最小生成树", "传递闭包",
        "主析取范式", "主合取范式", "前束范式",
        "生成函数", "特征方程", "特征根", "非齐次递推", "矩阵树定理",
        "二部图", "二分图", "拓扑排序", "拓扑序列", "最大匹配", "色数", "消解",
        "rsa", "线性同余", "同余方程", "模逆元", "中国剩余定理",
    )
    has_multi_step_topic = any(
        keyword in normalized
        for keyword in multi_step_keywords
    )
    if has_multi_step_topic:
        score += 1

    # 旧版大量“求最短路 / 判断同构 / 求主范式”只得到 1 分，
    # 最终仍被判成简单，导致 AI 不启用中等题的 high reasoning。
    # 当高级主题同时出现明确求解动作时，再加 1 分，使它至少进入中等。
    explicit_action = bool(re.search(
        r"(?:求|计算|判断|判定|证明|构造|画出|写出|列出|找出|确定|给出|求解|解答|化为|转换为|^解(?!释))",
        normalized,
    ))

    if has_multi_step_topic and explicit_action:
        score += 1

    # 通用“任务结构”信号：比单纯关键词更稳。
    # 同一道题同时要求“写出/求/判断/证明/说明”等两个以上不同动作，
    # 通常至少是中等；三个以上紧密任务再额外抬一档，但不会单靠文字长短判难。
    action_tokens = re.findall(
        r"(?:求解|计算|求|判断|判定|证明|求证|构造|写出|列出|找出|确定|给出|说明|画出|绘制|化为|转换为|验证|检验)",
        normalized,
    )
    action_kinds = set(action_tokens)
    if len(action_kinds) >= 2:
        score = max(score, 2)
    if len(action_kinds) >= 3 and subquestion_count >= 2:
        score += 1

    # 中文题干常把“写邻接矩阵并求通路数”写成“写...并求...”，其中“写”没有“写出”二字。
    # 直接识别两个被“并/再/然后/同时/且”连接的任务，使这类组合任务至少进入中等。
    linked_tasks = bool(re.search(
        r"(?:写|求|计算|判断|判定|证明|构造|列出|给出|画出|绘制|化为|转换为)"
        r".{1,48}(?:并|再|然后|同时|且|以及)"
        r".{0,16}(?:写|求|计算|判断|判定|证明|构造|列出|给出|画出|绘制|化为|转换为)",
        normalized,
    ))
    if linked_tasks:
        score = max(score, 2)

    # “用某定理/算法解……”中的“解”经常紧跟在术语后面，旧正则会漏掉。
    # 只在其后马上出现变量、数字、方程/同余等求解对象时把它当作求解动作。
    inline_solve = bool(re.search(
        r"解(?=(?:[a-z0-9]|同余|方程|递推|不等式|矩阵|关系|系统))",
        normalized,
    ))
    if has_multi_step_topic and inline_solve:
        score = max(score, 2)

    # 有些自然题干不会直接出现“非齐次递推/矩阵树定理”等大词，
    # 但分类器已经可靠落到了这些知识点。用知识点作为第二信号，
    # 只判断“是否属于典型多步任务”，不按知识点数量机械抬难度。
    advanced_points = {
        "关系闭包", "范式", "前束范式", "线性同余方程",
        "模逆与中国剩余定理", "RSA公钥密码", "生成函数", "线性齐次递推", "非齐次递推",
        "图同构", "欧拉图", "哈密顿图", "最短路", "最小生成树", "矩阵树定理",
        "图匹配", "拓扑排序", "平面图",
    }
    has_advanced_point = any(point in advanced_points for point in points)
    if has_advanced_point and not has_multi_step_topic:
        score += 1
        if explicit_action:
            score += 1

    # 大指数取模不是直接计算大整数：通常需要快速幂、幂的周期、
    # 费马小定理等。题干虽短，不能因此一律标为“简单”。
    # 只匹配“明确出现底数^大指数 + 模/除数取余”的结构，避免把
    # 普通幂运算、指数为 2 的基础计算或一般整数取余错误抬档。
    power_match = re.search(
        r"(?<![A-Za-z0-9_])(?P<base>\d+)\s*\^\s*(?:"
        r"\{\s*(?P<braced>\d{2,12})\s*\}|"
        r"\(\s*(?P<parenthesized>\d{2,12})\s*\)|"
        r"(?P<plain>\d{2,12}))",
        normalized,
    )
    mod_match = re.search(
        r"(?:\bmod(?:ulo)?\s*\(?\s*|\\(?:pmod|bmod|mod)\s*\{?\s*|模\s*|除以?\s*)"
        r"(?P<modulus>\d+)",
        normalized,
    )
    if power_match and mod_match:
        exponent = int(next(power_match.group(name) for name in
                            ("braced", "parenthesized", "plain")
                            if power_match.group(name) is not None))
        base = int(power_match.group("base"))
        modulus = int(mod_match.group("modulus"))
        has_remainder_context = bool(re.search(
            r"余数|取余|求余|余多少|模|mod|同余|\\pmod|\\bmod", normalized,
        ))
        if exponent >= 20 and modulus > 1 and base % modulus != 0 and has_remainder_context:
            score = max(score, 2)

    # 关系幂题常只写 R²、R³，没有“复合关系”等自然语言关键字。
    # 求两个不同的关系幂一般需要重复关系复合，不应一概判为简单。
    if "关系" in normalized:
        powers = re.findall(
            r"(?<![a-z0-9_])r\s*(?:\^\s*\{?\s*(\d+)\s*\}?|([³⁴⁵⁶⁷⁸⁹]))",
            normalized,
        )
        if len({a or b for a, b in powers}) >= 2:
            score = max(score, 2)

    # 截图回归：扩展欧几里得算法不是一次 gcd 计算。
    # 当题目还要找到 gcd 的整数线性组合 / 贝祖系数时，至少有
    # 欧几里得算法和回代两个步骤；不能按简短计算题直接判简单。
    bezout_equation = bool(re.search(
        r"(?<![0-9a-z_])\d+\s*[xy]\s*[+\-]\s*\d+\s*[xy]\s*=",
        normalized,
    ))
    bezout_language = bool(re.search(
        r"(?:整数\s*[xy]|整数解|贝祖|裴蜀|扩展欧几里得|线性组合)",
        normalized,
    ))
    if bezout_equation and (
        "gcd" in normalized or "最大公约数" in normalized or bezout_language
    ):
        score = max(score, 2)

    # 一道题需要同时判定关系的多种性质，不能仅因数据规模小就标简单。
    # 只判断其中一个性质的概念题仍保持原有规则。
    relation_properties = set()
    for canonical, patterns in {
        "自反": ("自反性", "自反"),
        "反自反": ("反自反性", "反自反"),
        "对称": ("对称性", "对称"),
        "反对称": ("反对称性", "反对称"),
        "传递": ("传递性", "传递"),
    }.items():
        if any(label in normalized for label in patterns):
            relation_properties.add(canonical)
    if "反自反" in relation_properties:
        relation_properties.discard("自反")
    if "反对称" in relation_properties:
        relation_properties.discard("对称")
    if len(relation_properties) >= 3 and ("关系" in normalized or "r=" in normalized):
        score = max(score, 2)

    # 映射/函数的复合约束计数不是一步代入题。
    # 例如“统计满足 f(f(x))=f(x) / f(f(x))=x 的映射个数”需要分析
    # 不动点、像集或置换循环结构；即使集合只有 5 个元素，仍属于明显多步计数。
    nested_function = bool(re.search(
        r"[a-z]\s*\(\s*[a-z]\s*\(\s*[a-z]\s*\)\s*\)",
        normalized,
    ))
    mapping_count = bool(
        ("映射" in normalized or "函数" in normalized)
        and re.search(r"(?:个数|多少(?:个)?|共有多少|计数|数量)", normalized)
    )
    if nested_function and mapping_count:
        score = max(score, 3)
        if subquestion_count >= 2 or re.search(
            r"(?:f\s*\(\s*f\s*\([^)]*\)\s*\)\s*=\s*f\s*\(|"
            r"f\s*\(\s*f\s*\([^)]*\)\s*\)\s*=\s*[a-z])",
            normalized,
        ):
            score = max(score, 4)

    # 证明一个结构性结论后还要“利用/应用”它继续证明或判定，属于明显多阶段推理。
    if question_type == "证明题" and re.search(
        r"(?:并|再|然后|进而|从而).{0,12}(?:利用|应用|证明|推出|说明)",
        normalized,
    ):
        score = max(score, 4)

    # 生成函数 + 带上下界的整数解计数通常要构造截断多项式并取系数，
    # 比普通二项式展开明显更复杂。
    if "生成函数" in normalized and re.search(r"[xyz]\d*\s*[≤<>=]", normalized) and re.search(r"=\s*\d+", normalized):
        score = max(score, 4)

    # 全点对最短路、负权和正确性说明同时出现时，已超出一次套算法的基础题。
    if (
        ("最短路" in normalized or "最短路径" in normalized)
        and re.search(r"(?:所有|全部|任意).{0,6}(?:点对|顶点对|两点)", normalized)
        and re.search(r"(?:负权|负边|负权边)", normalized)
        and re.search(r"(?:证明|说明|验证).{0,8}(?:正确|正确性|为何)", normalized)
    ):
        score = max(score, 4)

    # 图谱分析 + 矩阵树定理是两类相互依赖的计算，不能仅凭“两小问”
    # 把完整拉普拉斯谱与生成树计数的组合题判作普通中等题。
    if (
        re.search(r"拉普拉斯|laplacian", normalized)
        and re.search(r"特征值|特征向量|谱", normalized)
        and re.search(r"矩阵树定理|生成树", normalized)
    ):
        score = max(score, 4)

    # 关系满足多个公理限制时，同时优化 |R| 并枚举所有极值配置，
    # 涉及极值结构与非平凡计数；与仅检查自反/对称/传递性区别开。
    if (
        "关系" in normalized
        and re.search(r"(?:最大值|最小值|最大|最小|最多|最少|极值)", normalized)
        and re.search(r"(?:共有多少|多少个|个数|数量|计数|多少种|多少个关系)", normalized)
        and re.search(r"(?:自反|对称|传递|反对称|等价关系|偏序)", normalized)
    ):
        score = max(score, 4)

    # 按旋转/反射等对称关系计数，需要按等价类（通常使用 Burnside/Polya）
    # 分析，而不是普通排列。颜色次数等额外限制还需要再结合条件计数。
    # 不因题面没有直接写“排列组合/伯恩赛德”就判成简单。
    if _symmetry_counting_task(normalized):
        score = max(score, 2)
        constrained_colours = bool(re.search(
            r"(?:至少|至多|恰好|正好|仅|必须|都要|均|每种|限制|次数|出现|"
            r"不相邻|相邻|禁止|必须包含|其中.{0,18}次)", normalized
        ))
        if constrained_colours or subquestion_count >= 2:
            score = max(score, 4)

    # 结构化枚举计数：不是因为有“图/个数”就判困难，而是同时要求
    # 枚举一类数学结构，并逐步叠加独立限制。用于图、关系、映射等，
    # 避免每次遇到新的综合计数题都靠补具体题干关键词。
    counts_structures = bool(re.search(
        r"(?:求|计算|统计|确定|问|写出).{0,72}(?:个数|数量|多少(?:个|种)|数目|种数|方案数|总数)"
        r"|(?:多少(?:个|种)|个数|种数|方案数|数量).{0,16}(?:图|关系|映射|函数)",
        normalized,
    ))
    # 区分“数符合条件的图”与“给定图中数顶点/边”：后者只是基础计算。
    if "图" in normalized and not re.search(
        r"图\s*[a-z]?\s*(?:的)?(?:个数|数量|种数|数目|方案数)"
        r"|(?:几|多少)(?:个|种)(?:不同)?图", normalized,
    ):
        counts_structures = False
    structures = bool(re.search(
        r"(?:无向图|有向图|简单图|连通图|二分图|二部图|图g|"
        r"关系r|关系|映射|函数|排列|组合|方案)", normalized,
    ))
    graph_constraints = {
        "连通": bool(re.search(r"连通", normalized)),
        "边数限制": bool(re.search(r"(?:恰|正好|刚好|至多|至少|恰有|共有|恰好).{0,8}(?:条)?边|\d+\s*条边", normalized)),
        "二分": bool(re.search(r"二分图|二部图|二分", normalized)),
        "结构约束": bool(re.search(r"无环|欧拉|哈密顿|正则图|平面图|完全匹配|度数限制|度序列", normalized)),
    }
    abstract_constraints = {
        "性质": bool(re.search(r"自反|对称|反对称|传递|单射|满射|双射|幂等", normalized)),
        "精确数目": bool(re.search(r"恰好|恰有|正好|至少|至多|只含|且仅|刚好", normalized)),
        "附加条件": bool(re.search(r"同时|满足|并且|且|其中", normalized)),
    }
    active_constraints = (
        sum(graph_constraints.values()) if "图" in normalized
        else sum(abstract_constraints.values())
    )
    if counts_structures and structures and active_constraints >= 1:
        score = max(score, 2)
        # 多个子任务逐层加约束，或三个互不相同的条件下进行结构计数，
        # 往往需要分类讨论、容斥或构造性推导，属于非平凡计数。
        if active_constraints >= 2 and (subquestion_count >= 2 or active_constraints >= 3):
            score = max(score, 4)

    if _constrained_binary_counting(normalized):
        # 禁止子串的变长计数通常要建状态或递推，不能按单步计数评为简单。
        score = max(score, 2)

    # 规模或额外输出要求会显著增加步骤，但不单靠长文本抬难度。
    if re.search(r"(?:[7-9]|\d{2,})\s*(?:个)?顶点", normalized):
        score += 1
    if re.search(r"(?:给出|写出|构造).{0,12}(?:同构)?映射", normalized):
        score += 1
    # 对多小问已加过难度分，不再因末尾“并写出全部解”等同一任务的
    # 答案格式要求重复计分；单问里的额外独立任务仍可加分。
    if subquestion_count < 2 and re.search(
        r"(?:并|同时|再).{0,16}(?:画|构造|证明|给出|写出)", normalized
    ):
        score += 1

    # 不按 knowledge_points 的数量直接抬难度。该列表会自动带出前置/相关点，
    # 数量多不等于题目本身难，避免普通关系题被虚高成“困难”。

    # 很短的概念/直接判断题保持简单，不因为术语本身被抬高。
    if question_type == "概念题" and len(normalized) <= 80:
        score = min(score, 1)

    # “列出 A×B、再求 |A×B|”虽然有两个小问，却都是同一个
    # 笛卡尔积的基础操作，不应机械因两种动作就判中等。
    if (
        subquestion_count <= 2
        and not has_multi_step_topic
        and not has_advanced_point
        and re.search(r"(?:写出|列出).{0,24}(?:[a-z]\s*×\s*[a-z]|\\times)", normalized)
        and re.search(r"(?:求|计算).{0,12}\|\s*[a-z]\s*×\s*[a-z]\s*\|", normalized)
    ):
        score = min(score, 1)

    if score >= 4:
        return "困难"
    if score >= 2:
        return "中等"
    return "简单"


def _keyword_weight(keyword):
    # 更长、更具体的术语权重更高，减轻“群”“树”等短词误触发。
    length = len(keyword)
    if length >= 6:
        return 5
    if length >= 4:
        return 3
    if length >= 2:
        return 2
    return 1



# 题目不一定直接写出“数论/组合/图论”等课程名称。
# 先识别数学结构，再将其映射回既有的课程模块与知识图谱节点。
# 这里全是高辨识度的模式：无法判断时应当保留待识别，不强塞“综合”。
@lru_cache(maxsize=2048)
def _structural_topic_evidence(text):
    value = _normalize(text)
    compact = re.sub(r"\s+", "", value)
    matches = []

    def add(category, point, *patterns):
        if any(re.search(pattern, compact, re.IGNORECASE) for pattern in patterns):
            matches.append((category, point))

    # 幂取模/求余：覆盖自然中文、LaTeX、% 与标准同余写法。
    add("初等数论", "同余与模运算",
        r"(?:除以|被)\d+(?:所得|的|时|后)?(?:的)?(?:余数|余几|余多少|求余|取余)",
        r"(?:余数|求余|取余|余多少).{0,45}(?:除以|模)\d+",
        r"\\(?:pmod|bmod|mod)\{?\d+",
        r"\bmod(?:ulo)?\(?\d+",
        r"\d+\^\{?\d+\}?%\d+",
        r"(?:\d+|[a-z])\s*≡.{0,55}(?:mod|模|\(mod|\\pmod)",
        r"\d+(?:的|次)?(?:幂|次方|\^\{?\d+\}?).{0,24}(?:模\d+|除以\d+).{0,12}(?:余|结果)",
        r"(?:模|对)\d+(?:取余|求余|的余数|取模)",
    )
    add("初等数论", "整除与素数",
        r"(?:\d+|[a-z])\|(?:\d+|[a-z])",
        r"(?:求|找|判断|列出).{0,22}(?:质因数|质数|素数|因子|因数|约数|整除)",
    )
    add("初等数论", "最大公因数与欧几里得算法",
        r"(?:gcd|lcm)\s*\(", r"裴蜀|贝祖|扩展欧几里得|辗转相除",
    )
    add("初等数论", "欧拉定理与费马小定理",
        r"(?:\\varphi|\\phi|φ|ϕ)\s*\(?\d+", r"欧拉函数|费马小定理",
    )
    add("集合与关系", "集合运算",
        r"(?:[a-z]|\})\s*(?:∩|∪|\\cap|\\cup|⊆|⊂|\\subseteq|\\subset)\s*(?:[a-z]|\{)",
        r"(?:幂集|求补集|对称差|求并集|求交集)",
    )
    add("集合与关系", "关系性质",
        r"(?:关系r|二元关系|关系矩阵).{0,45}(?:自反|反自反|传递|对称)",
    )
    add("集合与关系", "偏序关系",
        r"(?:哈斯图|hassediagram|偏序集|极大元|极小元|上界|下界|最小上界|最大下界)",
    )
    add("函数", "单射满射双射",
        r"(?:单射|满射|双射|一一对应|双射映射)",
    )
    add("函数", "函数与映射",
        r"[a-z]\s*:\s*[a-z]\s*(?:→|\\to|\\rightarrow)\s*[a-z]",
    )
    add("谓词逻辑", "量词",
        r"∀|∃|\\forall|\\exists",
    )
    add("命题逻辑", "范式",
        r"\bcnf\b|\bdnf\b|(?:主析取|主合取|极小项|极大项)",
    )
    add("计数与组合", "排列与组合",
        r"(?:c|a)\s*\(?\d+\s*,\s*\d+\)?",
        r"从\d+(?:名|个|种|件|人|本)?.{0,12}(?:中)?(?:选|挑|取)\d+(?:名|个|种|件|人|本)?",
    )
    add("计数与组合", "鸽巢原理",
        r"(?:至少有|必有).{0,20}(?:相同|同一).{0,15}(?:抽屉|盒子|生日|余数)",
    )
    add("递推关系", "递推关系建模",
        r"(?:a|f|t)_(?:\{?n\}?|n)=(?:(?![，。；]).){0,90}(?:a|f|t)_\{?n[-−]\d+\}?",
        r"(?:fibonacci|斐波那契|递推数列|递归式)",
    )
    add("图论", "图的基本概念",
        r"(?:顶点|结点|节点|度序列).{0,20}(?:边|度|图)",
        r"(?:k|c|p)_?\{?\d+\}?(?:的|图|有|中)",
    )
    add("图论", "图同构",
        r"(?:图|顶点|邻接).{0,45}同构|同构.{0,45}(?:图|顶点|邻接)",
    )
    add("图论", "邻接矩阵",
        r"邻接矩阵|(?:a\^\{?\d+\}?).{0,28}(?:长度为\d+|通路数|路径数)",
    )
    add("图论", "欧拉图", r"欧拉(?:通路|路径|回路|路|图)")
    add("图论", "哈密顿图", r"哈密顿(?:通路|路径|回路|路|图)")
    add("图论", "最短路", r"(?:dijkstra|dijsktra|最短路径|最短路)")
    add("图论", "最小生成树", r"(?:kruskal|prim算法|最小生成树)")
    add("代数结构", "群与子群", r"(?:子群|循环群|陪集|群的阶|拉格朗日定理)")
    add("代数结构", "代数系统", r"(?:封闭性|结合律|交换律|单位元|逆元).{0,20}(?:二元运算|运算\*|运算∘)")

    # 不依赖教材关键词的语义结构：逻辑连接词 + 命题变元。
    # 避免把函数 f:A→B、图的有向边误判为命题逻辑。
    has_logic_variables = bool(re.search(r"(?<![a-z])(?:p|q|r)(?![a-z])", value))
    logical_connectives = bool(re.search(
        r"[∧∨¬↔⇒⇔⊕]|\\(?:land|lor|neg|lnot|leftrightarrow|implies|iff)\b|"
        r"(?<![a-z])(?:p|q|r)\s*(?:→|->)\s*(?:p|q|r)(?![a-z])",
        value,
    ))
    if has_logic_variables and logical_connectives and not re.search(r"[∀∃]|\\(?:forall|exists)", value):
        matches.append(("命题逻辑", "逻辑联结词"))
        if re.search(r"(?:重言|永真|等价|等值|恒真|等值式|↔|⇔|\\leftrightarrow)", value):
            matches.append(("命题逻辑", "逻辑等价"))
    if re.search(r"(?:重言式|矛盾式|永真式|永假式|可满足式|永真命题)", value):
        matches.append(("命题逻辑", "命题与真值"))

    # A×B 是离散数学中最常用的笛卡尔积记法；只认可大写集合名，
    # 避免把一般的向量叉积误判为集合题。
    if re.search(r"(?<![a-z])[a-z]\s*(?:×|\\times)\s*[a-z](?![a-z])", value, re.I) and re.search(
        r"(?:写出|列出|元素|集合|关系|笛卡尔|有序对|a\s*×\s*b)", value, re.I
    ):
        matches.append(("集合与关系", "笛卡尔积与关系"))

    # P(A) / 2^|A| 是幂集；P(x) 仅在有集合语境时才能算幂集。
    if re.search(r"(?:幂集|power\s*set|(?:求|计算|写出).{0,20}p\([a-z]\))", value) and re.search(
        r"(?:集合|子集|幂集|power\s*set|\{[^{}]*\})", value,
    ):
        matches.append(("集合与关系", "集合运算"))

    # 鸽巢原理的自然语言：需保证/至少多少人/必有两人 同月、同天。
    if re.search(r"(?:至少|最少|保证|确保|必然|必有).{0,32}(?:人|学生|同学|物品|球|袜子)", value) and re.search(
        r"(?:同一|相同|一样|两人|两名|两件|两个|重复).{0,22}(?:月|月份|生日|颜色|抽屉|盒子)|"
        r"(?:生日|月份|颜色|盒子).{0,25}(?:同一|相同|一样|两人|两名|重复)", value,
    ):
        matches.append(("计数与组合", "鸽巢原理"))
    # 另一种句型：保证“有两人生日在同一月份”，主语在后。
    if re.search(r"(?:保证|至少|最少).{0,28}(?:两人|两名).{0,25}(?:生日|月份|同月)", value):
        matches.append(("计数与组合", "鸽巢原理"))

    # 二进制串禁用相邻模式 => 有限状态/递推计数；不应默认当简单二项式题。
    if re.search(r"(?:二进制|[01]串|01串|0-1串).{0,60}(?:不含|禁止|不出现|不能出现|不包含|避免).{0,22}(?:连续|相邻|子串|模式)", value) or re.search(
        r"(?:不含|禁止|不出现|不包含).{0,30}(?:连续|相邻).{0,35}(?:二进制|01串|[01]串)", value,
    ):
        matches.append(("递推关系", "递推关系建模"))
        matches.append(("计数与组合", "基本计数原理"))
    if re.search(r"(?:长度为|长为|长度是|位数为)[a-z0-9]+.{0,25}(?:二进制串|01串|[01]串)", value) and re.search(
        r"(?:个数|多少|数量|计数|方案)", value,
    ):
        matches.append(("计数与组合", "基本计数原理"))

    # 奇偶性 / 整数整除的证明题。仅凭“证明”不能归为证明与归纳。
    if re.search(r"(?:偶数|奇数|奇偶性|被\d+整除|整除|整数解)", value) and re.search(
        r"(?:n\s*(?:\^\s*\{?\d+\}?|[²³])|所有整数|任意整数|恒为|必为|总为|总是)", value,
    ):
        matches.append(("初等数论", "整除与素数"))

    # 以代数结构为问句中心。模 n 运算只是定义群/环的背景，不是主考数论。
    if re.search(r"(?:构成|成为|是|满足|判断|证明).{0,25}(?:群|半群|子群|环|域|幺半群)|"
                 r"(?:群|环|域).{0,25}(?:公理|封闭|逆元|单位元|结合)", value):
        matches.append(("代数结构", "群与子群" if "群" in value else "代数系统"))

    return list(dict.fromkeys(matches))

def _score_categories(text):
    normalized = _normalize(text)
    scores = {}

    for category, rule in CATEGORY_RULES.items():
        score = 0

        # 分类不仅看大类关键词，也使用各知识点自身的别名。
        # 旧版只扫描 rule["keywords"]，会漏掉“色数 / 组合数 / 关系的幂”等
        # 已经存在于 point 规则、却没有重复写进大类关键词的自然表达。
        keywords = []
        seen = set()
        for keyword in rule.get("keywords", []):
            if isinstance(keyword, str) and keyword not in seen:
                seen.add(keyword)
                keywords.append(keyword)
        for point_keywords in (rule.get("points") or {}).values():
            for keyword in point_keywords or []:
                if isinstance(keyword, str) and keyword not in seen:
                    seen.add(keyword)
                    keywords.append(keyword)

        for keyword in keywords:
            if keyword.lower() in normalized:
                score += _keyword_weight(keyword)
        scores[category] = score

    # 题目型结构证据优先于简短的泛化词（如“树”“像”“群”）。
    for category, _point in _structural_topic_evidence(text):
        scores[category] = scores.get(category, 0) + 8

    # 量词符号本身就是谓词逻辑的强信号，不能被“否定/公式”等
    # 命题逻辑通用词压过去。
    if "∀" in normalized or "∃" in normalized:
        scores["谓词逻辑"] = scores.get("谓词逻辑", 0) + 8

    # 自然中文“3^2024除以17所得余数”与“3^2024 mod 17”语义相同。
    # 必须同时出现具体除数及余数语义，避免把泛泛的“除法”误判为数论。
    if re.search(r"除以?\s*\d+.{0,16}(?:余数|余几|求余)", normalized):
        scores["初等数论"] = scores.get("初等数论", 0) + 6

    # 题干常写“设 A 上的关系 R=...，求 R² 与 R³”，不能因为出现
    # “集合 A”便只判成集合运算。R 的幂是关系复合/关系运算。
    if "关系" in normalized and re.search(
        r"(?<![a-z0-9_])r\s*(?:\^\s*\{?\s*\d+\s*\}?|[³⁴⁵⁶⁷⁸⁹])",
        normalized,
    ):
        scores["集合与关系"] = scores.get("集合与关系", 0) + 5

    # “同构”同时存在于代数结构与图论语境。出现明确图语境时，
    # 应判作图论，不让“同构”这个单词把图同构误拉到代数结构。
    graph_isomorphism = bool(re.search(
        r"(?:图|顶点|边|邻接|g\s*[_-]?\d+|图\s*\d+).{0,36}同构"
        r"|同构.{0,36}(?:图|顶点|边|邻接|g\s*[_-]?\d+|图\s*\d+)",
        normalized,
        flags=re.IGNORECASE,
    ))
    if graph_isomorphism:
        scores["图论"] = scores.get("图论", 0) + 8
        scores["代数结构"] = max(
            0,
            scores.get("代数结构", 0) - _keyword_weight("同构"),
        )

    # 分类目标优先于背景符号：例如“模4加法构成群”主模块是代数结构，
    # “图的同构”主模块是图论，不被共用词和相关数学工具抢占。
    algebra_goal = re.search(
        r"(?:构成|成为|是否是|是不是|判断是否|证明.{0,8}是|满足).{0,20}(?:群|环|域|半群)"
        r"|(?:群|环|域).{0,24}(?:公理|封闭性|结合律|逆元|单位元)", normalized,
    )
    if algebra_goal:
        scores["代数结构"] = max(scores.get("代数结构", 0), max(scores.values(), default=0) + 7)
        if not re.search(r"(?:求余|余数|同余方程|整除|素数|模逆元|费马|欧拉函数)", normalized):
            scores["初等数论"] = min(scores.get("初等数论", 0), 2)

    # 明确指定证明方法时，归纳/反证本身是主考点；递推式只是证明对象。
    if re.search(r"(?:用|利用|采用|通过|使用).{0,6}(?:强归纳法|完全归纳法|数学归纳法|归纳法|反证法)", normalized):
        scores["证明与归纳"] = max(scores.get("证明与归纳", 0), max(scores.values(), default=0) + 4)

    # 公式重言式/命题等价属于命题逻辑；仅有“→”不能断言。
    if re.search(r"(?:重言式|永真式|逻辑等价|等值式)", normalized) or (
        re.search(r"[∧∨¬↔]|\\(?:land|lor|neg|leftrightarrow)", normalized)
        and re.search(r"(?<![a-z])(?:p|q|r)(?![a-z])", normalized)
    ):
        scores["命题逻辑"] = max(scores.get("命题逻辑", 0), max(scores.values(), default=0) + 4)

    # 递推计数的主模块是递推关系，但保留“计数与组合”为相关模块。
    if _constrained_binary_counting(normalized):
        scores["递推关系"] = max(scores.get("递推关系", 0), scores.get("计数与组合", 0) + 3)

    return scores


def _extract_points(text, category):
    normalized = _normalize(text)
    rule = CATEGORY_RULES.get(category)
    if not rule:
        return []

    scored = []
    for point, keywords in rule["points"].items():
        hit_score = sum(
            _keyword_weight(keyword)
            for keyword in keywords
            if keyword.lower() in normalized
        )
        if hit_score:
            scored.append((hit_score, point))

    scored.sort(key=lambda item: (-item[0], item[1]))
    result = [point for _score, point in scored[:4]]

    # 公式/自然语言结构可以提供教材术语之外的具体知识点。
    # 只插入当前已选择模块的节点，避免把别的模块混入知识图谱。
    structural_points = [point for detected_category, point in _structural_topic_evidence(text)
                         if detected_category == category]
    if structural_points:
        result = list(dict.fromkeys(structural_points + result))[:4]

    if category == "计数与组合" and _symmetry_counting_task(normalized):
        result = ["排列与组合"] + [point for point in result if point != "排列与组合"]
        result = result[:4]

    if category == "初等数论" and re.search(
        r"除以?\s*\d+.{0,16}(?:余数|余几|求余)", normalized
    ) and "同余与模运算" not in result:
        result.insert(0, "同余与模运算")
        result = result[:4]

    # “两个图是否同构”常只写“图 + 同构”，不会出现连续的“图同构”四个字。
    # 分类器已经能借助图语境确认是图论，这里把它稳定登记为独立知识点，
    # 避免右侧知识点和知识图谱只显示“图的基本概念”。
    if category == "图论" and re.search(
        r"(?:图|顶点|边|邻接|g\s*[_-]?\d+|图\s*\d+).{0,36}同构"
        r"|同构.{0,36}(?:图|顶点|边|邻接|g\s*[_-]?\d+|图\s*\d+)",
        normalized,
        flags=re.IGNORECASE,
    ):
        result = ["图同构"] + [point for point in result if point != "图同构"]
        result = result[:4]

    # 公式型递推题往往不会写“齐次/非齐次”四个字，只给出 a_n 与前项关系。
    # 先把 RHS 中所有“系数 × 前项”删除；若仍有常数/n/指数项等残余，
    # 则按非齐次登记，否则按线性齐次登记。这样可直接覆盖常见教材写法。
    if category == "递推关系":
        recurrence_match = re.search(
            r"a(?:_?\{?n\}?|ₙ)\s*=\s*([^\n，,；;]+)",
            normalized,
            flags=re.IGNORECASE,
        )
        if recurrence_match and re.search(
            r"a(?:_?\{?n\s*[-−]\s*\d+\}?|ₙ[₋-]?\d*)",
            recurrence_match.group(1),
            flags=re.IGNORECASE,
        ):
            rhs = recurrence_match.group(1)
            residual = re.sub(
                r"[+\-−]?\s*(?:\d+(?:\.\d+)?\s*\*?\s*)?"
                r"a(?:_?\{?n\s*[-−]\s*\d+\}?|ₙ[₋-]?\d*)",
                "",
                rhs,
                flags=re.IGNORECASE,
            )
            residual = re.sub(r"[\s+\-−()]+", "", residual)
            residual = re.sub(
                r"(?:的)?(?:通项公式|通项|一般项|表达式)$",
                "",
                residual,
            )
            recurrence_point = "非齐次递推" if residual else "线性齐次递推"
            result = [recurrence_point] + [
                point
                for point in result
                if point not in ("线性齐次递推", "非齐次递推")
            ]
            result = result[:4]

    # 关系幂的符号型表达，优先归到“关系运算”，而不是“集合运算”。
    if category == "集合与关系" and "关系" in normalized and re.search(
        r"(?<![a-z0-9_])r\s*(?:\^\s*\{?\s*\d+\s*\}?|[³⁴⁵⁶⁷⁸⁹])",
        normalized,
    ):
        result = ["关系运算"] + [point for point in result if point != "关系运算"]
        result = result[:4]

    if result:
        return result

    compact = re.sub(r"\s+", "", normalized)

    # 结构化兜底只在没有任何 point 关键词时启用。
    if category == "命题逻辑" and re.search(r"(?:^|[^a-z])(?:cnf|dnf)(?:$|[^a-z])", normalized, flags=re.IGNORECASE):
        return ["范式"]
    if category == "谓词逻辑":
        if "∀" in normalized or "∃" in normalized:
            if "否定" in normalized:
                return ["量词推理与否定", "量词"]
            return ["量词"]
        if re.search(r"(?:符号化|形式化|翻译成|写成).{0,20}(?:公式|逻辑式)?", compact):
            return ["量词", "谓词与个体域"]
    if category == "集合与关系":
        if re.search(r"[A-Za-z](?:×|\\times|x)[A-Za-z]", compact):
            return ["笛卡尔积与关系"]
        if re.search(r"(?:^|[^a-z])r(?:\^\d+|[²³⁴⁵⁶⁷⁸⁹])", compact):
            return ["关系运算"]
    if category == "初等数论" and re.search(r"(?:φ|\\varphi|\\phi)\(?\d+", compact):
        return ["欧拉定理与费马小定理"]
    if category == "计数与组合":
        if "生日相同" in compact or "生日一样" in compact:
            return ["鸽巢原理"]
        if re.search(r"(?:排成一排|排队|排列|从\d+.*(?:选|取)\d+|二进制串)", compact):
            return ["排列与组合"]
    if category == "递推关系" and re.search(r"a(?:_?\{?n\}?|ₙ)=", compact, flags=re.IGNORECASE):
        # 常数项/额外项存在时按非齐次优先，否则至少能落到递推建模。
        if re.search(r"a(?:_?\{?n\}?|ₙ)=.{0,80}a(?:_?\{?n[-−]\d+\}?|ₙ).*(?:[+−-]\d+|n)", compact, flags=re.IGNORECASE):
            return ["非齐次递推"]
        return ["递推关系建模"]
    if category == "图论":
        if "色数" in compact:
            return ["图着色"]
        if re.search(r"(?:^|[^a-z])(?:k|c|p)(?:_?\{?\d+\}?|_?n)(?:$|[^a-z])", normalized, flags=re.IGNORECASE):
            return ["图的基本概念"]
    if category == "初等数论":
        if re.search(r"(?:模|mod|同余).{0,16}逆元|逆元.{0,16}(?:模|mod|同余)", normalized, flags=re.IGNORECASE):
            return ["模逆与中国剩余定理"]
    if category == "代数结构":
        if re.search(r"(?:运算|二元运算).{0,20}(?:结合|交换|封闭|单位元|幺元)|(?:结合律|交换律|封闭性)", normalized):
            return ["代数系统"]

    return []


def _recover_discrete_math_category(text, scores):
    normalized = _normalize(text)
    compact = re.sub(r"\s+", "", normalized)

    # 先补“教材词没有直接出现，但结构上高度明确”的自然表达/数学符号。
    # 这些规则只在常规关键词完全没有命中时使用，不覆盖高置信度分类。
    if re.search(r"(?:^|[^a-z])(?:cnf|dnf)(?:$|[^a-z])", normalized, flags=re.IGNORECASE):
        return "命题逻辑"

    if (
        re.search(r"(?:符号化|形式化|翻译成(?:谓词|逻辑)?公式|写成(?:谓词|逻辑)?公式)", compact)
        and re.search(r"(?:所有|任意|每个|存在|有的|至少一个|没有一个|任何)", compact)
    ):
        return "谓词逻辑"

    # A×B / A\times B 这类纯符号集合题。
    if (
        re.search(r"[A-Za-z]\s*(?:×|\\times|x)\s*[A-Za-z]", normalized)
        and ("{" in text or "集合" in normalized or "笛卡尔" in normalized)
    ):
        return "集合与关系"

    # “求 R² / R^3”在离散数学语境中通常是关系的幂。
    if re.search(r"(?:^|[^a-z])r\s*(?:\^\s*\d+|[²³⁴⁵⁶⁷⁸⁹])", normalized):
        return "集合与关系"

    # 欧拉函数常直接写成 φ(n) / \varphi(n)。
    if re.search(r"(?:φ|\\varphi|\\phi)\s*\(\s*\d+", normalized):
        return "初等数论"

    # “3 模 7 的逆元”常不会写成“模逆元”这个连续术语。
    if re.search(r"(?:模|mod|同余).{0,16}逆元|逆元.{0,16}(?:模|mod|同余)", normalized, flags=re.IGNORECASE):
        return "初等数论"

    # 代数系统性质题常只问“这个运算是否结合/封闭”，不出现“群/环”等名词。
    if re.search(r"(?:运算|二元运算).{0,20}(?:结合|交换|封闭|单位元|幺元)|(?:结合律|交换律|封闭性)", normalized):
        return "代数结构"

    # 常见自然语言计数题：不强迫用户必须写“排列/组合/鸽巢”术语。
    if re.search(r"(?:本|个|名|人|物).{0,10}(?:不同).{0,10}(?:排成一排|排队|排列)", compact):
        return "计数与组合"
    if re.search(r"从\d+(?:名|个)?.{0,8}(?:中)?(?:选|挑|取)\d+(?:名|个)?", compact):
        return "计数与组合"
    if "生日相同" in compact or "生日一样" in compact:
        return "计数与组合"
    if re.search(r"二进制串.{0,18}(?:恰有|正好有|包含)\d+个?1", compact):
        return "计数与组合"

    # 没写“递推”二字，但式子本身已经是 a_n 与前项的递推关系。
    if re.search(
        r"a(?:_?\{?n\}?|ₙ)\s*=.{0,80}a(?:_?\{?n\s*[-−]\s*\d+\}?|ₙ[₋-]?\d*)",
        compact,
        flags=re.IGNORECASE,
    ):
        return "递推关系"

    # K5 / K_5 / K_{5} / C_n / P_n 等标准图记号。
    if re.search(r"(?:^|[^a-z])(?:k|c|p)\s*(?:_?\{?\d+\}?|_?n)(?:$|[^a-z])", normalized, flags=re.IGNORECASE):
        return "图论"

    fallback_patterns = [
        ("图论", [
            "度序列", "度数列", "简单图", "图化", "可图化", "简单图化", "可简单图化", "havel", "hakimi", "havel-hakimi",
            "握手定理", "实现度序列", "邻接矩阵", "邻接表", "顶点", "边", "图 g", "图g", "欧拉", "哈密顿",
        ]),
        ("集合与关系", [
            "关系", "集合", "等价关系", "偏序", "闭包", "关系矩阵", "笛卡尔积", "等价类", "划分",
        ]),
        ("函数", ["单射", "满射", "双射", "映射", "原像", "逆函数"]),
        ("命题逻辑", ["真值表", "命题", "蕴含", "逻辑等价", "析取范式", "合取范式"]),
        ("谓词逻辑", ["谓词", "量词", "全称", "存在量词", "自由变元"]),
        ("证明与归纳", ["归纳法", "反证法", "直接证明", "强归纳"]),
        ("计数与组合", ["排列", "组合", "容斥", "鸽巢", "抽屉原理", "生成函数"]),
        ("递推关系", ["递推", "递归关系", "特征方程", "非齐次"]),
        ("初等数论", ["同余", "整除", "欧拉函数", "费马小定理", "欧几里得"]),
        ("代数结构", ["群", "子群", "同态", "同构", "环", "域", "布尔代数"]),
    ]

    for category, keywords in fallback_patterns:
        if any(keyword.lower() in normalized for keyword in keywords):
            return category

    # 不再用“离散数学综合”冒充具体分类。规则没有证据时保留待识别，
    # 前端会对旧/待识别题目自动重新分析；具体离散数学术语继续在上面的规则中补全。
    return "待识别"


def _classify_content(text):
    # 只对“短自然语言指令”做错字/同音字规范化。数学题面中的上标、
    # LaTeX、集合符号等必须原样保留，否则 NFKC 会把 R² 这类结构改坏。
    raw_text = str(text or "")
    math_dense = bool(
        "【题目】" in raw_text
        or re.search(r"[=≡∈⊆⊂{}\[\]$^]", raw_text)
        or len(re.findall(r"\d", raw_text)) >= 4
        or raw_text.count("\n") >= 2
    )
    analysis_text = (
        normalize_user_request_text(raw_text)
        if len(raw_text) <= 180 and not math_dense
        else raw_text
    )
    scores = _score_categories(analysis_text)
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    primary, top_score = ordered[0] if ordered else ("待识别", 0)

    # Equivalent configurations of a necklace / circular colouring belong
    # to counting, even when the problem never says “permutation/combination”.
    if _symmetry_counting_task(_normalize(analysis_text)):
        primary = "计数与组合"
        top_score = max(top_score, 7)
        ordered = sorted(
            [(category, (7 if category == "计数与组合" else score))
             for category, score in scores.items()],
            key=lambda item: (-item[1], item[0]),
        )

    if top_score <= 0:
        recovered = _recover_discrete_math_category(analysis_text, scores)
        return {
            "category": recovered,
            "related_categories": [],
            "knowledge_points": _extract_points(analysis_text, recovered) if recovered in CATEGORY_RULES else [],
            "confidence": "低" if recovered == "待识别" else "中",
            # recover 规则本身已经提供了结构证据。给明确恢复出的分类一个
            # 最低有效分，使“什么是 / 如何 / 纯符号题”可以成为新的当前题，
            # 而不是被继续绑定到上一道题。
            "score": 0 if recovered == "待识别" else 1,
        }

    second_score = ordered[1][1] if len(ordered) > 1 else 0

    evidence_categories = {
        category for category, _point in _structural_topic_evidence(analysis_text)
    }
    related = [
        category
        for category, score in ordered[1:]
        if (score >= max(4, int(top_score * 0.40))
            and (category in evidence_categories or score >= max(6, int(top_score * 0.70))))
    ][:3]

    if top_score >= 9 or (top_score >= 6 and top_score >= second_score + 3):
        confidence = "高"
    elif top_score >= 3:
        confidence = "中"
    else:
        confidence = "低"

    return {
        "category": primary,
        "related_categories": related,
        "knowledge_points": _extract_points(analysis_text, primary),
        "confidence": confidence,
        "score": top_score,
    }




def classification_needs_semantic_fallback(teaching):
    """有限度的高风险复核，不为正常高置信度题增加二次 AI 调用。"""
    if not isinstance(teaching, dict):
        return False
    if teaching.get("category") == "待识别":
        return True
    # 冲突性证据且仅靠弱规则判定，交给后台语义分类判断。
    return teaching.get("confidence") == "低" or (
        teaching.get("confidence") == "中"
        and len(teaching.get("related_categories") or []) >= 2
    )

def _is_image_input(text):
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in _INTERNAL_IMAGE_MARKERS)


def analyze_question(text):
    """分析单条题目文本，主要用于测试和独立调用。"""
    mode = _detect_mode(text)
    classified = _classify_content(text)

    focus_points = _infer_focus_points(
        [{"role": "user", "content": text}],
        classified["category"],
        classified["knowledge_points"],
        text,
        mode,
        classified["score"],
    )

    question_type = _detect_question_type(text, mode)

    related_points = []
    for related_category in classified["related_categories"]:
        for point in _extract_points(text, related_category):
            if point not in classified["knowledge_points"] and point not in related_points:
                related_points.append(point)
            if len(related_points) >= 3:
                break
        if len(related_points) >= 3:
            break

    result = {
        "category": classified["category"],
        "related_categories": classified["related_categories"],
        "knowledge_points": classified["knowledge_points"],
        "related_knowledge_points": related_points,
        "focus_points": focus_points,
        "question_type": question_type,
        "difficulty": _estimate_difficulty(
            text,
            classified["knowledge_points"],
            question_type,
        ),
        "mode": mode,
        "mode_label": MODE_LABELS[mode],
        "confidence": classified["confidence"],
        "input_source": "图片识题" if _is_image_input(text) else "文本输入",
    }

    return _enrich_with_graph(result)


def _normalize_question_reference_text(text):
    return re.sub(r"\s+", "", str(text or "").strip())


def _has_explicit_exercise_generation_cue(text):
    value = _normalize_question_reference_text(text)
    if not value or len(value) > 140:
        return False

    return bool(
        re.search(r"(?:出|生成|来|安排|准备).{0,10}(?:题目|题|练习)", value)
        or re.search(r"给我(?:来|出|生成)?(?:一|两|二|几|个|道|\d){1,3}.{0,10}(?:题目|题|练习)", value)
        or re.search(r"(?:再来|再出|再给|换)(?:一|两|二|几|个|道|\d){0,3}(?:题目|题|练习)", value)
        or re.search(r"(?:想|要|想要|可以|能不能).{0,8}(?:做|练|刷).{0,16}(?:题目|题|练习)", value)
        or re.fullmatch(r"(?:请)?给我(?:下一道题|下一题|下一个题)", value)
    )


def _parse_question_reference_number(raw):
    """把 1~99 的阿拉伯/中文题号转换为整数。"""
    value = str(raw or "").strip().replace("两", "二")
    if not value:
        return None

    if re.fullmatch(r"\d{1,3}", value):
        number = int(value)
        return number if number >= 1 else None

    digits = {
        "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    }

    if value in digits:
        return digits[value] or None

    if re.fullmatch(r"[一二三四五六七八九]?十[一二三四五六七八九]?", value):
        left, _, right = value.partition("十")
        tens = digits[left] if left else 1
        ones = digits[right] if right else 0
        number = tens * 10 + ones
        return number if number >= 1 else None

    return None


def _question_ordinal_reference(text):
    """识别会话历史的“第一题 / 第一大题 / 第2个练习题”。

    故意不识别“第2小题 / 第2问”：那是当前大题内部的小问，不是历史第2题。
    """
    value = _normalize_question_reference_text(text)
    if not value or len(value) > 90:
        return None

    if re.search(r"倒数第[零一二三四五六七八九十两\d]{1,4}", value):
        return None

    match = re.search(
        r"第([零一二三四五六七八九十两\d]{1,4})(?:个|道)?(?:大|练习|例|习)?题(?:目)?",
        value,
    )
    if not match:
        return None

    return _parse_question_reference_number(match.group(1))


def _question_reverse_ordinal_reference(text):
    value = _normalize_question_reference_text(text)
    if not value or len(value) > 90:
        return None

    match = re.search(
        r"倒数第([零一二三四五六七八九十两\d]{1,4})(?:个|道)?(?:大|练习|例|习)?题(?:目)?",
        value,
    )
    if not match:
        return None

    return _parse_question_reference_number(match.group(1))


def _question_boundary_reference(text):
    value = _normalize_question_reference_text(text)
    if not value or len(value) > 90:
        return ""

    if re.search(r"(?:最开始|最早|开头|起初)(?:的)?(?:那|这|一)?(?:道|个)?(?:大|练习)?题(?:目)?", value):
        return "first"

    if re.search(r"(?:最后|最末|最晚|最新)(?:的)?(?:那|这|一)?(?:道|个)?(?:大|练习)?题(?:目)?", value):
        return "last"

    if (
        re.search(r"(?:当前|现在|目前|正在讲|刚才|刚刚)(?:的)?(?:这|那|一)?(?:道|个)?(?:大|练习)?题(?:目)?", value)
        or re.fullmatch(r"(?:这|那|本)(?:一)?(?:道|个)?(?:大)?题(?:目)?(?:呢|吗|啊|呀|吧|不(?:太|怎么)?会|不会|怎么做|如何做|再讲一下|讲一下|继续|提示一下)?", value)
    ):
        return "current"

    return ""


def _parse_relative_question_offset(text):
    value = _normalize_question_reference_text(text)
    if not value:
        return None

    # “最后一道题”包含“后一道题”字面子串，先排除边界指代。
    if re.search(
        r"(?:最后|最末|最晚|最新|最开始|最早|开头|起初)(?:的)?(?:那|这|一)?(?:道|个)?(?:大|练习)?题(?:目)?",
        value,
    ):
        return None

    if re.search(r"(?:上上|前前)(?:一)?(?:道|个)?(?:大|练习)?题", value):
        return -2
    if re.search(r"(?:下下|后后)(?:一)?(?:道|个)?(?:大|练习)?题", value):
        return 2
    if re.search(r"(?:再|又)(?:往|向)?(?:上|前)(?:一)?(?:道|个)?(?:大|练习)?题", value):
        return -2
    if re.search(r"(?:再|又)(?:往|向)?(?:下|后)(?:一)?(?:道|个)?(?:大|练习)?题", value):
        return 2

    match = re.search(
        r"(?:往|向)(?:前|上)([零一二三四五六七八九十两\d]{1,4})(?:道|个)?(?:大|练习)?题",
        value,
    )
    if match:
        steps = _parse_question_reference_number(match.group(1))
        return -steps if steps else None

    match = re.search(
        r"(?:往|向)(?:后|下)([零一二三四五六七八九十两\d]{1,4})(?:道|个)?(?:大|练习)?题",
        value,
    )
    if match:
        steps = _parse_question_reference_number(match.group(1))
        return steps if steps else None

    if re.search(
        r"(?:上一道(?:大|练习)?题|上一(?:大|练习)?题|上一个(?:大|练习)?题|"
        r"前一道(?:大|练习)?题|前一(?:大|练习)?题|前一个(?:大|练习)?题|"
        r"前面(?:的)?(?:那|这|一)?(?:道|个)?(?:大|练习)?题|"
        r"刚才上一道(?:大|练习)?题|刚才上一(?:大|练习)?题)",
        value,
    ):
        return -1

    if re.search(
        r"(?:下一道(?:大|练习)?题|下一(?:大|练习)?题|下一个(?:大|练习)?题|"
        r"后一道(?:大|练习)?题|后一(?:大|练习)?题|后一个(?:大|练习)?题|"
        r"后面(?:的)?(?:那|这|一)?(?:道|个)?(?:大|练习)?题)",
        value,
    ):
        return 1

    return None


def _relative_question_reference(text):
    value = _normalize_question_reference_text(text)
    if not value or len(value) > 110:
        return None

    # 当前大题内部的“第2小题 / 第2问”及其前后小问，不参与会话题目导航。
    if re.search(
        r"第[零一二三四五六七八九十两\d]{1,4}(?:个|道)?小题|第[零一二三四五六七八九十两\d]{1,4}问",
        value,
    ):
        return None

    reverse_match = re.search(
        r"倒数第([零一二三四五六七八九十两\d]{1,4})(?:个|道)?(?:大|练习|例|习)?题(?:目)?",
        value,
    )
    if reverse_match:
        anchor_reverse_ordinal = _parse_question_reference_number(reverse_match.group(1))
        suffix = value[reverse_match.end():]
        offset = _parse_relative_question_offset(suffix)
        if anchor_reverse_ordinal and offset:
            return {
                "offset": offset,
                "anchor_ordinal": None,
                "anchor_reverse_ordinal": anchor_reverse_ordinal,
                "anchor_boundary": "",
            }

    normal_match = re.search(
        r"第([零一二三四五六七八九十两\d]{1,4})(?:个|道)?(?:大|练习|例|习)?题(?:目)?",
        value,
    )
    if normal_match and "倒数第" not in value:
        anchor_ordinal = _parse_question_reference_number(normal_match.group(1))
        suffix = value[normal_match.end():]
        offset = _parse_relative_question_offset(suffix)
        if anchor_ordinal and offset:
            return {
                "offset": offset,
                "anchor_ordinal": anchor_ordinal,
                "anchor_reverse_ordinal": None,
                "anchor_boundary": "",
            }

    boundary_anchors = (
        ("first", r"(?:最开始|最早|开头|起初)(?:的)?(?:那|这|一)?(?:道|个)?(?:大|练习)?题(?:目)?"),
        ("last", r"(?:最后|最末|最晚|最新)(?:的)?(?:那|这|一)?(?:道|个)?(?:大|练习)?题(?:目)?"),
        ("current", r"(?:当前|现在|目前|正在讲|刚才|刚刚)(?:的)?(?:这|那|一)?(?:道|个)?(?:大|练习)?题(?:目)?"),
    )

    for anchor_boundary, pattern in boundary_anchors:
        match = re.search(pattern, value)
        if not match:
            continue
        suffix = value[match.end():]
        offset = _parse_relative_question_offset(suffix)
        if offset:
            return {
                "offset": offset,
                "anchor_ordinal": None,
                "anchor_reverse_ordinal": None,
                "anchor_boundary": anchor_boundary,
            }

    offset = _parse_relative_question_offset(value)
    if not offset:
        return None

    return {
        "offset": offset,
        "anchor_ordinal": None,
        "anchor_reverse_ordinal": None,
        "anchor_boundary": "",
    }

def _is_previous_question_followup(text):
    value = _normalize_question_reference_text(text)
    if not value or len(value) > 100 or _has_explicit_exercise_generation_cue(value):
        return False

    reference = _relative_question_reference(value)
    return bool(reference and reference["offset"] < 0)


def _is_next_question_followup(text):
    value = _normalize_question_reference_text(text)
    if not value or len(value) > 100 or _has_explicit_exercise_generation_cue(value):
        return False

    reference = _relative_question_reference(value)
    return bool(reference and reference["offset"] > 0)


def _is_ordinal_question_followup(text):
    value = _normalize_question_reference_text(text)
    ordinal = _question_ordinal_reference(value)
    if ordinal is None or len(value) > 90:
        return False

    if _has_explicit_exercise_generation_cue(value):
        return False

    if re.search(
        r"第[零一二三四五六七八九十两\d]{1,4}(?:个|道)?(?:大|练习|例|习)?题(?:目)?[：:]?"
        r"(?:已知|设|给定|若|求|证明|计算|判断|写出|列出)",
        value,
    ):
        return False

    if _relative_question_reference(value):
        return False

    if re.search(
        r"(?:还记得|回到|返回|切到|跳到|再讲|讲一下|解释|提示|不(?:太|怎么)?会|不会|有点不会|"
        r"做不来|没思路|没头绪|卡住|不懂|没懂|还是不会|继续|完整解析|答案|怎么做|如何做|看一下)",
        value,
    ):
        return True

    return bool(re.fullmatch(
        r"第[零一二三四五六七八九十两\d]{1,4}(?:个|道)?(?:大|练习|例|习)?题(?:目)?(?:呢|吗|啊|呀|吧)?",
        value,
    ))


def _is_reverse_ordinal_question_followup(text):
    value = _normalize_question_reference_text(text)
    return bool(
        _question_reverse_ordinal_reference(value)
        and len(value) <= 90
        and not _has_explicit_exercise_generation_cue(value)
    )


def _is_boundary_question_followup(text):
    value = _normalize_question_reference_text(text)
    return bool(
        _question_boundary_reference(value)
        and not _has_explicit_exercise_generation_cue(value)
    )


def _is_question_navigation_followup(text):
    return (
        _is_previous_question_followup(text)
        or _is_next_question_followup(text)
        or _is_ordinal_question_followup(text)
        or _is_reverse_ordinal_question_followup(text)
        or _is_boundary_question_followup(text)
    )


def _structural_question_reference(text):
    value = _normalize_question_reference_text(text)
    if not value:
        return None

    relative = _relative_question_reference(value)
    if relative:
        return {
            "kind": "relative",
            "offset": relative["offset"],
            "anchor_ordinal": relative["anchor_ordinal"],
            "anchor_reverse_ordinal": relative["anchor_reverse_ordinal"],
            "anchor_boundary": relative["anchor_boundary"],
        }

    reverse_ordinal = _question_reverse_ordinal_reference(value)
    if reverse_ordinal:
        return {"kind": "reverse_ordinal", "ordinal": reverse_ordinal}

    ordinal = _question_ordinal_reference(value)
    if ordinal:
        return {"kind": "ordinal", "ordinal": ordinal}

    boundary = _question_boundary_reference(value)
    if boundary:
        return {"kind": boundary}

    return None


def _resolve_structural_history_position(reference, count, current_pos):
    if not reference or count <= 0:
        return None

    kind = reference.get("kind")
    position = None

    if kind == "relative":
        anchor = reference.get("anchor_ordinal")
        reverse_anchor = reference.get("anchor_reverse_ordinal")
        boundary_anchor = reference.get("anchor_boundary")

        if anchor:
            base = anchor - 1
        elif reverse_anchor:
            base = count - reverse_anchor
        elif boundary_anchor == "first":
            base = 0
        elif boundary_anchor == "last":
            base = count - 1
        else:
            base = current_pos

        if base is None or base < 0 or base >= count:
            return None
        position = base + int(reference.get("offset") or 0)
    elif kind == "ordinal":
        position = int(reference.get("ordinal") or 0) - 1
    elif kind == "reverse_ordinal":
        position = count - int(reference.get("ordinal") or 0)
    elif kind == "first":
        position = 0
    elif kind == "last":
        position = count - 1
    elif kind == "current":
        position = current_pos

    if position is None or position < 0 or position >= count:
        return None

    return position

def _looks_like_explicit_generated_question(text):
    """只把带明确题目标题的 assistant 内容视为 AI 生成题，避免把普通分步讲解误判为新题。"""
    value = str(text or "").strip()
    if not value:
        return False

    return bool(re.search(
        r"(?:"
        r"【(?:题目|练习题)】"
        r"|(?:^|\n)\s*#{1,4}\s*(?:题目|练习题)\s*(?:\n|$)"
        r"|(?:^|\n)\s*\*\*(?:题目|练习题)[:：]?\*\*\s*(?:\n|$)"
        r"|(?:^|\n)\s*(?:题目|练习题)\s*[:：]?\s*(?:\n|$)"
        r")",
        value,
        flags=re.MULTILINE,
    ))


def _extract_image_printed_question(text):
    value = str(text or "")
    markers = ("【题目文字】", "【题干与公式识别】")
    marker = next((item for item in markers if item in value), None)
    if not marker:
        return ""

    start = value.find(marker) + len(marker)
    ends = []
    for end_marker in ("【图形信息】", "【图形结构识别】", "【我的要求】"):
        pos = value.find(end_marker, start)
        if pos >= 0:
            ends.append(pos)

    end = min(ends) if ends else len(value)
    return value[start:end].strip()


def _looks_like_formal_printed_question(text):
    value = str(text or "").strip()
    if not value:
        return False

    compact = re.sub(r"\s+", "", value)

    if re.search(r"(?:^|\n)\s*(?:[（(]\s*\d{1,2}\s*[）)]|\d{1,2}[.．、])\s*\S+", value):
        return True

    if re.search(r"^(?:设|已知|给定|若|求|求解|证明|计算|判断|写出|列出|选择|填空|解答|下列)", compact):
        return True

    if re.search(r"^(?:图中|图[A-Za-z0-9_]*|在图.+中).*(?:求|判断|证明|计算|写出|列出|多少|几个|是否)", compact):
        return True

    if re.search(r"[？?]$", compact) and re.search(
        r"命题|公式|集合|关系|函数|图|矩阵|树|通路|回路|欧拉|哈密顿|递推|组合|群|环|域",
        compact,
    ):
        return True

    return False


def _extract_image_user_request(text):
    value = str(text or "")

    # API 消息使用这组内部标记。
    match = re.search(
        r"【本轮唯一需要执行的用户请求】\s*([\s\S]*?)\s*【本轮请求结束】",
        value,
    )
    if match:
        return match.group(1).strip()

    # 兼容聊天历史中的可见图片消息。
    marker = "【我的要求】"
    start = value.find(marker)
    if start < 0:
        return ""
    return value[start + len(marker):].strip()


def _looks_like_formal_image_request(text):
    """纯图情况下，只把明确的解题任务登记为题目。

    “这里有几个点/几条边/这是什么”属于临时观察询问：照常回答，
    但不进入题目历史、难度评级和错题本。
    """
    value = re.sub(r"\s+", "", str(text or "").strip())
    if not value:
        return False

    # 明确排除用户要求不要登记的观察型问题。
    if re.search(
        r"(?:这里|这个|图里|图中|里面|这张图).{0,10}"
        r"(?:有)?(?:多少|几个|几条)(?:个)?(?:点|顶点|节点|边|线)"
        r"|(?:多少|几个|几条)(?:个)?(?:点|顶点|节点|边|线)",
        value,
    ):
        return False

    if re.search(r"^(?:这|这个|这里|图里|图中|里面).{0,12}(?:是什么|什么意思|怎么看|怎么读)$", value):
        return False

    # 自然语言里的正式解题动作。
    if re.search(
        r"^(?:请|麻烦|帮我|帮忙)?(?:看一下|看看|帮我看下)?"
        r"(?:判断(?:一下)?|判定|证明|求证|求解|计算|算(?:一下)?|求(?:一下|出)?|"
        r"写出|写一下|列出|列一下|找出|找一下|给出|构造|画出|画一下|作出|确定|说明)",
        value,
    ):
        return True

    # 省略动词但语义仍明显是在完成一道图论题。
    return bool(re.search(
        r"(?:是否|是不是).{0,12}(?:同构|连通|欧拉图|哈密顿图|树|平面图|二分图)"
        r"|(?:同不同构|同构吗|是否同构|是否连通|欧拉(?:通路|回路|图)|"
        r"哈密顿(?:通路|回路|图)|最短(?:路|路径)|最小生成树|生成树|"
        r"邻接矩阵|关联矩阵|度数序列|割点|割边|桥|着色|色数)",
        value,
    ))


def _looks_like_user_question_for_context(text):
    """判断一条 user 消息是否是在提出新的学习题，而不是控制/追问语句。"""
    value = str(text or "").strip()
    if not value:
        return False

    if _is_question_navigation_followup(value) or looks_like_exercise_request(value):
        return False

    if _detect_mode(value) == "check_answer":
        return False

    classified = _classify_content(value)
    if classified["score"] <= 0:
        return False

    if _is_image_input(value):
        printed = _extract_image_printed_question(value)
        if _looks_like_formal_printed_question(printed):
            return True
        return _looks_like_formal_image_request(
            _extract_image_user_request(value)
        )

    compact = re.sub(r"\s+", "", value)

    # 明确题干/问法；概念型“什么是欧拉图”也属于一道当前学习问题。
    if re.search(
        r"(?:^|[。；;!?！？])(?:设|已知|给定|若|求|求解|证明|计算|判断|写出|列出|选择|填空)",
        value,
    ):
        return True

    if re.search(r"^(?:什么是|为什么|为何|如何|怎样)", compact):
        return True

    if re.search(r"[？?]$", compact) and len(compact) >= 6:
        return True

    if re.search(r"[（(]\s*\d{1,2}\s*[)）]", value):
        return True

    return len(value) >= 60


def extract_current_request(text):
    """题目锚点用于定位；教学模式只读取其中的本轮请求。"""
    value = str(text or "")
    match = re.search(r"【本轮唯一需要执行的用户请求】\s*([\s\S]*?)\s*【本轮请求结束】", value)
    return match.group(1).strip() if match else value.strip()


def _extract_explicit_target_question(text):
    """读取前端为“上一道题”导航附带的明确目标题干。"""
    value = str(text or "")
    start_marker = "【当前指向题目】"
    end_marker = "【当前指向题目结束】"

    start = value.find(start_marker)
    if start < 0:
        return ""

    start += len(start_marker)
    end = value.find(end_marker, start)
    target = value[start:end if end >= 0 else None].strip()
    return target


def _active_question_from_messages(messages):
    """按对话顺序恢复当前所指题目。

    新题会把当前题切到自己；普通“继续/再解释”保持当前题；
    支持“第几题 / 倒数第几题 / 上一道 / 下一道 / 第一题 / 最后一题 / 当前题”等导航。
    若前端已经显式附带“【当前指向题目】”，则优先采用该题，
    避免最近消息窗口截断或相对导航重复计算后猜错。
    """
    history = []
    active_pos = None
    explicit_active = None

    for item in messages if isinstance(messages, list) else []:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = item.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        content = content.strip()
        if not content:
            continue

        if role == "user":
            explicit_target = _extract_explicit_target_question(content)
            if explicit_target:
                classified = _classify_content(explicit_target)
                if classified["score"] > 0:
                    explicit_active = (explicit_target, classified)
                continue

            if _is_question_navigation_followup(content):
                if history:
                    reference = _structural_question_reference(content)
                    base_pos = (
                        len(history) - 1
                        if active_pos is None
                        else active_pos
                    )
                    resolved = _resolve_structural_history_position(
                        reference,
                        len(history),
                        base_pos,
                    )
                    if resolved is not None:
                        active_pos = resolved
                continue

        is_question = False
        if role == "user":
            is_question = _looks_like_user_question_for_context(content)
        elif role == "assistant":
            is_question = _looks_like_explicit_generated_question(content)

        if not is_question:
            continue

        classified = _classify_content(content)
        if classified["score"] <= 0:
            continue

        history.append((content, classified))
        active_pos = len(history) - 1
        explicit_active = None

    if explicit_active is not None:
        return explicit_active

    if active_pos is None or not history:
        return None

    return history[active_pos]


def analyze_messages(messages):
    """
    结合最近对话分析当前教学状态。

    关键点：
    - “教学模式”只看学生本轮最新要求，避免历史里的“给我答案”污染当前意图；
    - 新题出现时切换到新题；普通短追问保持当前题；
    - 支持绝对题号、倒序题号、上一道/下一道、第一道/最后一道/当前题等会话题目导航；
    - “第2小题 / 第2问”保留为当前大题内部小问，不误当成会话历史第2题。
    """
    if not isinstance(messages, list):
        return analyze_question("")

    user_messages = []
    for item in messages:
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = item.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        content = content.strip()
        if content:
            user_messages.append(content)

    if not user_messages:
        return analyze_question("")

    latest = user_messages[-1]
    mode = _detect_mode(extract_current_request(latest))

    active = _active_question_from_messages(messages)

    if active:
        classification_text, classified = active
    else:
        # 极少数没有识别出“题目消息”的旧对话，保留原来的最近可识别主题兜底。
        latest_classified = _classify_content(latest)
        classification_text = latest
        classified = latest_classified

        if latest_classified["score"] < 3:
            for previous in reversed(user_messages[:-1]):
                previous_classified = _classify_content(previous)
                if previous_classified["score"] >= 3:
                    classification_text = previous
                    classified = previous_classified
                    break

    input_source = (
        "图片识题"
        if _is_image_input(classification_text) or _is_image_input(latest)
        else "文本输入"
    )

    focus_points = _infer_focus_points(
        messages,
        classified["category"],
        classified["knowledge_points"],
        classification_text,
        mode,
        classified["score"],
    )

    question_type = _detect_question_type(classification_text, mode)

    return _enrich_with_graph({
        "category": classified["category"],
        "related_categories": classified["related_categories"],
        "knowledge_points": classified["knowledge_points"],
        "focus_points": focus_points,
        "question_type": question_type,
        "difficulty": _estimate_difficulty(
            classification_text,
            classified["knowledge_points"],
            question_type,
        ),
        "mode": mode,
        "mode_label": MODE_LABELS[mode],
        "confidence": classified["confidence"],
        "input_source": input_source,
    })


def teaching_prompt(context):
    """把确定性分类结果转换为本轮 AI 的教学控制提示。"""
    context = context or {}
    category = context.get("category") or "待识别"
    related = context.get("related_categories") or []
    points = context.get("knowledge_points") or []
    focus_points = context.get("focus_points") or []
    question_type = context.get("question_type") or "一般题"
    mode = context.get("mode") or "hint"
    mode_label = context.get("mode_label") or MODE_LABELS["hint"]
    confidence = context.get("confidence") or "低"
    input_source = context.get("input_source") or "文本输入"
    prerequisite_points = context.get("prerequisite_points") or []
    knowledge_path = context.get("knowledge_path") or []
    difficulty = context.get("difficulty") if context.get("difficulty") in ("简单", "中等", "困难") else ""
    exercise_target_difficulty = (
        context.get("exercise_target_difficulty")
        if context.get("exercise_target_difficulty") in ("简单", "中等", "困难")
        else (difficulty or "中等")
    )

    retest_core_points = [
        str(item).strip() for item in (context.get("retest_core_points") or [])
        if str(item).strip()
    ][:4]
    normalized_exercise_request = str(
        context.get("normalized_exercise_request") or ""
    ).strip()[:180]

    points_text = "、".join(points) if points else "暂未可靠识别"
    focus_text = "、".join(focus_points) if focus_points else "暂未识别出突出难点"
    related_text = "、".join(related) if related else "无"
    prerequisites_text = "、".join(prerequisite_points) if prerequisite_points else "无明确前置知识"
    path_text = " → ".join(knowledge_path) if knowledge_path else "暂无"

    exercise_difficulty_instruction = {
        "简单": (
            "目标难度严格为简单：只考一个核心知识点，题意直接，通常1到2个关键步骤即可完成；"
            "不要叠加多个高阶考点，不要故意增加繁琐计算。"
        ),
        "中等": (
            "目标难度严格为中等：围绕1到2个核心知识点，安排连续的两到三步推理或计算。"
            "优先设计1到2个彼此关联的小问，第二问最好需要使用第一问的结论或在同一结构上继续分析；"
            "例如欧几里得算法后继续求贝祖系数，关系矩阵后继续判断多种性质，邻接矩阵后继续分析固定长度通路。"
            "不要只给一步即可直接计算的 gcd、集合元素列举、定义照抄、单次代入、只求一个矩阵元素等基础题；"
            "也不要用三个以上互不相关任务堆成假难度。"
            "除非当前知识点确实无法合理构造中等题，否则不得主动降为简单。"
            "输出前必须在内部自检：若熟练学生一眼一步即可完成，就重新构造；若任务过多则降低复杂度。"
            "不要输出自检过程，只输出最终达到中等难度的题目。"
        ),
        "困难": (
            "目标难度严格为困难：必须需要明显的多步推理、结构分析、非平凡计数/构造，或两个紧密关联知识点的组合；"
            "最好包含至少两个相互依赖的任务，或一个需要分类讨论/证明/构造的核心任务。"
            "不能只靠换大数字、直接套定义、简单集合列举、单次 gcd/矩阵填写来冒充困难，也不能只把中等题多加一个无关小问。"
            "但必须仍在当前离散数学知识范围内，不用偏题怪题制造假难度。"
            "除非当前知识点本身无法合理形成困难题，否则不得降为简单或普通直接题。"
            "输出前在内部自检：如果一个熟练学生能用一两个直接步骤完成，就重新构造更有推理深度的题目；"
            "不要输出自检过程，只输出最终困难题。"
        ),
    }[exercise_target_difficulty]
    if retest_core_points and exercise_target_difficulty == "中等":
        exercise_difficulty_instruction += (
            "本次复测存在多个必须同时考查的核心考点；请减少数字规模、合并相互依赖的小问来控制整体难度，"
            "不要机械地把多考点理解为必须出困难题，也不要遗漏任何一项。"
        )

    mode_instruction = {
        "hint": (
            "默认只做提示式辅导：先说明关键知识点，再给1到2个下一步提示；"
            "不要直接给最终答案或完整推导，最后可用一个问题引导学生继续。"
        ),
        "full_solution": (
            "学生已明确要求完整答案，可以给出完整、分步且可核验的解答。"
        ),
        "concept": (
            "这是概念理解请求，可以直接解释概念，并配一个简短例子；不必强行使用提示模式。"
        ),
        "exercise": (
            "学生要求生成练习。用户可见部分必须严格只包含题目本身。"
            + (
                f"系统对本轮短指令的本地纠错结果为：{normalized_exercise_request}。"
                "它只用于理解用户可能的错别字/同音字，不得改写数学题面。"
                if normalized_exercise_request else ""
            )
            + f"本次练习目标难度为{exercise_target_difficulty}。{exercise_difficulty_instruction}"
            + (
                "本次是错题的多考点复测，以下考点每项均须在题干中得到实质考查："
                + "、".join(retest_core_points) + "。可缩小数字或图规模控制在目标难度，"
                "但不能只选其中一项，也不能仅在题干里提及而不实际考查。"
                if retest_core_points else ""
            )
            + "如果请求附有【当前指向题目】，以这道题作为同知识点练习的唯一参照，"
            "保持其核心考点，变换条件或数值；不要取用会话里另一道题的考点，也不要回答原题。"
            "固定使用“【题目】”作为题干标题；标题前不要写“好的、给你一道题”等开场白。"
            "题目后绝对不要附提示、思路提示、解题思路、思路、关键点、引导问题、解题方向、答案、解析、"
            "‘你先试试/卡住再告诉我’等任何教学话术。"
            "题目条件必须自洽、信息充分、确有答案；不要设计无解却要求唯一数值答案的题。"
            "生成前在内部快速检查题意、可解性和隐藏答案是否一致，禁止编造未经核算的最终结果。"
            "在整条回答最后，额外追加一个仅供系统读取的隐藏答案块，格式必须严格为："
            "[[WRONGBOOK_ANSWER]]最终答案[[/WRONGBOOK_ANSWER]]。"
            "隐藏答案块里只写最终答案本身，绝对不要写理由、计算过程、解析或提示。"
            "如果有多个小问，只按(1)(2)(3)分别给最终结果。"
            "除【题目】、题干和隐藏答案块外，不允许输出其它内容。"
        ),
        "check_answer": (
            "学生在检查自己的作答。开头先用一句自然中文明确判断："
            "如果全部正确，说“这次作答正确”；如果存在任何实质错误，说“这次作答有错误”；"
            "如果信息不足，说“现有信息不足以判断”。然后再指出正确之处、错误类型和最早出错位置，"
            "先给纠正方向，不自动把整题完整答案全部展开。"
        ),
    }.get(mode, "采用提示式辅导，不直接替学生完成整道题。")

    return (
        "\n\n【本轮教学分析（系统内部控制信息）】\n"
        f"输入来源：{input_source}\n"
        f"所属模块：{category}\n"
        f"相关模块：{related_text}\n"
        f"问题类型：{question_type}\n"
        f"知识点：{points_text}\n"
        f"本题难点：{focus_text}\n"
        f"前置知识：{prerequisites_text}\n"
        f"知识脉络：{path_text}\n"
        f"教学模式：{mode_label}\n"
        f"分类置信度：{confidence}\n"
        f"执行要求：{mode_instruction}\n"
        "‘本题难点’描述的是题目本身，不代表学生实际不会；回答仍必须以学生当前问题为准。\n"
        "若当前问题正涉及本题难点，可以优先解释该环节；若学生的提问或作答确实暴露困难，再结合前置知识进行提示。\n"
        "分类结果只是教学辅助信号，不是事实来源。若分类与题目实际内容冲突，"
        "必须以题目内容为准，不得为了迎合标签而编造知识点。"
    )
