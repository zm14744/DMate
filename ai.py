import requests
import os
import time
import random
import base64
import json
import re
import io
import math
import threading

from PIL import Image, ImageOps, ImageEnhance, ImageFilter

from teaching import teaching_prompt


DEEPSEEK_API_KEY = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_CHAT_MODEL = (
    os.environ.get("DEEPSEEK_CHAT_MODEL", "deepseek-flash")
    or "deepseek-flash"
).strip()

# DMate text and image services use the configured DeepSeek endpoint only.
# OCR/Vision 保持现有 DeepSeek 路径。
API_KEY = DEEPSEEK_API_KEY
API_URL = DEEPSEEK_API_URL

# 调试模式：True 时返回模拟回复，不调用真实 API
ASK_AI_MOCK = False

# 控制单次请求规模，避免上下文无限增长和费用失控
MAX_HISTORY_MESSAGES = 32
MAX_HISTORY_CHARS = 60000
MAX_MESSAGE_CHARS = 6000
MAX_OUTPUT_TOKENS = max(2000, min(6000, int(os.environ.get("DEEPSEEK_MAX_OUTPUT_TOKENS", "5000"))))
# 中等和困难统一采用 high 思考；max 不再对外开放。
# high 模式仍需为最终解答保留足够输出预算。
MEDIUM_MAX_OUTPUT_TOKENS = max(
    MAX_OUTPUT_TOKENS,
    min(12000, int(os.environ.get("MEDIUM_MAX_OUTPUT_TOKENS", "8000"))),
)
MAX_CONTINUATION_ROUNDS = 1

SYSTEM_PROMPT = r"""你是离散数学智能辅学系统中的教学助手。

你的目标不是单纯替学生做题，而是帮助学生理解离散数学知识、形成解题思路，并能够独立完成问题。

【教学原则】
1. 对“题目求解、练习题、扫描得到的题目”，默认采用“提示优先”：
   - 不直接给最终答案。
   - 先指出涉及的知识点。
   - 给出一到两个关键提示或下一步思路。
   - 可以通过提问引导学生继续思考。
2. 只有当学生明确提出“给我答案”“完整解析”“直接解出来”“告诉我最终答案”等要求时，才提供完整解答。
3. 如果学生只是询问概念、定义、定理含义，可以正常直接解释，不必强制使用提示模式。
4. 对“出题”“生成练习题”，只呈现可作答题目，不自动附提示、思路、解题方向、关键知识点或引导语；如果学生在同一轮明确要求“出题并给答案/解析”，仍执行完整的复合请求。题目生成与解题提示是不同阶段。
5. 如果学生答案有错误，先指出错误类型和思路问题，不要立刻把整道题答案全部给出。
6. 如果请求上下文中出现多条用户消息，以最后一条用户消息为准；但该条消息中同时提出的多个明确要求必须全部处理，例如“出题并附答案、解析、涉及知识点”，不得只完成第一个动作。更早的消息仅用于必要的指代和上下文。
7. 图片识题会把内容整理成“【题目文字】”和“【图形信息】”（也兼容旧标签“【题干与公式识别】”“【图形结构识别】”），两部分职责不同：
   - 题目的文字要求、编号、问法，以“题目文字”为主。
   - 图中的顶点、边、箭头、邻接关系、层次和二维结构，以“图形信息”为主。
   - 图形区域附近的 OCR 乱码、边名、顶点名重复内容已尽量清理；不要把残留的局部噪声当成关键冲突。
   - 遇到【图形信息】中 OpenCV 核验的顶点和直线边时，优先采用像素证据；它只确认直线边，不能据此证明不存在曲线、自环、重边或箭头。仅列出部分已确认边时，绝不能认定“没列出来的边就不存在”。对冲突或不确定的连接，应明确提示核对，不得自行补边。
   - 如果【图形信息】出现“【图形结构待核对】”，说明独立两次识别的边集存在冲突或第二次复核未完成。这不是一张已确认的图；不得将它当完整图计算同构、树、欧拉、度数、团数等确定结论。可继续解答同一试卷中与该图无关的文字小问，对受影响小问明确说明需要核对原图。
   - e1、e2、e3 这类写在边旁的符号默认是边的名称，不是权值；只有题目明确是带权图或图中存在清楚、独立的数值权重时，才按权值处理。
   - 图形信息中标记为“可能/不确定”的内容不能当作确定事实；如果不影响当前问题，就先忽略，不要因此中断教学。
   - 只有当两部分对“会直接改变答案的关键信息”给出相互矛盾、且都较可信的结果时，才请学生确认。
   - 能依据高置信度信息继续讲解时，就继续讲解，不要仅因为少量识别瑕疵要求学生重新确认原图。

【数学格式要求】
- 所有数学公式必须使用可被 MathJax 直接解析的标准 LaTeX。
- 行内公式使用 `$...$`；独立公式使用 `$$...$$`；每一个 `$` 必须成对闭合。
- 下标必须写成 `_`，例如 `$a_{ij}$`、`$v_1$`；表示下标时禁止写成 `\_`，更禁止写成 `*{ij}`。
- 矩阵维数写成 `$A=(a_{ij})_{5\times 5}$`，禁止写成 `*{5\times5}`。
- 分段定义必须使用 `cases`，例如：
  $$
  a_{ij}=
  \begin{cases}
  1, & v_i\text{ 与 }v_j\text{ 相邻},\\
  0, & \text{否则}.
  \end{cases}
  $$
- 只要数学定义中出现“若/当……则取某值，否则取另一值”，必须排成多行 `cases`。
- 严禁把分段定义压成一行，例如 `a_{ij}=\{1, 条件, 0, 否则\}` 这种写法即使能渲染也视为错误格式。
- 分段定义的左侧也必须放在同一个数学块里；禁止先在普通文本中写 `a_{ij}=`，再另起 `$$...$$`。
- 数学公式与中文说明要分开。例如应写 `$A=(a_{ij})_{5\times5}$ 满足：`，不要把“满足、其中”等中文直接塞进 `$...$`。
- `v_1`、`a_{ij}`、`A^2`、`\to`、`\frac`、`\begin{bmatrix}` 等任何 LaTeX/上下标表达都必须处在 `$...$` 或 `$$...$$` 中，禁止裸露在普通文本里。
- 公式中的中文说明必须放入 `\text{...}`，不要把“满足、否则、相邻”等中文裸写在数学公式内部。
- 矩阵示例：
  $$
  \begin{bmatrix}
  a & b\\
  c & d
  \end{bmatrix}
  $$
- 组合数：$\binom{n}{k}$。
- 图论：$\operatorname{tr}(A^2)$。
- 输出前自行检查：美元符号是否配对、上下标花括号是否闭合、`\begin{...}` 与 `\end{...}` 是否成对。
- 禁止输出 `INLINE`、`BLOCK` 等内部占位词。
- 禁止使用非标准伪 LaTeX 标记。
- 数学下标绝不能用 Markdown 星号代替；禁止出现 `a*{ij}`、`*a*{ij}`、`)*{5\\times5}`、`$*` 这类写法。
- 不要用 `*...*` 或 `**...**` 包裹数学公式；公式只用成对的 `$...$` 或 `$$...$$`。

【回答风格】
- 使用中文回答。
- 表达清楚、简洁。
- 不堆砌无关内容。
- 需要分步时按自然逻辑分步，不要制造过多层级。
"""



# 图像理解模型：独立读取题干并解析图形结构，不直接解题。
VISION_MODEL = os.environ.get(
    "DEEPSEEK_VISION_MODEL",
    "deepseek-flash"
)
VISION_MAX_OUTPUT_TOKENS = 3000
VISION_ENABLED = os.environ.get(
    "VISION_ANALYSIS_ENABLED",
    "1"
).strip().lower() not in {"0", "false", "off", "no"}

VISION_PROMPT = """你是离散数学题目的“图片文字校对 + 图形结构解析器”。

第一张图是用户上传的完整图片，后续图片是同一张图的局部放大，不是新题。
图片可能包含题干文字，也可能完全没有文字，只包含一个或多个离散数学图形。
请先独立读取整张图片，再整理文字与图形。你的任务不是解题，而是把图片整理成两部分：
1. corrected_text：干净、可读的题目文字；
2. visual_text：OCR 难以表达的图形结构信息。

【corrected_text 要求】
- 只根据图片逐字转录题干，每道小问单独一行，不改写问法。
- 如果整张图片本来就没有题干文字，corrected_text 必须返回空字符串；这不是识别失败。
- 保留题目标题、题干、(1)(2)(3)…等小问及数学符号。
- 逐问核对顶点下标、指数、数字、起点和终点；相邻小问可能使用不同顶点。
- 不得把上一问的顶点复制到下一问，也不得根据图中哪个点居中、出现频率或解题便利性猜题干。
- 先看局部放大图中的字符，再对照整图定位；局部图有重复内容时只保留一次。
- 删除“夹在题干和小问之间”的图形 OCR 噪声，例如图中的 v1、e1、e2、线段附近乱码等。
- 不要把图中边名、顶点名的散落标签重复塞进题目正文。
- 看不清的数字/符号在原位置写“[待核对]”，并写入 uncertain_fields；禁止选一个猜测值冒充确定结果。

【visual_text 要求】
- 图论优先确认：有向/无向、是否带权、顶点、边连接关系、箭头、自环、重边。
- 对彩色图、反色深色背景、蓝绿红黄节点、空心圆、文字标号位于节点内、矩形/菱形节点，也必须尝试定位实际顶点；不能仅因为没有黑色实心点就判为无图。
- 逐条追踪所有弧线和折线，尤其是两点之间的平行边、环、自环、箭头与方向。不能用直线边的 OpenCV 候选列表代替这些图形；箭头尖端指向的才是有向边终点。
- 多个相邻的复杂图（K_5、K_{3,3}、Petersen、状态机、有向多重图等）需依照图例/边界独立编号，不能把不同图的局部线条组合成一张图。
- 若 OpenCV 未检测到图或只给出 partial/unknown，意味着 CPU 几何识别证据不足，不代表图不存在；仍然独立用完整原图及局部图判断。无法确认边时只标出待核对，不补造边。
- 如果同一张图片里有两个或更多彼此分开的图，必须分别写成“图1”“图2”……，不要把它们合并成一个图。
- 对包含三幅及以上有 a/b/c 等明确顶点标签的无向图，请为每幅图单独成行，固定格式为“图1（G1）：无向图，顶点 a、b、c、...。边：a-b、b-c、...。共 N 条边。”；编号和标签按原图，不要把四幅图合并成一段泛泛的位置描述。N 必须等于该行不同无向边的实际条数，且同一无向边只列一次。
- 如果图中的顶点没有任何可读标签，不要因此放弃识别，也不要把“没有标签”当成不确定项。请为每张图独立创建临时顶点名，例如 G1_v1、G1_v2……和 G2_v1、G2_v2……。
- 临时顶点编号按视觉位置保持稳定：优先从上到下扫描；处在同一高度带时从左到右。首次列出临时顶点时，用括号补充大致位置（如“左上、上中、右下”），随后逐条给出边。
- 对无标签图，至少输出：每张图的顶点数、是否有向/带权、临时顶点及位置、完整可确认的边集合；若存在自环或重边要单独注明。这样后续系统即使没有原始顶点名，也能依据邻接结构继续推理。
- 顶点即使没有圆点也可能由线段端点或明确汇合处表示；不要因为“没有点标记”就判定没有顶点。反过来，单纯两条边在画面上交叉、但没有圆点或明显汇合语义时，不要擅自把交叉处新增为顶点；确实无法判断时才标记为不确定。
- 不要把边的弯折处当成新顶点；每个临时顶点都必须对应图片中实际可辨认的端点、圆点或连接节点。
- 如果图片只有纯图形、没有任何题干文字，只要能确认图形结构，仍应正常返回 visual_text，并将 has_visual_structure 设为 true。
- e1、e2、e3 这类写在边旁的符号默认是“边的名称”，绝不能自动解释成权值 1、2、3。
- 只有题目明确说明是带权图，或图片中存在与边名分离且清晰可确认的数值时，才输出边权。
- 不要根据 OCR 的乱码猜出 22、86 之类的权值。
- 如果是树、哈斯图、状态图、矩阵、真值表等，也要按结构描述。
- 只写能从图中确认的信息；不确定的地方标“可能/不确定”。
- 先数清每个图中的实心/空心顶点圆、孤立顶点，再逐条沿线追踪端点；不允许根据“看起来是三角形/星形”推断边数。
- 对每一对顶点分别统计实际边数。两点之间若有一条直线和一条弧线，则只有这一对是二重边；其他边仍是单边。绝不能写成“三角形每条边都是平行边”，除非三对顶点确实各有两条边。
- 图中的孤立圆点不与任何线相连就必须记为度数 0 的顶点，不能误认为文字句号、边端装饰，也不能凭空连边。
- 对多图并列的情况，先判断是同一题下左右两个独立图，还是同一个图的多个不连通分量；以标签、间距和题目布局为依据，不确定就明确标记，不得猜测成一个连通图。
- 每个图先列顶点位置、再列边（重边按重数列出），最后重新计算顶点度数并核对握手定理（度数和 = 2×边数，环计入两次）；不一致时自行逐边重查，仍不能确认的边标为不确定。
- 每条边逐一核对两个端点；只有确实连接同一对顶点的两条边才叫重边。
- 边 a-b 与 b-a 在无向简单图中完全相同；不要把反向写法列成两条边，也不要同时宣称“无重边”和给出重复边。输出前对每张图的无向边集合去重，检查“共 N 条边”是否等于唯一边数。
- 两条斜线交叉不是新顶点，也不是新边。必须确认实际从 b 出发的线是否真的落在 f 上；不得因为 b-e 与 a-f 相交就额外写出 b-f。
- 对黑色实心点的教材图，先逐一数出所有黑点，再沿连续线迹从一个黑点追到另一个黑点。
- 斜线相互交叉而交点没有实心点时，应继续沿原来斜率前进，不能在交叉处转向、换线或添加连接。
- 对每个独立图先建立“可见黑点位置 → a/b/c 等文字标签”的对应关系；文字靠近哪个点需要核对，不能只按阅读顺序猜字母。
- 严格按每条线实际落到的终点确认边，禁止按图形外观补足 n-1 条边；不连通图也可能是有效的完整识别结果。
- 最后核对各图的顶点数、实线边数、每个顶点相接的线条数；握手定理只能检查内部计数，无法证明识别出的边确实存在。
- 六点三排两列的图，只有原图确实标注 a、b 为上排，c、d 为中排，e、f 为下排时才能如此匹配；谨防将 a-c 写成 b-c 或将 b-e 写成 a-e。交叉处没有黑点时，沿同一条线的方向继续追踪到实际端点，不许转到另一条线。
- 问哪些图是树时，必须由每个图的边集计算连通分量，且连通并有 n-1 条边才是树。不连通时即使边数满足 n-1 也不是树；正文结论和最后答案必须一致。
- 局部放大图是同一原图的放大或适度增强，增强可能制造伪影。原图端点看不清时写入 uncertain_fields，不能凭增强图片“补画”边。
- OpenCV 候选图中的 v1/v2 是按图像位置给的临时编号，并非真实 a/b 标签；先用位置核对标签，再核对候选连接。如与可见原图不符，不得照抄 OpenCV。
- 不要解题，不要给答案。

【图片用途识别】
- 同时判断这张图片是否包含待解答的离散数学题目（image_kind）。
- exercise：有明确题目/小问；或者是用于图论题的独立图、无标签图、矩阵等可作为题目核对的数学结构，即使没有文字也选 exercise。
- non_exercise：明确只是课件知识点、定义表、笔记、答案说明、普通照片、网页截图等，没有待求解的题目；不可凭空编造题干或小问。
- uncertain：图片模糊、局部被裁剪，无法确信是否为题目；不要为了拦截而把纯图题误判为非题目。
- 只根据原图判断，不要因为正文里有“设”“是”“证明方法”等说明性语句，就认定存在题目。

请只返回一个 JSON 对象，不要 Markdown 代码块，不要额外解释：
{
  "corrected_text": "校对后的完整题目文字",
  "visual_text": "图形结构描述；若没有需要补充的图形结构则为空字符串",
  "has_visual_structure": true,
  "image_kind": "exercise",
  "uncertain_fields": ["看不清的位置和符号；若没有则返回空数组"]
}
其中 has_visual_structure 只能是 true 或 false；image_kind 只能是 exercise、non_exercise、uncertain。
"""

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _success(reply):
    return {
        "ok": True,
        "reply": reply
    }


def _failure(error):
    return {
        "ok": False,
        "error": error
    }


def _trim_messages(messages):
    """限制历史消息数量、单条长度和总字符量，优先保留最近上下文。"""
    if not isinstance(messages, list):
        return []

    normalized = []
    for item in messages[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = item.get("content", "")

        if role not in ("user", "assistant"):
            continue

        if not isinstance(content, str):
            content = str(content)

        content = content.strip()
        if not content:
            continue

        if len(content) > MAX_MESSAGE_CHARS:
            content = content[:MAX_MESSAGE_CHARS] + "\n[内容过长，已截断]"

        normalized.append({
            "role": role,
            "content": content
        })

    # 32 条只是数量上限。为了避免极端情况下 32 条都接近 6000 字符，
    # 再加一层总字符预算；从最近消息向前保留，保证最新请求优先。
    trimmed_reversed = []
    total_chars = 0

    for item in reversed(normalized):
        content_len = len(item["content"])

        if trimmed_reversed and total_chars + content_len > MAX_HISTORY_CHARS:
            break

        trimmed_reversed.append(item)
        total_chars += content_len

    return list(reversed(trimmed_reversed))



def _repair_common_latex_typos(text):
    """
    修复非常明确、低风险的 LaTeX / Markdown 笔误。
    不猜数学结论，只修格式字符。
    """
    if not isinstance(text, str) or not text:
        return text

    repaired = text

    # 下标：a\_{ij} -> a_{ij}
    repaired = re.sub(
        r"\\_\{([A-Za-z0-9,]+)\}",
        r"_{\1}",
        repaired
    )

    # a*{ij} -> a_{ij}
    repaired = re.sub(
        r"(?<![A-Za-z0-9])([A-Za-z])\*\{([A-Za-z0-9]{1,8})\}",
        r"\1_{\2}",
        repaired
    )

    # (a_{ij})*{5\times5} -> (a_{ij})_{5\times5}
    repaired = re.sub(
        r"(\))\*\{(\d+\s*\\times\s*\d+)\}",
        r"\1_{\2}",
        repaired
    )

    # a{ij} -> a_{ij}（只修邻接矩阵常见变量 a）
    repaired = re.sub(
        r"(?<![A-Za-z0-9_])a\{([A-Za-z0-9,]{1,8})\}",
        r"a_{\1}",
        repaired
    )

    # (a_{ij}){5\times5} -> (a_{ij})_{5\times5}
    repaired = re.sub(
        r"(\(a_\{ij\}\))\{(\d+\s*\\times\s*\d+)\}",
        r"\1_{\2}",
        repaired
    )

    # 模型偶尔会在公式边界旁插入 Markdown 强调星号：
    repaired = repaired.replace("$*", "$").replace("*$", "$")

    # 行首 "*a_{ij}" 这种不是正常列表，而是公式强调符残留。
    repaired = re.sub(
        r"(?m)^[ \t]*\*([A-Za-z](?:_\{[^}\n]+\})?)",
        r"\1",
        repaired
    )

    return repaired


def _strip_markdown_code_for_math_checks(text):
    """代码示例中的 $、下标、LaTeX 不属于数学公式渲染错误。"""
    value = re.sub(r"```[\s\S]*?```", " ", str(text or ""))
    return re.sub(r"`[^`\n]*`", " ", value)


def _backslash_math_delimiters_balanced(text):
    r"""与 $...$ 并行支持 MathJax 常用的 \( ... \) 和 \[ ... \]。"""
    tokens = re.findall(r"\\[\(\)\[\]]", text)
    stack = []
    matches = {r"\)": r"\(", r"\]": r"\["}
    for token in tokens:
        if token in (r"\(", r"\["):
            stack.append(token)
        elif not stack or stack.pop() != matches[token]:
            return False
    return not stack


def _math_delimiters_balanced(text):
    """
    检查 $...$ 与 $$...$$ 是否成对。
    这里只做格式体检，不尝试解释数学内容。
    """
    if not isinstance(text, str):
        return False

    text = _strip_markdown_code_for_math_checks(text)
    mode = None
    index = 0
    length = len(text)

    while index < length:
        char = text[index]

        # 跳过转义美元符号
        if char == "\\":
            index += 2
            continue

        if char != "$":
            index += 1
            continue

        is_double = (
            index + 1 < length
            and text[index + 1] == "$"
        )

        token = "$$" if is_double else "$"

        if mode is None:
            mode = token
        elif mode == token:
            mode = None
        else:
            # 在 $...$ 内遇到 $$，或反过来，都视为可疑。
            return False

        index += 2 if is_double else 1

    return mode is None



def _iter_math_segments(text):
    if not isinstance(text, str):
        return []

    segments = []
    index = 0
    length = len(text)

    while index < length:
        if text[index] == "\\":
            index += 2
            continue

        if text[index] != "$":
            index += 1
            continue

        is_double = index + 1 < length and text[index + 1] == "$"
        token = "$$" if is_double else "$"
        start = index + len(token)
        cursor = start

        while cursor < length:
            if text[cursor] == "\\":
                cursor += 2
                continue

            if text.startswith(token, cursor):
                segments.append((token, text[start:cursor]))
                index = cursor + len(token)
                break

            cursor += 1
        else:
            break

    return segments


def _has_naked_chinese_in_math(content):
    if not isinstance(content, str) or not content:
        return False

    scrubbed = re.sub(
        r"\\text\{[^{}]*\}",
        "",
        content
    )

    return bool(re.search(r"[\u4e00-\u9fff]", scrubbed))


def _remove_math_for_plaintext_checks(text):
    # 支持两套同样合法的 MathJax 定界符，避免把 \(a_{ij}\)
    # 等正确数学表达式误报为裸 LaTeX，再发起昂贵的重生成。
    plain = _strip_markdown_code_for_math_checks(text)
    plain = re.sub(r"\\\[[\s\S]*?\\\]", " ", plain)
    plain = re.sub(r"\\\([\s\S]*?\\\)", " ", plain)
    plain = re.sub(r"\$\$[\s\S]*?\$\$", " ", plain)
    plain = re.sub(r"\$(?!\$)(?:\\.|[^$\n])+\$", " ", plain)
    return plain


def _looks_like_broken_math(text):
    if not isinstance(text, str) or not text.strip():
        return True

    # 这是前端临时标记，绝不允许模型把它当作数学内容输出。
    if re.search(r"MATHPROTECTTOKEN\d+ENDTOKEN|DMATE_MATH_\d+_END", text):
        return True

    suspicious_patterns = (
        r"\\_\{",          # a\_{ij}
        r"\*\{[^}\n]+\}",  # a*{ij} / )*{5\times5}
        r"\$\*",
        r"\*\$",
    )

    if any(re.search(pattern, _strip_markdown_code_for_math_checks(text))
           for pattern in suspicious_patterns):
        return True

    if not _math_delimiters_balanced(text):
        return True

    stripped = _strip_markdown_code_for_math_checks(text)
    if not _backslash_math_delimiters_balanced(stripped):
        return True

    # begin/end 必须成对，但不要扫描 fenced code 块中的示例。
    environments = re.findall(r"\\(begin|end)\{([A-Za-z*]+)\}", stripped)
    env_stack = []
    for kind, name in environments:
        if kind == "begin":
            env_stack.append(name)
        elif not env_stack or env_stack.pop() != name:
            return True
    if env_stack:
        return True

    # 分段定义被错误压成一行：
    # 例如 a_{ij}=\{1, 条件, 0, \text{否则}\}
    pseudo_piecewise = re.search(
        r"=\s*\\?\{[^$\n]{0,240}(?:否则|otherwise)[^$\n]{0,80}",
        stripped,
        flags=re.IGNORECASE
    )

    if pseudo_piecewise and r"\begin{cases}" not in text:
        return True

    # 更具体地识别邻接矩阵等“1/0/否则”定义被摊成一行的情况。
    flattened_condition = re.search(
        r"(?:[A-Za-z]_\{[^}]+\})\s*="
        r"[^$]{0,300}(?:^|[^0-9])1(?:[^0-9]|$)"
        r"[^$]{0,300}(?:^|[^0-9])0(?:[^0-9]|$)"
        r"[^$]{0,300}否则",
        text,
        flags=re.DOTALL
    )

    if flattened_condition and r"\begin{cases}" not in text:
        return True

    plain_text = _remove_math_for_plaintext_checks(text)

    # 去掉代码块/行内代码后，普通正文里不应残留裸 LaTeX。
    plain_for_latex = re.sub(
        r"```[\s\S]*?```|`[^`\n]*`",
        "",
        plain_text
    )

    if re.search(
        r"\\(?:begin|end|frac|sqrt|to|rightarrow|Rightarrow|xrightarrow|operatorname|binom)\b",
        plain_for_latex
    ):
        return True

    if re.search(
        r"(?<![A-Za-z0-9])"
        r"[A-Za-z](?:_\{[^}\n]{1,30}\}|_[A-Za-z0-9]{1,12})",
        plain_for_latex
    ):
        return True

    # a_{ij}= 被放在普通文本中，后面才另起数学块。
    if re.search(
        r"(?m)^[ \t]*a_\{ij\}\s*=\s*$",
        plain_text
    ):
        return True

    # 邻接矩阵维数漏掉下标符号。
    if re.search(
        r"A\s*=\s*\(a_\{ij\}\)\s*\{\d+\s*\\times\s*\d+\}",
        text
    ):
        return True

    if "\x08" in text or "\x0c" in text:
        return True

    return False



def _fallback_math_to_readable_text(text):
    """
    如果 LaTeX 结构损坏且自动重生成失败，
    将常见数学标记转成可读纯文本，避免整次对话被打断。
    """
    if not isinstance(text, str):
        return ""

    value = _repair_common_latex_typos(text)

    replacements = (
        (r"\begin{cases}", "\n"),
        (r"\end{cases}", "\n"),
        (r"\left", ""),
        (r"\right", ""),
        (r"\times", "×"),
        (r"\cdot", "·"),
        (r"\leq", "≤"),
        (r"\le", "≤"),
        (r"\geq", "≥"),
        (r"\ge", "≥"),
        (r"\neq", "≠"),
        (r"\rightarrow", "→"),
        (r"\Rightarrow", "⇒"),
        (r"\in", "∈"),
    )

    for old, new in replacements:
        value = value.replace(old, new)

    value = re.sub(
        r"\\text\{([^{}]*)\}",
        r"\1",
        value
    )

    value = value.replace("$$", "")
    value = value.replace("$", "")
    value = value.replace(r"\\", "\n")

    value = re.sub(
        r"\\(?:displaystyle|quad|qquad)",
        " ",
        value
    )
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)

    return value.strip()


def _text_provider_configs(preferred_provider=None):
    """The configured DeepSeek text provider; no third-party competition gateway."""
    if not DEEPSEEK_API_KEY:
        return []
    return [{
        "id": "deepseek",
        "name": "DeepSeek",
        "url": DEEPSEEK_API_URL,
        "api_key": DEEPSEEK_API_KEY,
        "model": DEEPSEEK_CHAT_MODEL,
    }]


def _reasoning_effort_for_context(teaching_context):
    """生成题目单独控制推理预算；解题仍按难度决定思考强度。"""
    context = teaching_context or {}
    # 只有 high 可以作为显式覆盖；历史记录携带 max 也无法启用。
    if context.get("mode") != "exercise":
        override = str(context.get("reasoning_effort_override") or "").lower()
        if override == "high":
            return "high"
    if context.get("mode") == "exercise":
        override = context.get("generation_reasoning_effort")
        if override in ("none", "high"):
            return override
    return "high" if str(context.get("difficulty", "")).strip() in ("中等", "困难") else "none"


def _build_text_payload(provider, messages, reasoning_effort="none", max_tokens=None):
    effort = str(reasoning_effort or "none").strip().lower()
    # 请求层最后一道保险：调用者即使直接传 max，也只能发 high。
    if effort == "max":
        effort = "high"
    if effort not in ("none", "high"):
        effort = "none"

    if max_tokens is not None:
        token_limit = int(max_tokens)
    elif effort == "high":
        token_limit = MEDIUM_MAX_OUTPUT_TOKENS
    else:
        token_limit = MAX_OUTPUT_TOKENS

    payload = {
        "model": provider["model"],
        "messages": messages,
        "max_tokens": token_limit,
        "stream": False,
    }

    if effort == "high":
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = "high"
    else:
        payload["thinking"] = {"type": "disabled"}

    return payload




def _provider_request_timeout(provider, reasoning_effort, default_timeout):
    """Keep the existing DeepSeek timeout and response handling."""
    return default_timeout


# 每个工作线程独立保持文本 API 的 HTTP 连接；避免每次完成一次
# 普通聊天或出题重试都重复 TLS 握手。Vision/OCR 请求路径不改。
_TEXT_HTTP_LOCAL = threading.local()


def _text_http_session():
    session = getattr(_TEXT_HTTP_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        _TEXT_HTTP_LOCAL.session = session
    return session


def _request_text_completion(
    messages,
    retries=2,
    reasoning_effort="none",
    max_tokens=None,
    preferred_provider=None,
    timeout=(10, 60),
):
    """
    调用文本模型。

    通过 DeepSeek 完成文本请求，保留原有的错误处理、重试与思考强度策略。
    """
    # 即使上层意外传入旧版 max，也不得写入 provider 请求与日志。
    if str(reasoning_effort or "").lower() == "max":
        reasoning_effort = "high"
    providers = _text_provider_configs(preferred_provider)
    if not providers:
        return {
            "ok": False,
            "error": "AI 服务尚未完成配置，请联系管理员。",
        }

    last_status = None
    last_error = None
    saw_empty_body = False

    for provider_index, provider in enumerate(providers):
        # 单一 DeepSeek 线路保留原有重试次数。
        is_last = provider_index == len(providers) - 1
        attempts = max(1, retries + 1)
        if not is_last:
            attempts = 1

        provider_timeout = _provider_request_timeout(
            provider,
            reasoning_effort,
            timeout,
        )

        payload = _build_text_payload(
            provider,
            messages,
            reasoning_effort=reasoning_effort,
            max_tokens=max_tokens,
        )
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json",
        }

        for attempt in range(attempts):
            try:
                mode_text = {
                    "high": "high 思考",
                }.get(reasoning_effort, "非思考")
                print(
                    f"正在调用{provider['name']} "
                    f"{provider['model']}（{mode_text}，"
                    f"第 {attempt + 1}/{attempts} 次）"
                )

                call_start = time.monotonic()
                response = _text_http_session().post(
                    provider["url"],
                    headers=headers,
                    json=payload,
                    timeout=provider_timeout,
                )
                elapsed = time.monotonic() - call_start
                print(f"{provider['name']} API耗时 {elapsed:.2f}s；HTTP {response.status_code}")
                last_status = response.status_code

                if response.status_code in RETRYABLE_STATUS:
                    if attempt < attempts - 1:
                        wait_seconds = (2 ** attempt) + random.uniform(0, 0.4)
                        print(
                            f"{provider['name']} 暂时不可用，"
                            f"HTTP {response.status_code}，"
                            f"{wait_seconds:.1f} 秒后重试"
                        )
                        time.sleep(wait_seconds)
                        continue
                    break

                if not response.ok:
                    print(
                        f"{provider['name']} 请求失败："
                        f"HTTP {response.status_code}；"
                        f"响应内容：{response.text[:500]}"
                    )
                    break

                try:
                    result = response.json()
                except ValueError as exc:
                    last_error = exc
                    print(
                        f"{provider['name']} 返回内容解析失败：{repr(exc)}"
                    )
                    break

                if "error" in result:
                    print(
                        f"{provider['name']} API 返回错误："
                        f"{result['error']}"
                    )
                    break

                choices = result.get("choices")
                if not choices:
                    print(
                        f"{provider['name']} 返回缺少 choices：{result}"
                    )
                    break

                choice = choices[0] if isinstance(choices[0], dict) else {}
                message = choice.get("message", {})
                content = message.get("content") if isinstance(message, dict) else None

                if not isinstance(content, str) or not content.strip():
                    reasoning_content = (
                        message.get("reasoning_content")
                        if isinstance(message, dict)
                        else None
                    )
                    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
                    print(
                        f"{provider['name']} 返回正文为空；"
                        f"reasoning_len="
                        f"{len(reasoning_content) if isinstance(reasoning_content, str) else 0}；"
                        f"finish_reason={choice.get('finish_reason')}；"
                        f"completion_tokens={usage.get('completion_tokens', '未知')}；"
                        f"token_limit={payload.get('max_tokens', '未指定')}"
                    )
                    saw_empty_body = True
                    break


                return {
                    "ok": True,
                    "choice": choice,
                    "content": content.strip(),
                    "provider_id": provider["id"],
                    "provider_name": provider["name"],
                    "model": provider["model"],
                }

            except requests.exceptions.Timeout as exc:
                last_error = exc
                print(f"{provider['name']} 请求超时（耗时 {time.monotonic() - call_start:.2f}s）：{repr(exc)}")
                if attempt < attempts - 1:
                    wait_seconds = (2 ** attempt) + random.uniform(0, 0.4)
                    time.sleep(wait_seconds)
                    continue
                break

            except requests.exceptions.ConnectionError as exc:
                last_error = exc
                print(f"{provider['name']} 网络连接异常：{repr(exc)}")
                if attempt < attempts - 1:
                    wait_seconds = (2 ** attempt) + random.uniform(0, 0.4)
                    time.sleep(wait_seconds)
                    continue
                break

            except requests.exceptions.RequestException as exc:
                last_error = exc
                print(f"{provider['name']} 请求异常：{repr(exc)}")
                break

            except Exception as exc:
                last_error = exc
                print(f"{provider['name']} 未知异常：{repr(exc)}")
                break

        if provider_index < len(providers) - 1:
            print(
                f"{provider['name']} 当前不可用，自动切换到"
                f"{providers[provider_index + 1]['name']}。"
            )

    if saw_empty_body:
        return {
            "ok": False,
            "empty_body": True,
            "error": "AI 只生成了内部推理，未输出解答正文。",
        }

    if last_status is not None:
        return {
            "ok": False,
            "status_code": last_status,
            "error": _friendly_http_error(last_status),
        }

    if isinstance(last_error, requests.exceptions.Timeout):
        return {
            "ok": False,
            "error": "AI 服务响应时间过长，请稍后重新发送。",
        }

    if isinstance(last_error, requests.exceptions.ConnectionError):
        return {
            "ok": False,
            "error": "暂时无法连接 AI 服务，请检查网络后重试。",
        }

    return {
        "ok": False,
        "error": "AI 服务暂时不可用，请稍后重试。",
    }


def _regenerate_broken_math_answer(
    final_messages,
    broken_content,
    preferred_provider=None,
    reasoning_effort="none",
):
    """
    仅在答案数学格式损坏时额外重生成一次。
    优先沿用刚才成功的供应路径；该路径失效时仍可自动回退。
    """
    repair_instruction = (
        "你上一条回答中的 Markdown/LaTeX 格式损坏了。"
        "请完整重写上一条回答，保持原来的数学含义、教学方式和答案内容，"
        "不要提到‘格式修复’或这条指令。"
        "严格使用标准 MathJax LaTeX：行内 $...$，独立公式 $$...$$；"
        "下标只用 _{...}；所有‘若……否则……’的条件定义必须使用多行 cases；"
        "整个 a_{ij}=\\begin{cases}...\\end{cases} 必须放在同一对 $$ 中；"
        "矩阵维数写成 $A=(a_{ij})_{5\\times5}$，中文‘满足/其中’放在公式外；"
        "禁止把 a_{ij}={1, 条件, 0, 否则} 摊成一行；"
        "禁止使用星号代替下标，禁止出现 a*{ij}、$*、*a*{ij}。"
        "输出前检查所有美元符号、花括号和 begin/end 是否成对。"
    )

    retry_messages = list(final_messages)
    retry_messages.append({
        "role": "assistant",
        "content": broken_content,
    })
    retry_messages.append({
        "role": "user",
        "content": repair_instruction,
    })

    result = _request_text_completion(
        retry_messages,
        retries=0,
        reasoning_effort=reasoning_effort,
        preferred_provider=preferred_provider,
    )
    if not result.get("ok"):
        print("数学格式重生成失败：所有可用文本路径均失败")
        return None

    content = result.get("content", "")
    repaired = _repair_common_latex_typos(content)

    if _looks_like_broken_math(repaired):
        print("数学格式重生成后仍检测到异常")
        return None

    print("数学格式异常已自动重生成")
    return repaired


def _continue_truncated_answer(
    api_messages,
    partial_content,
    preferred_provider=None,
    reasoning_effort="none",
):
    """当模型因为输出长度限制截断时，最多自动续写一次并拼接完整答案。"""
    content = str(partial_content or "").strip()
    if not content:
        return content

    messages = list(api_messages)
    messages.append({
        "role": "assistant",
        "content": content,
    })

    current_provider = preferred_provider

    for _round in range(MAX_CONTINUATION_ROUNDS):
        messages.append({
            "role": "user",
            "content": (
                "上一条回答因为输出长度限制被截断了。请只从截断处继续，"
                "不要从头重复，不要添加新的开场白；保持原来的 Markdown/LaTeX 格式，"
                "直到把原本要回答的内容完整结束。"
            ),
        })

        result = _request_text_completion(
            messages,
            retries=0,
            reasoning_effort=reasoning_effort,
            preferred_provider=current_provider,
        )
        if not result.get("ok"):
            print("长回答自动续写失败：所有可用文本路径均失败")
            break

        piece = str(result.get("content", "") or "").strip()
        if not piece:
            break

        content = content.rstrip() + "\n" + piece
        current_provider = result.get("provider_id") or current_provider

        choice = result.get("choice") or {}
        if choice.get("finish_reason") != "length":
            break

        messages.append({
            "role": "assistant",
            "content": piece,
        })

    return content.strip()


def _friendly_http_error(status_code):
    """把常见 HTTP 错误转换为用户可读的中文提示。"""
    if status_code == 400:
        return "AI 请求内容有误，请稍后重新发送。"
    if status_code in (401, 403):
        return "AI 服务配置异常，请联系管理员。"
    if status_code == 402:
        return "AI 服务当前不可用，请联系管理员检查账户状态。"
    if status_code == 429:
        return "当前访问人数较多，请稍后再试。"
    if status_code in (500, 502, 503, 504):
        return "AI 服务暂时繁忙，请稍后再试。"
    return "AI 服务暂时出现异常，请稍后再试。"


def ask_ai(messages, retries=2, teaching_context=None):
    """
    使用 DeepSeek 生成文本回复。
    简单请求关闭思考；中等和困难题均使用 high 思考。
    """
    if ASK_AI_MOCK:
        return _success("""这是一条模拟回复。

提示：这道题可以先判断它属于哪个离散数学知识点，再尝试写出第一步需要构造的数学对象。

例如矩阵可以正常显示为：

$$
\\begin{bmatrix}
1 & 2 \\\\
3 & 4
\\end{bmatrix}
$$
""")

    if not DEEPSEEK_API_KEY:
        print("AI API 配置错误：DEEPSEEK_API_KEY 未设置")
        return _failure("AI 服务尚未完成配置，请联系管理员。")

    clean_messages = _trim_messages(messages)
    if not clean_messages:
        return _failure("没有检测到有效的消息内容。")

    context = teaching_context or {}
    system_content = SYSTEM_PROMPT + teaching_prompt(context)
    if context.get("mode") == "full_solution":
        reference = str(context.get("solution_reference_answer") or "").strip()[:1200]
        if reference:
            # 参考答案源于出题时的本地缓存，未经独立证明，必须复核。
            system_content += (
                "\n【本题生成时保存的参考答案（可能有误，仅供交叉核对）】\n"
                + reference + "\n【参考答案结束】\n"
                "你必须独立推导并检查是否与参考答案一致。"
                "如果发现参考答案错误，应明确纠正，不能迎合错误答案。"
                "学生要求完整解析：逐小问给结论和必要证明或计算步骤，"
                "最后输出清晰的最终答案，禁止只输出内部思考。"
            )
    api_messages = [
        {"role": "system", "content": system_content}
    ] + clean_messages

    reasoning_effort = _reasoning_effort_for_context(teaching_context)
    if reasoning_effort == "high":
        # high 同时用于中等与困难题；难度与思考强度是两个独立字段。
        detected_difficulty = str(context.get("difficulty") or "未确定")
        source = "用户指定" if context.get("reasoning_effort_override") else "自动选择"
        print(f"解题配置：题目难度={detected_difficulty}；思考强度={reasoning_effort}（{source}）。")

    is_full_solution = context.get("mode") == "full_solution"
    # 普通聊天的旧重试策略不变；完整解答避免在 high 超时后自动重复数轮。
    result = _request_text_completion(
        api_messages,
        retries=0 if is_full_solution else retries,
        reasoning_effort=reasoning_effort,
    )
    if is_full_solution and not result.get("ok") and (
        result.get("empty_body") or result.get("status_code") in (429, 500, 502, 503, 504)
        or not result.get("status_code")
    ):
        # 只补救一次：关闭 thinking 以强制留下可呈现的正文。
        print("完整解析首次无有效正文，尝试一次非思考模式恢复。")
        # 首次 high 推理只返回 reasoning_content 时，明确要求恢复一份可展示的
        # 最终解答（不是继续推理），避免再次用同一提示生成空正文。
        recovery_messages = list(api_messages) + [{
            "role": "user",
            "content": (
                "上一轮没有产生可展示的最终答案。现在请直接给出本题的最终解答正文，"
                "逐小问给出结论、必要证明和验算；不要输出内部推理、过程说明或道歉。"
                "使用规范数学公式并确保所有公式定界符闭合。"
                "答案可以精炼，但不能省略关键推导。"
            ),
        }]
        fallback = _request_text_completion(
            recovery_messages,
            retries=0,
            reasoning_effort="none",
            max_tokens=min(MAX_OUTPUT_TOKENS, 5000),
            timeout=(8, 45),
        )
        if fallback.get("ok"):
            result = fallback
    if not result.get("ok"):
        return _failure(
            result.get("error")
            or "AI 服务暂时不可用，请稍后重试。"
        )

    choice = result.get("choice") or {}
    content = str(result.get("content", "") or "").strip()
    provider_id = result.get("provider_id")

    # 练习出题由 /chat 统一限制为最多两次候选生成。不能在 AI 层暗中
    # 自动续写/重生成，否则两次候选可能变成 4~6 次昂贵的网络调用。
    is_exercise_generation = (teaching_context or {}).get("mode") == "exercise"
    if choice.get("finish_reason") == "length":
        if is_exercise_generation:
            print("练习生成输出截断，交由出题校验流程处理。")
            return _failure("出题内容被截断，请重新生成。")
        print("检测到回答达到输出长度上限，自动继续生成。")
        content = _continue_truncated_answer(
            api_messages,
            content,
            preferred_provider=provider_id,
            reasoning_effort="none" if is_full_solution else reasoning_effort,
        )

    content = _repair_common_latex_typos(content)

    if _looks_like_broken_math(content) and not is_exercise_generation:
        print("检测到无法由本地规则直接修复的数学格式异常，尝试一次重写。")
        regenerated = _regenerate_broken_math_answer(
            api_messages,
            content,
            preferred_provider=provider_id,
            reasoning_effort="none" if is_full_solution else reasoning_effort,
        )

        if regenerated:
            content = regenerated
        else:
            print(
                "数学格式自动重生成未成功，"
                "已降级为可读文本，避免中断当前对话。"
            )
            content = _fallback_math_to_readable_text(content)
            if not content:
                return _failure("AI 服务没有生成有效回答，请重新发送。")

    if is_exercise_generation and _looks_like_broken_math(content):
        print("练习生成数学格式异常，交由受限出题纠偏处理。")
        return _failure("生成题目的数学格式不完整，请重新生成。")

    print(
        f"AI 调用成功：{result.get('provider_name', '未知路径')} / "
        f"{result.get('model', '')}"
    )
    return _success(content)

def _guess_image_mime(raw):
    """根据文件头判断 DeepSeek Vision 支持的图片 MIME。"""
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        return None

    data = bytes(raw[:16])

    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"

    return None



def _extract_vision_json(content):
    """从视觉模型输出中稳健提取 JSON。"""
    if not isinstance(content, str):
        return None

    text = content.strip()
    if not text:
        return None

    # 兼容模型偶尔包一层 ```json ... ```
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    first = text.find("{")
    last = text.rfind("}")
    if first < 0 or last <= first:
        return None

    try:
        data = json.loads(text[first:last + 1])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    corrected_text = data.get("corrected_text", "")
    visual_text = data.get("visual_text", "")
    raw_has_visual = data.get("has_visual_structure", bool(visual_text))
    image_kind = data.get("image_kind", "uncertain")
    if image_kind not in {"exercise", "non_exercise", "uncertain"}:
        image_kind = "uncertain"

    if isinstance(raw_has_visual, bool):
        has_visual = raw_has_visual
    elif isinstance(raw_has_visual, str):
        has_visual = raw_has_visual.strip().lower() in {
            "1", "true", "yes", "on"
        }
    else:
        has_visual = bool(raw_has_visual)

    if not isinstance(corrected_text, str) or not isinstance(visual_text, str):
        return None

    corrected_text = corrected_text.strip()
    visual_text = visual_text.strip()

    # 截断会丢题目条件；异常长输出交由调用方重试/回退，不使用半道题。
    if len(corrected_text) > 5000 or len(visual_text) > 3000:
        return None
    if not corrected_text and not visual_text and image_kind != "non_exercise":
        return None
    uncertain_fields = data.get("uncertain_fields", [])
    if not isinstance(uncertain_fields, list):
        return None
    uncertain_fields = [x.strip()[:240] for x in uncertain_fields[:12]
                        if isinstance(x, str) and x.strip()]

    return {
        "corrected_text": corrected_text,
        "visual_text": visual_text if bool(has_visual) else "",
        "has_visual_structure": bool(has_visual and visual_text),
        "image_kind": image_kind,
        "uncertain_fields": uncertain_fields,
    }


def _vision_success(corrected_text, visual_text, uncertain_fields=None, image_kind="uncertain"):
    return {
        "ok": True,
        # 保留 reply 字段，兼容已有 app.py / 旧代码。
        "reply": visual_text,
        "corrected_text": corrected_text,
        "visual_text": visual_text,
        "image_kind": image_kind,
        "uncertain_fields": uncertain_fields or [],
    }


def _diagram_grid_crops(image, *, individual=False):
    """Find genuinely blank gutters between textbook graph panels.

    This supplies magnified *image evidence*, not a claimed topology. Require
    blank columns across the whole drawing; regular point layouts alone are
    not enough to assert that a figure contains several separate graphs.
    Six-tree sheets are commonly 3 columns x 2 rows; cutting at 60% height
    truncates incident edges and causes the model to invent closing strokes.
    """
    width, height = image.size
    if width < 240 or height < 180:
        return []
    scaled = image.convert("L")
    factor = min(1.0, 650.0 / max(width, height))
    if factor < 1:
        scaled = scaled.resize(
            (max(1, int(width * factor)), max(1, int(height * factor))),
            Image.Resampling.BILINEAR
        )
    w, h = scaled.size
    pixels = scaled.load()
    col_ink = [0] * w
    row_ink = [0] * h
    for y in range(h):
        for x in range(w):
            if pixels[x, y] < 205:
                col_ink[x] += 1
                row_ink[y] += 1

    def blank_gutters(counts, transverse, n, limit):
        threshold = max(1, int(transverse * .004))
        shortest = max(7, int(n * .027))
        runs = []
        begin = None
        for pos in range(n + 1):
            empty = pos < n and counts[pos] <= threshold
            if empty and begin is None:
                begin = pos
            elif not empty and begin is not None:
                if (pos - begin >= shortest
                        and begin >= int(n * .09)
                        and pos <= int(n * .91)):
                    runs.append((begin, pos))
                begin = None
        # Prefer actual broad panel gutters to tiny blank slots in lettering.
        return sorted(runs, key=lambda pair: pair[1]-pair[0], reverse=True)[:limit]

    x_gaps = blank_gutters(col_ink, h, w, 3)
    if not x_gaps:
        return []
    x_cuts = sorted(round((a+b)/2 * width/w) for a, b in x_gaps)
    columns = len(x_cuts) + 1
    # This detector only supplies crops for ordinary 2/3/4-column arrangements.
    if columns not in (2, 3, 4):
        return []
    y_gaps = blank_gutters(row_ink, w, h, 1)
    y_cuts = [round((a+b)/2 * height/h) for a, b in y_gaps]
    # Only use separate row crops when a substantial horizontal gutter
    # truly separates panels. Otherwise group complete columns.
    x_edges = [0, *x_cuts, width]
    y_edges = [0, *y_cuts, height]
    if individual and len(y_edges) == 3:
        boxes = [
            (x_edges[i], y_edges[j], x_edges[i+1], y_edges[j+1])
            for j in range(2) for i in range(columns)
        ]
    else:
        boxes = [
            (x_edges[i], 0, x_edges[i+1], height)
            for i in range(columns)
        ]
    # A small margin into the otherwise empty gutter never touches another
    # graph but avoids losing vertex circles exactly on a panel boundary.
    output = []
    for left, top, right, bottom in boxes:
        margin_x = min(12, max(3, int(width * .007)))
        margin_y = min(12, max(3, int(height * .007)))
        box = (max(0,left-margin_x), max(0,top-margin_y),
               min(width,right+margin_x), min(height,bottom+margin_y))
        if box[2]-box[0] >= 65 and box[3]-box[1] >= 65:
            output.append(image.crop(box))
    return output


def _prepare_vision_images(image_bytes, review_regions=None, graph_regions=None):
    """返回整图和局部放大 PNG；所有图片使用同一个 EXIF 方向。

    有 OCR 区域时优先放大题干；如果 review_regions 为 None，表示普通 OCR
    没拿到可用文字，此时按纯图模式同时补充上下、左右半幅，方便识别
    并排或上下排列的多个无标签图。
    """
    with Image.open(io.BytesIO(image_bytes)) as source:
        original = ImageOps.exif_transpose(source).convert("RGB")
    width, height = original.size

    def encode(image, max_side, enlarge=False):
        longest = max(image.size)
        scale = min(3.0 if enlarge else 1.0, max_side / longest)
        if scale != 1.0:
            image = image.resize(
                (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                Image.Resampling.LANCZOS,
            )
        output = io.BytesIO()
        image.save(output, format="PNG")
        encoded = base64.b64encode(output.getvalue()).decode("ascii")
        return "data:image/png;base64," + encoded

    def enhance_crop(image):
        # The original full image is always sent unchanged. Only a bounded
        # crop gets slight contrast + unsharp-mask to help read faint labels.
        # Unlike thresholding this does not erase thin graph lines.
        if min(image.size) < 40:
            return image
        enhanced = ImageEnhance.Contrast(image).enhance(1.12)
        return enhanced.filter(ImageFilter.UnsharpMask(radius=1.0, percent=95, threshold=2))

    pure_visual_mode = review_regions is None
    crops = []
    if graph_regions and len(graph_regions)>4:
        # Many textbook diagrams on two slides: use grouped row crops rather
        # than sending a paid vision model 8-12 tiny duplicated pictures.
        region_groups=[]
        for box in sorted(graph_regions,key=lambda r:(r[1]+r[3])/2):
            cy=(box[1]+box[3])/2
            if not region_groups or cy-(region_groups[-1][-1][1]+region_groups[-1][-1][3])/2>.14:
                region_groups.append([box])
            else:region_groups[-1].append(box)
        graph_regions=[(min(r[0] for r in group),min(r[1] for r in group),
                        max(r[2] for r in group),max(r[3] for r in group))
                       for group in region_groups[:3]]
    # Full-image graph localization feeds targeted crops BEFORE OCR title crops.
    # Expand outward to retain entire incident edges and vertex circles.
    for region in (graph_regions or [])[:4]:
        try:
            x1,y1,x2,y2 = [float(v) for v in region]
            if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):continue
            margin_x=max(.013,(x2-x1)*.1)
            margin_y=max(.015,(y2-y1)*.12)
            box=(max(0,int((x1-margin_x)*width)),max(0,int((y1-margin_y)*height)),
                 min(width,int((x2+margin_x)*width)),min(height,int((y2+margin_y)*height)))
            if box[2]-box[0]>25 and box[3]-box[1]>25:crops.append(original.crop(box))
        except (TypeError,ValueError,OverflowError):continue
    for region in (review_regions or [])[:2]:
        try:
            if len(region) != 4:
                continue
            values = [float(x) for x in region]
            if not all(math.isfinite(x) and 0 <= x <= 1 for x in values):
                continue
            x1, y1, x2, y2 = values
            if x2 <= x1 or y2 <= y1:
                continue
            box = (math.floor(x1 * width), math.floor(y1 * height),
                   math.ceil(x2 * width), math.ceil(y2 * height))
            crops.append(original.crop(box))
        except (TypeError, ValueError, OverflowError):
            continue
    # Prefer whitespace-demarcated columns over the old arbitrary top/bottom
    # cuts. A Stanford 3x2 tree slide must keep all six diagrams intact.
    if len(graph_regions or []) < 2:
        panel_crops = _diagram_grid_crops(original)
        if len(panel_crops) >= 2:
            crops = panel_crops[:4]
    # OCR may only find a tiny “(b)” caption and supply review regions around
    # the caption while missing the actual graph above it. Preserve structural
    # left/right crops for wide graph illustrations even when OCR found text.
    if crops and len(graph_regions or []) < 3 and width >= height * 1.28:
        crops.extend([
            original.crop((0, 0, math.ceil(width * 0.57), height)),
            original.crop((math.floor(width * 0.43), 0, width, height)),
        ])
    # Four diagrams in one landscape textbook row need four *separate*
    # magnified columns. OCR review regions often cover only the title,
    # while generic top/bottom crops shrink the edge crossings too much.
    # The full original is still always sent as the first image.
    if width >= height * 2.1 and len(graph_regions or []) < 3:
        crops = [
            original.crop((
                max(0, round(width * (i / 4 - .018))), 0,
                min(width, round(width * ((i + 1) / 4 + .018))), height
            )) for i in range(4)
        ]
    if not crops:
        if pure_visual_mode:
            # 纯图模式同时覆盖上下排列和左右排列；保留约 20% 重叠，
            # 避免恰好位于中线附近的顶点/边被裁断。
            crops = [
                original.crop((0, 0, width, math.ceil(height * 0.6))),
                original.crop((0, math.floor(height * 0.4), width, height)),
                original.crop((0, 0, math.ceil(width * 0.6), height)),
                original.crop((math.floor(width * 0.4), 0, width, height)),
            ]
        else:
            crops = [
                original.crop((0, 0, width, math.ceil(height * 0.6))),
                original.crop((0, math.floor(height * 0.4), width, height)),
            ]
    # A single full image plus at most four targeted crops bounds the number
    # of paid Vision image inputs. Prefer complete graph regions over generic
    # left/right halves and avoid sending duplicate overlapping crops.
    crops = crops[:4]
    return [encode(original, 2200)] + [encode(enhance_crop(crop), 1600, True) for crop in crops]


def analyze_image_structure(image_bytes, ocr_text="", retries=1, review_regions=None, opencv_graphs=None):
    """
    使用整图与局部放大图独立转录题干、解析图形结构。
    ocr_text 参数为兼容旧调用保留，不发送给视觉模型；由 app.py 比较两个结果。

    这是 OCR 的增强层：
    - OCR 失败不依赖这里；
    - Vision 失败也不会让已经成功的 OCR 整体失败。
    """
    if not VISION_ENABLED:
        return _failure("图形理解功能当前已关闭。")

    if not API_KEY:
        print("DeepSeek Vision 配置错误：未设置 DEEPSEEK_API_KEY")
        return _failure("图形理解服务尚未完成配置。")

    if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
        return _failure("没有检测到有效图片内容。")

    mime = _guess_image_mime(image_bytes)
    if not mime:
        return _failure("该图片格式暂不支持图形理解，请使用 JPG、PNG、GIF 或 WebP。")

    try:
        image_urls = _prepare_vision_images(
            image_bytes, review_regions,
            graph_regions=(opencv_graphs or {}).get("regions", [])
        )
    except Exception as exc:
        print(f"Vision 图片预处理失败：{type(exc).__name__}")
        return _failure("图片局部放大失败，已保留文字识别结果。")
    content_parts = [{"type": "text", "text": VISION_PROMPT}]
    verified = (opencv_graphs or {}).get("graphs", [])
    if verified:
        content_parts.append({"type":"text", "text":(
            "以下是 OpenCV 从实心圆点及连续像素线迹得到的位置候选，不是已经识别出的顶点字母。"
            "先用每个顶点的归一化 x/y 位置匹配原图的 a/b/c 等标签，再逐线确认边。"
            "交叉点无实心圆点时不得换线或添加顶点；不要为了满足树的 n-1 条边而补边。"
            "confidence=partial 或 uncertain_edges 不得作为确定结论；若原图与候选矛盾，以原图为准。\n"
            + json.dumps(verified, ensure_ascii=False)[:5500]
        )})
    for index, data_url in enumerate(image_urls):
        content_parts.append({"type": "text", "text": "完整上传图片" if index == 0 else f"局部放大 {index}"})
        content_parts.append({"type": "image_url", "image_url": {"url": data_url, "detail": "high"}})

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": content_parts
            }
        ],
        # 图形结构提取是短输出任务，不需要思考模式。
        # DeepSeek Chat Completions 默认会开启 thinking；
        # 显式关闭可避免输出预算被 reasoning_content 占用，
        # 最终 content 为空的情况。
        "thinking": {"type": "disabled"},
        "max_tokens": VISION_MAX_OUTPUT_TOKENS,
        "stream": False
    }

    total_attempts = max(1, retries + 1)

    for attempt in range(total_attempts):
        try:
            print(
                f"正在调用 DeepSeek Vision（第 {attempt + 1}/{total_attempts} 次）"
            )

            response = requests.post(
                API_URL,
                headers=headers,
                json=payload,
                timeout=(10, 90)
            )

            if response.status_code in RETRYABLE_STATUS:
                if attempt < total_attempts - 1:
                    wait_seconds = (2 ** attempt) + random.uniform(0, 0.4)
                    print(
                        f"DeepSeek Vision 暂时不可用，HTTP {response.status_code}，"
                        f"{wait_seconds:.1f} 秒后重试"
                    )
                    time.sleep(wait_seconds)
                    continue

                return _failure(
                    "图形结构理解暂时不可用，已保留文字识别结果。"
                )

            if not response.ok:
                print(
                    f"DeepSeek Vision 请求失败：HTTP {response.status_code}；"
                    f"响应内容：{response.text[:500]}"
                )
                return _failure(
                    "图形结构理解暂时不可用，已保留文字识别结果。"
                )

            try:
                result = response.json()
            except ValueError as exc:
                print(f"DeepSeek Vision 返回解析失败：{repr(exc)}")
                return _failure(
                    "图形结构理解暂时不可用，已保留文字识别结果。"
                )

            choices = result.get("choices")
            if not choices:
                print(f"DeepSeek Vision 返回缺少 choices：{result}")
                return _failure(
                    "图形结构理解暂时不可用，已保留文字识别结果。"
                )

            choice = choices[0] if isinstance(choices[0], dict) else {}
            message = choice.get("message", {})
            if not isinstance(message, dict):
                message = {}

            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                reasoning_content = message.get("reasoning_content")
                reasoning_len = (
                    len(reasoning_content)
                    if isinstance(reasoning_content, str)
                    else 0
                )
                finish_reason = choice.get("finish_reason")
                usage = result.get("usage")

                print(
                    "DeepSeek Vision 返回空内容："
                    f"finish_reason={finish_reason!r}；"
                    f"reasoning_len={reasoning_len}；"
                    f"usage={usage!r}"
                )

                # 实验模型偶发空内容时自动再试一次，
                # 不让一次空响应直接把图形理解判定为失败。
                if attempt < total_attempts - 1:
                    time.sleep((2 ** attempt) + random.uniform(0, 0.4))
                    continue

                return _failure(
                    "图形结构理解没有返回有效结果，已保留文字识别结果。"
                )

            # 输出用尽预算时，即便是可解析 JSON，也可能漏掉后面的小问。
            parsed = None if choice.get("finish_reason") == "length" else _extract_vision_json(content)

            if parsed is None:
                print(
                    "DeepSeek Vision 返回内容不是有效 JSON："
                    f"{content[:500]!r}"
                )

                # 结构化结果很关键。第一次格式异常时自动再试一次，
                # 避免把一坨 JSON/自然语言直接显示给学生。
                if attempt < total_attempts - 1:
                    time.sleep((2 ** attempt) + random.uniform(0, 0.4))
                    continue

                return _failure(
                    "图片内容整理暂时失败，已保留普通文字识别结果。"
                )

            corrected_text = parsed["corrected_text"]
            visual_text = parsed["visual_text"]

            # 校对文字为空时不强行覆盖 OCR；app.py 会自动回退原 OCR。
            print(
                "DeepSeek Vision 调用成功："
                f"corrected_text={len(corrected_text)} chars；"
                f"visual_text={len(visual_text)} chars"
            )

            return _vision_success(
                corrected_text,
                visual_text,
                parsed["uncertain_fields"],
                parsed["image_kind"],
            )

        except requests.exceptions.Timeout as exc:
            print(f"DeepSeek Vision 请求超时：{repr(exc)}")
            if attempt < total_attempts - 1:
                time.sleep((2 ** attempt) + random.uniform(0, 0.4))
                continue
            return _failure(
                "图形结构理解响应较慢，已保留文字识别结果。"
            )

        except requests.exceptions.ConnectionError as exc:
            print(f"DeepSeek Vision 网络连接异常：{repr(exc)}")
            if attempt < total_attempts - 1:
                time.sleep((2 ** attempt) + random.uniform(0, 0.4))
                continue
            return _failure(
                "图形结构理解暂时无法连接，已保留文字识别结果。"
            )

        except requests.exceptions.RequestException as exc:
            print(f"DeepSeek Vision 请求异常：{repr(exc)}")
            return _failure(
                "图形结构理解请求失败，已保留文字识别结果。"
            )

        except Exception as exc:
            print(f"DeepSeek Vision 未知异常：{repr(exc)}")
            return _failure(
                "图形结构理解暂时出现异常，已保留文字识别结果。"
            )

    return _failure(
        "图形结构理解暂时不可用，已保留文字识别结果。"
    )



GRAPH_AUDIT_PROMPT = """你是图论原始图片的第二名独立逐边核验员。只看所附原图和放大图，
不得使用其他模型已经给出的边集，不要推理解题结果。只核验图片中两个有标签的无向图。
必须按顶点位置先辨认标签，再对每一条笔画像素沿线追踪到实际两个端点。

重点：
- 两条直线在空白处交叉但没有实心圆点时，继续沿原来的斜率追踪；
  交叉处有实心黑点才是独立顶点，原斜线应当拆成两条边。
- 一条外部弧线要分别追踪两端：弧线经过某个顶点附近不等于从该顶点出发。
- 不要把经过左上点旁边的弧线当成左上点→右上点，需看它到底连左下或右下。
- 不要把直线和外部弧线误算成重边；只有两条线确实有相同端点才是重边。
- 顶点标签可能是字母 a～h 或整数 1～8（日本会津大学原图就是两种标签的对应）；先建立圆点与真实标签的对应关系，不要按阅读顺序猜边，也不能把整数当作边权或顶点个数。
- 每一条顶点边的 JSON 标签必须保留原有字母或数字，不允许把数字标签擅自改成 v1、v2；两张图标签形式不同并不代表不能同构。
- 边数必须实际数线条得到，不得因为你猜想两图同构而修改边集。
- 若一条边的端点无法完全确认，complete 必须 false，不许猜测边名。
- 不要输出图同构或其他问题答案，也不允许依据两个图应当同构来补造边。
- 只包含题干/说明文字而没有两幅完整无向图时不造图，graphs 设为空数组。

严格输出 JSON 对象，且仅此对象：
{"graphs":[
 {"index":1,"directed":false,"vertices":["a","b"],"edges":[["a","b"]],"complete":true},
 {"index":2,"directed":false,"vertices":["v","w"],"edges":[["v","w"]],"complete":true}
]}
若无法识别完整边集，使用 complete:false 和仅确认的边；不能用近似边凑齐。
"""


DIRECTED_GRAPH_AUDIT_PROMPT = """你是独立的高校图论有向图图像逐箭头核验员。必须只看原始图片及局部放大图，不使用其他模型转录。
图片可能有图(1)、图(2)、图(3)等多张独立的有向图。请逐图辨认所有顶点标签、每一条有向边的准确起点和箭头尖端。
尤其：图与图之间空白处绝对不存在跨图连接；两条线交叉且没有实心顶点时不可虚构节点；箭头尖端决定边的方向。
不能根据“理应连通”补边；不要用连通性的结论倒推图。看不清任何关键箭头或端点时将该图 complete 设为 false。
只返回 JSON 且格式严格为：
{"graphs":[{"index":1,"directed":true,"vertices":["a","b"],"edges":[["a","b"]],"complete":true}]}
请按原图全部编号逐一列出；不要输出问题答案。"""

MULTI_LABELLED_GRAPH_EDGE_AUDIT_PROMPT = """你是图论教材中三至六幅并列无向图的独立逐边审查员。只看原图和局部放大，不读取第一次 OCR 的边集，不解答题目。
请先找到每个完整独立图 G1、G2、G3……，逐图数黑点，核对每个点对应的 a、b、c、d、e、f 等原始标签。
对每条线从起点沿连续像素追踪至终点：交叉处没有实心黑点必须直行，不得换线；例如 b-e 和 a-f 相交不能额外构造 b-f。
无向边 a-b 和 b-a 是同一条，简单图禁止重复列出。不要为了使图“像树”而增删边。
一张图的边数必须等于去重后的边列表长度，全部顶点必须明确。无法确认关键端点就设置 complete=false，不猜测。
按原图从左到右排序，一幅图一个对象。只返回 JSON：
{"graphs":[{"index":1,"directed":false,"vertices":["a","b","c","d","e","f"],"edges":[["a","c"],["b","c"]],"complete":true}]}
若不存在三至六幅各有可读标签的完整无向图，graphs 返回空数组；不要虚构边。"""


MULTI_GRAPH_VERTEX_AUDIT_PROMPT = """你是第二位独立逐点审图员，不得读取其他模型生成的结构或利用题目要求猜出答案。
你会看到包含多幅互相独立的图论图形的原图及放大图，例如 Stanford 六种无标号树。
请为每一幅图按从左到右、从上到下的排列（图1、图2……），认真数出实际画出的顶点实心或空心小圆点个数与连续边笔画数。
若有多个上下排列的图，先在整图里确定每幅图的边界，局部放大图仅用于核实该边界里的线段。顶点处的一条线必须沿线连续延伸到另一真实顶点才算一条边。六点树图常有开放的两端，不能凭视觉对称或轮廓把末端自动闭合成第六条边。
顶点文字、线段交叉点（无实心圆）、线段折点不算新增顶点。不得根据“题目写六顶点”就让每张图有六个点；必须数画面。
若图形局部被遮挡、圆点不清或边界被裁切，complete=false，不猜数值。
仅输出严格 JSON 结构，不解释题目，不给图论结论：
{"graphs":[{"index":1,"vertex_count":6,"edge_count":5,"complete":true}]}
每幅图一个条目，不漏图，不把同一局部放大再当一张新图。"""


SINGLE_LABELLED_GRAPH_AUDIT_PROMPT = """你是第二名独立的图论原图逐边审查员。只根据上传的完整原图与放大图，不读取任何其他模型已生成的顶点表或边表。
本次图片主要有且只有一张带 A、B、C 等字母标签的无向图。请先锁定原图所有圆点与对应标签，再逐条沿笔画连续追踪每一条边到两端。
特别注意斜线交叉点如果没有黑色圆点绝非新顶点；连续直线要按原本走向跟踪，不可在交点转向；靠近另外顶点但实际并未连接的线不能凭位置添加新边。
例如 A—B 的笔画不等于 A—C；只有从 A 点实际延伸到 C 点的线才可写 A—C，不能因几何上靠近 C 就补造边。
先独立确认所有原始顶点，再列出完整无向边集；任何顶点或边的端点不清楚请将 complete=false，禁止猜测，也禁止根据题目想要的直径或色数倒推出边。
严格只输出以下 JSON 对象，不要任何自然语言：
{"graphs":[{"index":1,"directed":false,"vertices":["A","B"],"edges":[["A","B"]],"complete":true}]}
如果图片没有恰好一张完整的带字母无向图，graphs设为空数组。"""

def verify_graph_image_independently(image_bytes, retries=1, directed=False, count_only=False, single=False, multi_edges=False, panel_count=4):
    """A second *independent* image-model read for complex graph topology.

    Used for graph-isomorphism diagrams and independently checked directed
    connectivity diagrams, where Vision can misread arrowheads or crossings.
    Failure is explicit and never interpreted as agreement.
    """
    if not VISION_ENABLED or not API_KEY:
        return {"ok": False, "error": "图形逐边复核不可用"}
    if _guess_image_mime(image_bytes) is None:
        return {"ok": False, "error": "不支持的图片格式"}
    try:
        with Image.open(io.BytesIO(image_bytes)) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
        width, height = image.size
        # Always retain the original entire picture, and send overlapping
        # close-ups of each *actual graph region*. Prior NJU three-arrow
        # figures were tiny in an almost-square 1048×1170 worksheet: neither
        # the old wide nor portrait branch added ANY enlargement. Aizu's
        # vertically stacked two graphs had the same near-square issue.
        crops = [image]
        grid_crops = _diagram_grid_crops(
            image, individual=(count_only or multi_edges)
        )
        if (count_only and len(grid_crops) >= 4):
            # Independent full-panel crops, not 60%-height slices; essential
            # for six Stanford unlabeled trees in two rows.
            crops.extend(grid_crops[:8])
        elif (multi_edges and len(grid_crops) == max(3, min(6, int(panel_count)))):
            crops.extend(grid_crops)
        elif multi_edges and width >= height * 1.85:
            # Split 3-6 figure rows at their real panel count; fixed quarters
            # can cut a three/six-figure drawing through the middle of an edge.
            count = max(3, min(6, int(panel_count)))
            for i in range(count):
                crops.append(image.crop((
                    max(0, round(width * (i / count - .018))), 0,
                    min(width, round(width * ((i + 1) / count + .018))), height
                )))
        elif directed and 0.65 <= width / height <= 1.40:
            # A university worksheet often has 3 numbered arrow figures in
            # one horizontal row amid heading and unrelated proof exercises.
            # Include the full central band AND overlapping thirds so every
            # arrowhead can be followed to its precise dot.
            top = round(height * .25)
            bottom = round(height * .78)
            crops.append(image.crop((0, top, width, bottom)))
            for left, right in ((0, .40), (.30, .70), (.60, 1)):
                crops.append(image.crop((
                    round(left * width), top, round(right * width), bottom
                )))
        elif width >= height * 1.3:
            crops.extend([
                image.crop((0, 0, math.ceil(width * .60), height)),
                image.crop((math.floor(width * .40), 0, width, height)),
            ])
        elif height >= width:
            # Include borderline portrait sources such as Aizu's 402x453
            # two-graph isomorphism sheet; previously 1.15 was too strict,
            # silently skipping BOTH magnified diagrams.
            crops.extend([
                image.crop((0, 0, width, math.ceil(height * .60))),
                image.crop((0, math.floor(height * .40), width, height)),
            ])
        else:
            crops.extend([
                image.crop((0, 0, math.ceil(width * .60), height)),
                image.crop((math.floor(width * .40), 0, width, height)),
            ])
        def encode(im, max_side):
            factor = min(2.4, max_side / max(im.size))
            if factor != 1:
                im = im.resize((round(im.width * factor), round(im.height * factor)),
                               Image.Resampling.LANCZOS)
            out = io.BytesIO()
            im.save(out, format="PNG")
            return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")
        images = [encode(im, 1800) for im in crops]
    except Exception as exc:
        print("逐边核验图片准备失败：", type(exc).__name__)
        return {"ok": False, "error": "无法放大图形"}
    audit_prompt = (MULTI_LABELLED_GRAPH_EDGE_AUDIT_PROMPT if multi_edges else
                    MULTI_GRAPH_VERTEX_AUDIT_PROMPT if count_only else
                    SINGLE_LABELLED_GRAPH_AUDIT_PROMPT if single else
                    DIRECTED_GRAPH_AUDIT_PROMPT if directed else GRAPH_AUDIT_PROMPT)
    content = [{"type":"text", "text":audit_prompt}]
    for number, url in enumerate(images):
        content.extend([
            {"type":"text","text":"完整图像" if number == 0 else f"放大图形区域 {number}"},
            {"type":"image_url","image_url":{"url":url,"detail":"high"}},
        ])
    payload = {
        "model": VISION_MODEL,
        "messages": [{"role":"user","content":content}],
        "thinking":{"type":"disabled"},
        "max_tokens": min(2400, VISION_MAX_OUTPUT_TOKENS),
        "stream":False,
    }
    headers={"Authorization":f"Bearer {API_KEY}", "Content-Type":"application/json"}
    for attempt in range(max(1, retries + 1)):
        try:
            response=requests.post(API_URL, headers=headers, json=payload, timeout=(10,75))
            if not response.ok:
                if response.status_code in RETRYABLE_STATUS and attempt < retries:
                    time.sleep(1)
                    continue
                return {"ok":False,"error":f"图形复核服务 HTTP {response.status_code}"}
            choices=response.json().get("choices") or []
            message=choices[0].get("message") if choices else None
            text=message.get("content") if isinstance(message,dict) else None
            if not isinstance(text,str) or not text.strip():
                if attempt < retries:
                    continue
                return {"ok":False,"error":"图形复核未输出结构"}
            match=re.search(r"\{[\s\S]*\}", text.strip())
            if not match:
                return {"ok":False,"error":"图形复核结果不是 JSON"}
            data=json.loads(match.group(0))
            graphs=data.get("graphs")
            if not isinstance(graphs,list):
                return {"ok":False,"error":"图形复核未输出列表"}
            return {"ok":True,"graphs":graphs}
        except (requests.exceptions.Timeout,requests.exceptions.ConnectionError) as exc:
            if attempt < retries:
                continue
            return {"ok":False,"error":f"图形复核网络异常：{type(exc).__name__}"}
        except Exception as exc:
            print("独立逐边复核异常：",repr(exc))
            return {"ok":False,"error":"图形复核失败"}
    return {"ok":False,"error":"图形复核失败"}
