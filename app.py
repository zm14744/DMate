import os
import json
import re
import secrets
import threading
import time
import smtplib
import ssl
import hmac
import requests
import hashlib
from email.message import EmailMessage
from datetime import timedelta
from collections import defaultdict, deque, OrderedDict
import ipaddress

from flask import Flask, jsonify, render_template, request, session, make_response, redirect
from werkzeug.security import check_password_hash, generate_password_hash

from ai import ask_ai, analyze_image_structure
try:
    from graph_recognition import recognize_graphs
except (ImportError, OSError) as _graph_import_error:
    print(f"OpenCV 图结构模块不可用，保留原 Vision 识别：{_graph_import_error}")
    recognize_graphs = None
from classification_semantic import classify_ambiguous_questions
from teaching import (
    analyze_messages,
    analyze_question,
    extract_current_request,
    looks_like_exercise_request,
    normalize_user_request_text,
)


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

# 邮件发送：Brevo API 为主通道，原 QQ/SMTP 保留为自动备用通道。
BREVO_API_KEY = (os.environ.get("BREVO_API_KEY") or "").strip()
BREVO_SENDER_EMAIL = (
    os.environ.get("BREVO_SENDER_EMAIL")
    or os.environ.get("SMTP_FROM_EMAIL")
    or ""
).strip()
BREVO_SENDER_NAME = (
    os.environ.get("BREVO_SENDER_NAME")
    or os.environ.get("SMTP_FROM_NAME")
    or "DMate"
).strip()
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
BREVO_CONFIGURED = bool(BREVO_API_KEY and BREVO_SENDER_EMAIL)

SMTP_HOST = (os.environ.get("SMTP_HOST") or "smtp.qq.com").strip()
try:
    SMTP_PORT = int((os.environ.get("SMTP_PORT") or "465").strip())
except (TypeError, ValueError):
    SMTP_PORT = 465
SMTP_USERNAME = (os.environ.get("SMTP_USERNAME") or "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD") or ""
SMTP_FROM_EMAIL = (os.environ.get("SMTP_FROM_EMAIL") or SMTP_USERNAME).strip()
SMTP_FROM_NAME = (os.environ.get("SMTP_FROM_NAME") or "DMate").strip()
SMTP_USE_SSL = _env_bool("SMTP_USE_SSL", True)
SMTP_CONFIGURED = bool(
    SMTP_HOST and SMTP_PORT and SMTP_USERNAME and SMTP_PASSWORD and SMTP_FROM_EMAIL
)
EMAIL_DELIVERY_CONFIGURED = bool(BREVO_CONFIGURED or SMTP_CONFIGURED)

# Android 安装版使用 APK；普通 Android 浏览器通过浏览器安装菜单添加网页应用。
ANDROID_APK_URL = (os.environ.get("ANDROID_APK_URL") or "").strip()

# 桌面客户端：Windows / macOS / Linux 统一使用 Tauri，不再依赖浏览器 PWA。
DESKTOP_WINDOWS_URL = (os.environ.get("DESKTOP_WINDOWS_URL") or "").strip()
DESKTOP_MACOS_URL = (os.environ.get("DESKTOP_MACOS_URL") or "").strip()
DESKTOP_LINUX_DEB_URL = (os.environ.get("DESKTOP_LINUX_DEB_URL") or "").strip()
DESKTOP_LINUX_APPIMAGE_URL = (os.environ.get("DESKTOP_LINUX_APPIMAGE_URL") or "").strip()

MAX_SYNC_JSON_BYTES = 12 * 1024 * 1024
AUTH_RATE_LIMIT_WINDOW = 60
AUTH_RATE_LIMIT_COUNT = 20
EMAIL_CODE_TTL_SECONDS = 10 * 60
EMAIL_CODE_RESEND_SECONDS = 60
EMAIL_CODE_MAX_ATTEMPTS = 6
EMAIL_CODE_MAX_PER_HOUR = 8
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
    # 普通浏览器关闭/重新打开后仍保持登录；用户持续使用时滚动续期。
    SESSION_REFRESH_EACH_REQUEST=True,
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
# Unmatched cancellation messages must not accumulate indefinitely.
# The client uses unique request IDs; 120s covers normal OCR request startup.
OCR_CANCEL_TTL_SECONDS = 120.0
OCR_CANCEL_MAX_PENDING = 1024
_cancelled_ocr_requests = OrderedDict()  # request ID -> monotonic expiration

# Only trust forwarding headers when the directly-connected proxy is explicitly
# configured. An arbitrary public client must never choose its own rate-limit IP.
TRUSTED_PROXY_CIDRS = []
for _cidr in (os.environ.get("TRUSTED_PROXY_CIDRS") or "").split(","):
    if _cidr.strip():
        try:
            TRUSTED_PROXY_CIDRS.append(ipaddress.ip_network(_cidr.strip(), strict=False))
        except ValueError:
            print("忽略无效的 TRUSTED_PROXY_CIDRS 项。")

RATE_LIMIT_MAX_IDENTITIES = 4096


def _normalize_ocr_request_id(value):
    request_id = str(value or "").strip()
    if not request_id or len(request_id) > 128:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", request_id):
        return ""
    return request_id


def _trim_ocr_cancellations(now):
    # OrderedDict preserves insertion order. Old IDs expire even when OCR
    # cancellation notices arrive without a matching upload.
    for key, expiry in list(_cancelled_ocr_requests.items()):
        if expiry <= now:
            _cancelled_ocr_requests.pop(key, None)
    while len(_cancelled_ocr_requests) > OCR_CANCEL_MAX_PENDING:
        _cancelled_ocr_requests.popitem(last=False)


def _mark_ocr_cancelled(request_id):
    request_id = _normalize_ocr_request_id(request_id)
    if not request_id:
        return False
    with _ocr_cancel_lock:
        now = time.monotonic()
        _trim_ocr_cancellations(now)
        _cancelled_ocr_requests.pop(request_id, None)
        _cancelled_ocr_requests[request_id] = now + OCR_CANCEL_TTL_SECONDS
        _trim_ocr_cancellations(now)
    return True


def _take_ocr_cancelled(request_id):
    request_id = _normalize_ocr_request_id(request_id)
    if not request_id:
        return False
    with _ocr_cancel_lock:
        now = time.monotonic()
        _trim_ocr_cancellations(now)
        return _cancelled_ocr_requests.pop(request_id, None) is not None


def _get_client_ip():
    remote = (request.remote_addr or "").strip()
    try:
        peer = ipaddress.ip_address(remote)
    except ValueError:
        return "unknown"
    if not any(peer in network for network in TRUSTED_PROXY_CIDRS):
        return str(peer)

    # Walk backwards over the trusted proxy chain. Never take the leftmost
    # X-Forwarded-For value blindly: the client could have supplied it.
    chain = (request.headers.get("X-Forwarded-For") or "").split(",")
    for candidate in reversed(chain):
        try:
            address = ipaddress.ip_address(candidate.strip())
        except ValueError:
            return str(peer)
        if not any(address in network for network in TRUSTED_PROXY_CIDRS):
            return str(address)
    return str(peer)


def _trim_rate_limit_identities(history_map, now, window):
    # Bound the per-process rate-limit bookkeeping even under hostile traffic.
    if len(history_map) <= RATE_LIMIT_MAX_IDENTITIES:
        return
    for key, history in list(history_map.items()):
        if not history or now - history[-1] > window:
            history_map.pop(key, None)
    while len(history_map) > RATE_LIMIT_MAX_IDENTITIES:
        history_map.pop(next(iter(history_map)))


def _check_rate_limit(ip, route_name):
    """
    简单内存限流：
    - /chat 每分钟最多 20 次
    - /ocr  每分钟最多 10 次
    """
    limit = (
        RATE_LIMIT_CHAT if route_name == "chat" else
        45 if route_name == "ocr_cancel" else RATE_LIMIT_OCR
    )

    # A signed logged-in session gets its own quota. Without this, users
    # behind the same hosted reverse proxy can exhaust each other's allowance.
    account_id = session.get("user_id")
    identity = f"user:{account_id}" if account_id else f"ip:{ip}"
    key = f"{route_name}:{identity}"
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
        _trim_rate_limit_identities(_request_history, now, RATE_LIMIT_WINDOW)
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
        _trim_rate_limit_identities(_auth_rate_history, now, AUTH_RATE_LIMIT_WINDOW)
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
                            email VARCHAR(254),
                            email_key VARCHAR(254),
                            email_verified_at TIMESTAMPTZ,
                            password_hash TEXT NOT NULL,
                            recovery_code_hash TEXT,
                            recovery_code_created_at TIMESTAMPTZ,
                            auth_version BIGINT NOT NULL DEFAULT 1,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    # 兼容已经存在的账号表：部署后自动补列，不需要手工迁移数据库。
                    cur.execute("ALTER TABLE dm_users ADD COLUMN IF NOT EXISTS email VARCHAR(254)")
                    cur.execute("ALTER TABLE dm_users ADD COLUMN IF NOT EXISTS email_key VARCHAR(254)")
                    cur.execute("ALTER TABLE dm_users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ")
                    cur.execute("ALTER TABLE dm_users ADD COLUMN IF NOT EXISTS recovery_code_hash TEXT")
                    cur.execute("ALTER TABLE dm_users ADD COLUMN IF NOT EXISTS recovery_code_created_at TIMESTAMPTZ")
                    cur.execute("ALTER TABLE dm_users ADD COLUMN IF NOT EXISTS auth_version BIGINT NOT NULL DEFAULT 1")
                    cur.execute("""
                        CREATE UNIQUE INDEX IF NOT EXISTS dm_users_email_key_unique
                        ON dm_users(email_key)
                        WHERE email_key IS NOT NULL
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
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS dm_email_codes (
                            id BIGSERIAL PRIMARY KEY,
                            purpose VARCHAR(16) NOT NULL,
                            email VARCHAR(254) NOT NULL,
                            email_key VARCHAR(254) NOT NULL,
                            username_key VARCHAR(64),
                            user_id BIGINT REFERENCES dm_users(id) ON DELETE CASCADE,
                            code_digest VARCHAR(64) NOT NULL,
                            attempts INTEGER NOT NULL DEFAULT 0,
                            expires_at TIMESTAMPTZ NOT NULL,
                            consumed_at TIMESTAMPTZ,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS dm_email_codes_lookup_idx
                        ON dm_email_codes(purpose, email_key, created_at DESC)
                    """)
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS dm_email_codes_user_idx
                        ON dm_email_codes(user_id, created_at DESC)
                    """)
            _auth_schema_ready = True
            return True
        except Exception as exc:
            print(f"账号数据库初始化失败：{repr(exc)}")
            return False


RECOVERY_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,63}$")


def _new_recovery_code():
    # 注册时自动赠送一枚高熵恢复码；明文只返回这一次。
    raw = "".join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(16))
    return "DM-" + "-".join(raw[index:index + 4] for index in range(0, 16, 4))


def _normalize_recovery_secret(value):
    # 新版允许用户登录后自行设置恢复码；只去掉首尾空白。
    return str(value or "").strip()


def _legacy_normalize_recovery_code(value):
    # 兼容旧版：旧恢复码写库前会去掉分隔符并转成大写。
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def _valid_custom_recovery_code(value):
    secret = _normalize_recovery_secret(value)
    if len(secret) < 8 or len(secret) > 64:
        return False
    return not any(ord(ch) < 32 or ord(ch) == 127 for ch in secret)


def _recovery_code_matches(stored_hash, supplied):
    if not stored_hash:
        return False
    current = _normalize_recovery_secret(supplied)
    if not current:
        return False
    try:
        if check_password_hash(stored_hash, current):
            return True
        legacy = _legacy_normalize_recovery_code(supplied)
        return bool(legacy and legacy != current and check_password_hash(stored_hash, legacy))
    except Exception:
        return False


def _normalize_username(value):
    username = str(value or "").strip()
    if not re.fullmatch(r"[\w.\-\u4e00-\u9fff]{2,32}", username, flags=re.UNICODE):
        return None, None, "用户名需为 2–32 个字符，只使用文字、数字、下划线、点或短横线。"
    return username, username.casefold(), None


def _normalize_email(value):
    email = str(value or "").strip()
    if len(email) > 254 or not EMAIL_RE.fullmatch(email):
        return None, None, "请输入正确的邮箱地址。"
    return email, email.casefold(), None


def _normalize_auth_credentials(payload):
    payload = payload if isinstance(payload, dict) else {}
    username, username_key, error = _normalize_username(payload.get("username"))
    if error:
        return None, None, error
    password = str(payload.get("password") or "")
    if len(password) < 6 or len(password) > 128:
        return None, None, "密码长度需为 6–128 个字符。"
    return username, username_key, None


def _normalize_login_credentials(payload):
    payload = payload if isinstance(payload, dict) else {}
    identifier = str(payload.get("identifier") or payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not identifier:
        return None, None, None, "请输入用户名或邮箱。"
    if len(password) < 6 or len(password) > 128:
        return None, None, None, "密码长度需为 6–128 个字符。"

    if "@" in identifier:
        email, email_key, error = _normalize_email(identifier)
        if error:
            return None, None, None, "请输入正确的用户名或邮箱。"
        return "email", email, email_key, None

    username, username_key, error = _normalize_username(identifier)
    if error:
        return None, None, None, "请输入正确的用户名或邮箱。"
    return "username", username, username_key, None


def _email_code_digest(purpose, email_key, code):
    payload = f"{purpose}|{email_key}|{code}".encode("utf-8")
    return hmac.new(
        AUTH_SECRET_KEY.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()


def _new_email_code():
    return f"{secrets.randbelow(1_000_000):06d}"


def _verification_email_content(code, purpose):
    purpose_title = {
        "register": "注册",
        "reset": "重置密码",
        "bind": "绑定邮箱",
    }.get(purpose, "邮箱验证")

    subject = f"DMate - {purpose_title}验证码"
    text_content = (
        f"你的验证码是：{code}\n\n"
        "验证码 10 分钟内有效。\n"
        "如果不是你本人操作，请忽略这封邮件。\n\n"
        "如果收件箱中没有看到邮件，请检查垃圾邮件箱。"
    )
    html_content = f"""<!doctype html>
<html lang="zh-CN">
  <body style="margin:0;padding:24px;background:#f6f7f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;color:#111827;">
    <div style="max-width:520px;margin:0 auto;background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;padding:28px;">
      <div style="font-size:22px;font-weight:700;margin-bottom:18px;">DMate</div>
      <div style="font-size:15px;line-height:1.7;margin-bottom:12px;">你的{purpose_title}验证码是：</div>
      <div style="font-size:32px;font-weight:700;letter-spacing:8px;margin:18px 0 22px;">{code}</div>
      <div style="font-size:14px;line-height:1.7;color:#4b5563;">验证码 10 分钟内有效。如果不是你本人操作，请忽略这封邮件。</div>
      <div style="font-size:13px;line-height:1.7;color:#6b7280;margin-top:18px;">未收到邮件时，请同时检查垃圾邮件箱。</div>
    </div>
  </body>
</html>"""
    return subject, text_content, html_content


def _send_via_brevo(email, subject, text_content, html_content):
    if not BREVO_CONFIGURED:
        raise RuntimeError("Brevo is not configured")

    response = requests.post(
        BREVO_API_URL,
        headers={
            "accept": "application/json",
            "api-key": BREVO_API_KEY,
            "content-type": "application/json",
        },
        json={
            "sender": {
                "name": BREVO_SENDER_NAME,
                "email": BREVO_SENDER_EMAIL,
            },
            "to": [{"email": email}],
            "subject": subject,
            "textContent": text_content,
            "htmlContent": html_content,
        },
        timeout=(5, 15),
    )
    if response.status_code < 200 or response.status_code >= 300:
        body = (response.text or "").replace("\n", " ")[:500]
        raise RuntimeError(
            f"Brevo returned HTTP {response.status_code}: {body}"
        )


def _send_via_smtp(email, subject, text_content):
    if not SMTP_CONFIGURED:
        raise RuntimeError("SMTP fallback is not configured")

    msg = EmailMessage()
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    msg["To"] = email
    msg["Subject"] = subject
    msg.set_content(text_content)

    context = ssl.create_default_context()
    if SMTP_USE_SSL:
        with smtplib.SMTP_SSL(
            SMTP_HOST,
            SMTP_PORT,
            context=context,
            timeout=15,
        ) as smtp:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(msg)


def _send_verification_email(email, code, purpose):
    if not EMAIL_DELIVERY_CONFIGURED:
        raise RuntimeError("email delivery is not configured")

    subject, text_content, html_content = _verification_email_content(code, purpose)

    # 主通道：Brevo。只有 Brevo 失败时才尝试原 QQ/SMTP。
    if BREVO_CONFIGURED:
        try:
            _send_via_brevo(email, subject, text_content, html_content)
            return "brevo"
        except Exception as exc:
            print(f"Brevo 邮件发送失败，准备尝试 SMTP 备用通道：{repr(exc)}")
            if not SMTP_CONFIGURED:
                raise

    if SMTP_CONFIGURED:
        _send_via_smtp(email, subject, text_content)
        return "smtp"

    raise RuntimeError("no email delivery provider is configured")


def _email_unavailable_response():
    return jsonify({
        "ok": False,
        "emailConfigured": False,
        "error": "邮箱验证码服务尚未配置，请检查 Brevo 或 SMTP 环境变量。",
    }), 503


def _email_code_send_limit(cur, purpose, email_key, user_id=None):
    params = [purpose, email_key]
    user_clause = ""
    if user_id is not None:
        user_clause = " AND user_id = %s"
        params.append(int(user_id))

    cur.execute(
        f"""
        SELECT created_at
        FROM dm_email_codes
        WHERE purpose = %s AND email_key = %s{user_clause}
        ORDER BY created_at DESC
        LIMIT 1
        """,
        tuple(params),
    )
    latest = cur.fetchone()
    if latest and latest.get("created_at"):
        age = time.time() - latest["created_at"].timestamp()
        if age < EMAIL_CODE_RESEND_SECONDS:
            wait = max(1, int(EMAIL_CODE_RESEND_SECONDS - age + 0.999))
            return False, f"请 {wait} 秒后再发送验证码。"

    params = [purpose, email_key]
    user_clause = ""
    if user_id is not None:
        user_clause = " AND user_id = %s"
        params.append(int(user_id))
    cur.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM dm_email_codes
        WHERE purpose = %s
          AND email_key = %s{user_clause}
          AND created_at > NOW() - INTERVAL '1 hour'
        """,
        tuple(params),
    )
    count = int((cur.fetchone() or {}).get("count") or 0)
    if count >= EMAIL_CODE_MAX_PER_HOUR:
        return False, "验证码发送次数过多，请稍后再试。"
    return True, None


def _latest_email_code(cur, purpose, email_key, user_id=None, username_key=None):
    clauses = [
        "purpose = %s",
        "email_key = %s",
        "consumed_at IS NULL",
    ]
    params = [purpose, email_key]
    if user_id is not None:
        clauses.append("user_id = %s")
        params.append(int(user_id))
    elif purpose in {"reset", "bind"}:
        clauses.append("user_id IS NULL")
    if username_key is not None:
        clauses.append("username_key = %s")
        params.append(username_key)

    cur.execute(
        f"""
        SELECT id, code_digest, attempts, expires_at
        FROM dm_email_codes
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC
        LIMIT 1
        """,
        tuple(params),
    )
    return cur.fetchone()


def _verify_email_code(cur, purpose, email_key, supplied_code, user_id=None, username_key=None):
    code = re.sub(r"\D", "", str(supplied_code or ""))
    if len(code) != 6:
        return None, "请输入 6 位邮箱验证码。"

    row = _latest_email_code(
        cur,
        purpose,
        email_key,
        user_id=user_id,
        username_key=username_key,
    )
    if not row:
        return None, "请先发送邮箱验证码。"
    if row.get("expires_at") and row["expires_at"].timestamp() < time.time():
        return None, "验证码已过期，请重新发送。"
    attempts = int(row.get("attempts") or 0)
    if attempts >= EMAIL_CODE_MAX_ATTEMPTS:
        return None, "验证码错误次数过多，请重新发送。"

    expected = _email_code_digest(purpose, email_key, code)
    if not hmac.compare_digest(str(row.get("code_digest") or ""), expected):
        cur.execute(
            "UPDATE dm_email_codes SET attempts = attempts + 1 WHERE id = %s",
            (int(row["id"]),),
        )
        return None, "验证码不正确。"

    return int(row["id"]), None


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
                    """
                    SELECT id, username, email, email_key, email_verified_at,
                           recovery_code_hash, auth_version
                    FROM dm_users
                    WHERE id = %s
                    """,
                    (user_id,),
                )
                user = cur.fetchone()
                if not user:
                    return None

                current_version = int(user.get("auth_version") or 1)
                session_version = session.get("auth_version")
                if isinstance(session_version, int):
                    if session_version != current_version:
                        session.clear()
                        return None
                else:
                    # 兼容本功能上线前签发的旧登录 Cookie。
                    session["auth_version"] = current_version

                return user
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


def _normalize_sync_part_names(raw_value):
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        values = raw_value.split(",")
    elif isinstance(raw_value, (list, tuple, set)):
        values = raw_value
    else:
        return []

    allowed = ("sessions", "learning", "appearance")
    result = []
    seen = set()
    for raw in values:
        value = str(raw or "").strip()
        if value in allowed and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _sync_manifest_from_data(data):
    snapshot = data if isinstance(data, dict) else {}
    manifest = {}
    for key in ("sessions", "learning", "appearance"):
        section = snapshot.get(key)
        if section is None:
            payload = b"null"
        else:
            payload = json.dumps(
                section,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        manifest[key] = {
            "hash": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }
    return manifest


@app.route("/auth/me", methods=["GET"])
def auth_me():
    if not AUTH_CONFIGURED:
        return jsonify({
            "ok": True,
            "configured": False,
            "emailConfigured": EMAIL_DELIVERY_CONFIGURED,
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
            "emailConfigured": EMAIL_DELIVERY_CONFIGURED,
            "authenticated": False,
        })

    return jsonify({
        "ok": True,
        "configured": True,
        "emailConfigured": EMAIL_DELIVERY_CONFIGURED,
        "authenticated": True,
        "user": {
            "username": user["username"],
            "email": user.get("email") or "",
        },
        "hasRecoveryCode": bool(user.get("recovery_code_hash")),
        "hasVerifiedEmail": bool(user.get("email_verified_at") and user.get("email")),
    })


@app.route("/auth/email/send-code", methods=["POST"])
def auth_send_email_code():
    if not AUTH_CONFIGURED or not _ensure_auth_schema():
        return _auth_unavailable_response()
    if not EMAIL_DELIVERY_CONFIGURED:
        return _email_unavailable_response()
    if not _auth_rate_allowed("send-email-code"):
        return jsonify({"ok": False, "error": "操作过于频繁，请稍后再试。"}), 429
    if not request.is_json:
        return jsonify({"ok": False, "error": "请求格式不正确。"}), 400

    payload = request.get_json(silent=True)
    payload = payload if isinstance(payload, dict) else {}
    purpose = str(payload.get("purpose") or "").strip().lower()
    email, email_key, error = _normalize_email(payload.get("email"))
    if error:
        return jsonify({"ok": False, "error": error}), 400
    if purpose not in {"register", "reset", "bind"}:
        return jsonify({"ok": False, "error": "验证码用途不正确。"}), 400

    user_id = None
    username_key = None

    try:
        with _auth_connect() as conn:
            with conn.cursor() as cur:
                # 清理过期很久的验证码记录，避免表无限增长。
                cur.execute("""
                    DELETE FROM dm_email_codes
                    WHERE created_at < NOW() - INTERVAL '2 days'
                       OR (consumed_at IS NOT NULL AND consumed_at < NOW() - INTERVAL '1 day')
                """)

                if purpose == "register":
                    username, username_key, username_error = _normalize_username(payload.get("username"))
                    if username_error:
                        return jsonify({"ok": False, "error": username_error}), 400
                    cur.execute(
                        "SELECT 1 FROM dm_users WHERE username_key = %s",
                        (username_key,),
                    )
                    if cur.fetchone():
                        return jsonify({"ok": False, "error": "这个用户名已经被使用。"}), 409
                    cur.execute(
                        "SELECT 1 FROM dm_users WHERE email_key = %s",
                        (email_key,),
                    )
                    if cur.fetchone():
                        return jsonify({"ok": False, "error": "这个邮箱已经绑定了账号。"}), 409

                elif purpose == "reset":
                    cur.execute(
                        "SELECT id FROM dm_users WHERE email_key = %s AND email_verified_at IS NOT NULL",
                        (email_key,),
                    )
                    target = cur.fetchone()
                    if not target:
                        # 不暴露某个邮箱是否存在；前端统一提示检查邮箱/垃圾箱。
                        return jsonify({
                            "ok": True,
                            "expiresIn": EMAIL_CODE_TTL_SECONDS,
                            "resendAfter": EMAIL_CODE_RESEND_SECONDS,
                        })
                    user_id = int(target["id"])

                else:  # bind
                    user = _current_auth_user()
                    if not user:
                        session.clear()
                        return jsonify({"ok": False, "error": "请先登录。"}), 401
                    user_id = int(user["id"])
                    cur.execute(
                        "SELECT id FROM dm_users WHERE email_key = %s AND id <> %s",
                        (email_key, user_id),
                    )
                    if cur.fetchone():
                        return jsonify({"ok": False, "error": "这个邮箱已经绑定了其他账号。"}), 409

                allowed, limit_error = _email_code_send_limit(
                    cur, purpose, email_key, user_id=user_id
                )
                if not allowed:
                    return jsonify({"ok": False, "error": limit_error}), 429

                code = _new_email_code()
                digest = _email_code_digest(purpose, email_key, code)
                cur.execute(
                    """
                    INSERT INTO dm_email_codes (
                        purpose, email, email_key, username_key, user_id,
                        code_digest, expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s,
                            NOW() + (%s * INTERVAL '1 second'))
                    """,
                    (
                        purpose,
                        email,
                        email_key,
                        username_key,
                        user_id,
                        digest,
                        EMAIL_CODE_TTL_SECONDS,
                    ),
                )
                _send_verification_email(email, code, purpose)
    except Exception as exc:
        print(f"发送邮箱验证码失败：{repr(exc)}")
        return jsonify({"ok": False, "error": "验证码发送失败，请稍后再试。"}), 502

    return jsonify({
        "ok": True,
        "expiresIn": EMAIL_CODE_TTL_SECONDS,
        "resendAfter": EMAIL_CODE_RESEND_SECONDS,
    })


@app.route("/auth/register", methods=["POST"])
def auth_register():
    if not AUTH_CONFIGURED or not _ensure_auth_schema():
        return _auth_unavailable_response()
    if not EMAIL_DELIVERY_CONFIGURED:
        return _email_unavailable_response()
    if not _auth_rate_allowed("register"):
        return jsonify({"ok": False, "error": "操作过于频繁，请稍后再试。"}), 429
    if not request.is_json:
        return jsonify({"ok": False, "error": "请求格式不正确。"}), 400

    payload = request.get_json(silent=True)
    payload = payload if isinstance(payload, dict) else {}
    username, username_key, error = _normalize_auth_credentials(payload)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    email, email_key, email_error = _normalize_email(payload.get("email"))
    if email_error:
        return jsonify({"ok": False, "error": email_error}), 400
    email_code = str(payload.get("emailCode") or "").strip()
    password = str(payload.get("password") or "")

    password_hash = generate_password_hash(password, method="scrypt")
    recovery_code = _new_recovery_code()
    recovery_code_hash = generate_password_hash(
        _normalize_recovery_secret(recovery_code),
        method="scrypt",
    )

    try:
        with _auth_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM dm_users WHERE username_key = %s",
                    (username_key,),
                )
                if cur.fetchone():
                    return jsonify({"ok": False, "error": "这个用户名已经被使用。"}), 409
                cur.execute(
                    "SELECT 1 FROM dm_users WHERE email_key = %s",
                    (email_key,),
                )
                if cur.fetchone():
                    return jsonify({"ok": False, "error": "这个邮箱已经绑定了账号。"}), 409

                code_id, verify_error = _verify_email_code(
                    cur,
                    "register",
                    email_key,
                    email_code,
                    username_key=username_key,
                )
                if verify_error:
                    return jsonify({"ok": False, "error": verify_error}), 400

                cur.execute(
                    """
                    INSERT INTO dm_users (
                        username, username_key, email, email_key, email_verified_at,
                        password_hash, recovery_code_hash, recovery_code_created_at
                    )
                    VALUES (%s, %s, %s, %s, NOW(), %s, %s, NOW())
                    RETURNING id, username, email, auth_version
                    """,
                    (
                        username,
                        username_key,
                        email,
                        email_key,
                        password_hash,
                        recovery_code_hash,
                    ),
                )
                user = cur.fetchone()
                cur.execute(
                    "INSERT INTO dm_user_data (user_id) VALUES (%s)",
                    (user["id"],),
                )
                cur.execute(
                    "UPDATE dm_email_codes SET consumed_at = NOW() WHERE id = %s",
                    (code_id,),
                )
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505":
            return jsonify({"ok": False, "error": "用户名或邮箱已经被使用。"}), 409
        print(f"注册失败：{repr(exc)}")
        return jsonify({"ok": False, "error": "注册失败，请稍后再试。"}), 500

    session.clear()
    session["user_id"] = int(user["id"])
    session["auth_version"] = int(user.get("auth_version") or 1)
    session.permanent = True
    return jsonify({
        "ok": True,
        "configured": True,
        "emailConfigured": EMAIL_DELIVERY_CONFIGURED,
        "authenticated": True,
        "user": {
            "username": user["username"],
            "email": user.get("email") or email,
        },
        "revision": 0,
        "hasRecoveryCode": True,
        "hasVerifiedEmail": True,
        # 注册时赠送的明文恢复码只返回这一次，数据库只保存 scrypt 哈希。
        "recoveryCode": recovery_code,
    })


@app.route("/auth/login", methods=["POST"])
def auth_login():
    if not AUTH_CONFIGURED or not _ensure_auth_schema():
        return _auth_unavailable_response()
    if not _auth_rate_allowed("login"):
        return jsonify({"ok": False, "error": "操作过于频繁，请稍后再试。"}), 429
    if not request.is_json:
        return jsonify({"ok": False, "error": "请求格式不正确。"}), 400

    payload = request.get_json(silent=True)
    payload = payload if isinstance(payload, dict) else {}
    kind, identifier, identifier_key, error = _normalize_login_credentials(payload)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    password = str(payload.get("password") or "")

    try:
        with _auth_connect() as conn:
            with conn.cursor() as cur:
                if kind == "email":
                    cur.execute(
                        """
                        SELECT id, username, email, password_hash,
                               recovery_code_hash, auth_version
                        FROM dm_users
                        WHERE email_key = %s
                        """,
                        (identifier_key,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, username, email, password_hash,
                               recovery_code_hash, auth_version
                        FROM dm_users
                        WHERE username_key = %s
                        """,
                        (identifier_key,),
                    )
                user = cur.fetchone()
                if not user or not check_password_hash(user["password_hash"], password):
                    return jsonify({"ok": False, "error": "用户名/邮箱或密码不正确。"}), 401
    except Exception as exc:
        print(f"登录查询失败：{repr(exc)}")
        return jsonify({"ok": False, "error": "登录失败，请稍后再试。"}), 500

    session.clear()
    session["user_id"] = int(user["id"])
    session["auth_version"] = int(user.get("auth_version") or 1)
    session.permanent = True
    return jsonify({
        "ok": True,
        "configured": True,
        "emailConfigured": EMAIL_DELIVERY_CONFIGURED,
        "authenticated": True,
        "user": {
            "username": user["username"],
            "email": user.get("email") or "",
        },
        "hasRecoveryCode": bool(user.get("recovery_code_hash")),
        "hasVerifiedEmail": bool(user.get("email")),
    })


@app.route("/auth/email/bind", methods=["POST"])
def auth_bind_email():
    """旧账号绑定邮箱，或已绑定账号更换邮箱。需要当前密码 + 邮箱验证码。"""
    if not AUTH_CONFIGURED or not _ensure_auth_schema():
        return _auth_unavailable_response()
    if not EMAIL_DELIVERY_CONFIGURED:
        return _email_unavailable_response()
    if not _auth_rate_allowed("bind-email"):
        return jsonify({"ok": False, "error": "操作过于频繁，请稍后再试。"}), 429
    if not request.is_json:
        return jsonify({"ok": False, "error": "请求格式不正确。"}), 400

    user = _current_auth_user()
    if not user:
        session.clear()
        return jsonify({"ok": False, "error": "请先登录。"}), 401

    payload = request.get_json(silent=True)
    payload = payload if isinstance(payload, dict) else {}
    password = str(payload.get("password") or "")
    email, email_key, error = _normalize_email(payload.get("email"))
    email_code = str(payload.get("emailCode") or "").strip()
    if error:
        return jsonify({"ok": False, "error": error}), 400
    if not password:
        return jsonify({"ok": False, "error": "请输入当前密码。"}), 400

    try:
        with _auth_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT password_hash FROM dm_users WHERE id = %s",
                    (int(user["id"]),),
                )
                row = cur.fetchone()
                if not row or not check_password_hash(row["password_hash"], password):
                    return jsonify({"ok": False, "error": "密码不正确。"}), 401

                cur.execute(
                    "SELECT id FROM dm_users WHERE email_key = %s AND id <> %s",
                    (email_key, int(user["id"])),
                )
                if cur.fetchone():
                    return jsonify({"ok": False, "error": "这个邮箱已经绑定了其他账号。"}), 409

                code_id, verify_error = _verify_email_code(
                    cur,
                    "bind",
                    email_key,
                    email_code,
                    user_id=int(user["id"]),
                )
                if verify_error:
                    return jsonify({"ok": False, "error": verify_error}), 400

                cur.execute(
                    """
                    UPDATE dm_users
                    SET email = %s,
                        email_key = %s,
                        email_verified_at = NOW()
                    WHERE id = %s
                    RETURNING email
                    """,
                    (email, email_key, int(user["id"])),
                )
                updated = cur.fetchone()
                cur.execute(
                    "UPDATE dm_email_codes SET consumed_at = NOW() WHERE id = %s",
                    (code_id,),
                )
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505":
            return jsonify({"ok": False, "error": "这个邮箱已经绑定了其他账号。"}), 409
        print(f"绑定邮箱失败：{repr(exc)}")
        return jsonify({"ok": False, "error": "绑定邮箱失败，请稍后再试。"}), 500

    return jsonify({
        "ok": True,
        "email": updated.get("email") or email,
        "hasVerifiedEmail": True,
    })


@app.route("/auth/recovery-code", methods=["POST"])
def auth_recovery_code():
    """已登录用户输入当前密码后，自行设置/修改恢复码。"""
    if not AUTH_CONFIGURED or not _ensure_auth_schema():
        return _auth_unavailable_response()
    if not _auth_rate_allowed("recovery-code"):
        return jsonify({"ok": False, "error": "操作过于频繁，请稍后再试。"}), 429
    if not request.is_json:
        return jsonify({"ok": False, "error": "请求格式不正确。"}), 400

    user = _current_auth_user()
    if not user:
        session.clear()
        return jsonify({"ok": False, "error": "请先登录。"}), 401

    payload = request.get_json(silent=True)
    payload = payload if isinstance(payload, dict) else {}
    password = str(payload.get("password") or "")
    new_recovery_code = _normalize_recovery_secret(payload.get("newRecoveryCode"))

    if not password:
        return jsonify({"ok": False, "error": "请输入当前密码。"}), 400
    if not _valid_custom_recovery_code(new_recovery_code):
        return jsonify({
            "ok": False,
            "error": "新恢复码需为 8–64 个字符，且不能包含控制字符。",
        }), 400

    recovery_hash = generate_password_hash(new_recovery_code, method="scrypt")

    try:
        with _auth_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT password_hash FROM dm_users WHERE id = %s",
                    (int(user["id"]),),
                )
                row = cur.fetchone()
                if not row or not check_password_hash(row["password_hash"], password):
                    return jsonify({"ok": False, "error": "密码不正确。"}), 401

                cur.execute(
                    """
                    UPDATE dm_users
                    SET recovery_code_hash = %s,
                        recovery_code_created_at = NOW()
                    WHERE id = %s
                    """,
                    (recovery_hash, int(user["id"])),
                )
    except Exception as exc:
        print(f"修改恢复码失败：{repr(exc)}")
        return jsonify({"ok": False, "error": "修改恢复码失败，请稍后再试。"}), 500

    return jsonify({
        "ok": True,
        "hasRecoveryCode": True,
    })


@app.route("/auth/recover-password-email", methods=["POST"])
def auth_recover_password_email():
    """使用已验证邮箱 + 6 位验证码重置密码。成功后自动登录。"""
    if not AUTH_CONFIGURED or not _ensure_auth_schema():
        return _auth_unavailable_response()
    if not EMAIL_DELIVERY_CONFIGURED:
        return _email_unavailable_response()
    if not _auth_rate_allowed("recover-password-email"):
        return jsonify({"ok": False, "error": "操作过于频繁，请稍后再试。"}), 429
    if not request.is_json:
        return jsonify({"ok": False, "error": "请求格式不正确。"}), 400

    payload = request.get_json(silent=True)
    payload = payload if isinstance(payload, dict) else {}
    email, email_key, error = _normalize_email(payload.get("email"))
    email_code = str(payload.get("emailCode") or "").strip()
    new_password = str(payload.get("newPassword") or "")
    if error:
        return jsonify({"ok": False, "error": error}), 400
    if len(new_password) < 6 or len(new_password) > 128:
        return jsonify({"ok": False, "error": "新密码长度需为 6–128 个字符。"}), 400

    try:
        with _auth_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, email, recovery_code_hash, auth_version
                    FROM dm_users
                    WHERE email_key = %s AND email_verified_at IS NOT NULL
                    """,
                    (email_key,),
                )
                user = cur.fetchone()
                if not user:
                    return jsonify({"ok": False, "error": "邮箱或验证码不正确。"}), 401

                code_id, verify_error = _verify_email_code(
                    cur,
                    "reset",
                    email_key,
                    email_code,
                    user_id=int(user["id"]),
                )
                if verify_error:
                    return jsonify({"ok": False, "error": verify_error}), 400

                new_password_hash = generate_password_hash(new_password, method="scrypt")
                cur.execute(
                    """
                    UPDATE dm_users
                    SET password_hash = %s,
                        auth_version = auth_version + 1
                    WHERE id = %s
                    RETURNING id, username, email, recovery_code_hash, auth_version
                    """,
                    (new_password_hash, int(user["id"])),
                )
                updated = cur.fetchone()
                cur.execute(
                    "UPDATE dm_email_codes SET consumed_at = NOW() WHERE id = %s",
                    (code_id,),
                )
    except Exception as exc:
        print(f"邮箱重置密码失败：{repr(exc)}")
        return jsonify({"ok": False, "error": "重置密码失败，请稍后再试。"}), 500

    session.clear()
    session["user_id"] = int(updated["id"])
    session["auth_version"] = int(updated.get("auth_version") or 1)
    session.permanent = True
    return jsonify({
        "ok": True,
        "authenticated": True,
        "user": {
            "username": updated["username"],
            "email": updated.get("email") or email,
        },
        "hasRecoveryCode": bool(updated.get("recovery_code_hash")),
        "hasVerifiedEmail": True,
    })


@app.route("/auth/recover-password", methods=["POST"])
def auth_recover_password():
    """使用用户名 + 恢复码重置密码。不会找回旧密码。"""
    if not AUTH_CONFIGURED or not _ensure_auth_schema():
        return _auth_unavailable_response()
    if not _auth_rate_allowed("recover-password"):
        return jsonify({"ok": False, "error": "操作过于频繁，请稍后再试。"}), 429
    if not request.is_json:
        return jsonify({"ok": False, "error": "请求格式不正确。"}), 400

    payload = request.get_json(silent=True)
    payload = payload if isinstance(payload, dict) else {}
    username = str(payload.get("username") or "").strip()
    recovery_code = _normalize_recovery_secret(payload.get("recoveryCode"))
    new_password = str(payload.get("newPassword") or "")

    if not re.fullmatch(r"[\w.\-\u4e00-\u9fff]{2,32}", username, flags=re.UNICODE):
        return jsonify({"ok": False, "error": "请输入正确的用户名。"}), 400
    if not recovery_code:
        return jsonify({"ok": False, "error": "请输入恢复码。"}), 400
    if len(new_password) < 6 or len(new_password) > 128:
        return jsonify({"ok": False, "error": "新密码长度需为 6–128 个字符。"}), 400

    try:
        with _auth_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, email, recovery_code_hash, auth_version
                    FROM dm_users
                    WHERE username_key = %s
                    """,
                    (username.casefold(),),
                )
                user = cur.fetchone()

                if not user or not _recovery_code_matches(
                    user.get("recovery_code_hash"), recovery_code
                ):
                    return jsonify({
                        "ok": False,
                        "error": "用户名或恢复码不正确。",
                    }), 401

                new_password_hash = generate_password_hash(
                    new_password, method="scrypt"
                )
                cur.execute(
                    """
                    UPDATE dm_users
                    SET password_hash = %s,
                        auth_version = auth_version + 1
                    WHERE id = %s
                    RETURNING id, username, email, recovery_code_hash, auth_version
                    """,
                    (new_password_hash, int(user["id"])),
                )
                updated = cur.fetchone()
    except Exception as exc:
        print(f"重置密码失败：{repr(exc)}")
        return jsonify({"ok": False, "error": "重置密码失败，请稍后再试。"}), 500

    session.clear()
    session["user_id"] = int(updated["id"])
    session["auth_version"] = int(updated.get("auth_version") or 1)
    session.permanent = True

    return jsonify({
        "ok": True,
        "authenticated": True,
        "user": {
            "username": updated["username"],
            "email": updated.get("email") or "",
        },
        "hasRecoveryCode": bool(updated.get("recovery_code_hash")),
        "hasVerifiedEmail": bool(updated.get("email")),
    })


@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    # 只退出当前浏览器；账号和云端学习数据仍然保留。
    session.clear()
    return jsonify({"ok": True})


@app.route("/auth/delete-account", methods=["POST"])
def auth_delete_account():
    """
    永久注销当前账号。

    - 必须处于登录状态；
    - 必须再次输入当前密码；
    - 删除 dm_users 后，dm_user_data / 已关联验证码通过 ON DELETE CASCADE 一并删除；
    - 当前浏览器本地 localStorage/IndexedDB 不在服务器端删除。
    """
    if not AUTH_CONFIGURED or not _ensure_auth_schema():
        return _auth_unavailable_response()
    if not _auth_rate_allowed("delete-account"):
        return jsonify({"ok": False, "error": "操作过于频繁，请稍后再试。"}), 429
    if not request.is_json:
        return jsonify({"ok": False, "error": "请求格式不正确。"}), 400

    user_id = session.get("user_id")
    if not isinstance(user_id, int):
        session.clear()
        return jsonify({"ok": False, "error": "请先登录。"}), 401

    payload = request.get_json(silent=True)
    payload = payload if isinstance(payload, dict) else {}
    password = str(payload.get("password") or "")
    if not password:
        return jsonify({"ok": False, "error": "请输入当前密码。"}), 400

    try:
        with _auth_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, password_hash
                    FROM dm_users
                    WHERE id = %s
                    """,
                    (user_id,),
                )
                user = cur.fetchone()

                if not user:
                    session.clear()
                    return jsonify({"ok": False, "error": "账号不存在或已被注销。"}), 401

                if not check_password_hash(user["password_hash"], password):
                    return jsonify({"ok": False, "error": "密码不正确。"}), 401

                cur.execute(
                    "DELETE FROM dm_users WHERE id = %s RETURNING id",
                    (user_id,),
                )
                deleted = cur.fetchone()
                if not deleted:
                    return jsonify({"ok": False, "error": "注销失败，请稍后再试。"}), 500
    except Exception as exc:
        print(f"注销账号失败：{repr(exc)}")
        return jsonify({"ok": False, "error": "注销账号失败，请稍后再试。"}), 500

    session.clear()
    return jsonify({
        "ok": True,
        "deleted": True,
    })


@app.route("/sync", methods=["GET", "PUT"])
def sync_user_data():
    if not AUTH_CONFIGURED or not _ensure_auth_schema():
        return _auth_unavailable_response()

    user = _current_auth_user()
    if not user:
        return jsonify({"ok": False, "error": "请先登录。"}), 401

    user_id = int(user["id"])

    if request.method == "GET" and request.args.get("revisionOnly") == "1":
        # 每 1.2 秒仅查询整数 revision；不能频繁读取整份 JSON 再哈希。
        try:
            with _auth_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT revision FROM dm_user_data WHERE user_id = %s",
                        (user_id,),
                    )
                    revision_row = cur.fetchone()
            return jsonify({
                "ok": True,
                "revision": int(revision_row["revision"] or 0) if revision_row else 0,
            })
        except Exception as exc:
            print(f"检查云端同步版本失败：{repr(exc)}")
            return jsonify({"ok": False, "error": "检查云端版本失败。"}), 500

    if request.method == "GET":
        try:
            row = _sync_row_for_user(user_id)
            requested_parts = _normalize_sync_part_names(request.args.get("parts"))
            expected_raw = request.args.get("expectedRevision")
            expected_revision = int(expected_raw) if expected_raw is not None else None
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "同步版本号无效。"}), 400
        except Exception as exc:
            print(f"读取云端数据失败：{repr(exc)}")
            return jsonify({"ok": False, "error": "读取云端数据失败。"}), 500

        actual_revision = int(row["revision"] or 0)
        # manifest 和分段查询都绑定某一版本。变化后返回冲突而不是回传
        # 新版本号 + 老的请求分段，防止被误标为已完整同步。
        if expected_revision is not None and expected_revision != actual_revision:
            return jsonify({
                "ok": False, "conflict": True,
                "error": "查询期间云端数据已更新，请重新获取版本。",
                "revision": actual_revision,
            }), 409

        manifest = _sync_manifest_from_data(row["data"] or {})
        if request.args.get("manifestOnly") == "1":
            return jsonify({"ok": True, "revision": actual_revision, "parts": manifest})

        return jsonify({
            "ok": True,
            "data": ({
                key: (row["data"] or {}).get(key)
                for key in requested_parts
            } if requested_parts else (row["data"] or {})),
            "revision": actual_revision,
            "updatedAt": row["updated_at"].isoformat() if row.get("updated_at") else None,
            "parts": manifest,
        })

    if not request.is_json:
        return jsonify({"ok": False, "error": "请求格式不正确。"}), 400

    payload = request.get_json(silent=True)
    payload = payload if isinstance(payload, dict) else {}
    data = payload.get("data")
    if payload.get("force"):
        return jsonify({"ok": False, "error": "不支持强制覆盖云端数据，请合并后重试。"}), 400

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
                        "parts": _sync_manifest_from_data(cloud["data"] or {}),
                    }), 409

        return jsonify({
            "ok": True,
            "revision": int(updated["revision"]),
            "updatedAt": updated["updated_at"].isoformat() if updated.get("updated_at") else None,
            "parts": _sync_manifest_from_data(data),
        })
    except Exception as exc:
        print(f"写入云端数据失败：{repr(exc)}")
        return jsonify({"ok": False, "error": "同步失败，请稍后再试。"}), 500


@app.route("/favicon.ico")
def favicon_ico():
    """Default website/favicon fallback is transparent THIN linework, not an app tile."""
    response = app.send_static_file("icons/favicon.ico")
    response.headers["Content-Type"] = "image/x-icon"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


def _serve_dmate_manifest(filename):
    """The same native DMate icon, corrected for Android browser launcher scaling."""
    with open(os.path.join(app.static_folder, filename), "r", encoding="utf-8") as source:
        manifest = json.load(source)
    user_agent = request.headers.get("User-Agent", "")
    variant = None
    if re.search(r"Android", user_agent, re.IGNORECASE):
        if re.search(r"EdgA/|Edg/|Edge/", user_agent, re.IGNORECASE):
            variant = "edge"
        elif re.search(r"Firefox/|Fennec/", user_agent, re.IGNORECASE):
            variant = "fennec"
    if variant:
        for item in manifest.get("icons", []):
            size = item.get("sizes", "").split("x")[0]
            if item.get("purpose", "any") == "any" and size in {"192", "512"}:
                item["src"] = f"/static/icons/android-{variant}-{size}-v21.png?v=dmate-native-vector-v22-20261019"
    # Android ONLY: provide dedicated maskable artwork. Previously these
    # entries were deleted, so launchers placed the square icon inside a
    # white adaptive-icon frame. Desktop/iOS manifest output is unchanged.
    if re.search(r"Android", user_agent, re.IGNORECASE) and not re.search(
        r"DMateAndroid/|DMateDesktop/", user_agent, re.IGNORECASE
    ):
        manifest["icons"] = [
            *[icon for icon in manifest.get("icons", [])
              if "maskable" not in icon.get("purpose", "any").split()],
            {
                "src": "/static/icons/android-pwa-maskable-192-v24.png?v=android-maskable-v24-20261019",
                "sizes": "192x192", "type": "image/png", "purpose": "maskable"
            },
            {
                "src": "/static/icons/android-pwa-maskable-512-v24.png?v=android-maskable-v24-20261019",
                "sizes": "512x512", "type": "image/png", "purpose": "maskable"
            }
        ]
        response = make_response(json.dumps(manifest, ensure_ascii=False))
    response.headers["Content-Type"] = "application/manifest+json; charset=utf-8"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Vary"] = "User-Agent"
    return response


@app.route("/manifest.webmanifest")
def web_app_manifest():
    return _serve_dmate_manifest("manifest.webmanifest")


@app.route("/manifest-mobile.webmanifest")
def web_app_manifest_mobile():
    """Compatibility manifest for Android browsers checking the current page scope.

    QQ, Quark, UC, Baidu and several OEM browsers inspect the / homepage
    itself when deciding whether to expose 'Add to home screen'. The standard
    PWA manifest stays limited to /pwa/ so desktop Edge doesn't capture /.
    """
    return _serve_dmate_manifest("manifest-mobile.webmanifest")


@app.route("/service-worker.js")
def service_worker():
    response = app.send_static_file("service-worker.js")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.route("/install")
def install_page():
    """Compact installation page for browser-specific installation guidance."""
    mobile_android = bool(re.search(r"Android", request.headers.get("User-Agent", ""), re.IGNORECASE))
    response = make_response(render_template("install.html", is_android=mobile_android))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


@app.route("/")
def home():
    # 普通 Android 浏览器提供网页安装指引与 APK 备用渠道；已安装的 APK 隐藏重复入口。
    # APK 自己追加 DMateAndroid/<version> UA，可据此隐藏网页内的下载入口。
    user_agent = request.headers.get("User-Agent", "")
    is_android = bool(re.search(r"Android", user_agent, re.IGNORECASE))
    is_ios = bool(re.search(r"iPhone|iPad|iPod|Macintosh.*Mobile", user_agent, re.IGNORECASE))
    is_mac_safari = bool(re.search(r"Macintosh|Mac OS X", user_agent, re.IGNORECASE)
        and re.search(r"Safari/", user_agent, re.IGNORECASE)
        and not re.search(r"Chrome/|Chromium/|CriOS/|Edg/|OPR/|Firefox/|FxiOS/", user_agent, re.IGNORECASE))
    is_dmate_android_app = bool(re.search(r"DMateAndroid/", user_agent, re.IGNORECASE))
    is_dmate_desktop_app = bool(re.search(r"DMateDesktop/", user_agent, re.IGNORECASE))
    is_android_browser = is_android and not is_dmate_android_app
    is_windows_browser = bool(re.search(r"Windows", user_agent, re.IGNORECASE) and not is_dmate_desktop_app)
    is_android_edge = bool(is_android_browser and re.search(r"EdgA/|Edg/|Edge/", user_agent, re.IGNORECASE))
    is_android_firefox = bool(is_android_browser and re.search(r"Firefox/|Fennec/", user_agent, re.IGNORECASE))
    # Some Android browsers only expose their add-to-desktop menu when the
    # page being viewed (/) lies within the manifest's declared scope.
    is_android_install_compat_browser = bool(
        is_android_browser and re.search(
            r"QQBrowser|MQQBrowser|Quark|UCBrowser|UCWEB|BaiduBrowser|"
            r"baiduboxapp|MiuiBrowser|HuaweiBrowser|HeyTapBrowser|"
            r"OPPOBrowser|VivoBrowser|HonorBrowser",
            user_agent,
            re.IGNORECASE,
        )
    )

    # 首页直接注入与 teaching.py / app.py 共用的 knowledge_graph.json，
    # 避免前端再维护一份硬编码图谱而产生不同步。
    # 客户端通过远程网页获取新功能：不允许 WebView/PWA 缓存旧 HTML
    # 和旧 script.js 版本号，否则新版交互即使上线也可能不生效。
    response = make_response(render_template(
        "index.html",
        knowledge_graph_data=KNOWLEDGE_GRAPH_DATA,
        is_android=is_android,
        is_ios=is_ios,
        is_mac_safari=is_mac_safari,
        is_android_browser=is_android_browser,
        is_windows_browser=is_windows_browser,
        is_android_edge=is_android_edge,
        is_android_firefox=is_android_firefox,
        is_android_install_compat_browser=is_android_install_compat_browser,
        is_dmate_android_app=is_dmate_android_app,
        is_dmate_desktop_app=is_dmate_desktop_app,
        android_apk_url=ANDROID_APK_URL,
        desktop_windows_url=DESKTOP_WINDOWS_URL,
        desktop_macos_url=DESKTOP_MACOS_URL,
        desktop_linux_deb_url=DESKTOP_LINUX_DEB_URL,
        desktop_linux_appimage_url=DESKTOP_LINUX_APPIMAGE_URL,
    ))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


@app.route("/pwa/")
def pwa_home():
    """Dedicated installed-PWA launch URL; keep the public website root outside its scope."""
    return home()



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

    value = value[:6000].strip()

    # AI 返回“暂时无法出题”等拒绝/故障文字时，绝不能把它登记成题目。
    # 标题【题目】本身不能证明内容是题目；必须同时有可执行的数学任务。
    if len(value) < 7:
        return ""
    if re.search(
        r"^(?:抱歉|对不起|很抱歉|无法|不能|暂时不能|暂时无法|出题失败|生成失败|"
        r"没有可用题目|未能生成|目前没有|请稍后|请重试|服务异常|错误[:：]|error\b)",
        value,
        flags=re.IGNORECASE,
    ):
        return ""
    if re.search(
        r"(?:无法|不能|未能|暂时).{0,16}(?:生成|提供|给出|出).{0,8}(?:题目|练习题|题)"
        r"|(?:请重新出题|请稍后重试|服务暂时不可用)",
        value[:180],
    ):
        return ""
    if re.search(r"^(?:好的|没问题|收到)[！!。，,\s]*$", value):
        return ""
    # 避免把用户的“出一道难题”命令回声、知识点介绍或闲聊存入错题本。
    # 对纯符号、选择/填空、证明/构造、图论和自然语言题面均保留兼容。
    has_action = bool(re.search(
        r"(?:求|计算|证明|求证|判断|判定|确定|写出|列出|找出|求解|解出|"
        r"构造|设计|画出|标出|绘制|给出|推导|枚举|统计|化简|转换|化为|填写|"
        r"选择|选出|试问|问[:：]?|回答下列|回答以下|以下哪|下列哪|"
        r"是否|多少(?:个|种|条|次)?|几种|几条|几人|有几|使得|满足)",
        value,
    ))
    has_math_context = bool(re.search(
        r"(?:集合|关系|函数|映射|图|树|顶点|边|整数|素数|质数|同余|"
        r"整除|矩阵|代数|群|环|序列|数列|递推|排列|组合|计数|鸽巢|"
        r"逻辑|真值|谓词|命题|元素|路径|回路|概率|算法|公式|方程|"
        r"gcd|lcm|最短路|欧拉|哈密顿|\\[a-zA-Z]+|"
        r"[A-Za-z]\s*(?:\^|_|=|∈|\()|\d+)",
        value,
    ))
    if not (has_action and (has_math_context or len(value) >= 24)):
        return ""
    return value


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


def _exercise_math_content_valid(question, answer):
    """拒绝缺失公式占位符和明显自相矛盾的图论前提。

    这里只做零成本、可确定的错误检查；它不是完整的数学证明器。
    """
    source = str(question or "") + "\n" + str(answer or "")
    if re.search(r"MATHPROTECTTOKEN\d+ENDTOKEN|DMATE_MATH_\d+_END", source, re.I):
        return False
    if re.search(r"(?:待补充|待填写|TODO|未生成|公式缺失|占位符|undefined|null)", source, re.I):
        return False
    # 在简单图里，不同边最多共享一个端点是定义的直接推论；
    # 绝不等价于图无四圈。屏蔽这种有明确逻辑冲突的生成题。
    if re.search(r"(?:简单无向图|无向简单图|简单图)", source):
        # 必须出现“即/等价”等因果或等价说法才判错；如果题目另外
        # 明确要求无四圈，虽然边共享限制冗余，但不是逻辑矛盾。
        misconception = (
            r"(?:任意|任何|所有)两条(?:不同|不相同|互异)?(?:的)?边"
            r".{0,20}(?:最多|至多)(?:只)?有(?:一|1)个公共(?:顶点|端点)"
            r".{0,12}(?:即|亦即|等价于|也就是说|意味着|因此)"
            r".{0,15}(?:不含|没有|不存在|无)(?:长度为|长为)?"
            r"[\s$\\]*(?:4|四).{0,6}(?:圈|环|回路)"
        )
        if re.search(misconception, source):
            return False
    # K4 自身含有长度为 4 的圈，不能用互不相交的 K4 构造无四圈图。
    # 只拦截把 K4 当作“满足无四圈条件”的肯定性构造，不拦截反例讨论。
    c4_forbidden = bool(re.search(
        r"(?:不含|没有|不存在|无)(?:长度为|长为)?[\s$\\]*(?:4|四).{0,6}(?:圈|环|回路)",
        str(question or "")
    ))
    k4_construction = bool(re.search(
        r"(?:取|选择|构造|由|并图|并集|组[成合])[^。；\n]{0,55}K[_\s{}]*4|"
        r"K[_\s{}]*4[^。；\n]{0,55}(?:不含|没有|不存在|无)[^。；\n]{0,8}(?:4|四).{0,6}(?:圈|环|回路)",
        str(answer or ""), re.I
    ))
    if c4_forbidden and k4_construction:
        return False
    return True


def _exercise_problem_complete(question, answer):
    """保守检查条件不全、多个小问却只有一个占位答案的情况。"""
    text = str(question or "").strip()
    value = str(answer or "").strip()
    if not text or not value:
        return False
    # 仅拦截明确要求从具体图求数值，却没有提供任何图结构信息的题。
    if (re.search(r"(?:求|计算|写出).{0,24}(?:最短路|最短路径|邻接矩阵|色多项式)", text)
            and re.search(r"图\s*[A-Z]", text, flags=re.IGNORECASE)
            and not re.search(r"边集|顶点集|边为|顶点为|相邻|邻接关系|完全图|圈图|环图|路径图|"
                              r"有向图.*边|无向图.*边|矩阵为|\{\s*[v\d]", text)):
        return False
    items = re.findall(r"(?:^|\n)\s*[（(]\s*(\d+)\s*[)）]", text)
    if len(set(items)) >= 2:
        # 多小问必须逐问给出实际答案；不能以一项数值或“略”蒙混过关。
        if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
            return False
        answered = set(re.findall(r"(?:^|\n)\s*[（(]\s*(\d+)\s*[)）]", value))
        if not set(items).issubset(answered):
            return False
    return _exercise_math_content_valid(text, value)


def _exercise_answer_valid(answer):
    """错题本必须在首次展示前拿到非占位的隐藏答案。"""
    value = _clean_answer_only(answer).strip()
    if not value or len(value) > 2000:
        return False
    if re.fullmatch(
        r"(?:最终答案|答案|略|无|待定|待填写|待计算|自行计算|自行求解|"
        r"参见解析|见解析|请自行.*|无法确定|不知道|TODO|N/A|\?+)",
        value, flags=re.IGNORECASE,
    ):
        return False
    if "[[WRONGBOOK_ANSWER" in value:
        return False
    # 模型会偶尔对含证明题返回“略（证明见解析）”，但此时系统其实
    # 尚未验证证明。不能把这种占位答案存入错题本并公开显示为正确答案。
    if re.search(
        r"(?:^|[：:、。；;\s）)])(?:略|见解析|证明见解析|参见解析|待证|证明略|步骤略)"
        r"(?:[（(]|[。；;\s]|$)", value, flags=re.I
    ):
        return False
    if re.search(r"MATHPROTECTTOKEN\d+ENDTOKEN|DMATE_MATH_\d+_END", value):
        return False
    return True


def _exercise_answer_simple_consistency(question, answer):
    """只核查极窄且可精确计算的单问幂模题；其余题不猜测答案。"""
    text = str(question or "")
    value = str(answer or "").strip()
    # 若有多小问/中国剩余/模运算的后续条件，则不做此种单问核验。
    if re.search(r"[（(]\s*[1-9]\s*[)）]|中国剩余|费马|\n\s*\d+[.、]", text):
        return True
    match = re.search(
        r"(?:求|计算)\s*(\d{1,10})\s*(?:\^|\*\*|\^\{)\s*(\d{1,10})\}?"
        r"\s*(?:除以|\s*(?:mod|bmod)\s*|\\(?:mod|bmod)\s*)\s*(\d{1,10})",
        text, flags=re.IGNORECASE,
    )
    if not match or not re.fullmatch(r"[+-]?\d+", value):
        return True
    a, b, modulus = (int(group) for group in match.groups())
    if modulus <= 0:
        return False
    return int(value) % modulus == pow(a, b, modulus)


def _requested_exercise_difficulty(text):
    """提取用户真正表达的练习难度，避免把知识范围词误当成难度。

    设计原则：
    1. 只做本地正则/语义邻接判断，不调用模型，不增加网络延迟；
    2. ``初级数论 / 基础图论 / 入门集合`` 这类词优先视为知识范围，
       但 ``基础题 / 入门题 / 不难的题`` 等明确修饰题目时仍识别为简单；
    3. 多个难度要求冲突时，以用户最后一次明确要求为准；
    4. 未明确指定难度返回空串，调用方统一按中等处理。
    """
    value = normalize_user_request_text(text)
    if not value:
        return ""

    matches = []
    protected = []

    def overlaps_protected(begin, end):
        return any(begin < right and end > left for left, right in protected)

    def protect(expressions):
        for expression in expressions:
            for match in re.finditer(expression, value, flags=re.IGNORECASE):
                protected.append(match.span())

    def collect(difficulty, expressions, reserve=True, priority=0):
        for expression in expressions:
            for match in re.finditer(expression, value, flags=re.IGNORECASE):
                begin, end = match.span()
                if overlaps_protected(begin, end):
                    continue
                matches.append((begin, end, priority, difficulty))
                if reserve:
                    protected.append((begin, end))

    # 这些词本身是离散数学里的知识范围/术语，而不是用户在说“题目简单”。
    # 只保护紧邻的复合词；“基础一点的图论题”“简单的图论题”仍会被当作难度要求。
    domain_words = (
        r"离散数学|初等数论|数论|图论|集合论|集合|二元关系|关系|函数|映射|"
        r"命题逻辑|谓词逻辑|数理逻辑|逻辑|组合数学|排列组合|组合|计数|"
        r"递推关系|递推|代数结构|抽象代数|布尔代数|群论|群|环|域|格论|格|"
        r"偏序|等价关系|矩阵|邻接矩阵|树|网络|欧拉图|哈密顿图|二部图|"
        r"图同构|最短路|最小生成树|生成函数|容斥原理|鸽巢原理|同余|模运算|"
        r"欧几里得算法|中国剩余定理|rsa"
    )
    protect((
        rf"(?:基础|初级|入门)(?:{domain_words})",
        # 图论中的“简单图/简单路径”等是数学术语，绝不能把“简单”当难度。
        r"简单(?:图(?!论)|路径|通路|回路|圈|链)",
    ))

    # -------- 先收集带否定/程度修饰的完整短语，避免被里面的“难/简单”二次命中 --------
    # 平衡表达、不要太简单、稍微有点难：先锁定为中等，防止后面的“简单/难”裸词拆开误判。
    collect("中等", (
        r"(?:不要|(?<![特级])别|不想要)?(?:太|过于)?难.{0,8}(?:也|又|并且|同时).{0,8}(?:不要|别)?(?:太|过于)?简单",
        r"(?:不要|(?<![特级])别|不想要)?(?:太|过于)?简单.{0,8}(?:也|又|并且|同时).{0,8}(?:不要|别)?(?:太|过于)?难",
        r"(?:不要|(?<![特级])别|不用|无需|不必)(?:出|来|给|弄|搞|做|整)?(?:一?道|一个)?(?:太|这么|那么|很|特别|过于)?(?:简单|容易)",
        r"(?:不简单|不太简单|不怎么简单|不算简单|不是很简单|没那么简单|不那么简单|不容易|不太容易)",
        r"(?:稍微|稍稍|略微|略|有点|有一点|稍)(?:有)?难(?:一?点|一点儿|点|一些|些)?",
        r"(?:稍微|稍稍|略微|略|有点|有一点|稍)(?:有)?(?:难度|挑战)(?:一?点|一点儿|点|一些|些)?",
        r"(?:稍微|稍稍|略微|略|有点|有一点|稍)(?:有)?(?:复杂|烧脑)(?:一?点|一点儿|点|一些|些)?",
        r"(?:有难度|有一点挑战|有点挑战)",
        r"(?:中等偏难|中等偏易)",
        r"(?:不简单也不难|不难也不简单|不易不难|不难不易|难易适中)",
    ), priority=90)

    # 简单：明确要求不要难、容易一些、适合新手等。
    collect("简单", (
        r"(?:不难|不太难|不怎么难|不算难|不是很难|没那么难|不那么难|并不难|不困难|不太困难|不是很困难)",
        r"(?:不要|(?<![特级])别|不用|无需|不必|(?<![特级])别给我|不要给我)(?:出|来|给|弄|搞|做|整)?(?:一?道|一个)?(?:太|这么|那么|很|特别|过于)?(?:难|困难)",
        r"难度(?:低|小|不高|不大|低一点|低一些|小一点|小一些|降一点|降低一点)",
        r"(?:降低|调低|降一降|往下调)(?:一下|一点|一些)?(?:题目)?难度",
        r"(?:难度)?(?:往简单|往容易)(?:调|降)?(?:一点|一些)?",
        r"(?:不要|(?<![特级])别|不用|无需|不必)(?:太|这么|那么|很|特别|过于)?(?:复杂|烧脑)",
        r"(?:不复杂|不太复杂|不怎么复杂|不烧脑|不太烧脑)",
        r"(?:简单|容易|轻松|友好)(?:一?点|一点儿|一些|些|点儿)?",
        r"(?:偏简单|偏易|较简单|较易|更简单|更容易)",
        r"(?:再|比(?:上一题|上题|刚才|前一题|之前))?(?:简单|容易)(?:一?点|一些|些)",
        r"(?:基础|入门|初级)(?:题|练习|难度|水平|级别|级|档|档位)",
        r"(?:简单|容易|轻松|基础|入门|初级)(?:的)?(?:题目|题|练习)(?:吧|呢|呗)?",
        r"(?:基础|入门)(?:一?点|一点儿|一些|些)",
        r"(?:新手|小白|初学者|零基础)(?:题|练习|能做|适合)",
        r"适合(?:新手|小白|初学者|入门|零基础)",
        r"(?:热身|练手|送分)(?:题|练习)",
        r"低阶(?:题|练习|难度)?",
        r"(?<![a-z])easy(?![a-z])",
    ), priority=40)

    # 中等：明确要求适中；或“稍微有点难/不要太简单”这类落在中间档的表达。
    collect("中等", (
        r"(?:中等偏难|中等偏易|中等难度|中等|适中|难度适中)",
        r"(?:普通|一般|正常|常规|标准)(?:难度|题|练习|一点|点|些)?",
        r"(?:正常点|普通点|一般点|适中一点|居中一点|中间一点)",
        r"(?:难度)?(?:居中|中间档|中间水平)",
        r"(?:期末|考试|作业|课内|课堂|常规考试)(?:水平|难度|题)",
        r"(?:中阶|中级)(?:题|练习|难度|水平|级别|级)?",
        r"(?:中等|适中|普通|一般|正常|常规|标准)(?:的)?(?:题目|题|练习)(?:吧|呢|呗)?",
        r"(?<![a-z])medium(?![a-z])|(?<![a-z])normal(?![a-z])",
    ), priority=50)

    # 困难：明确要求难、挑战、拔高、竞赛等。注意“稍微难一点”已在上面预留为中等。
    collect("困难", (
        r"(?:最高难度|最难|极难|超难|超级难|非常难|特别难|很难|巨难|变态难)",
        r"(?:困难|高难度?|高难|难度高|难度大|难度拉满)",
        r"(?:提高|调高|拉高|升高)(?:一下|一点|一些)?(?:题目)?难度",
        r"(?:难度)?(?:往难|往高)(?:调|升)?(?:一点|一些)?",
        r"(?:难一点(?:儿)?|难点儿|难一些|难些|更难|较难|偏难|再难一点(?:儿)?|再难一些)",
        r"(?:比(?:上一题|上题|刚才|前一题|之前))(?:更)?难(?:一?点|一些|些)?",
        r"(?:复杂一?点|复杂一些|偏复杂|更复杂|较复杂)",
        r"(?:挑战题|有挑战性|挑战性强|高挑战|高强度)",
        r"(?:难|困难|高难|复杂|烧脑|挑战)(?:的)?(?:题目|题|练习)(?:吧|呢|呗)?",
        r"(?:压轴|拔高|竞赛|奥赛|进阶|高阶|高级|烧脑)(?:题|练习|难度|级别|水平|级)?",
        r"(?:综合性很强|综合性强|多步推理|非平凡)(?:的)?(?:题|练习)?",
        r"(?<![a-z])hard(?![a-z])",
    ), priority=60)

    # -------- 再补最通用的裸词，但避开前面保护的学科术语和完整短语 --------
    collect("困难", (r"困难",), reserve=False, priority=10)
    collect("中等", (r"中等", r"适中"), reserve=False, priority=10)
    collect("简单", (r"简单", r"容易", r"轻松"), reserve=False, priority=10)

    if not matches:
        return ""

    # 用户后面补充的要求优先；同一位置发生重叠时，更具体的短语（priority 高）优先。
    matches.sort(key=lambda item: (item[0], item[1], item[2]))
    return matches[-1][3]


def _exercise_reference_matches(reference_teaching, generated_teaching):
    """校验“同知识点出题”是否真的保持了参照题核心考点。

    返回：(是否通过, 失败原因)。
    分类未知时不凭空断言偏题；一旦两边都能识别出知识点，就要求至少有
    一个核心知识点重合，避免“同为图论但从图同构漂到最短路”这类假匹配。
    """
    if not isinstance(reference_teaching, dict) or not isinstance(generated_teaching, dict):
        return True, ""

    expected_category = str(reference_teaching.get("category") or "").strip()
    actual_category = str(generated_teaching.get("category") or "").strip()

    expected_categories = {expected_category, *(reference_teaching.get("related_categories") or [])} - {"", "待识别"}
    actual_categories = {actual_category, *(generated_teaching.get("related_categories") or [])} - {"", "待识别"}
    if expected_categories and actual_categories and expected_categories.isdisjoint(actual_categories):
        return False, "生成的练习偏离了参照题所属模块。"

    required_points = {
        str(item).strip()
        for item in (reference_teaching.get("retest_core_points") or [])
        if str(item).strip()
    }
    expected_points = required_points or {
        str(item).strip()
        for item in (
            reference_teaching.get("focus_points")
            or reference_teaching.get("knowledge_points")
            or []
        )
        if str(item).strip()
    }
    actual_points = {
        str(item).strip()
        for item in (
            (generated_teaching.get("focus_points") or [])
            + (generated_teaching.get("knowledge_points") or [])
        )
        if str(item).strip()
    }

    # 错题本多考点复测是“全部核心考点”，不能只重合一项就放行。
    # 无结构化复测范围的普通“同知识点”请求，保留此前至少一项交集的逻辑。
    if required_points:
        missing = sorted(required_points - actual_points)
        if missing:
            return False, "复测题遗漏核心知识点：" + "、".join(missing)
    elif expected_points and actual_points and expected_points.isdisjoint(actual_points):
        return False, "生成的练习偏离了参照题核心知识点。"

    return True, ""


def _requested_reasoning_effort(text):
    """本轮显式要求模型思考档位，独立于题目难度分类。

    仅匹配带有命令意味的短语；历史题干里提到 max/high 不触发。
    """
    value = re.sub(r"\s+", "", str(text or "").lower())
    # 先排除单纯禁止某个档位的句子，避免“不要用 max”被当成启用 max。
    patterns = {
        "max": (
            # “出一道最高难度题”是题目难度，不是 max 思考指令。
            r"(?:请|要|必须|改用|使用|采用|开启|启用|切到|换成|按照|按|用|以|给我用)"
            r".{0,8}max(?:思考|推理|强度|档|模式)?",
            r"(?:请|要|必须|改用|使用|采用|开启|启用|切到|换成|按照|按|用|以|给我用)"
            r".{0,8}(?:最高|最大)(?:思考|推理|强度|档|模式)",
            r"(?:max|最高|最大)(?:思考|推理|强度|档|模式)(?:来|去|处理|求解|解答|解析)",
        ),
        "high": (
            r"(?:请|要|必须|改用|使用|采用|开启|启用|切到|换成|按照|按|用|以|给我用)"
            r".{0,8}high(?:思考|推理|强度|档|模式)?",
            r"high(?:思考|推理|强度|档|模式)(?:来|去|处理|求解|解答|解析)",
        ),
    }
    matched = []
    for effort, expressions in patterns.items():
        for expr in expressions:
            for hit in re.finditer(expr, value, re.I):
                vicinity = value[max(0, hit.start()-10):hit.end()]
                # 区分“你刚才用 high 而不是 max”（描述）和“现在改用 max”（命令）。
                if re.search(r"(?:不要|别|不用|禁止|无需|不准|而不是|不是)(?:.{0,5})(?:max|high|最高|最大)", vicinity):
                    continue
                if re.search(r"(?:你刚才|刚才|之前|上次|先前|刚刚).{0,5}(?:用|使用)(?:high|max)", vicinity) and not re.search(r"请|现在|改用|换成|接下来|必须", vicinity):
                    continue
                matched.append((hit.end(), effort))
    if not matched:
        return ""
    return max(matched)[1]


def _parse_requested_outputs(instruction):
    """Read independent output requests and their local negation/future scopes.

    Only the current *instruction* is inspected, never the old problem statement.
    A prohibition on explaining must not suppress a separately requested answer,
    and a promise to review later must not trigger immediate answer disclosure.
    """
    text = re.sub(r"\s+", "", normalize_user_request_text(instruction))
    empty = {"answer": False, "explanation": False, "knowledge": False, "hints": False}
    if not text:
        return empty
    if re.search(
        r"(?:出题|生成题).{0,12}(?:功能|代码|错误|bug|逻辑|机制|为什么|怎么不行)"
        r"|(?:讲讲|讨论|解释).{0,30}(?:出题|生成题|出.{0,8}题).{0,20}"
        r"(?:功能|为什么不行|问题|错误|bug)", text, re.I
    ):
        return empty

    # Clause-level parsing matters: “答案现在给，解析等我做完再说” has
    # two different temporal scopes. A blanket future/negative flag is wrong.
    parts = [p for p in re.split(r"[，,。；;！!？?]|(?=但是|(?<!不)但(?=给|不|要|是))", text) if p]
    result = dict(empty)
    answer_term = r"(?:最终答案|参考答案|正确答案|完整答案|答案|回答|解答|结果|结论)"
    solution_term = r"(?:详细解析|完整解析|解题过程|解题步骤|解法|推导过程|证明过程|完整证明|详细步骤|步骤|过程|解析|讲解|推导|求解过程)"
    answer_negative = rf"(?:不要|别|不用|无需|不需要|不必|禁止|暂不|先不|不给|不公布|别给).{{0,7}}{answer_term}"
    explanation_negative = rf"(?:不要|别|不用|无需|不需要|不必|禁止|暂不|先不|不给).{{0,7}}{solution_term}"
    answer_positive = (
        rf"(?:给出|给我|给|附上|附带|提供|输出|写出|展示|告诉我|告诉|公布|附|要|同时|并|然后|再|顺便|一起)"
        rf".{{0,13}}{answer_term}|{answer_term}.{{0,6}}(?:现在给|立即给|一起给|直接给|也给|先给|给出|附上|发给我|都给)|"
        rf"(?:题目|出题|练习|题).{{0,14}}(?:和|与|及|以及|并|同时|然后|附|带).{{0,12}}{answer_term}"
    )
    solution_positive = (
        rf"(?:给出|给我|给|附上|附带|提供|输出|写出|展示|告诉我|告诉|同时|并|然后|再|顺便|一起|带上)"
        rf".{{0,13}}{solution_term}|"
        rf"(?:并|然后|同时|顺便|再)(?:完整)?(?:解释|讲解|解答|解出来|求解|做出来|证明|分析答案)|"
        rf"(?:题目|出题|练习|题|答案|结果).{{0,12}}(?:和|与|及|以及|并|同时|附|带).{{0,10}}{solution_term}|"
        rf"{solution_term}.{{0,5}}(?:也|一起|都)?(?:给出|给我|附上|提供|写出|要)"
    )
    future_prefix = r"(?:等我|待我|我(?:先|自己|来)?(?:做|答|解|完成)|答完|写完|做完|完成后|下次|以后|稍后|晚点)"

    def deferred(clause, word_pattern):
        return bool(
            re.search(rf"{future_prefix}.{{0,18}}(?:再|才|后|然后).{{0,10}}{word_pattern}", clause)
            or re.search(rf"{word_pattern}.{{0,10}}{future_prefix}.{{0,16}}(?:再|才|说|讲|给|公布|批改|检查|评价)", clause)
            or re.search(rf"{word_pattern}.{{0,10}}(?:稍后|晚点|以后|下次)(?:再)?(?:给|说|讲|公布)", clause)
        )

    answer_is_forbidden = False
    for part in parts:
        # Only answer-related phrases trigger answer detection; do not infer
        # an answer just because the student requested a "证明题".
        neg_answer = bool(re.search(answer_negative, part)) or bool(re.search(
            rf"{answer_term}.{{0,10}}(?:都不要|均不要|不用|不需要)", part
        ))
        neg_explain = bool(re.search(explanation_negative, part)) or bool(re.search(
            rf"{solution_term}.{{0,10}}(?:都不要|均不要|不用|不需要)", part
        ))
        both_negative = bool(re.search(
            r"(?:答案|回答|解析|步骤|过程).{0,10}(?:和|与|及).{0,10}"
            r"(?:答案|回答|解析|步骤|过程).{0,5}(?:都不要|均不要)", part
        ))
        if both_negative:
            neg_answer = neg_explain = True
        only_problem = bool(re.search(
            r"(?:只|仅)(?:给|要|需|出|生成)?(?:一道|一题|一个)?(?:题目|题干|练习)(?:就行|即可|好了)?$", part
        ))
        only_hint = bool(re.search(r"(?:只|仅)(?:给|要|需)(?:我)?(?:一些|一?点)?(?:提示|思路)", part))
        only_answer = bool(re.search(r"(?:只|仅)(?:给|要|需)?(?:最后|最终|参考)?答案", part))

        answer_now = bool(re.search(answer_positive, part))
        explain_now = bool(re.search(solution_positive, part))
        answer_later = deferred(part, answer_term) or bool(re.search(
            r"(?:先出题|先给题|先给我题|出题|出一道题).{0,18}(?:之后|再|然后|并)"
            r"(?:批改|检查|点评)(?:我|我的)?(?:答案|回答)", part
        ))
        explain_later = deferred(part, solution_term)
        # “先出题，等我回答再批改” is a follow-up promise, not an answer.
        review_later = bool(re.search(
            r"(?:等我|待我|我先|我自己|我来|做完|答完|写完|之后|下次|稍后|晚点)"
            r".{0,20}(?:再|才)(?:帮我|给我|替我)?(?:批改|检查|点评|评价)", part
        ))

        if neg_answer or only_problem or only_hint:
            result["answer"] = False
            if neg_answer:
                answer_is_forbidden = True
        elif answer_now and not answer_later and not review_later:
            result["answer"] = True
            answer_is_forbidden = False
        if neg_explain or only_problem or only_hint or only_answer:
            result["explanation"] = False
        elif explain_now and not explain_later and not review_later:
            result["explanation"] = True
            # Complete solution implies disclosure of the answer unless a
            # separate, explicit no-answer instruction forbids it.
            if not neg_answer and not only_hint and not answer_is_forbidden:
                result["answer"] = True

        knowledge_positive = bool(re.search(
            r"(?:并|同时|顺便|再|附|给出|列出|告诉我|分析|说明|带上|包含|提供)"
            r".{0,14}(?:涉及的?知识点|相关知识点|考点|知识点分析|知识点|对应模块)|"
            r"(?:题目|出题).{0,8}(?:涉及|考查|对应)(?:什么|哪些)?(?:知识点|考点)", part
        ))
        hint_positive = bool(re.search(
            r"(?:并|同时|顺便|再|附|给出|附上|提供|告诉我|只给|仅给|带上|给我|给|来)"
            r".{0,12}(?:解题提示|关键提示|提示|初步思路|思考方向|思路)|"
            r"(?:先|只|仅)(?:给|说)(?:我)?(?:一?点|一些)?提示", part
        ))
        if re.search(r"(?:不要|别|无需|不需要|不用).{0,5}(?:知识点|考点)",part):
            result["knowledge"] = False
        elif knowledge_positive:
            result["knowledge"] = True
        if re.search(r"(?:不要|别|无需|不需要|不用).{0,5}(?:提示|思路)",part):
            result["hints"] = False
        elif hint_positive:
            result["hints"] = True

    # Do not disclose a final answer if the student explicitly prohibited it.
    # “不要答案但给过程” becomes process guidance, not a solved exercise.
    if answer_is_forbidden and result["explanation"]:
        result["explanation"] = False
        result["hints"] = True
    if result["explanation"]:
        result["hints"] = False
    return result


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
    client_requests_solution = request_kind == "solution"

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
    normalized_action_for_exercise = normalize_user_request_text(
        latest_action_for_exercise
    )

    # 同知识点出题的参照题由前端显式提交。只接收题干，分类由后端重新计算。
    reference = data.get("exercise_reference")
    reference_teaching = None
    is_wrongbook_retest = False
    original_retest_difficulty = ""
    if reference is not None:
        if (not client_requires_exercise or not isinstance(reference, dict)
                or not isinstance(reference.get("question"), str)
                or not reference["question"].strip()
                or len(reference["question"]) > MAX_MESSAGE_CHARS):
            return jsonify({"error": "练习参照题格式不正确，请重新选择题目。"}), 400
        reference_text = reference["question"].strip()
        reference_teaching = analyze_question(reference_text)
        # 仅当确实来自错题本复测时才继承难度；普通同考点出题不受影响。
        is_wrongbook_retest = reference.get("retest") is True
        if is_wrongbook_retest:
            saved_level = reference.get("difficulty")
            inferred_level = (reference_teaching or {}).get("difficulty")
            original_retest_difficulty = (
                saved_level if saved_level in ("简单", "中等", "困难")
                else inferred_level if inferred_level in ("简单", "中等", "困难")
                else "中等"
            )
        # 错题复测由客户端携带保存的“全部核心考点”；不从原题的
        # focus_points (通常只有前两项) 反推，避免遗漏其它知识点。
        core_points = reference.get("core_points")
        if isinstance(core_points, list) and isinstance(reference_teaching, dict):
            filtered = list(dict.fromkeys(
                point.strip() for point in core_points
                if isinstance(point, str) and 0 < len(point.strip()) <= 40
            ))[:4]
            if filtered:
                reference_teaching["retest_core_points"] = filtered
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
    # 完整解析只在本轮用户明确请求时开启；不能通过请求参数
    # 绕过学生“不要给答案”的明确指令。
    current_instruction = extract_current_request(
        next((item["content"] for item in reversed(cleaned)
              if item["role"] == "user"), "")
    )
    # Separate the two independent user intents: disclose the final answer,
    # and show a worked solution. Negating one must NOT negate the other.
    # In particular “给答案但不要解析” still requires the answer, while
    # “出题后我来答，你再批改” must not reveal the answer immediately.
    output_intent = _parse_requested_outputs(current_instruction)
    explicit_solution = output_intent["answer"]
    explicit_explanation = output_intent["explanation"]
    # max 已停用。用户明确要求 max 时立即如实告知，不悄悄用 high 冒充。
    # 本轮询问以前是否使用 max、或者明确说“不要用 max”，不在此列。
    if _requested_reasoning_effort(current_instruction) == "max":
        return jsonify({
            "reply": (
                "DMate 当前不支持 max 思考强度。"
                "中等和困难题的解答统一使用 high。"
                "请不指定 max，直接提出题目或要求完整解析。"
            ),
            "unsupported_effort": "max",
        })

    solution_mode = bool(explicit_solution or (
        (teaching or {}).get("mode") == "full_solution"
        and not re.search(r"(?:不要|别|不用|无需|不需要).{0,5}(?:答案|解答)", current_instruction)
    ))
    if solution_mode:
        teaching = dict(teaching or {})
        teaching["mode"] = "full_solution"
        teaching["mode_label"] = "完整解析"

    # 仅当本轮确实要求答案、客户端发送的题干与实际请求锚点一致时，
    # 才使用这道生成题之前保存的参考答案；不查其他账号或会话。
    solution_reference_answer = ""
    if solution_mode and not client_requires_exercise:
        ref = data.get("solution_reference")
        if isinstance(ref, dict):
            q = ref.get("question")
            a = ref.get("answer")
            if (isinstance(q, str) and isinstance(a, str)
                    and 5 <= len(q.strip()) <= 6000
                    and 0 < len(a.strip()) <= 1200
                    and q.strip() in cleaned[-1]["content"]):
                solution_reference_answer = a.strip()
                teaching["solution_reference_answer"] = solution_reference_answer

    # 题目难度优先采用前端明确指向的题目快照，不重新从追问语句
    # 推测难度。只接受已包含在本轮用户消息中的同一题目锚点。
    if not client_requires_exercise:
        question_context = data.get("question_context")
        if isinstance(question_context, dict):
            pinned_question = str(question_context.get("question") or "").strip()
            pinned_difficulty = str(question_context.get("difficulty") or "").strip()
            current_user_content = next(
                (item["content"] for item in reversed(cleaned)
                 if item["role"] == "user"), ""
            )
            if (10 <= len(pinned_question) <= 6000
                    and pinned_difficulty in ("简单", "中等", "困难")
                    and "【当前指向题目】" in current_user_content
                    and pinned_question in current_user_content):
                # 客户端的题目难度标签可能由旧版分类器生成。
                # 后端重新评估真实题干，不盲目相信旧标签。
                fresh = analyze_question(pinned_question)
                rechecked = (fresh or {}).get("difficulty")
                selected = rechecked if rechecked in ("简单", "中等", "困难") else pinned_difficulty
                teaching = dict(teaching or {})
                teaching["difficulty"] = selected
                if selected != pinned_difficulty:
                    print(f"修正旧题难度：标签={pinned_difficulty}，重新评估={selected}")
                else:
                    print(f"当前题目难度已复核：{selected}")

        explicit_effort = _requested_reasoning_effort(current_instruction)
        client_effort = str(data.get("reasoning_effort_override") or "").lower()
        # 客户端的续用偏好只在它携带了有效题目锚点时接受。
        has_pinned_question = bool(
            isinstance(question_context, dict)
            and isinstance(question_context.get("question"), str)
            and "【当前指向题目】" in current_user_content
            and question_context["question"].strip() in current_user_content
        )
        selected_effort = ("high" if explicit_effort == "high" else "") or (
            "high" if has_pinned_question and client_effort == "high" else ""
        )
        if selected_effort:
            teaching = dict(teaching or {})
            teaching["reasoning_effort_override"] = selected_effort
            print(f"本轮使用明确指定的 {selected_effort} 思考档位。")

    # 双保险：前端 request_kind 是强信号，但后端仍独立理解自然语言。
    # 因此用户换成“随便来一道 / 整个难题 / 考我一道”等说法时，
    # 即使前端某次没有命中，也不会退回普通聊天模式。
    server_detected_exercise = looks_like_exercise_request(
        normalized_action_for_exercise
    )
    effective_exercise_request = bool(
        client_requires_exercise
        or (teaching or {}).get("mode") == "exercise"
        or server_detected_exercise
    )

    # 用户明确要求“出题并给答案/解析”时，必须执行复合任务。
    # 不影响普通出题的隐藏答案和难度校验。
    exercise_solution_requested = bool(
        effective_exercise_request and explicit_solution
    )
    exercise_explanation_requested = bool(
        effective_exercise_request and explicit_explanation
    )

    # 只对独立出题采用本轮请求。避免把几十轮历史题目交给模型，
    # 造成串题、额外 token 和意外耗时。同知识点复测仍保留结构化参照题。
    # 如果客户端显式提供参照题，前面已组装成单条带锚点的请求。
    explicit_topic_teaching = None
    if effective_exercise_request and not reference_teaching:
        if normalized_action_for_exercise:
            explicit_topic_teaching = analyze_question(normalized_action_for_exercise)
        if latest_user_before_reference is not None:
            cleaned = [{
                "role": "user",
                "content": latest_user_before_reference["content"],
            }]

    # 明确难度要求与内部默认难度必须区分。内部默认只用于提示 AI，
    # 不能作为拒绝正常生成题目的硬约束。
    explicit_exercise_difficulty = ""
    if effective_exercise_request:
        teaching = dict(reference_teaching or explicit_topic_teaching or teaching or {})
        requested_difficulty = _requested_exercise_difficulty(
            normalized_action_for_exercise
        )
        # 错题复测：默认继承原错题保存的难度。仅用户在本轮明确下达
        # “改出简单/困难”指令时覆盖；普通出题依旧默认中等。
        # 复测提示中的“与原题相同”属于内部说明，不是一条改难度命令。
        if is_wrongbook_retest:
            requested_difficulty = original_retest_difficulty
        explicit_exercise_difficulty = requested_difficulty
        exercise_target_difficulty = requested_difficulty or "中等"

        teaching["mode"] = "exercise"
        teaching["mode_label"] = "练习出题"
        if reference_teaching and reference_teaching.get("retest_core_points"):
            teaching["retest_core_points"] = reference_teaching["retest_core_points"]
        teaching["question_type"] = teaching.get("question_type") or "出题请求"
        teaching["difficulty"] = exercise_target_difficulty
        teaching["exercise_target_difficulty"] = exercise_target_difficulty
        original_compact_request = re.sub(
            r"\s+", "", str(latest_action_for_exercise or "").strip().lower()
        )
        if normalized_action_for_exercise and normalized_action_for_exercise != original_compact_request:
            teaching["normalized_exercise_request"] = normalized_action_for_exercise

    # 出题只需要“设计一道符合目标难度的题”，不需要用与解困难题相同的 max 推理。
    # 目标难度仍由 exercise_target_difficulty 严格写进教学提示；模型思考强度
    # 与题目难度分开。生成练习先快速设计并通过本地检查，不做无正文的长推理。
    # 真正解题时中等/困难统一采用 high。
    ai_teaching = teaching
    if effective_exercise_request:
        ai_teaching = dict(teaching or {})
        target_for_generation = ai_teaching.get("exercise_target_difficulty") or "中等"
        # 题目生成与题目解答分开控制思考强度：
        # 练习生成优先非思考，质量纠偏也优先重新设计具体题目，
        # 避免困难题在 high 模式下长时间推理但最终正文为空。
        # 真正解题时中等/困难均为 high。
        ai_teaching["generation_reasoning_effort"] = "none"

    # 网络层零自动重试 + 质量层最多一次重生成：避免一次出题叠加
    # 3 次 HTTP 重试、app 兜底、格式修补、难度纠偏导致几十秒到数分钟等待。
    # 普通聊天继续使用原来的网络重试行为。
    try:
        if effective_exercise_request:
            result = ask_ai(cleaned, retries=0, teaching_context=ai_teaching)
        else:
            # 普通聊天完全沿用此前的调用签名与重试逻辑。
            result = ask_ai(cleaned, teaching_context=ai_teaching)
    except Exception as exc:
        print(f"/chat AI 首次请求异常：{repr(exc)}")
        if not effective_exercise_request:
            return jsonify({"error": "AI 服务暂时出现异常，请稍后重试。"}), 500
        result = {"ok": False, "error": "AI 服务暂时出现异常"}

    if not isinstance(result, dict):
        print("AI 返回格式异常：", type(result).__name__)
        result = {"ok": False, "error": "AI 服务返回格式异常"}

    # 若首次网络请求失败或推理用完预算没有正文，也进入同一个二次候选，
    # 而不是先调用若干次兜底后再单独做纠偏。
    if effective_exercise_request and (not result.get("ok") or not str(result.get("reply") or "").strip()):
        error_message = str(result.get("error") or "模型未返回正文")
        print("练习首次生成失败，使用唯一一次轻量补救：", error_message)
        fallback_context = dict(ai_teaching)
        fallback_context["generation_reasoning_effort"] = "none"  # 只降低思考耗时，不降低出题目标
        fallback_context["exercise_target_difficulty"] = teaching["exercise_target_difficulty"]
        try:
            result = ask_ai(cleaned[-1:], retries=0, teaching_context=fallback_context)
        except Exception as fallback_exc:
            print("练习轻量补救失败：", repr(fallback_exc))
            result = {"ok": False, "error": "AI 服务暂时出现异常"}
        if not isinstance(result, dict):
            result = {"ok": False, "error": "AI 服务返回格式异常"}
        # 无论补救是否成功，不再发起第三次请求。
        generation_retry_used = True
    else:
        generation_retry_used = False

    if not result.get("ok"):
        if solution_mode and solution_reference_answer and not effective_exercise_request:
            # 失败时仍可展示出题时保存的最终答案，清楚说明缺少独立推导。
            # 不声称有完整解析，也不静默伪造证明。
            return jsonify({
                "reply": (
                    "本次完整解析没有成功生成。\n\n"
                    "**出题时保存的参考答案（尚未独立复核）：**\n\n"
                    + solution_reference_answer
                    + "\n\n请稍后重试“给出答案和解析”以获取推导过程。"
                ),
                "solution_partial": True,
                "teaching": {k: v for k, v in teaching.items() if k != "solution_reference_answer"},
            })
        return jsonify({"error": result.get("error") or "这次没有生成有效题目，请重试。"}), 503

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
            or looks_like_exercise_request(
                latest_user_text
            )
        )

        generated_question = ""

        if is_exercise_request:
            # 一份候选题只能通过统一的校验后登记：
            # 有真实可作答的题干、参照知识点相符、独立出题未偏离显式学科。
            # 两次候选共用这套验证，避免错误提示/偏题内容绕过检查。
            requested_category = str(
                (explicit_topic_teaching or {}).get("category") or ""
            ).strip()
            requested_points = set(
                str(item).strip() for item in
                (explicit_topic_teaching or {}).get("knowledge_points", [])
                if str(item).strip()
            )
            is_narrow_topic = bool(
                requested_points
                and requested_category not in ("", "待识别")
                and not re.fullmatch(
                    r"(?:出|来|给|考).{0,10}(?:离散数学|数论|图论|集合|逻辑|关系|函数|计数|递推|代数)(?:题|练习|题目)?",
                    normalized_action_for_exercise or "",
                )
            )
            # 广泛的“图论/数论”请求不要求命中某个具体前置知识点；
            # 用户明确说了“邻接矩阵/同构/中国剩余定理”等才校验具体考点。
            explicit_topic_terms = (
                "邻接矩阵", "图同构", "中国剩余定理", "模逆", "前束范式",
                "真值表", "欧拉", "哈密顿", "最短路", "最小生成树",
                "关系矩阵", "关系的幂", "传递闭包", "二部图", "拓扑排序",
                "生成函数", "鸽巢", "容斥", "数学归纳", "费马小定理",
                "同余方程", "递推", "群同态", "置换", "函数复合",
            )
            is_narrow_topic = is_narrow_topic and any(
                word in (normalized_action_for_exercise or "")
                for word in explicit_topic_terms
            )

            def evaluate(candidate_reply):
                if not isinstance(candidate_reply, str):
                    return None, "AI 没有返回题目文本"
                visible, hidden_answer = _split_exercise_answer(candidate_reply)
                question_text = _extract_generated_question(visible)
                if not question_text:
                    return None, "AI 返回的不是可作答的数学题"
                cleaned_answer = _clean_answer_only(hidden_answer)
                if not _exercise_answer_valid(cleaned_answer):
                    return None, "生成题目没有有效的隐藏答案"
                if not _exercise_answer_simple_consistency(question_text, cleaned_answer):
                    return None, "题目与隐藏答案不一致"
                try:
                    info = analyze_question(question_text)
                except Exception as analyze_exc:
                    print("出题分析异常：", repr(analyze_exc))
                    return None, "题目分析失败"
                if not isinstance(info, dict):
                    return None, "题目分类结果无效"
                if reference_teaching:
                    matches, reason = _exercise_reference_matches(reference_teaching, info)
                    if not matches:
                        return None, reason
                if requested_category not in ("", "待识别"):
                    generated_category = str(info.get("category") or "").strip()
                    actual_categories = {generated_category, *(info.get("related_categories") or [])}
                    if requested_category not in actual_categories and generated_category not in ("", "待识别"):
                        return None, "生成题偏离指定学科"
                    if is_narrow_topic and generated_category in ("", "待识别"):
                        return None, "生成题未能确认指定知识点"
                    if is_narrow_topic and requested_category in actual_categories:
                        generated_points = set(
                            str(point).strip() for point in
                            (info.get("focus_points") or []) + (info.get("knowledge_points") or [])
                            if str(point).strip()
                        )
                        if generated_points and requested_points.isdisjoint(generated_points):
                            return None, "生成题偏离指定知识点"
                if not _exercise_problem_complete(question_text, cleaned_answer):
                    return None, "生成的题目条件不完整或隐藏答案缺少小问结果"
                return {
                    "reply": candidate_reply,
                    "question": question_text,
                    "answer": cleaned_answer,
                    "teaching": info,
                }, ""

            first_candidate, first_error = evaluate(reply)
            chosen_candidate = first_candidate
            target_difficulty = teaching.get("exercise_target_difficulty") or "中等"
            rank = {"简单": 0, "中等": 1, "困难": 2}

            first_level = (first_candidate or {}).get("teaching", {}).get("difficulty")
            # 纠偏与修补共用唯一的第二次生成机会。
            needs_retry = not first_candidate or (
                # 仅严格指定难度或错题复测在首次有效题偏档时再试一次。
                # 普通“随便出一道题”有完整题与答案即可返回，避免
                # 一个主观难度标签让生成耗时翻倍。
                (is_wrongbook_retest or bool(explicit_exercise_difficulty))
                and first_level in rank
                and target_difficulty in rank
                and first_level != target_difficulty
            )
            if needs_retry and not generation_retry_used:
                reason = first_error or (
                    f"首次候选难度估计为{first_level}，而目标为{target_difficulty}"
                )
                print("练习生成进行一次质量纠偏：", reason)
                retry_messages = list(cleaned[-1:])
                # 不要复用大段聊天历史；有参照题时保留前面准备好的带参照请求。
                # 纠偏仍是最多第二次模型请求。只有困难题使用新的定向纠偏：
                # 不升级 high 思考，以避免消耗几十秒后仍没有可用正文。
                if target_difficulty == "困难" and first_candidate:
                    retry_content = (
                        f"前次候选没有通过难度检查：{reason}。"
                        "请保留我要求的学科、知识点和参照题核心考点，"
                        "重新设计一题真正的困难题：要求非平凡的结构证明、"
                        "分类讨论、极值分析、受约束计数或构造中的至少一种，"
                        "并让至少两个步骤实质相互依赖。"
                        "单小问题目本身也必须有真实的多阶段推理深度。"
                        "不要只是加大数字、添加无关小问或改变难度标签。"
                        "检查全部题目条件、可解性和隐藏答案准确性，不输出检查过程。"
                        "严格只输出【题目】题干及[[WRONGBOOK_ANSWER]]答案[[/WRONGBOOK_ANSWER]]。"
                    )
                else:
                    # 简单/中等以及首次无效的兜底提示保持原来的行为。
                    retry_content = (
                        f"上一次生成没有通过题目检查：{reason}。"
                        f"请重新设计一题符合{target_difficulty}难度的离散数学题。"
                        "必须保持用户指定的学科/知识点及参照题的核心考点。"
                        "困难题要有非平凡的结构分析或计数/证明，"
                        "中等题应有紧密相关的两到三步推理，简单题只需基础操作。"
                        "请先在内部自行验证题目可解、条件完整、答案一致，不展示自检。"
                        "严格只输出【题目】题干及[[WRONGBOOK_ANSWER]]答案[[/WRONGBOOK_ANSWER]]。"
                    )
                retry_messages.append({"role": "user", "content": retry_content})
                retry_context = dict(ai_teaching)
                retry_context["generation_reasoning_effort"] = "none"
                retry_context["exercise_target_difficulty"] = target_difficulty
                try:
                    retry_result = ask_ai(
                        retry_messages,
                        retries=0,
                        teaching_context=retry_context,
                    )
                except Exception as retry_exc:
                    print("练习纠偏失败：", repr(retry_exc))
                    retry_result = None
                if isinstance(retry_result, dict) and retry_result.get("ok") is True:
                    second_candidate, second_error = evaluate(retry_result.get("reply"))
                    if second_candidate:
                        second_level = second_candidate["teaching"].get("difficulty")
                        if chosen_candidate is None:
                            chosen_candidate = second_candidate
                        elif second_level in rank and first_level in rank:
                            if abs(rank[second_level] - rank[target_difficulty]) < abs(rank[first_level] - rank[target_difficulty]):
                                chosen_candidate = second_candidate
                    else:
                        print("第二次练习未通过校验：", second_error)

            if chosen_candidate is None:
                # 不把拒绝出题、服务故障文案或跨学科内容登记为真实练习。
                return jsonify({
                    "error": (first_error + "请重新出题。") if first_error else "这次没有生成有效题目，请重新出题。",
                    "teaching": teaching,
                }), 502

            chosen_level = chosen_candidate["teaching"].get("difficulty")
            # 本地分类器的难度是估计值，不是数学正确性证明。候选已通过
            # 题干完整性、隐藏答案和参照考点校验时，不应仅因标签偏差
            # 就丢弃有效题目。保留实际标签，同时向客户端回报差异。
            if chosen_level != target_difficulty:
                print(f"练习有效但难度估计存在偏差：目标={target_difficulty}，实际={chosen_level}")
                generation_note = (
                    f"目标难度为{target_difficulty}，本次题目被估计为{chosen_level or '未确定'}；"
                    "题目已保留，请按实际难度核对。"
                )
            else:
                generation_note = ""

            reply = chosen_candidate["reply"]
            generated_question = chosen_candidate["question"]
            generated_answer = chosen_candidate["answer"]
            generated_teaching = chosen_candidate["teaching"]
            actual_difficulty = generated_teaching.get("difficulty")
            # 题干和参照知识点校验通过后即可展示；难度评级如实返回。
            reply = "【题目】\n\n" + generated_question
            if exercise_solution_requested:
                # The generation model supplies a private *final* answer, not a
                # proof. For an explicit solution request, expose the checked
                # answer; request a separate proof only when requested.
                answer_section = "【答案】\n\n" + generated_answer
                if exercise_explanation_requested:
                    explain_context = dict(generated_teaching or {})
                    explain_context["mode"] = "full_solution"
                    explain_context["mode_label"] = "完整解析"
                    explain_context["difficulty"] = actual_difficulty or "中等"
                    try:
                        explained = ask_ai([{"role":"user", "content":(
                            "请独立求解下面的离散数学题，必须给出完整推导、最终答案，"
                            "核对每个结果。若参考答案有误请纠正。\n"
                            "【题目】\n" + generated_question +
                            "\n【待核对参考答案】\n" + generated_answer
                        )}], retries=0, teaching_context=explain_context)
                    except Exception as explain_exc:
                        print("综合出题解析降级：", type(explain_exc).__name__)
                        explained = {}
                    explanation_text = str(explained.get("reply") or "").strip() if isinstance(explained, dict) else ""
                    explanation_text = _EXERCISE_ANSWER_PATTERN.sub("", explanation_text).strip()
                    if (isinstance(explained, dict) and explained.get("ok") and explanation_text
                            and not re.search(r"MATHPROTECTTOKEN\d+ENDTOKEN|DMATE_MATH_\d+_END", explanation_text, re.I)):
                        answer_section += "\n\n【解析】\n\n" + explanation_text
                    else:
                        answer_section += "\n\n解析暂时未能生成，已先保留出题时的参考答案。"
                reply += "\n\n" + answer_section
            if output_intent.get("knowledge"):
                # Use freshly analyzed *generated question* metadata, rather
                # than the instruction's topic list or stale previous question.
                knowledge_points = list(dict.fromkeys(
                    str(item).strip() for item in (
                        (generated_teaching or {}).get("knowledge_points") or []
                    ) + (
                        (generated_teaching or {}).get("focus_points") or []
                    ) if isinstance(item, str) and item.strip()
                ))[:6]
                if knowledge_points:
                    reply += "\n\n【涉及知识点】\n\n" + "、".join(knowledge_points)
                else:
                    category = str((generated_teaching or {}).get("category") or "").strip()
                    if category and category != "待识别":
                        reply += "\n\n【涉及知识点】\n\n" + category
            if output_intent.get("hints") and not exercise_explanation_requested:
                hint_context = dict(generated_teaching or {})
                hint_context["mode"] = "hint"
                hint_context["mode_label"] = "提示引导"
                try:
                    hint_result = ask_ai([{"role": "user", "content": (
                        "针对下面刚生成的练习题，给出两条具体、有用的解题提示，"
                        "不得公布最终答案，不得完成证明或代替学生解题。\n"
                        "【题目】\n" + generated_question
                    )}], retries=0, teaching_context=hint_context)
                except Exception as hint_exc:
                    print("综合出题提示降级：", type(hint_exc).__name__)
                    hint_result = {}
                hint_text = str(hint_result.get("reply") or "").strip() if isinstance(hint_result, dict) else ""
                # A hint request must never leak a final answer if the model
                # ignores its instruction and outputs a solution instead.
                appears_to_disclose_answer = bool(re.search(
                    r"【(?:答案|最终答案|解析)】|\[\[WRONGBOOK_ANSWER|(?:最终|参考|正确)?答案\s*[:：为是]",
                    hint_text, flags=re.IGNORECASE
                ))
                # The model may disclose the exact stored solution without a
                # heading. Reject a hint that reproduces that answer verbatim.
                normalized_answer = re.sub(r"\s+", "", generated_answer)
                normalized_hint = re.sub(r"\s+", "", hint_text)
                if len(normalized_answer) >= 8 and normalized_answer in normalized_hint:
                    appears_to_disclose_answer = True
                if isinstance(hint_result, dict) and hint_result.get("ok") and hint_text and not appears_to_disclose_answer:
                    reply += "\n\n【提示】\n\n" + hint_text
                else:
                    reply += "\n\n【提示】\n\n暂时没能生成可靠的提示。"

        response = {
            "reply": reply,
            "teaching": {k: v for k, v in teaching.items() if k != "solution_reference_answer"},
            "generated_exercise": bool(is_exercise_request and generated_question)
        }

        if generated_teaching:
            response["generated_teaching"] = generated_teaching

        if is_exercise_request and generation_note:
            response["exercise_generation_notice"] = generation_note

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
    fallback_entries = []

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
        if teaching is not None:
            fallback_entries.append((key, text[:6000], teaching))

    # 可选 AI 语义复核只在错题本的后台批量补全启用；普通 /chat
    # 依旧仅调用本地分类，不串行增加一次模型请求。
    if data.get("semantic_fallback") is True and fallback_entries:
        refined = classify_ambiguous_questions(fallback_entries)
        for result in results:
            better = refined.get(result["key"])
            if better:
                result["teaching"] = better

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


def _looks_like_non_question_ocr(text, visual_text):
    """Only reject high-confidence knowledge notes if vision classification is unavailable.

    A math graph without prose is deliberately NOT rejected here.
    We don't use broad rules such as "no question mark" since actual exercises often
    omit interrogatives or consist solely of a graph/matrix.
    """
    source = str(text or "").strip()
    visual = str(visual_text or "").strip()
    if not source or visual:
        return False
    if re.search(r"(?:求解?|计算|证明|试证|解答|作图|画出|写出|列出|判断|确定|求出|选择|填空|回答|思考题|例题|练习题|习题|[?？])", source):
        return False
    note_titles = re.search(
        r"(?:知识点(?:总结|归纳|梳理)|课程(?:简介|大纲)|学习目标|教学目标|"
        r"概念总结|定义与性质|运算表判别|性质汇总|本章小结|课堂笔记)",
        source,
    )
    definition_bullets = sum(bool(re.search(rf"{word}[：:]", source)) for word in (
        "封闭性", "交换律", "结合律", "幂等律", "单位元", "零元", "逆元", "定义", "性质"
    ))
    return bool(note_titles or definition_bullets >= 3)


def _ocr_has_exercise_evidence(text):
    """有明确题目小问时，不让偶发的 Vision 非题分类误杀 OCR 结果。

    只匹配动作+数学对象或者连续小问，不能把普通笔记中的定义误认成题。
    """
    source = str(text or "")
    numbered = len(set(re.findall(r"(?:^|\n)\s*[（(]\s*(\d{1,2})\s*[）)]", source)))
    question_action = bool(re.search(
        r"(?:回答(?:下列|以下)?问题|写出|求出|求|计算|判断|判定|证明|求证|列出|求解|画出)", source
    ))
    math_context = bool(re.search(
        r"(?:图|邻接矩阵|顶点|边|通路|回路|同余|整除|集合|关系|函数|数论|矩阵|欧拉|代数|证明)", source
    ))
    return (numbered >= 2 and question_action) or (question_action and math_context and len(source) >= 18)


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
    if not _check_rate_limit(_get_client_ip(), "ocr_cancel"):
        return jsonify({"error": "撤销请求过于频繁，请稍后再试。"}), 429
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
                # 模糊纯图或文字识别失败均转交 Vision，不直接拒绝图片。
                ocr_fallback_reason = str(exc)
                print(f"普通 OCR 未得到可用文字，转纯图 Vision：{ocr_fallback_reason}")
            except Exception as exc:
                # 模型初始化/临时资源异常可能没有包装成 OCRError。
                # OCR 与 Vision 相互隔离，单路失败不应杀掉整次图片请求。
                ocr_fallback_reason = "普通文字识别暂时不可用"
                print(f"文字 OCR 异常，改走 Vision 兜底：{type(exc).__name__}")
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

        # CPU-only OpenCV graph recognition is opportunistic and bounded.
        # Any uncertainty or failure leaves the original Vision/OCR fallback intact.
        graph_cv = {'graphs': [], 'status': 'not_graph', 'regions': []}
        possible_graph = (len(ocr_text) < 20 or bool(re.search(
            r"图|顶点|边|连通|邻接|路径|欧拉|哈密顿|G[123₁₂₃]", ocr_text
        )))
        if possible_graph and recognize_graphs is not None:
            try:
                graph_cv = recognize_graphs(raw, text_hint=ocr_text,
                                            allow_without_context=(len(ocr_text) < 20))
            except Exception as cv_exc:
                print(f"OpenCV 图结构识别降级：{type(cv_exc).__name__}")

        try:
            vision_result = analyze_image_structure(
                raw, review_regions=vision_regions, opencv_graphs=graph_cv
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
        image_kind = "uncertain"
        vision_warning = None
        uncertain_fields = []

        if (
            isinstance(vision_result, dict)
            and vision_result.get("ok") is True
        ):
            image_kind = vision_result.get("image_kind", "uncertain")
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

        # 提供给学生的是清晰的邻接关系，而不是 JSON 坐标、矩阵及调试日志。
        # 结构化 graph_structures 仍保留在 API 返回中供后端扩展。
        cv_graphs = graph_cv.get("graphs") or []
        if cv_graphs:
            readable = []
            all_complete = True
            for index, graph in enumerate(cv_graphs, 1):
                vertices = graph.get("vertices") or []
                edges = graph.get("edges") or []
                unknown = graph.get("uncertain_edges") or []
                full = graph.get("confidence") == "high" and not unknown
                all_complete = all_complete and full
                lines = [f'G{index}：{len(vertices)} 个顶点，检测到 {len(edges)} 条直线边。']
                if edges:
                    lines.append('边：' + '、'.join(
                        f'{edge[0]}—{edge[1]}' for edge in edges
                        if isinstance(edge, list) and len(edge) == 2
                    ) + '。')
                if unknown or not full:
                    lines.append('部分连接尚未确认，请结合原图核对，不能将未列出的边视为不存在。')
                    if graph_cv.get('elapsed_ms') is not None and (
                            graph.get('confidence') == 'partial'
                            and not unknown and len(edges) < len(vertices)):
                        lines.append('若图片较小或模糊，建议截取图形区域重新上传。')
                readable.append('\n'.join(lines))
            summary = '\n\n'.join(readable)
            # 只在图形证据不完整时附加 Vision 的结构补充，避免两份
            # 边集合冲突并把用户核对框撑满。保留普通曲线/有向等补充。
            if all_complete:
                # Straight-edge detector does not support arcs, multiple
                # edges, directions or weights: do not erase Vision evidence
                # for those structures merely because a straight-edge subset
                # looked complete.
                special = bool(re.search(r"有向|箭头|自环|重边|带权|弧线|曲线|孤立|不确定|待核对", visual_text))
                visual_text = summary + ('\n\n视觉补充（请核对）：\n' + visual_text if special else '')
            else:
                visual_text = summary + ('\n\n视觉补充（待核对）：\n' + visual_text if visual_text else '')

        # 撤销若发生在 Vision 调用期间，结果也直接丢弃。
        if request_id and _take_ocr_cancelled(request_id):
            return jsonify({"cancelled": True})

        # Vision 在原有同一次请求里判明为课件/笔记/照片时，不进入题目核对或 AI 解题。
        # uncertain 必须留给核对流程，避免误杀无题干的纯图论图形。
        if image_kind == "non_exercise" and not _ocr_has_exercise_evidence(ocr_text):
            return jsonify({
                "error": "这张图片看起来不是待解答的数学题目。请上传题目图片；如果只是想讨论知识点，可以直接在聊天框输入问题。",
                "not_a_question": True,
            }), 422

        if image_kind == "uncertain" and not _ocr_has_exercise_evidence(ocr_text) and _looks_like_non_question_ocr(
            corrected_text or ocr_text, visual_text
        ):
            return jsonify({
                "error": "识别到的主要是知识点说明或笔记，不是待解答的题目。请上传题目图片。",
                "not_a_question": True,
            }), 422

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
            # 兼容旧客户端：新增字段不影响现有 text / visual_text 处理。
            "graph_structures": cv_graphs,
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
