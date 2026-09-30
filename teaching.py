import json
import re
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
            "线性同余", "一次同余", "欧拉函数", "欧拉定理", "费马小定理", "rsa", "公钥密码",
        ],
        "points": {
            "整除与素数": ["整除", "素数", "质数", "合数", "因数", "约数"],
            "最大公因数与欧几里得算法": ["最大公因数", "最大公约数", "最小公倍数", "欧几里得算法", "辗转相除", "gcd", "lcm"],
            "同余与模运算": ["同余", "模运算", "mod"],
            "线性同余方程": ["线性同余", "一次同余", "同余方程"],
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
            "非齐次递推", "初始条件", "递推式",
        ],
        "points": {
            "递推关系建模": ["递推", "递推关系", "递归关系", "递推式"],
            "线性齐次递推": ["齐次递推", "特征方程"],
            "非齐次递推": ["非齐次递推"],
            "初始条件": ["初始条件"],
        },
    },
    "图论": {
        "keywords": [
            "图论", "无向图", "有向图", "顶点", "边集", "邻接", "邻接矩阵", "邻接表",
            "关联矩阵", "度矩阵", "度数", "路径", "回路", "圈", "连通", "连通分量",
            "欧拉", "哈密顿", "最短路", "dijkstra", "着色", "平面图", "匹配",
            "拉普拉斯矩阵", "laplacian", "树", "生成树", "最小生成树", "带权图", "权值",
            "矩阵树定理", "matrix-tree", "matrix tree", "kirchhoff", "基尔霍夫",
            "kruskal", "prim", "根树", "二叉树", "叶子", "割点", "割边", "桥", "生成森林",
            "支配集", "覆盖集", "独立集",
        ],
        "points": {
            "图的基本概念": ["无向图", "有向图", "顶点", "边集", "度数", "图论", "邻接表"],
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
            "陪集", "拉格朗日定理", "同态", "同构", "环", "域", "格", "布尔代数",
        ],
        "points": {
            "代数系统": ["代数系统", "代数结构", "半群", "幺半群"],
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

EXERCISE_PATTERNS = [
    "出题", "生成练习题", "给我一道题", "给几道题", "练习题", "随机出题",
    "复测题", "再测一道", "同知识点复测", "错题复测",
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
    "欧拉定理与费马小定理": ["欧拉定理", "费马小定理", "欧拉函数"],
    "排列与组合": ["排列", "组合", "排列数", "组合数", "c(n", "a(n"],
    "鸽巢原理": ["鸽巢", "抽屉"],
    "容斥原理": ["容斥"],
    "生成函数": ["生成函数"],
    "线性齐次递推": ["齐次递推", "特征方程"],
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


def _looks_like_exercise_request_text(text):
    """
    识别自然语言中的“让系统生成练习题”请求。
    覆盖出/生成/来/给/整/弄/安排/考我/刷题等常见说法，
    但仍限制为短请求，避免长篇讨论里偶然出现“题目”而误触发。
    """
    value = str(text or "").strip()
    value = re.sub(r"\s+", "", value)

    if not value or len(value) > 140:
        return False

    if re.search(
        r"^(?:不要|别|不用|无需).{0,18}(?:出|生成|来|给|整|弄).{0,8}(?:题目|题|练习)",
        value,
    ):
        return False

    targeted = bool(re.search(
        r"(?:出|生成|来|安排|准备|整|弄|给|考我|考一下|抽).{0,12}(?:题目|题|练习)"
        r"|(?:题目|题|练习).{0,8}(?:来一个|来一道|给一个|给一道|出一个|出一道)"
        r"|(?:想|要|想要|可以|能不能|帮我|让我).{0,10}(?:做|练|刷|考).{0,16}(?:题目|题|练习)",
        value,
    ))

    short_command = bool(
        re.search(
            r"^(?:请|麻烦)?(?:给我|帮我)?(?:再|重新|随机|随便)?"
            r"(?:来|出|给|整|弄|考我|刷)?(?:一道|一题|一个题)(?:吧|。|！|!)?$",
            value,
        )
    )

    repeat = bool(re.search(
        r"^(?:请|麻烦)?(?:给我|帮我)?(?:下一道题|下一题|下一个题|"
        r"再来一道|再来一题|换一道题|换一个题|换一道|换一题)(?:吧|。|！|!)?$",
        value,
    ))

    return targeted or short_command or repeat


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
    if (
        _looks_like_exercise_request_text(latest_text)
        or _contains_any(text, EXERCISE_PATTERNS)
    ):
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
    if "证明" in normalized:
        return "证明题"
    if "判断" in normalized or "是否" in normalized:
        return "判断题"
    if any(keyword in normalized for keyword in (
        "计算", "求", "写出", "列出", "det(", "行列式", "矩阵", "最短路", "生成树"
    )):
        return "计算题"
    return "综合题"


def _estimate_difficulty(text, knowledge_points=None, question_type="综合题"):
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
    if any(
        keyword in normalized
        for keyword in (
            "同构", "欧拉通路", "欧拉回路", "哈密顿",
            "最短路", "最小生成树", "传递闭包",
            "主析取范式", "主合取范式", "前束范式",
            "生成函数", "非齐次递推", "矩阵树定理",
            "rsa",
        )
    ):
        score += 1

    # 同一道题同时落到多个知识点时，给组合性留一档空间。
    if len(points) >= 3:
        score += 2
    elif len(points) >= 2:
        score += 1

    # 很短的概念/直接判断题保持简单，不因为术语本身被抬高。
    if question_type == "概念题" and len(normalized) <= 80:
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


def _score_categories(text):
    normalized = _normalize(text)
    scores = {}

    for category, rule in CATEGORY_RULES.items():
        score = 0
        for keyword in rule["keywords"]:
            if keyword.lower() in normalized:
                score += _keyword_weight(keyword)
        scores[category] = score

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
    return [point for _score, point in scored[:4]]


def _classify_content(text):
    scores = _score_categories(text)
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    primary, top_score = ordered[0] if ordered else ("待识别", 0)

    if top_score <= 0:
        return {
            "category": "待识别",
            "related_categories": [],
            "knowledge_points": [],
            "confidence": "低",
            "score": 0,
        }

    second_score = ordered[1][1] if len(ordered) > 1 else 0

    related = [
        category
        for category, score in ordered[1:]
        if score > 0 and score >= max(3, int(top_score * 0.55))
    ][:2]

    if top_score >= 9 or (top_score >= 6 and top_score >= second_score + 3):
        confidence = "高"
    elif top_score >= 3:
        confidence = "中"
    else:
        confidence = "低"

    return {
        "category": primary,
        "related_categories": related,
        "knowledge_points": _extract_points(text, primary),
        "confidence": confidence,
        "score": top_score,
    }


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

    result = {
        "category": classified["category"],
        "related_categories": classified["related_categories"],
        "knowledge_points": classified["knowledge_points"],
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

    # 明确排除用户特别要求不要登记的观察型问题。
    if re.search(
        r"(?:这里|这个|图里|图中|里面|这张图).{0,10}"
        r"(?:有)?(?:多少|几个|几条)(?:个)?(?:点|顶点|节点|边|线)"
        r"|(?:多少|几个|几条)(?:个)?(?:点|顶点|节点|边|线)",
        value,
    ):
        return False

    if re.search(r"^(?:这|这个|这里|图里|图中|里面).{0,12}(?:是什么|什么意思|怎么看|怎么读)$", value):
        return False

    # 只有明确要求完成一个数学任务，才把“纯图 + 要求”提升为正式题。
    return bool(re.search(
        r"^(?:请)?(?:判断|证明|求证|求解|计算|求|写出|列出|找出|给出|构造|画出|作出|确定|说明)"
        r"|(?:是否同构|是否连通|欧拉(?:通路|回路)|哈密顿(?:通路|回路)|最短(?:路|路径)|最小生成树|生成树|邻接矩阵|关联矩阵|度数序列)",
        value,
    ))


def _looks_like_user_question_for_context(text):
    """判断一条 user 消息是否是在提出新的学习题，而不是控制/追问语句。"""
    value = str(text or "").strip()
    if not value:
        return False

    if _is_question_navigation_followup(value) or _looks_like_exercise_request_text(value):
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
    question_type = context.get("question_type") or "综合题"
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
            "目标难度严格为中等：围绕1到2个核心知识点，安排正常的多步判断或计算，通常控制在1到2个小问；"
            "可以有少量综合，但不要同时堆叠3个以上独立任务，不要叠加证明、复杂构造和多个高阶考点。"
        ),
        "困难": (
            "目标难度严格为困难：允许多步推理、结构判断或知识点组合，体现明显挑战性；"
            "但必须仍在当前离散数学知识范围内，不用偏题怪题制造假难度。"
        ),
    }[exercise_target_difficulty]

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
            f"本次练习目标难度为{exercise_target_difficulty}。{exercise_difficulty_instruction}"
            "如果请求附有【当前指向题目】，以这道题作为同知识点练习的唯一参照，"
            "保持其核心考点，变换条件或数值；不要取用会话里另一道题的考点，也不要回答原题。"
            "固定使用“【题目】”作为题干标题；标题前不要写“好的、给你一道题”等开场白。"
            "题目后绝对不要附提示、思路提示、解题思路、思路、关键点、引导问题、解题方向、答案、解析、"
            "‘你先试试/卡住再告诉我’等任何教学话术。"
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
