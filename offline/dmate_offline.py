#!/usr/bin/env python3
"""DMate Offline: local-only learning workspace (Python standard library).

Network boundary: the HTTP server binds to 127.0.0.1 and the only outgoing
connection is to the local Ollama port on 127.0.0.1. No account or cloud API.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import sqlite3
import sys
from urllib.parse import urlsplit
import uuid
import webbrowser

HERE = Path(__file__).resolve().parent
DATA_HOME = Path(os.environ.get("DMATE_OFFLINE_HOME", "~/.dmate-offline")).expanduser()
DB_FILE = DATA_HOME / "dmate.sqlite3"
MAX_JSON_BYTES = 10 * 1024 * 1024
SYSTEM_PROMPT = (
    "你是 DMate Offline，一个专注于离散数学与大学课程的本地辅学助手。"
    "优先说明解题思路，分步骤推导，提醒学生自行核验结论。"
    "数学公式使用标准 LaTeX 标记。不要假装运行过工具或已经验证图片细节。"
)


@contextmanager
def database():
    con = sqlite3.connect(DB_FILE, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def initialize():
    DATA_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
    with database() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS messages_by_session
          ON messages(session_id, id);
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK(kind IN ('note','mistake')),
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            updated_at TEXT NOT NULL
        );
        """)


def ollama_port():
    raw = os.environ.get("DMATE_OFFLINE_OLLAMA_PORT", "11434")
    value = int(raw)
    if not 1 <= value <= 65535:
        raise ValueError("Ollama 端口必须为 1–65535")
    return value


def available_models():
    try:
        con = http.client.HTTPConnection("127.0.0.1", ollama_port(), timeout=2)
        try:
            con.request("GET", "/api/tags")
            response = con.getresponse()
            if response.status != 200:
                raise OSError("Ollama 无法列出本地模型")
            models = json.loads(response.read(512 * 1024)).get("models", [])
            # Never offer Ollama cloud models in an explicitly offline app.
            names = sorted({
                x["name"] for x in models
                if isinstance(x, dict)
                and isinstance(x.get("name"), str)
                and not x["name"].lower().endswith(("-cloud", ":cloud"))
            })
            return (names[:100], None) if names else (
                [], "未发现本地模型；请先运行 ollama pull qwen3:4b")
        finally:
            con.close()
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return [], "无法连接本机 Ollama；请先启动 Ollama 并下载模型"


def validate_image(raw):
    if raw is None:
        return None
    if not isinstance(raw, str) or len(raw) > 9 * 1024 * 1024:
        raise ValueError("图片大小超出限制（最多 6 MiB）")
    if not raw.startswith("data:image/") or ";base64," not in raw:
        raise ValueError("图片格式不正确")
    mime, encoded = raw.split(";base64,", 1)
    if mime not in ("data:image/jpeg", "data:image/png", "data:image/webp"):
        raise ValueError("只支持 PNG、JPEG 或 WebP")
    try:
        binary = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("图片数据无效") from exc
    if not 0 < len(binary) <= 6 * 1024 * 1024:
        raise ValueError("图片大小超出限制（最多 6 MiB）")
    if not (binary.startswith(b"\x89PNG\r\n\x1a\n")
            or binary.startswith(b"\xff\xd8\xff")
            or (binary.startswith(b"RIFF") and binary[8:12] == b"WEBP")):
        raise ValueError("图片内容和格式不匹配")
    return encoded


def graph_analysis(data):
    directed = data.get("directed") is True
    names = []
    seen = set()

    def add(name):
        name = name.strip()
        if not name or len(name) > 40:
            raise ValueError("顶点名不能为空或超过 40 个字符")
        if name not in seen:
            names.append(name)
            seen.add(name)

    vertices = data.get("vertices", "")
    edges_text = data.get("edges", "")
    if not isinstance(vertices, str) or not isinstance(edges_text, str):
        raise ValueError("顶点和边必须为文本")
    for name in vertices.replace("\n", ",").split(","):
        if name.strip():
            add(name)
    edges = set()
    for line in edges_text.splitlines():
        line = line.strip()
        if not line:
            continue
        pair = line.replace("->", " ").replace(",", " ").split()
        if len(pair) != 2:
            raise ValueError("每行填写一条边，如 A B")
        a, b = pair
        add(a)
        add(b)
        if a == b:
            raise ValueError("当前图论工具仅支持无自环简单图")
        edge = (a, b) if directed else tuple(sorted((a, b)))
        edges.add(edge)
    if len(names) > 60 or len(edges) > 300:
        raise ValueError("最多支持 60 个顶点、300 条边")
    order = {name: i for i, name in enumerate(names)}
    adjacency = {name: set() for name in names}
    indegree = {name: 0 for name in names}
    for a, b in edges:
        adjacency[a].add(b)
        indegree[b] += 1
        if not directed:
            adjacency[b].add(a)
            indegree[a] += 1
    # Components are weakly connected components for directed graphs.
    undirected = {name: set() for name in names}
    for a, b in edges:
        undirected[a].add(b)
        undirected[b].add(a)
    components = []
    unvisited = set(names)
    for vertex in names:
        if vertex not in unvisited:
            continue
        queue = deque([vertex])
        unvisited.remove(vertex)
        group = []
        while queue:
            current = queue.popleft()
            group.append(current)
            for other in sorted(undirected[current], key=order.get):
                if other in unvisited:
                    unvisited.remove(other)
                    queue.append(other)
        components.append(group)
    start = data.get("start") or (names[0] if names else "")
    if start and start not in seen:
        raise ValueError("起点不属于顶点集合")
    bfs = []
    if start:
        queue = deque([start])
        visited = {start}
        while queue:
            current = queue.popleft()
            bfs.append(current)
            for other in sorted(adjacency[current], key=order.get):
                if other not in visited:
                    visited.add(other)
                    queue.append(other)
    degree = {
        name: ({"out": len(adjacency[name]), "in": indegree[name]}
               if directed else len(adjacency[name]))
        for name in names
    }
    return {
        "vertices": names,
        "edges": [list(pair) for pair in sorted(edges, key=lambda p: (order[p[0]], order[p[1]]))],
        "directed": directed,
        "degree": degree,
        "components": components,
        "bfs": bfs,
        "adjacency_matrix": [
            [1 if b in adjacency[a] else 0 for b in names] for a in names
        ],
        "is_tree": (not directed and bool(names) and len(components) == 1
                    and len(edges) == len(names) - 1),
    }


def backup_payload():
    with database() as con:
        return {
            "version": 1,
            "created_at": now(),
            "sessions": [dict(row) for row in con.execute("SELECT * FROM sessions ORDER BY created_at")],
            "messages": [dict(row) for row in con.execute(
                "SELECT session_id, role, content, created_at FROM messages ORDER BY id"
            )],
            "items": [dict(row) for row in con.execute("SELECT * FROM items ORDER BY updated_at")],
        }


def restore_backup(payload):
    if payload.get("version") != 1:
        raise ValueError("备份格式版本不受支持")
    sessions, messages, items = (payload.get(k) for k in ("sessions", "messages", "items"))
    if not all(isinstance(seq, list) for seq in (sessions, messages, items)):
        raise ValueError("备份缺少必要数据")
    if len(sessions) > 2000 or len(messages) > 30000 or len(items) > 10000:
        raise ValueError("备份记录超出限制")
    with database() as con:
        con.execute("DELETE FROM messages")
        con.execute("DELETE FROM sessions")
        con.execute("DELETE FROM items")
        for s in sessions:
            if (not isinstance(s, dict) or not all(
                isinstance(s.get(k), str) and 0 < len(s[k]) <= n
                for k, n in (("id", 64), ("title", 120), ("created_at", 64))
            )):
                raise ValueError("会话记录不正确")
            con.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                        (s["id"], s["title"], s["created_at"]))
        for m in messages:
            if (not isinstance(m, dict) or m.get("role") not in ("user", "assistant")
                    or not all(isinstance(m.get(k), str) and len(m[k]) <= n
                               for k, n in (("session_id", 64), ("content", 50000),
                                            ("created_at", 64)))):
                raise ValueError("消息记录不正确")
            con.execute("INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
                        (m["session_id"], m["role"], m["content"], m["created_at"]))
        for item in items:
            if (not isinstance(item, dict) or item.get("kind") not in ("note", "mistake")
                    or item.get("status") not in ("open", "resolved")
                    or not all(isinstance(item.get(k), str) and len(item[k]) <= n
                               for k, n in (("id", 64), ("title", 120),
                                            ("content", 10000), ("updated_at", 64)))):
                raise ValueError("笔记或错题记录不正确")
            con.execute("INSERT INTO items VALUES(?,?,?,?,?,?)", (
                item["id"], item["kind"], item["title"], item["content"],
                item["status"], item["updated_at"]))


class OfflineServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler):
        super().__init__(address, handler)
        self.csrf_token = secrets.token_urlsafe(32)


class Handler(BaseHTTPRequestHandler):
    server_version = "DMateOffline/0.1"

    def log_message(self, format, *args):
        print("[%s] %s" % (self.log_date_time_string(), format % args), file=sys.stderr)

    def send_bytes(self, content, mime="application/json; charset=utf-8", status=200, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
                         "form-action 'none'")
        if filename:
            self.send_header("Content-Disposition", 'attachment; filename="' + filename + '"')
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, value, status=200):
        self.send_bytes(json.dumps(value, ensure_ascii=False).encode("utf-8"), status=status)

    def reject(self, message, status=400):
        self.send_json({"error": message}, status=status)

    def check_host(self):
        host = self.headers.get("Host", "")
        if host not in ("localhost:%d" % self.server.server_port,
                        "127.0.0.1:%d" % self.server.server_port):
            self.reject("只允许本机访问", 403)
            return False
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            if (parsed.scheme != "http"
                    or parsed.hostname not in ("127.0.0.1", "localhost")
                    or parsed.port != self.server.server_port
                    or parsed.username or parsed.password):
                self.reject("跨站请求被拒绝", 403)
                return False
        return True

    def read_json(self):
        if self.headers.get("X-DMate-Local") != self.server.csrf_token:
            raise PermissionError("本机请求验证失败")
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            raise ValueError("请求必须是 JSON")
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= MAX_JSON_BYTES:
            raise ValueError("请求过大或为空")
        payload = json.loads(self.rfile.read(size))
        if not isinstance(payload, dict):
            raise ValueError("请求格式无效")
        return payload

    def static_file(self, name):
        if name in ("/", "/index.html"):
            target = HERE / "index.html"
        elif name in ("/app.js", "/style.css"):
            target = HERE / name.lstrip("/")
        elif name.startswith("/vendor/"):
            root = (HERE.parent / "static" / "vendor").resolve()
            target = (root / name.removeprefix("/vendor/")).resolve()
            if not target.is_relative_to(root):
                self.reject("无效的资源路径", 403)
                return
        else:
            self.reject("未找到", 404)
            return
        if not target.is_file():
            self.reject("资源不存在", 404)
            return
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            mime = "text/javascript"
        self.send_bytes(target.read_bytes(), mime + "; charset=utf-8")

    def do_GET(self):
        if not self.check_host():
            return
        path = urlsplit(self.path).path
        try:
            if path == "/api/bootstrap":
                with database() as con:
                    sessions = [dict(row) for row in con.execute(
                        "SELECT * FROM sessions ORDER BY created_at DESC LIMIT 200"
                    )]
                    items = [dict(row) for row in con.execute(
                        "SELECT * FROM items ORDER BY updated_at DESC LIMIT 1000"
                    )]
                models, error = available_models()
                self.send_json({"token": self.server.csrf_token, "sessions": sessions,
                                "items": items, "models": models, "ollama_error": error})
            elif path.startswith("/api/sessions/") and path.endswith("/messages"):
                session_id = path.split("/")[3]
                with database() as con:
                    if not con.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone():
                        self.reject("会话不存在", 404)
                        return
                    messages = [dict(row) for row in con.execute(
                        "SELECT role,content,created_at FROM messages WHERE session_id=? ORDER BY id",
                        (session_id,)
                    )]
                self.send_json({"messages": messages})
            elif path == "/api/export":
                if self.headers.get("X-DMate-Local") != self.server.csrf_token:
                    self.reject("本机请求验证失败", 403)
                    return
                content = json.dumps(backup_payload(), ensure_ascii=False, indent=2).encode("utf-8")
                self.send_bytes(content, "application/json; charset=utf-8",
                                filename="dmate-offline-backup.json")
            elif path.startswith("/api/"):
                self.reject("未找到", 404)
            else:
                self.static_file(path)
        except (ValueError, sqlite3.DatabaseError) as exc:
            self.reject(str(exc))

    def do_POST(self):
        if not self.check_host():
            return
        path = urlsplit(self.path).path
        try:
            data = self.read_json()
            if path == "/api/sessions":
                title = str(data.get("title", "新对话")).strip()[:120] or "新对话"
                sid = uuid.uuid4().hex
                with database() as con:
                    con.execute("INSERT INTO sessions VALUES(?,?,?)", (sid, title, now()))
                self.send_json({"id": sid, "title": title}, 201)
            elif path == "/api/items":
                kind = data.get("kind")
                if kind not in ("note", "mistake"):
                    raise ValueError("类型只能是笔记或错题")
                title = str(data.get("title", "")).strip()[:120]
                body = str(data.get("content", "")).strip()[:10000]
                if not title or not body:
                    raise ValueError("标题和内容不能为空")
                iid = uuid.uuid4().hex
                with database() as con:
                    con.execute("INSERT INTO items VALUES(?,?,?,?,?,?)",
                                (iid, kind, title, body, "open", now()))
                self.send_json({"id": iid}, 201)
            elif path == "/api/graph":
                self.send_json(graph_analysis(data))
            elif path == "/api/import":
                if data.get("confirm_replace") is not True or not isinstance(data.get("backup"), dict):
                    raise ValueError("导入需要明确确认替换本地数据")
                restore_backup(data["backup"])
                self.send_json({"ok": True})
            elif path == "/api/chat":
                self.chat(data)
            else:
                self.reject("未找到", 404)
        except PermissionError as exc:
            self.reject(str(exc), 403)
        except (ValueError, json.JSONDecodeError, sqlite3.IntegrityError) as exc:
            self.reject(str(exc))
        except (OSError, http.client.HTTPException) as exc:
            self.reject("本地服务暂时不可用", 502)

    def do_PATCH(self):
        if not self.check_host():
            return
        try:
            data = self.read_json()
            path = urlsplit(self.path).path
            if not path.startswith("/api/items/"):
                return self.reject("未找到", 404)
            iid = path.split("/")[-1]
            title = str(data.get("title", "")).strip()[:120]
            body = str(data.get("content", "")).strip()[:10000]
            status = data.get("status", "open")
            if not title or not body or status not in ("open", "resolved"):
                raise ValueError("笔记内容或状态无效")
            with database() as con:
                cur = con.execute(
                    "UPDATE items SET title=?, content=?,status=?,updated_at=? WHERE id=?",
                    (title, body, status, now(), iid))
                if cur.rowcount == 0:
                    return self.reject("记录不存在", 404)
            self.send_json({"ok": True})
        except (ValueError, PermissionError) as exc:
            self.reject(str(exc), 403 if isinstance(exc, PermissionError) else 400)

    def do_DELETE(self):
        if not self.check_host():
            return
        if self.headers.get("X-DMate-Local") != self.server.csrf_token:
            return self.reject("本机请求验证失败", 403)
        path = urlsplit(self.path).path
        try:
            if path.startswith("/api/items/"):
                table, ident = "items", path.split("/")[-1]
            elif path.startswith("/api/sessions/"):
                table, ident = "sessions", path.split("/")[-1]
            else:
                return self.reject("未找到", 404)
            with database() as con:
                con.execute("DELETE FROM " + table + " WHERE id=?", (ident,))
            self.send_json({"ok": True})
        except sqlite3.DatabaseError:
            self.reject("数据库操作失败", 500)

    def push(self, value):
        raw = (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
        self.wfile.write(raw)
        self.wfile.flush()

    def chat(self, data):
        sid = data.get("session_id")
        text = data.get("message", "")
        model = data.get("model")
        if not isinstance(sid, str) or not isinstance(text, str) or not isinstance(model, str):
            raise ValueError("聊天参数无效")
        text = text.strip()
        if not text or len(text) > 6000:
            raise ValueError("请输入 1–6000 个字符")
        image = validate_image(data.get("image"))
        models, error = available_models()
        if error:
            return self.reject(error, 503)
        if model not in models:
            return self.reject("该模型未在本机安装；请先运行 ollama pull", 400)
        with database() as con:
            if not con.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone():
                return self.reject("会话不存在", 404)
            history = [dict(r) for r in con.execute(
                "SELECT role,content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 14",
                (sid,))]
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend({"role": m["role"], "content": m["content"][:8000]}
                        for m in reversed(history))
        user_message = {"role": "user", "content": text}
        if image:
            user_message["images"] = [image]
        messages.append(user_message)
        payload = json.dumps({
            "model": model, "messages": messages,
            "stream": True, "think": None,
            "options": {"num_ctx": 4096, "temperature": 0.25},
        }).encode("utf-8")
        local = http.client.HTTPConnection("127.0.0.1", ollama_port(), timeout=180)
        try:
            local.request("POST", "/api/chat", body=payload,
                          headers={"Content-Type": "application/json"})
            remote = local.getresponse()
            if remote.status != 200:
                reason = remote.read(8192).decode("utf-8", errors="replace")
                return self.reject("本地模型请求失败：" + reason[:300], 502)
            with database() as con:
                con.execute("INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
                            (sid, "user", text + ("\n[已发送图片（未保存原图）]" if image else ""), now()))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            answer = []
            completed = False
            for line in remote:
                if len(line) > 2 * 1024 * 1024:
                    raise ValueError("本地模型响应过大")
                if not line.strip():
                    continue
                event = json.loads(line)
                delta = (event.get("message") or {}).get("content", "")
                if isinstance(delta, str) and delta:
                    answer.append(delta)
                    if sum(map(len, answer)) > 50000:
                        raise ValueError("本次回答超出长度限制")
                    self.push({"type": "delta", "text": delta})
                if event.get("error"):
                    raise ValueError(str(event["error"])[:250])
                if event.get("done"):
                    completed = True
                    break
            if completed and "".join(answer).strip():
                with database() as con:
                    con.execute(
                        "INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
                        (sid, "assistant", "".join(answer), now()))
                self.push({"type": "done"})
            else:
                self.push({"type": "error", "message": "本地模型没有返回完整回答"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (OSError, ValueError, json.JSONDecodeError, http.client.HTTPException):
            try:
                self.push({"type": "error", "message": "本地推理中断；未保存不完整回答"})
            except OSError:
                pass
        finally:
            local.close()


def main():
    parser = argparse.ArgumentParser(description="DMate Offline - 本地学习工作台")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口必须为 1–65535")
    initialize()
    try:
        server = OfflineServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        parser.error("本地端口无法使用：" + str(exc))
    url = "http://127.0.0.1:%d" % server.server_port
    print("DMate Offline 已启动：" + url)
    print("学习数据目录：" + str(DATA_HOME))
    print("Ctrl+C 退出。首次使用请先安装 Ollama 并下载本地模型。")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
