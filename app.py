import os
import json
import re
import threading
import time
from datetime import timedelta
from collections import defaultdict, deque

from flask import Flask, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from ai import ask_ai, analyze_image_structure
from teaching import analyze_messages, analyze_question, extract_current_request


# -----------------------------
# OCR 故障隔离
# -----------------------------
OCR_AVAILABLE = False
OCR_IMPORT_ERROR = None

try:
    from ocr import OCRError, load_models, recognize_image
    OCR_AVAILABLE = True
except Exception as exc:
    OCR_IMPORT_ERROR = repr(exc)
    print(f"OCR 模块导入失败：{OCR_IMPORT_ERROR}")

    class OCRError(Exception):
        pass

    load_models = None
    recognize_image = None



# -----------------------------
# 账号数据库（可选；未配置时不影响游客模式）
# -----------------------------
PSYCOPG_AVAILABLE = False
PSYCOPG_IMPORT_ERROR = None

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
    PSYCOPG_AVAILABLE = True
except Exception as exc:
    psycopg = None
    dict_row = None
    Jsonb = None
    PSYCOPG_IMPORT_ERROR = repr(exc)
    print(f"PostgreSQL 驱动不可用：{PSYCOPG_IMPORT_ERROR}")


def _env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() not in {
        "0", "false", "no", "off", "disable", "disabled"
    }


def _build_database_dsn():
    direct = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_CONNECTION_STRING")
        or os.environ.get("POSTGRES_URL")
        or ""
    ).strip()
    if direct:
        return direct

    host = (os.environ.get("PGHOST") or os.environ.get("POSTGRES_HOST") or "").strip()
    port = (os.environ.get("PGPORT") or os.environ.get("POSTGRES_PORT") or "5432").strip()
    dbname = (os.environ.get("PGDATABASE") or os.environ.get("POSTGRES_DATABASE") or "").strip()
    user = (os.environ.get("PGUSER") or os.environ.get("POSTGRES_USERNAME") or "").strip()
    password = (os.environ.get("PGPASSWORD") or os.environ.get("POSTGRES_PASSWORD") or "").strip()

    if host and dbname and user and password:
        return (
            f"host={host} port={port} dbname={dbname} "
            f"user={user} password={password}"
        )
    return ""


AUTH_DATABASE_DSN = _build_database_dsn()
AUTH_SECRET_KEY = (
    os.environ.get("AUTH_SECRET_KEY")
    or os.environ.get("SECRET_KEY")
    or ""
).strip()
AUTH_CONFIGURED = bool(
    PSYCOPG_AVAILABLE
    and AUTH_DATABASE_DSN
    and AUTH_SECRET_KEY
)
MAX_SYNC_JSON_BYTES = 5 * 1024 * 1024
AUTH_RATE_LIMIT_WINDOW = 60
AUTH_RATE_LIMIT_COUNT = 20
_auth_schema_lock = threading.Lock()
_auth_schema_ready = False
_auth_rate_lock = threading.Lock()
_auth_rate_history = defaultdict(deque)


app = Flask(__name__)

# 账号只使用服务器签名的 HttpOnly Cookie；前端 JS 不保存登录令牌。
app.config.update(
    SECRET_KEY=AUTH_SECRET_KEY or "auth-disabled-placeholder",
    SESSION_COOKIE_NAME="dm_tutor_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_env_bool("SESSION_COOKIE_SECURE", True),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)


# -----------------------------
# 知识图谱数据
# -----------------------------
_BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)
_KNOWLEDGE_GRAPH_PATH = os.path.join(
    _BASE_DIR,
    "knowledge_graph.json"
)


def _load_knowledge_graph():
    try:
        with open(
            _KNOWLEDGE_GRAPH_PATH,
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError("知识图谱文件格式不正确。")

        data.setdefault("version", 1)
        data.setdefault("title", "离散数学知识图谱")
        data.setdefault("description", "")
        data.setdefault("nodes", [])

        if not isinstance(data["nodes"], list):
            data["nodes"] = []

        return data

    except Exception as exc:
        print(
            f"知识图谱加载失败：{repr(exc)}"
        )
        return {
            "version": 1,
            "title": "离散数学知识图谱",
            "description": "知识图谱暂时不可用。",
            "nodes": []
        }


KNOWLEDGE_GRAPH_DATA = _load_knowledge_graph()


# -----------------------------
# 基础限制
# -----------------------------
MAX_MESSAGE_CHARS = 6000
MAX_MESSAGES_PER_REQUEST = 32

MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 单张图片最大 8MB

# multipart/form-data 本身还有少量协议开销，
# 所以 Flask 总请求上限略高于单张图片上限。
app.config["MAX_CONTENT_LENGTH"] = (
    MAX_IMAGE_BYTES + 512 * 1024
)

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_CHAT = 20
RATE_LIMIT_OCR = 10


# -----------------------------
# 运行状态
# -----------------------------
_ocr_ready = False
_ocr_status = (
    "未初始化"
    if OCR_AVAILABLE
    else "不可用"
)

_rate_lock = threading.Lock()
_request_history = defaultdict(deque)

# 图片识别撤销状态。当前部署使用单 worker + 多线程，进程内集合即可让
# “撤销”请求在普通 OCR 与 Vision 两阶段之间生效。
_ocr_cancel_lock = threading.Lock()
_cancelled_ocr_requests = set()


def _normalize_ocr_request_id(value):
    request_id = str(value or "").strip()
    if not request_id or len(request_id) > 128:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", request_id):
        return ""
    return request_id


def _mark_ocr_cancelled(request_id):
    request_id = _normalize_ocr_request_id(request_id)
    if not request_id:
        return False

    with _ocr_cancel_lock:
        _cancelled_ocr_requests.add(request_id)
    return True


def _take_ocr_cancelled(request_id):
    request_id = _normalize_ocr_request_id(request_id)
    if not request_id:
        return False

    with _ocr_cancel_lock:
        if request_id not in _cancelled_ocr_requests:
            return False
        _cancelled_ocr_requests.discard(request_id)
        return True


def _get_client_ip():
    forwarded = request.headers.get(
        "X-Forwarded-For",
        ""
    ).strip()

    if forwarded:
        return forwarded.split(",")[0].strip()

    return request.remote_addr or "unknown"


def _check_rate_limit(ip, route_name):
    """
    简单内存限流：
    - /chat 每分钟最多 20 次
    - /ocr  每分钟最多 10 次
    """
    limit = (
        RATE_LIMIT_CHAT
        if route_name == "chat"
        else RATE_LIMIT_OCR
    )

    key = f"{route_name}:{ip}"
    now = time.time()

    with _rate_lock:
        history = _request_history[key]

        while (
            history
            and now - history[0] > RATE_LIMIT_WINDOW
        ):
            history.popleft()

        if len(history) >= limit:
            return False

        history.append(now)
        return True


def _warm_ocr_models():
    """
    后台预热 OCR。

    普通文字模型成功即可视为 OCR 可用；
    公式模型失败时由 ocr.py 自动降级。
    """
    global _ocr_ready
    global _ocr_status

    if not OCR_AVAILABLE:
        _ocr_ready = False
        _ocr_status = "不可用"
        return

    try:
        _ocr_status = "加载中"
        model_status = load_models()

        _ocr_ready = bool(
            model_status.get("text_ready")
        )

        if model_status.get("formula_ready"):
            _ocr_status = "已就绪"
        else:
            _ocr_status = "已就绪（公式识别降级）"

        print(f"OCR 模型预热完成：{_ocr_status}")

    except Exception as exc:
        _ocr_ready = False
        _ocr_status = "加载失败"
        print(
            f"OCR 模型预热失败：{repr(exc)}"
        )


if OCR_AVAILABLE:
    threading.Thread(
        target=_warm_ocr_models,
        daemon=True
    ).start()


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({
        "error": "图片过大，请上传 8MB 以内的图片。"
    }), 413




# -----------------------------
# 账号 / 云同步
# -----------------------------
def _auth_rate_allowed(route_name):
    ip = _get_client_ip()
    key = f"auth:{route_name}:{ip}"
    now = time.time()

    with _auth_rate_lock:
        history = _auth_rate_history[key]
        while history and now - history[0] > AUTH_RATE_LIMIT_WINDOW:
            history.popleft()
        if len(history) >= AUTH_RATE_LIMIT_COUNT:
            return False
        history.append(now)
        return True


def _auth_unavailable_response():
    message = "账号系统尚未配置。请先连接 PostgreSQL，并设置 AUTH_SECRET_KEY。"
    if not PSYCOPG_AVAILABLE:
        message = "账号系统缺少 PostgreSQL 驱动，请更新 requirements.txt 后重新部署。"
    return jsonify({
        "ok": False,
        "configured": False,
        "error": message,
    }), 503


def _auth_connect():
    if not AUTH_CONFIGURED:
        raise RuntimeError("auth database is not configured")
    return psycopg.connect(
        AUTH_DATABASE_DSN,
        connect_timeout=6,
        row_factory=dict_row,
    )


def _ensure_auth_schema():
    global _auth_schema_ready
    if _auth_schema_ready:
        return True
    if not AUTH_CONFIGURED:
        return False

    with _auth_schema_lock:
        if _auth_schema_ready:
            return True
        try:
            with _auth_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS dm_users (
                            id BIGSERIAL PRIMARY KEY,
                            username VARCHAR(32) NOT NULL,
                            username_key VARCHAR(64) NOT NULL UNIQUE,
                            password_hash TEXT NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS dm_user_data (
                            user_id BIGINT PRIMARY KEY
                                REFERENCES dm_users(id) ON DELETE CASCADE,
                            data JSONB NOT NULL DEFAULT '{}'::jsonb,
                            revision BIGINT NOT NULL DEFAULT 0,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
            _auth_schema_ready = True
            return True
        except Exception as exc:
            print(f"账号数据库初始化失败：{repr(exc)}")
            return False


def _normalize_auth_credentials(payload):
    payload = payload if isinstance(payload, dict) else {}
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")

    if not re.fullmatch(r"[\w.\-\u4e00-\u9fff]{2,32}", username, flags=re.UNICODE):
        return None, None, "用户名需为 2–32 个字符，只使用文字、数字、下划线、点或短横线。"
    if len(password) < 6 or len(password) > 128:
        return None, None, "密码长度需为 6–128 个字符。"

    return username, username.casefold(), None


def _current_auth_user():
    user_id = session.get("user_id")
    if not isinstance(user_id, int):
        return None
    if not _ensure_auth_schema():
        return None

    try:
        with _auth_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, username FROM dm_users WHERE id = %s",
                    (user_id,),
                )
                return cur.fetchone()
    except Exception as exc:
        print(f"读取登录用户失败：{repr(exc)}")
        return None


def _sync_row_for_user(user_id):
    with _auth_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dm_user_data (user_id)
                VALUES (%s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (user_id,),
            )
            cur.execute(
                """
                SELECT data, revision, updated_at
                FROM dm_user_data
                WHERE user_id = %s
                """,
                (user_id,),
            )
            return cur.fetchone()


@app.route("/auth/me", methods=["GET"])
def auth_me():
    if not AUTH_CONFIGURED:
        return jsonify({
            "ok": True,
            "configured": False,
            "authenticated": False,
        })
    if not _ensure_auth_schema():
        return _auth_unavailable_response()

    user = _current_auth_user()
    if not user:
        session.clear()
        return jsonify({
            "ok": True,
            "configured": True,
            "authenticated": False,
        })

    return jsonify({
        "ok": True,
        "configured": True,
        "authenticated": True,
        "user": {"username": user["username"]},
    })


@app.route("/auth/register", methods=["POST"])
def auth_register():
    if not AUTH_CONFIGURED or not _ensure_auth_schema():
        return _auth_unavailable_response()
    if not _auth_rate_allowed("register"):
        return jsonify({"ok": False, "error": "操作过于频繁，请稍后再试。"}), 429
    if not request.is_json:
        return jsonify({"ok": False, "error": "请求格式不正确。"}), 400

    username, username_key, error = _normalize_auth_credentials(request.get_json(silent=True))
    if error:
        return jsonify({"ok": False, "error": error}), 400
    password = str((request.get_json(silent=True) or {}).get("password") or "")
    password_hash = generate_password_hash(password, method="scrypt")

    try:
        with _auth_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO dm_users (username, username_key, password_hash)
                    VALUES (%s, %s, %s)
                    RETURNING id, username
                    """,
                    (username, username_key, password_hash),
                )
                user = cur.fetchone()
                cur.execute(
                    "INSERT INTO dm_user_data (user_id) VALUES (%s)",
                    (user["id"],),
                )
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505":
            return jsonify({"ok": False, "error": "这个用户名已经被使用。"}), 409
        print(f"注册失败：{repr(exc)}")
        return jsonify({"ok": False, "error": "注册失败，请稍后再试。"}), 500

    session.clear()
    session["user_id"] = int(user["id"])
    session.permanent = True
    return jsonify({
        "ok": True,
        "configured": True,
        "authenticated": True,
        "user": {"username": user["username"]},
        "revision": 0,
    })


@app.route("/auth/login", methods=["POST"])
def auth_login():
    if not AUTH_CONFIGURED or not _ensure_auth_schema():
        return _auth_unavailable_response()
    if not _auth_rate_allowed("login"):
        return jsonify({"ok": False, "error": "操作过于频繁，请稍后再试。"}), 429
    if not request.is_json:
        return jsonify({"ok": False, "error": "请求格式不正确。"}), 400

    username, username_key, error = _normalize_auth_credentials(request.get_json(silent=True))
    if error:
        return jsonify({"ok": False, "error": error}), 400
    password = str((request.get_json(silent=True) or {}).get("password") or "")

    try:
        with _auth_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, password_hash
                    FROM dm_users
                    WHERE username_key = %s
                    """,
                    (username_key,),
                )
                user = cur.fetchone()
    except Exception as exc:
        print(f"登录查询失败：{repr(exc)}")
        return jsonify({"ok": False, "error": "登录失败，请稍后再试。"}), 500

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"ok": False, "error": "用户名或密码不正确。"}), 401

    session.clear()
    session["user_id"] = int(user["id"])
    session.permanent = True
    return jsonify({
        "ok": True,
        "configured": True,
        "authenticated": True,
        "user": {"username": user["username"]},
    })


@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/sync", methods=["GET", "PUT"])
def sync_user_data():
    if not AUTH_CONFIGURED or not _ensure_auth_schema():
        return _auth_unavailable_response()

    user = _current_auth_user()
    if not user:
        return jsonify({"ok": False, "error": "请先登录。"}), 401

    user_id = int(user["id"])

    if request.method == "GET":
        try:
            row = _sync_row_for_user(user_id)
        except Exception as exc:
            print(f"读取云端数据失败：{repr(exc)}")
            return jsonify({"ok": False, "error": "读取云端数据失败。"}), 500

        return jsonify({
            "ok": True,
            "data": row["data"] or {},
            "revision": int(row["revision"] or 0),
            "updatedAt": row["updated_at"].isoformat() if row.get("updated_at") else None,
        })

    if not request.is_json:
        return jsonify({"ok": False, "error": "请求格式不正确。"}), 400

    payload = request.get_json(silent=True)
    payload = payload if isinstance(payload, dict) else {}
    data = payload.get("data")
    force = bool(payload.get("force"))

    try:
        base_revision = int(payload.get("baseRevision", 0))
    except (TypeError, ValueError):
        base_revision = -1

    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "同步数据格式不正确。"}), 400
    if base_revision < 0:
        return jsonify({"ok": False, "error": "同步版本号不正确。"}), 400

    try:
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except Exception:
        return jsonify({"ok": False, "error": "同步数据无法序列化。"}), 400

    if len(encoded) > MAX_SYNC_JSON_BYTES:
        return jsonify({"ok": False, "error": "同步数据过大，请先清理部分历史记录。"}), 413

    try:
        with _auth_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO dm_user_data (user_id)
                    VALUES (%s)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    (user_id,),
                )

                if force:
                    cur.execute(
                        """
                        UPDATE dm_user_data
                        SET data = %s,
                            revision = revision + 1,
                            updated_at = NOW()
                        WHERE user_id = %s
                        RETURNING revision, updated_at
                        """,
                        (Jsonb(data), user_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE dm_user_data
                        SET data = %s,
                            revision = revision + 1,
                            updated_at = NOW()
                        WHERE user_id = %s AND revision = %s
                        RETURNING revision, updated_at
                        """,
                        (Jsonb(data), user_id, base_revision),
                    )

                updated = cur.fetchone()

                if not updated:
                    cur.execute(
                        """
                        SELECT data, revision, updated_at
                        FROM dm_user_data
                        WHERE user_id = %s
                        """,
                        (user_id,),
                    )
                    cloud = cur.fetchone()
                    conn.rollback()
                    return jsonify({
                        "ok": False,
                        "conflict": True,
                        "error": "云端数据已经被其他设备更新。",
                        "data": cloud["data"] or {},
                        "revision": int(cloud["revision"] or 0),
                        "updatedAt": cloud["updated_at"].isoformat() if cloud.get("updated_at") else None,
                    }), 409

        return jsonify({
            "ok": True,
            "revision": int(updated["revision"]),
            "updatedAt": updated["updated_at"].isoformat() if updated.get("updated_at") else None,
        })
    except Exception as exc:
        print(f"写入云端数据失败：{repr(exc)}")
        return jsonify({"ok": False, "error": "同步失败，请稍后再试。"}), 500


@app.route("/")
def home():
    # 首页直接注入与 teaching.py / app.py 共用的 knowledge_graph.json，
    # 避免前端再维护一份硬编码图谱而产生不同步。
    return render_template(
        "index.html",
        knowledge_graph_data=KNOWLEDGE_GRAPH_DATA,
    )



def _looks_like_exercise_request(text):
    """识别自然语言中的出题/继续练习请求，并过滤否定、复盘和功能讨论。"""
    value = re.sub(r"\s+", "", str(text or "").strip())

    if not value or len(value) > 140:
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

    # 常见省略“题”字的自然命令。
    if re.fullmatch(r"(?:请|麻烦)?(?:来)?考我(?:一下|下|几道?|一题|一道)?(?:吧)?", value):
        return True
    if re.fullmatch(r"(?:请|麻烦)?(?:陪我|让我|我想|想)?刷(?:几|一|两|二|\d+)?道?(?:题)?(?:吧)?", value):
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
        r"(?:谓词逻辑|命题逻辑|逻辑|数论|计数|组合|递推|图论|图|集合|关系|函数|代数|群|树|欧拉|哈密顿)"
        r"(?:题|练习)?(?:吧)?",
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


_EXERCISE_ANSWER_PATTERN = re.compile(
    r"\[\[WRONGBOOK_ANSWER\]\]([\s\S]*?)\[\[/WRONGBOOK_ANSWER\]\]",
    re.IGNORECASE
)


def _split_exercise_answer(reply):
    """
    从 AI 出题回复中提取系统隐藏答案。
    返回：(用户可见回复, 最终答案)
    """
    if not isinstance(reply, str):
        return "", ""

    match = _EXERCISE_ANSWER_PATTERN.search(reply)

    if not match:
        return reply.strip(), ""

    answer = match.group(1).strip()

    visible = _EXERCISE_ANSWER_PATTERN.sub(
        "",
        reply
    ).strip()

    return visible, answer


def _looks_like_generated_question_reply(text):
    value = str(text or "").strip()

    if not value:
        return False

    if re.search(
        r"【(?:题目|练习题)】"
        r"|(?:^|\n)\s*#{1,4}\s*(?:题目|练习题)\s*(?:\n|$)"
        r"|(?:^|\n)\s*\*\*(?:题目|练习题)[:：]?\*\*"
        r"|(?:^|\n)\s*(?:题目|练习题)\s*[:：]?\s*(?:\n|$)",
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

    has_problem_language = bool(
        re.search(
            r"(?:设|已知|给定|请回答|回答以下|回答下列|求|判断|写出|计算|证明)",
            value
        )
    )

    return bool(
        has_problem_language
        and (
            len(parenthesized) >= 2
            or len(numbered) >= 2
        )
    )


def _extract_generated_question(reply):
    """
    从 AI 练习回复中只提取题目本身。
    不依赖固定题型/知识点，支持单题、多小问、带/不带“题目”标题。
    """
    value = str(reply or "").strip()

    if not value:
        return ""

    heading_patterns = (
        # 先匹配完整加粗标题，避免只吃掉【题目】后留下一个孤立的 **。
        r"(?:^|\n)\s*(?:\*\*|__)\s*【(?:题目|练习题)】\s*(?:\*\*|__)\s*",
        r"【(?:题目|练习题)】",
        r"(?:^|\n)\s*#{1,4}\s*(?:题目|练习题)\s*(?:\n|$)",
        r"(?:^|\n)\s*(?:\*\*|__)\s*(?:题目|练习题)[:：]?\s*(?:\*\*|__)\s*",
        r"(?:^|\n)\s*(?:题目|练习题)\s*[:：]\s*",
        r"(?:^|\n)\s*(?:题目|练习题)\s*(?:\n|$)",
    )

    best = None

    for pattern in heading_patterns:
        match = re.search(pattern, value, flags=re.MULTILINE)
        if match and (best is None or match.start() < best.start()):
            best = match

    if best:
        value = value[best.end():].strip()
    else:
        start_patterns = (
            r"(?:^|\n)\s*(?=设)",
            r"(?:^|\n)\s*(?=已知)",
            r"(?:^|\n)\s*(?=给定)",
            r"(?:^|\n)\s*(?=下列)",
            r"(?:^|\n)\s*(?=在.{0,50}(?:图|集合|关系|系统|空间|序列|网络|情形)中)",
            r"(?:^|\n)\s*(?=求(?:解|证|出|$))",
            r"(?:^|\n)\s*(?=证明)",
            r"(?:^|\n)\s*(?=计算)",
            r"(?:^|\n)\s*(?=判断)",
        )

        start = None
        for pattern in start_patterns:
            match = re.search(pattern, value, flags=re.MULTILINE)
            if match and (start is None or match.start() < start.start()):
                start = match

        if start and start.start() > 0:
            prefix = value[:start.start()].strip()
            if (
                len(prefix) <= 180
                and re.search(
                    r"(?:好的|没问题|可以|这次|给你|我来|我们来|先来|出一道|练习一下|下面是)",
                    prefix
                )
            ):
                value = value[start.start():].strip()

    stop_patterns = (
        r"(?:^|\n)\s*(?:-{3,}\s*\n\s*)?(?:\*\*|__)?"
        r"(?:提示|思考提示|思路提示|解题提示|小提示|关键提示|方法提示|解题思路|思路)"
        r"\s*[:：]?(?:\*\*|__)?",
        r"(?:^|\n)\s*(?:#{1,6}\s*)?"
        r"(?:参考答案|答案|解析|解答|详细解析|解题过程|过程)\s*[:：]?",
        r"(?:^|\n)\s*答\s*[:：]",
        r"(?:^|\n)\s*(?:你先|请先|先尝试|可以先|做完后|卡住了|如果卡住|把答案发给我|告诉我你的进度).{0,220}$",
    )

    stop_index = len(value)
    for pattern in stop_patterns:
        match = re.search(
            pattern,
            value,
            flags=re.IGNORECASE | re.MULTILINE
        )
        if match:
            stop_index = min(stop_index, match.start())

    value = value[:stop_index].strip()
    value = _EXERCISE_ANSWER_PATTERN.sub("", value).strip()

    # 清掉标题切割后偶发残留的 Markdown 装饰，例如单独一行的 ** / __ / ---。
    value = re.sub(
        r"^(?:\s*(?:\*\*|__|[-—_=]{3,})\s*\n)+",
        "",
        value
    )
    value = re.sub(
        r"(?:\n\s*(?:\*\*|__|[-—_=]{3,})\s*)+$",
        "",
        value
    ).strip()

    return value[:6000]


def _clean_answer_only(text):
    """
    最后一道保险：答案区只保留“答案”，不把解析/理由混进去。
    """
    value = str(text or "").strip()

    if not value:
        return ""

    # 去掉常见开场。
    value = re.sub(
        r"^(?:好的[，,。\\s]*)?(?:以下是|最终答案(?:是|为)?)[：:\\s]*",
        "",
        value,
        flags=re.IGNORECASE
    ).strip()

    # 如果模型仍偷偷附带解析，从这些标题开始截断。
    cut_patterns = [
        r"\n\s*(?:#{1,6}\s*)?(?:解析|理由|过程|推导|说明|易错点)\s*[:：]?",
        r"\n\s*(?:因为|所以|由.+可得)\b",
    ]

    cut_index = len(value)

    for pattern in cut_patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            cut_index = min(cut_index, match.start())

    return value[:cut_index].strip()


def _requested_exercise_difficulty(text):
    """
    从自然语言出题请求中读取三档目标难度。
    返回值严格只有：简单 / 中等 / 困难 / 空串。
    """
    value = re.sub(r"\s+", "", str(text or "")).lower()
    if not value:
        return ""

    matches = []

    # “别太难 / 不要太简单”表达的是希望回到常规中档。
    for pattern in (
        r"不要太难", r"别太难", r"不用太难", r"别那么难", r"不要那么难",
        r"不要太简单", r"别太简单", r"不用太简单", r"正常点", r"普通点",
    ):
        for match in re.finditer(pattern, value):
            matches.append((match.start(), "中等"))

    patterns = (
        ("困难", (
            r"最高难度", r"最难", r"困难", r"高难", r"挑战题", r"难题",
            r"难度高", r"有难度", r"难的", r"难一点", r"难一些", r"难点儿", r"复杂一点",
        )),
        ("中等", (
            r"中等难度", r"中等", r"适中", r"普通难度", r"正常难度",
            r"一般难度", r"常规难度", r"适中一点", r"一般点",
        )),
        ("简单", (
            r"低难度", r"简单", r"基础", r"入门", r"容易", r"轻松",
            r"简单一点", r"简单一些", r"容易一点", r"容易些", r"基础一点",
        )),
    )

    for difficulty, expressions in patterns:
        for expression in expressions:
            for match in re.finditer(expression, value):
                prefix = value[max(0, match.start() - 6):match.start()]
                if re.search(r"(?:不要|别|不用|无需|不想要|不要太|别太)$", prefix):
                    continue
                matches.append((match.start(), difficulty))

    if not matches:
        return ""

    # 若一句话先否定一种难度、后明确指定另一种，以最后的明确表达为准。
    matches.sort(key=lambda item: item[0])
    return matches[-1][1]


@app.route("/chat", methods=["POST"])
def chat():
    ip = _get_client_ip()

    if not _check_rate_limit(ip, "chat"):
        return jsonify({
            "error": "当前请求过于频繁，请稍后再试。"
        }), 429

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "error": "请求格式不正确，请检查提交内容。"
        }), 400

    messages = data.get("messages")
    request_kind = str(data.get("request_kind", "") or "").strip().lower()
    client_requires_exercise = request_kind == "exercise"

    if not isinstance(messages, list):
        return jsonify({
            "error": "消息格式不正确，请重新发送。"
        }), 400

    if len(messages) > MAX_MESSAGES_PER_REQUEST:
        messages = messages[
            -MAX_MESSAGES_PER_REQUEST:
        ]

    cleaned = []

    for item in messages:
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
            return jsonify({
                "error": (
                    "单条消息过长，请控制在 "
                    f"{MAX_MESSAGE_CHARS} 个字符以内。"
                )
            }), 400

        cleaned.append({
            "role": role,
            "content": content
        })

    if not cleaned:
        return jsonify({
            "error": "没有检测到有效消息内容。"
        }), 400

    latest_user_before_reference = next(
        (item for item in reversed(cleaned) if item["role"] == "user"),
        None,
    )
    latest_action_for_exercise = extract_current_request(
        latest_user_before_reference["content"]
        if latest_user_before_reference
        else ""
    )

    # 同知识点出题的参照题由前端显式提交。只接收题干，分类由后端重新计算。
    reference = data.get("exercise_reference")
    reference_teaching = None
    if reference is not None:
        if (not client_requires_exercise or not isinstance(reference, dict)
                or not isinstance(reference.get("question"), str)
                or not reference["question"].strip()
                or len(reference["question"]) > MAX_MESSAGE_CHARS):
            return jsonify({"error": "练习参照题格式不正确，请重新选择题目。"}), 400
        reference_text = reference["question"].strip()
        reference_teaching = analyze_question(reference_text)
        # 无论客户端是否已打包锚点，后端都统一为一份参照题和一个当前动作。
        latest_user = next((item for item in reversed(cleaned) if item["role"] == "user"), None)
        if latest_user is None:
            return jsonify({"error": "缺少本次出题请求。"}), 400
        latest_action = extract_current_request(latest_user["content"])
        content = ("【当前指向题目】\n" + reference_text + "\n【当前指向题目结束】\n"
                   "【本轮唯一需要执行的用户请求】\n" + latest_action + "\n【本轮请求结束】")
        if len(content) > MAX_MESSAGE_CHARS:
            return jsonify({"error": "参照题和出题要求过长，请精简后重试。"}), 400
        cleaned = [{"role": "user", "content": content}]

    teaching = analyze_messages(cleaned)

    # 双保险：前端 request_kind 是强信号，但后端仍独立理解自然语言。
    # 因此用户换成“随便来一道 / 整个难题 / 考我一道”等说法时，
    # 即使前端某次没有命中，也不会退回普通聊天模式。
    server_detected_exercise = _looks_like_exercise_request(
        latest_action_for_exercise
    )
    effective_exercise_request = bool(
        client_requires_exercise
        or (teaching or {}).get("mode") == "exercise"
        or server_detected_exercise
    )

    if effective_exercise_request:
        teaching = dict(reference_teaching or teaching or {})
        requested_difficulty = _requested_exercise_difficulty(
            latest_action_for_exercise
        )

        # 用户明确指定难度时严格按指定值；
        # “照这题再出一道”且未指定时继承参照题；
        # 独立的“出个题”默认中等，避免无条件生成困难题。
        if requested_difficulty:
            exercise_target_difficulty = requested_difficulty
        elif reference_teaching and reference_teaching.get("difficulty") in (
            "简单", "中等", "困难"
        ):
            exercise_target_difficulty = reference_teaching["difficulty"]
        else:
            exercise_target_difficulty = "中等"

        teaching["mode"] = "exercise"
        teaching["mode_label"] = "练习出题"
        teaching["question_type"] = teaching.get("question_type") or "出题请求"
        teaching["difficulty"] = exercise_target_difficulty
        teaching["exercise_target_difficulty"] = exercise_target_difficulty

    try:
        result = ask_ai(
            cleaned,
            teaching_context=teaching
        )
    except Exception as exc:
        # app 层最后一道保险。
        print(
            f"/chat 调用 AI 模块异常：{repr(exc)}"
        )
        return jsonify({
            "error": "AI 服务暂时出现异常，请稍后重试。"
        }), 500

    if not isinstance(result, dict):
        print(
            "AI 模块返回格式异常："
            f"{type(result).__name__}"
        )
        return jsonify({
            "error": "AI 服务返回格式异常，请稍后重试。"
        }), 500

    if result.get("ok") is True:
        reply = result.get("reply", "")

        if not isinstance(reply, str) or not reply.strip():
            return jsonify({
                "error": "AI 服务没有生成有效回答，请重新发送。"
            }), 502

        generated_answer = ""
        generated_teaching = None

        latest_user_text = ""
        for item in reversed(cleaned):
            if item.get("role") == "user":
                latest_user_text = item.get("content", "")
                break

        is_exercise_request = (
            effective_exercise_request
            or teaching.get("mode") == "exercise"
            or _looks_like_exercise_request(
                latest_user_text
            )
        )

        generated_question = ""

        if is_exercise_request:
            visible_reply, generated_answer = _split_exercise_answer(
                reply
            )

            generated_answer = _clean_answer_only(
                generated_answer
            )

            generated_question = _extract_generated_question(
                visible_reply
            )

            # 强元数据兜底：本轮既然明确是出题请求，就不允许出现
            # “题目已经显示，但 generated_question 没登记”的状态。
            # 如果模型没有按标题格式输出，直接把清理后的可见正文登记为题干。
            if not generated_question:
                generated_question = str(visible_reply or "").strip()[:6000]

            if not generated_question:
                return jsonify({
                    "error": "练习题生成结果缺少有效题干，请重新出题。",
                    "teaching": teaching
                }), 502

            try:
                generated_teaching = analyze_question(
                    generated_question
                )
            except Exception as exc:
                print("AI 生成题知识识别失败：", repr(exc))
                return jsonify({
                    "error": "练习题已经生成，但题目登记失败，请重新出题。",
                    "teaching": teaching
                }), 500

            if not isinstance(generated_teaching, dict):
                return jsonify({
                    "error": "练习题已经生成，但题目分类无效，请重新出题。",
                    "teaching": teaching
                }), 500

            # 阻止已能明确分类的跨课程串题进入聊天和错题本。
            # 分类不能替代数学核验；分类未知时不据此断言模型出错。
            if reference_teaching:
                expected = reference_teaching.get("category")
                actual = generated_teaching.get("category")
                if expected not in (None, "", "待识别") and actual not in (None, "", "待识别", expected):
                    return jsonify({
                        "error": "生成的练习偏离了参照题的知识点，请重新生成。",
                        "teaching": teaching,
                    }), 502

            # 生成后再按实际题干验一次难度。默认“随便出一道”目标就是中等；
            # 若模型偶尔生成成简单/困难，自动重生成，不能把偏离目标的题直接展示。
            target_difficulty = teaching.get("exercise_target_difficulty")
            actual_difficulty = generated_teaching.get("difficulty")

            if (
                target_difficulty in ("简单", "中等", "困难")
                and actual_difficulty in ("简单", "中等", "困难")
                and actual_difficulty != target_difficulty
            ):
                matched_difficulty = False

                for retry_index in range(2):
                    retry_messages = list(cleaned)
                    retry_messages.append({
                        "role": "user",
                        "content": (
                            "系统校验发现刚才生成题的实际难度与目标难度不一致。"
                            f"请重新生成一道严格属于‘{target_difficulty}’难度的题。"
                            "保持原来的知识点/参照题要求，但调整步骤数量、综合程度和计算量。"
                            "仍然严格遵守系统规定的【题目】与隐藏答案格式，不要解释这次重生成。"
                        ),
                    })

                    try:
                        retry_result = ask_ai(
                            retry_messages,
                            teaching_context=teaching,
                        )
                    except Exception as exc:
                        print(
                            "练习难度自动重生成异常：",
                            repr(exc),
                        )
                        break

                    if not isinstance(retry_result, dict) or not retry_result.get("ok"):
                        break

                    retry_reply = retry_result.get("reply", "")
                    if not isinstance(retry_reply, str) or not retry_reply.strip():
                        continue

                    retry_visible, retry_answer = _split_exercise_answer(
                        retry_reply
                    )
                    retry_answer = _clean_answer_only(retry_answer)
                    retry_question = _extract_generated_question(
                        retry_visible
                    )
                    if not retry_question:
                        retry_question = str(retry_visible or "").strip()[:6000]
                    if not retry_question:
                        continue

                    try:
                        retry_teaching = analyze_question(
                            retry_question
                        )
                    except Exception as exc:
                        print(
                            "练习难度重生成后的题目分析失败：",
                            repr(exc),
                        )
                        continue

                    if not isinstance(retry_teaching, dict):
                        continue

                    if reference_teaching:
                        expected = reference_teaching.get("category")
                        retry_category = retry_teaching.get("category")
                        if (
                            expected not in (None, "", "待识别")
                            and retry_category not in (None, "", "待识别", expected)
                        ):
                            continue

                    if retry_teaching.get("difficulty") != target_difficulty:
                        continue

                    reply = retry_reply
                    generated_answer = retry_answer
                    generated_question = retry_question
                    generated_teaching = retry_teaching
                    matched_difficulty = True
                    print(
                        f"练习难度已在第 {retry_index + 1} 次自动重生成后匹配："
                        f"{target_difficulty}"
                    )
                    break

                if not matched_difficulty:
                    return jsonify({
                        "error": (
                            "连续生成的练习难度都偏离目标，已停止展示不匹配题目。"
                            "请重新出题。"
                        ),
                        "teaching": teaching,
                    }), 502

            # 只有题干、分类和目标难度都完成校验后，才把题目展示给前端。
            reply = (
                "【题目】\n\n"
                + generated_question
            )

        response = {
            "reply": reply,
            "teaching": teaching,
            "generated_exercise": bool(is_exercise_request and generated_question)
        }

        if generated_teaching:
            response["generated_teaching"] = generated_teaching

        if generated_question:
            response["generated_question"] = generated_question

        if generated_answer:
            response["generated_answer"] = generated_answer

        return jsonify(response)

    error = result.get(
        "error",
        "AI 服务暂时不可用，请稍后重试。"
    )

    return jsonify({
        "error": error,
        "teaching": teaching
    }), 503


@app.route("/analyze-questions", methods=["POST"])
def analyze_questions_batch():
    """批量重新识别历史题目的模块和知识点，不调用大模型。"""
    data = request.get_json(silent=True) or {}
    items = data.get("questions")

    if not isinstance(items, list):
        return jsonify({
            "error": "题目列表格式不正确。"
        }), 400

    results = []

    for item in items[:80]:
        if isinstance(item, dict):
            key = str(item.get("key", ""))
            text = str(item.get("text", "")).strip()
        else:
            key = ""
            text = str(item or "").strip()

        if not text:
            results.append({
                "key": key,
                "teaching": None
            })
            continue

        try:
            teaching = analyze_question(
                text[:6000]
            )
        except Exception as exc:
            print("历史题目知识识别失败：", repr(exc))
            teaching = None

        results.append({
            "key": key,
            "teaching": teaching
        })

    return jsonify({
        "results": results
    })


def _numbered_ocr_questions(text):
    """只比较正文的小问，不让图中散落的顶点标签参与题干校验。"""
    matches = list(re.finditer(
        r"(?m)^\s*(?:[（(]\s*(\d{1,2})\s*[）)]|([0-9]{1,2})[.．、])\s*",
        str(text or ""),
    ))
    questions = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        questions[match.group(1) or match.group(2)] = text[match.end():end].strip()
    return questions


def _ocr_math_tokens(text):
    """统一 v3 / v_3 / v_{3} / v₃ 等写法；不更改数字的值。"""
    value = str(text).translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
    value = re.sub(r"([A-Za-z])\s*_\s*\{?\s*(\d+)\s*\}?", r"\1\2", value)
    return re.findall(r"[A-Za-z]\s*\d+|\d+(?:\.\d+)?", value)


def _prepare_ocr_review(ocr_text, corrected_text, uncertain_fields=None):
    """Vision 是待核对候选。漏问时保留 OCR，数字变化明确列出。"""
    original = _numbered_ocr_questions(ocr_text)
    candidate = _numbered_ocr_questions(corrected_text)
    missing = sorted(set(original) - set(candidate), key=int) if corrected_text else []
    reasons = []
    changes = []
    if missing:
        reasons.append("另一份识别结果缺少第 " + "、".join(missing) + " 问，已保留原文字结果。")
        corrected_text = ""
    else:
        for number in sorted(set(original) & set(candidate), key=int):
            before, after = _ocr_math_tokens(original[number]), _ocr_math_tokens(candidate[number])
            if before != after:
                changes.append({"question": number, "ocr": "、".join(before), "vision": "、".join(after)})
        if changes:
            reasons.append("第 " + "、".join(x["question"] for x in changes) + " 问的数字或下标识别不一致，请对照原图。")
    for field in uncertain_fields or []:
        if isinstance(field, str) and field.strip():
            reasons.append(field.strip()[:240])
    return corrected_text or ocr_text, {"required": True, "reasons": reasons, "critical_changes": changes}


@app.route("/ocr/cancel", methods=["POST"])
def cancel_ocr():
    data = request.get_json(silent=True) or {}
    request_id = _normalize_ocr_request_id(data.get("request_id"))

    if not request_id:
        return jsonify({"error": "撤销请求无效。"}), 400

    _mark_ocr_cancelled(request_id)
    return jsonify({"cancelled": True})


@app.route("/ocr", methods=["POST"])
def ocr():
    # 普通 OCR 与 Vision 互为兜底。即使 PaddleOCR 暂时不可用，
    # 也允许 Vision 处理“只有图、没有文字”的题目。
    ip = _get_client_ip()

    if not _check_rate_limit(ip, "ocr"):
        return jsonify({
            "error": "图片识别请求过于频繁，请稍后再试。"
        }), 429

    request_id = _normalize_ocr_request_id(
        request.form.get("request_id", "")
    )

    # 如果撤销通知比上传请求更早抵达，直接结束，不启动模型。
    if request_id and _take_ocr_cancelled(request_id):
        return jsonify({"cancelled": True})

    uploaded = (
        request.files.get("image")
        or request.files.get("file")
    )

    if uploaded is None:
        return jsonify({
            "error": "没有检测到图片，请重新上传。"
        }), 400

    raw = uploaded.read()

    if not raw:
        return jsonify({
            "error": "图片内容为空，请重新上传。"
        }), 400

    if len(raw) > MAX_IMAGE_BYTES:
        return jsonify({
            "error": "图片过大，请上传 8MB 以内的图片。"
        }), 413

    try:
        result = {
            "text": "",
            "text_count": 0,
            "formula_count": 0,
            "warning": None,
            "review_regions": None,
        }
        ocr_fallback_reason = None
        ocr_succeeded = False

        if OCR_AVAILABLE and recognize_image is not None:
            try:
                result = recognize_image(raw)
                ocr_succeeded = True

                # 即使后台预热曾经失败，只要本次识别成功，就同步刷新就绪状态。
                global _ocr_ready
                global _ocr_status
                _ocr_ready = True
                _ocr_status = (
                    "已就绪（公式识别降级）"
                    if result.get("warning")
                    else "已就绪"
                )
            except OCRError as exc:
                # “完全无文字的图论图”会走到这里。不要直接 400，
                # 改由 Vision 读取整图及上下/左右局部。
                ocr_fallback_reason = str(exc)
                print(f"普通 OCR 未得到可用文字，转纯图 Vision：{ocr_fallback_reason}")
        else:
            ocr_fallback_reason = "普通文字 OCR 当前不可用"

        ocr_text = str(result.get("text", "") or "").strip()

        # 撤销若发生在普通 OCR 期间，到这里立即结束，不再调用 Vision。
        if request_id and _take_ocr_cancelled(request_id):
            return jsonify({"cancelled": True})

        # OCR 成功时使用它定位出的题干区域；OCR 无文字/失败时传 None，
        # 让 Vision 进入纯图模式，同时查看上下和左右局部。
        vision_regions = (
            result.get("review_regions", [])
            if ocr_succeeded
            else None
        )

        try:
            vision_result = analyze_image_structure(
                raw, review_regions=vision_regions
            )
        except Exception as exc:
            print(f"Vision 增强层异常：{type(exc).__name__}")
            vision_result = {
                "ok": False,
                "error": "图片复核暂时不可用。"
            }

        # 撤销若发生在 Vision 调用期间，模型返回后立即丢弃结果。
        if request_id and _take_ocr_cancelled(request_id):
            return jsonify({"cancelled": True})

        corrected_text = ""
        visual_text = ""
        vision_warning = None
        uncertain_fields = []

        if (
            isinstance(vision_result, dict)
            and vision_result.get("ok") is True
        ):
            corrected_text = str(
                vision_result.get("corrected_text", "")
            ).strip()

            visual_text = str(
                vision_result.get(
                    "visual_text",
                    vision_result.get("reply", "")
                )
            ).strip()

            if visual_text == "未发现需要补充的图形结构。":
                visual_text = ""
            uncertain_fields = vision_result.get("uncertain_fields", [])
            if not isinstance(uncertain_fields, list):
                uncertain_fields = []
        else:
            if isinstance(vision_result, dict):
                vision_warning = vision_result.get("error")
            if not vision_warning:
                vision_warning = (
                    "图形结构理解暂时不可用，已保留文字识别结果。"
                )

        # 撤销若发生在 Vision 调用期间，结果也直接丢弃。
        if request_id and _take_ocr_cancelled(request_id):
            return jsonify({"cancelled": True})

        # 两路都没有拿到任何可用内容时才真正判定识别失败。
        if not ocr_text and not corrected_text and not visual_text:
            message = (
                vision_warning
                or ocr_fallback_reason
                or "没有识别到有效的题目内容。"
            )
            return jsonify({
                "error": message + " 请尝试重新拍摄、裁剪，或提高图形与背景的对比度。"
            }), 400

        warnings = []
        if result.get("warning"):
            warnings.append(str(result.get("warning")))
        if ocr_fallback_reason and (corrected_text or visual_text):
            warnings.append("未识别到可用文字，已按纯图形模式解析。")
        if vision_warning and ocr_text:
            # OCR 有结果时 Vision 失败只是降级；纯图模式下如果 Vision 失败，
            # 上面已经作为整体失败返回，不再重复警告。
            warnings.append(str(vision_warning))

        display_text, review = _prepare_ocr_review(
            ocr_text, corrected_text, uncertain_fields
        )

        return jsonify({
            "text": display_text,
            "visual_text": visual_text,
            "raw_ocr_text": ocr_text,
            "review": review,
            "text_count": result.get(
                "text_count",
                0
            ),
            "formula_count": result.get(
                "formula_count",
                0
            ),
            "vision_used": bool(vision_result.get("ok")) if isinstance(vision_result, dict) else False,
            "warning": "；".join(warnings) if warnings else None,
        })

    except OCRError as exc:
        return jsonify({
            "error": str(exc)
        }), 400

    except Exception as exc:
        print(
            f"/ocr 接口异常：{repr(exc)}"
        )
        return jsonify({
            "error": "题目识别暂时失败，请稍后重试。"
        }), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok"
    })


@app.route("/ready", methods=["GET"])
def ready():
    return jsonify({
        "web": "正常",
        "ocr_available": OCR_AVAILABLE,
        "ocr_ready": _ocr_ready,
        "ocr_status": _ocr_status
    })


if __name__ == "__main__":
    port = int(
        os.environ.get("PORT", 5000)
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
