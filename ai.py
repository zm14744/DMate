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

from PIL import Image, ImageOps

from teaching import teaching_prompt


def _env_flag(name, default=True):
    value = os.environ.get(name)
    if value is None:
        return bool(default)
    return str(value).strip().lower() not in {
        "0", "false", "no", "off", "disable", "disabled"
    }


def _env_float(name, default, minimum, maximum):
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = float(default)
    return max(float(minimum), min(float(maximum), value))

DEEPSEEK_API_KEY = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_CHAT_MODEL = (
    os.environ.get("DEEPSEEK_CHAT_MODEL", "deepseek-flash")
    or "deepseek-flash"
).strip()

# 鲁信杯算力：优先使用。接口按赛事给出的 OpenAI Chat Completions
# 兼容格式调用。注意：赛事示例明确把模型写成 YOUR_MODEL_ID，因此这里
# 不再擅自把官方 DeepSeek 的模型名当作鲁信平台模型 ID。
#
# 推荐配置：
#   LUXIN_API_KEY=...
#   LUXIN_MODEL_ID=鲁信平台实际显示的模型 ID
#
# 如果没有显式配置 LUXIN_MODEL_ID，会尝试一次 /v1/models 自动发现；
# 发现失败就直接使用原 DeepSeek 兜底，不让鲁信配置拖死聊天。
LUXIN_API_KEY = (os.environ.get("LUXIN_API_KEY") or "").strip()
LUXIN_API_URL = (
    os.environ.get(
        "LUXIN_API_URL",
        "https://www.tokensd.com.cn/v1/chat/completions",
    )
    or "https://www.tokensd.com.cn/v1/chat/completions"
).strip()
LUXIN_MODELS_URL = (
    os.environ.get(
        "LUXIN_MODELS_URL",
        "https://www.tokensd.com.cn/v1/models",
    )
    or "https://www.tokensd.com.cn/v1/models"
).strip()
LUXIN_CHAT_MODEL = (os.environ.get("LUXIN_MODEL_ID") or "").strip()

# 鲁信总开关与熔断。海外部署可以显式设置 LUXIN_ENABLED=0，
# 此时请求路径与没有接鲁信时一样，完全不增加等待。
LUXIN_ENABLED = _env_flag("LUXIN_ENABLED", True)
LUXIN_CIRCUIT_BREAKER = _env_flag("LUXIN_CIRCUIT_BREAKER", True)
LUXIN_CIRCUIT_COOLDOWN = _env_float(
    "LUXIN_CIRCUIT_COOLDOWN_SECONDS", 600, 30, 3600
)
LUXIN_PROBE_CONNECT_TIMEOUT = _env_float(
    "LUXIN_PROBE_CONNECT_TIMEOUT", 1.5, 0.3, 5
)
LUXIN_PROBE_READ_TIMEOUT = _env_float(
    "LUXIN_PROBE_READ_TIMEOUT", 2.5, 0.5, 8
)

# 探测直接打到同一个 API 路径（使用 GET，不产生模型调用）。
# 即使返回 401/405，也说明海外服务器已经成功连到该 API 网关；
# 若网络层被国内访问限制拦住，则会在后台超时并打开熔断。
_LUXIN_DEFAULT_HEALTH_URL = LUXIN_API_URL
LUXIN_HEALTH_URL = (
    os.environ.get("LUXIN_HEALTH_URL")
    or _LUXIN_DEFAULT_HEALTH_URL
).strip()

_LUXIN_BREAKER_LOCK = threading.Lock()
_LUXIN_BREAKER_STATE = (
    "disabled"
    if (not LUXIN_ENABLED or not LUXIN_API_KEY)
    else ("closed" if not LUXIN_CIRCUIT_BREAKER else "unknown")
)
_LUXIN_BREAKER_OPEN_UNTIL = 0.0
_LUXIN_PROBE_RUNNING = False
_LUXIN_LAST_BREAKER_REASON = ""
_LUXIN_SKIP_LOGGED = False

_LUXIN_DISCOVERY_ATTEMPTED = False
_LUXIN_DISCOVERED_MODEL = ""
_LUXIN_MODEL_WARNING_SHOWN = False

# 兼容原有 Vision 路径：图片识别仍走原来的 DeepSeek 接口，
# 第二阶段已经稳定的 OCR/Vision 行为不因为接入鲁信算力而改变。
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
4. 如果学生要求“出题”“生成练习题”，只给题目，不附答案和解析；除非学生之后明确要求答案。
5. 如果学生答案有错误，先指出错误类型和思路问题，不要立刻把整道题答案全部给出。
6. 如果请求上下文中出现多条用户消息，只执行最后一条用户消息提出的当前任务；更早的用户消息只用于理解题目背景、指代和上下文，除非最后一条明确要求同时处理它们。不要主动补答或重新执行更早的用户请求。
7. 图片识题会把内容整理成“【题目文字】”和“【图形信息】”（也兼容旧标签“【题干与公式识别】”“【图形结构识别】”），两部分职责不同：
   - 题目的文字要求、编号、问法，以“题目文字”为主。
   - 图中的顶点、边、箭头、邻接关系、层次和二维结构，以“图形信息”为主。
   - 图形区域附近的 OCR 乱码、边名、顶点名重复内容已尽量清理；不要把残留的局部噪声当成关键冲突。
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
- 如果同一张图片里有两个或更多彼此分开的图，必须分别写成“图1”“图2”……，不要把它们合并成一个图。
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
- 每条边逐一核对两个端点；只有确实连接同一对顶点的两条边才叫重边。
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


def _math_delimiters_balanced(text):
    """
    检查 $...$ 与 $$...$$ 是否成对。
    这里只做格式体检，不尝试解释数学内容。
    """
    if not isinstance(text, str):
        return False

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
    plain = re.sub(
        r"\$\$[\s\S]*?\$\$",
        "",
        text
    )
    plain = re.sub(
        r"\$(?!\$)(?:\\.|[^$\n])+\$",
        "",
        plain
    )
    return plain


def _looks_like_broken_math(text):
    if not isinstance(text, str) or not text.strip():
        return True

    suspicious_patterns = (
        r"\\_\{",          # a\_{ij}
        r"\*\{[^}\n]+\}",  # a*{ij} / )*{5\times5}
        r"\$\*",
        r"\*\$",
    )

    if any(re.search(pattern, text) for pattern in suspicious_patterns):
        return True

    if not _math_delimiters_balanced(text):
        return True

    # 分段定义被错误压成一行：
    # 例如 a_{ij}=\{1, 条件, 0, \text{否则}\}
    pseudo_piecewise = re.search(
        r"=\s*\\?\{\s*[^$]{0,500}(?:否则|otherwise)[^$]{0,200}",
        text,
        flags=re.IGNORECASE | re.DOTALL
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


def _luxin_model_rank(model_id):
    """给 /v1/models 返回的模型做保守排序；无法判断时不乱选。"""
    value = str(model_id or "").strip().lower()
    if not value:
        return -1

    score = 0
    if "deepseek" in value:
        score += 40
    if "4.1" in value or "v4.1" in value or "v41" in value:
        score += 40
    if "flash" in value:
        score += 15
    if "chat" in value:
        score += 3
    return score


def _discover_luxin_model():
    """
    未设置 LUXIN_MODEL_ID 时只自动探测一次。

    赛事示例要求 YOUR_MODEL_ID，但公开示例没有给出具体值。这里优先
    使用 /v1/models；若接口不支持、鉴权失败或返回多个无法判断的模型，
    宁可跳过鲁信走原 DeepSeek，也不再猜一个错误模型名反复请求。
    """
    global _LUXIN_DISCOVERY_ATTEMPTED
    global _LUXIN_DISCOVERED_MODEL

    if _LUXIN_DISCOVERY_ATTEMPTED:
        return _LUXIN_DISCOVERED_MODEL

    _LUXIN_DISCOVERY_ATTEMPTED = True
    if not LUXIN_API_KEY:
        return ""

    headers = {"Authorization": f"Bearer {LUXIN_API_KEY}"}
    try:
        response = requests.get(
            LUXIN_MODELS_URL,
            headers=headers,
            timeout=(2, 3),
        )
    except requests.exceptions.RequestException as exc:
        print(f"鲁信模型列表访问失败：{type(exc).__name__}")
        return ""
    except Exception as exc:
        print(f"鲁信模型列表探测异常：{type(exc).__name__}")
        return ""

    if not response.ok:
        print(
            "鲁信模型列表不可用："
            f"HTTP {response.status_code}；请配置 LUXIN_MODEL_ID。"
        )
        return ""

    try:
        payload = response.json()
    except ValueError:
        print("鲁信模型列表不是有效 JSON；请配置 LUXIN_MODEL_ID。")
        return ""

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        print("鲁信模型列表格式未知；请配置 LUXIN_MODEL_ID。")
        return ""

    ids = []
    for item in data:
        if isinstance(item, dict):
            model_id = str(item.get("id") or "").strip()
        else:
            model_id = str(item or "").strip()
        if model_id and model_id not in ids:
            ids.append(model_id)

    if not ids:
        print("鲁信模型列表为空；请配置 LUXIN_MODEL_ID。")
        return ""

    if len(ids) == 1:
        _LUXIN_DISCOVERED_MODEL = ids[0]
    else:
        ranked = sorted(
            ((model_id, _luxin_model_rank(model_id)) for model_id in ids),
            key=lambda pair: pair[1],
            reverse=True,
        )
        best_id, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else -1
        # 只有“明显像 DeepSeek 4.1/Flash”且明显优于其它候选时才自动选。
        if best_score >= 55 and best_score > second_score:
            _LUXIN_DISCOVERED_MODEL = best_id
        else:
            preview = ", ".join(ids[:8])
            print(
                "鲁信返回多个模型但无法安全判断要用哪一个："
                f"{preview}。请显式配置 LUXIN_MODEL_ID。"
            )
            return ""

    print(f"鲁信自动发现模型：{_LUXIN_DISCOVERED_MODEL}")
    return _LUXIN_DISCOVERED_MODEL


def _resolved_luxin_model():
    configured = str(LUXIN_CHAT_MODEL or "").strip()
    if configured and configured.upper() != "YOUR_MODEL_ID":
        return configured
    return _discover_luxin_model()


def _luxin_breaker_open(reason, cooldown=None):
    """打开鲁信熔断；之后用户请求会直接走 DeepSeek，不等待鲁信。"""
    global _LUXIN_BREAKER_STATE
    global _LUXIN_BREAKER_OPEN_UNTIL
    global _LUXIN_LAST_BREAKER_REASON
    global _LUXIN_PROBE_RUNNING
    global _LUXIN_SKIP_LOGGED

    if not LUXIN_CIRCUIT_BREAKER:
        return

    wait_seconds = float(cooldown or LUXIN_CIRCUIT_COOLDOWN)
    with _LUXIN_BREAKER_LOCK:
        _LUXIN_BREAKER_STATE = "open"
        _LUXIN_BREAKER_OPEN_UNTIL = time.monotonic() + max(1.0, wait_seconds)
        _LUXIN_LAST_BREAKER_REASON = str(reason or "鲁信不可用")
        _LUXIN_PROBE_RUNNING = False
        _LUXIN_SKIP_LOGGED = False

    print(
        "鲁信熔断已开启："
        f"{_LUXIN_LAST_BREAKER_REASON}；"
        f"未来 {int(wait_seconds)} 秒用户请求直接走 DeepSeek。"
    )


def _luxin_breaker_close():
    """后台探测或真实请求成功后恢复鲁信主线路。"""
    global _LUXIN_BREAKER_STATE
    global _LUXIN_BREAKER_OPEN_UNTIL
    global _LUXIN_LAST_BREAKER_REASON
    global _LUXIN_PROBE_RUNNING
    global _LUXIN_SKIP_LOGGED

    with _LUXIN_BREAKER_LOCK:
        was_closed = _LUXIN_BREAKER_STATE == "closed"
        _LUXIN_BREAKER_STATE = "closed"
        _LUXIN_BREAKER_OPEN_UNTIL = 0.0
        _LUXIN_LAST_BREAKER_REASON = ""
        _LUXIN_PROBE_RUNNING = False
        _LUXIN_SKIP_LOGGED = False

    if not was_closed:
        print("鲁信后台探测成功：熔断关闭，后续请求恢复优先使用鲁信。")


def _luxin_probe_worker():
    """后台探路。整个函数运行在 daemon 线程中，不占用用户请求时间。"""
    global _LUXIN_PROBE_RUNNING

    try:
        # 这里只验证“服务器能不能连到鲁信站点”。任何 HTTP 状态码都说明
        # TCP/TLS 已经建立；真正的鉴权、模型权限仍由正式请求验证。
        requests.get(
            LUXIN_HEALTH_URL,
            timeout=(LUXIN_PROBE_CONNECT_TIMEOUT, LUXIN_PROBE_READ_TIMEOUT),
            allow_redirects=False,
        )

        # 若没有显式模型 ID，把模型发现也放在后台完成，避免第一条聊天消息
        # 为 /v1/models 额外等待。
        if not str(LUXIN_CHAT_MODEL or "").strip():
            model = _discover_luxin_model()
            if not model:
                _luxin_breaker_open("没有可用的鲁信模型 ID")
                return

        _luxin_breaker_close()

    except requests.exceptions.RequestException as exc:
        _luxin_breaker_open(
            f"后台连接探测失败（{type(exc).__name__}）"
        )
    except Exception as exc:
        _luxin_breaker_open(
            f"后台探测异常（{type(exc).__name__}）"
        )
    finally:
        with _LUXIN_BREAKER_LOCK:
            _LUXIN_PROBE_RUNNING = False


def _schedule_luxin_probe(force=False):
    """需要时启动一次后台探测；绝不在当前聊天请求里同步等待。"""
    global _LUXIN_BREAKER_STATE
    global _LUXIN_PROBE_RUNNING

    if not LUXIN_ENABLED or not LUXIN_API_KEY or not LUXIN_CIRCUIT_BREAKER:
        return False

    now = time.monotonic()
    with _LUXIN_BREAKER_LOCK:
        if _LUXIN_PROBE_RUNNING:
            return False
        if not force:
            if _LUXIN_BREAKER_STATE == "closed":
                return False
            if (
                _LUXIN_BREAKER_STATE == "open"
                and now < _LUXIN_BREAKER_OPEN_UNTIL
            ):
                return False

        _LUXIN_BREAKER_STATE = "probing"
        _LUXIN_PROBE_RUNNING = True

    threading.Thread(
        target=_luxin_probe_worker,
        name="luxin-health-probe",
        daemon=True,
    ).start()
    return True


def _luxin_ready_for_user_request():
    """是否允许本次用户请求走鲁信；未知/探测/熔断状态一律直接跳过。"""
    global _LUXIN_SKIP_LOGGED

    if not LUXIN_ENABLED or not LUXIN_API_KEY:
        return False
    if not LUXIN_CIRCUIT_BREAKER:
        return True

    now = time.monotonic()
    should_probe = False
    with _LUXIN_BREAKER_LOCK:
        state = _LUXIN_BREAKER_STATE
        if state == "closed":
            return True
        if state == "unknown":
            should_probe = True
        elif state == "open" and now >= _LUXIN_BREAKER_OPEN_UNTIL:
            should_probe = True

        if not _LUXIN_SKIP_LOGGED:
            _LUXIN_SKIP_LOGGED = True
            if state == "open":
                print("鲁信处于熔断冷却期：当前请求直接走 DeepSeek，不等待。")
            else:
                print("鲁信正在后台探测：当前请求直接走 DeepSeek，不等待。")

    if should_probe:
        _schedule_luxin_probe()
    return False


def _luxin_response_should_trip(status_code, reasoning_effort):
    """判断 HTTP 错误是否应让整个鲁信线路进入熔断。"""
    try:
        status = int(status_code)
    except (TypeError, ValueError):
        return True

    # 中等/困难的 400 可能只是赛事网关不认识 thinking 参数。
    # 这种情况仍允许简单请求继续吃鲁信额度，不全局熔断。
    effort = str(reasoning_effort or "none").strip().lower()
    if status == 400 and effort in ("high", "max"):
        return False

    return status in {400, 401, 403, 404, 408, 409, 429} or status >= 500


def _text_provider_configs(preferred_provider=None):
    """返回文本模型调用顺序：鲁信优先，原 DeepSeek 永久保留为兜底。"""
    global _LUXIN_MODEL_WARNING_SHOWN
    providers = []

    if LUXIN_API_KEY and _luxin_ready_for_user_request():
        luxin_model = _resolved_luxin_model()
        if luxin_model:
            providers.append({
                "id": "luxin",
                "name": "鲁信算力",
                "url": LUXIN_API_URL,
                "api_key": LUXIN_API_KEY,
                "model": luxin_model,
            })
        elif not _LUXIN_MODEL_WARNING_SHOWN:
            _LUXIN_MODEL_WARNING_SHOWN = True
            print(
                "已配置 LUXIN_API_KEY，但没有可用的鲁信模型 ID。"
                "请在环境变量中增加 LUXIN_MODEL_ID；当前自动使用原 DeepSeek 兜底。"
            )

    if DEEPSEEK_API_KEY:
        providers.append({
            "id": "deepseek",
            "name": "DeepSeek",
            "url": DEEPSEEK_API_URL,
            "api_key": DEEPSEEK_API_KEY,
            "model": DEEPSEEK_CHAT_MODEL,
        })

    if preferred_provider:
        providers.sort(
            key=lambda item: 0 if item["id"] == preferred_provider else 1
        )

    return providers


# 模块加载完成后立即后台探测一次。不会阻塞启动，也不会让第一条聊天消息等待。
if LUXIN_ENABLED and LUXIN_API_KEY and LUXIN_CIRCUIT_BREAKER:
    _schedule_luxin_probe(force=True)


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

    # 鲁信示例只保证 OpenAI Chat Completions 的基础字段。
    # 简单请求严格按示例发送，避免第三方网关因为 DeepSeek 私有字段直接 400。
    if (provider or {}).get("id") == "luxin":
        payload = {
            "model": provider["model"],
            "messages": messages,
            "stream": False,
        }
        if effort == "high":
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = "high"
        return payload

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
    """
    鲁信是优先算力，但不能让它的偶发卡顿拖住整个聊天。

    非思考请求（例如“你好”）只给鲁信一个很短的响应窗口；
    中等/困难题需要真正推理，因此保留更长时间。
    原 DeepSeek 兜底继续沿用调用方原来的超时设置。
    """
    if (provider or {}).get("id") != "luxin":
        return default_timeout

    effort = str(reasoning_effort or "none").strip().lower()
    if effort in ("max", "high"):
        return (6, 60)
    return (4, 10)

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

    默认顺序：鲁信算力 -> 原 DeepSeek。
    鲁信 Key 被撤销、额度不足、模型不可用、网络异常或返回格式异常时，
    自动切回原 DeepSeek，不让外部算力支援成为单点故障。
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
        # 有后备线路时，优先线路只尝试一次：失败就立即切换，
        # 避免“你好”这种简单请求因为鲁信卡顿被重复等待。
        # 最后的兜底线路仍保留原有重试次数。
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
                    if (
                        provider.get("id") == "luxin"
                        and _luxin_response_should_trip(
                            response.status_code, reasoning_effort
                        )
                    ):
                        _luxin_breaker_open(
                            f"HTTP {response.status_code}"
                        )
                    break

                if not response.ok:
                    print(
                        f"{provider['name']} 请求失败："
                        f"HTTP {response.status_code}；"
                        f"响应内容：{response.text[:500]}"
                    )
                    if (
                        provider.get("id") == "luxin"
                        and _luxin_response_should_trip(
                            response.status_code, reasoning_effort
                        )
                    ):
                        _luxin_breaker_open(
                            f"HTTP {response.status_code}"
                        )
                    break

                try:
                    result = response.json()
                except ValueError as exc:
                    last_error = exc
                    print(
                        f"{provider['name']} 返回内容解析失败：{repr(exc)}"
                    )
                    if provider.get("id") == "luxin":
                        _luxin_breaker_open("返回内容不是有效 JSON")
                    break

                if "error" in result:
                    print(
                        f"{provider['name']} API 返回错误："
                        f"{result['error']}"
                    )
                    if provider.get("id") == "luxin":
                        _luxin_breaker_open("API 返回 error")
                    break

                choices = result.get("choices")
                if not choices:
                    print(
                        f"{provider['name']} 返回缺少 choices：{result}"
                    )
                    if provider.get("id") == "luxin":
                        _luxin_breaker_open("返回缺少 choices")
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
                    print(
                        f"{provider['name']} 返回正文为空；"
                        f"reasoning_len="
                        f"{len(reasoning_content) if isinstance(reasoning_content, str) else 0}"
                    )
                    saw_empty_body = True
                    if provider.get("id") == "luxin":
                        _luxin_breaker_open("返回正文为空")
                    break

                if provider.get("id") == "luxin":
                    _luxin_breaker_close()

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
                if provider.get("id") == "luxin":
                    _luxin_breaker_open("请求超时")
                if attempt < attempts - 1:
                    wait_seconds = (2 ** attempt) + random.uniform(0, 0.4)
                    time.sleep(wait_seconds)
                    continue
                break

            except requests.exceptions.ConnectionError as exc:
                last_error = exc
                print(f"{provider['name']} 网络连接异常：{repr(exc)}")
                if provider.get("id") == "luxin":
                    _luxin_breaker_open("网络连接异常")
                if attempt < attempts - 1:
                    wait_seconds = (2 ** attempt) + random.uniform(0, 0.4)
                    time.sleep(wait_seconds)
                    continue
                break

            except requests.exceptions.RequestException as exc:
                last_error = exc
                print(f"{provider['name']} 请求异常：{repr(exc)}")
                if provider.get("id") == "luxin":
                    _luxin_breaker_open(
                        f"请求异常（{type(exc).__name__}）"
                    )
                break

            except Exception as exc:
                last_error = exc
                print(f"{provider['name']} 未知异常：{repr(exc)}")
                if provider.get("id") == "luxin":
                    _luxin_breaker_open(
                        f"未知异常（{type(exc).__name__}）"
                    )
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
    文本回答优先使用鲁信杯算力，异常时自动回退原 DeepSeek 路径。

    简单请求关闭思考；中等和困难题均使用 high 思考。
    鲁信优先，但简单请求若鲁信短时间无响应会快速回退原 DeepSeek。
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

    if not (LUXIN_API_KEY or DEEPSEEK_API_KEY):
        print("AI API 配置错误：LUXIN_API_KEY 与 DEEPSEEK_API_KEY 均未设置")
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
        fallback = _request_text_completion(
            api_messages,
            retries=0,
            reasoning_effort="none",
            max_tokens=min(MAX_OUTPUT_TOKENS, 4500),
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
        print("检测到 AI 数学格式异常，尝试自动重生成。")
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


def _prepare_vision_images(image_bytes, review_regions=None):
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

    pure_visual_mode = review_regions is None
    crops = []
    for region in (review_regions or [])[:4]:
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
    return [encode(original, 2200)] + [encode(crop, 1600, True) for crop in crops]


def analyze_image_structure(image_bytes, ocr_text="", retries=1, review_regions=None):
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
        image_urls = _prepare_vision_images(image_bytes, review_regions)
    except Exception as exc:
        print(f"Vision 图片预处理失败：{type(exc).__name__}")
        return _failure("图片局部放大失败，已保留文字识别结果。")
    content_parts = [{"type": "text", "text": VISION_PROMPT}]
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

