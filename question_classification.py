"""Durable, question-only labels, separate from each answer's evidence graph.

Only scoped fingerprints and catalog identifiers are retained. No question,
answer, evidence quotation or model response is written to this registry.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import unicodedata


VERSION = 1
_DIFFICULTIES = {"简单", "中等", "困难"}
_EMPTY_GRAPH = {"", "无", "无图形", "无图形信息", "none", "null", "[]", "{}"}


def canonical_question(text):
    """Normalize cosmetic spacing without merging lines or changing mathematics.

    NFC deliberately preserves superscripts, subscripts, case, punctuation and
    operators. Line boundaries can describe matrices or diagrams, so unlike
    a search index we must not remove them or join adjacent mathematical tokens.
    """
    value = unicodedata.normalize("NFC", str(text or "")).replace("\r\n", "\n").replace("\r", "\n").strip()
    if value.startswith("【当前指向题目】") and "【当前指向题目结束】" in value:
        value = value[len("【当前指向题目】"):].split("【当前指向题目结束】", 1)[0].strip()
    for marker in ("【题目文字】", "【题干与公式识别】"):
        if value.startswith(marker):
            value = value[len(marker):].split("【我的要求】", 1)[0].strip()
            # A graph's actual description is part of the problem identity;
            # only an explicitly empty graph section can match plain text.
            parts = re.split(r"[^\S\n]*【图形信息】|[^\S\n]*【图形结构识别】", value, maxsplit=1)
            value = parts[0].strip()
            if len(parts) == 2 and parts[1].strip().lower() not in _EMPTY_GRAPH:
                value += "\n【图形信息】\n" + parts[1].strip()
            break
    if value.startswith("【题目】"):
        value = value[len("【题目】"):].strip()
    parts = re.split(r"(?:^|\n)[^\S\n]*【图形信息】|(?:^|\n)[^\S\n]*【图形结构识别】", value, maxsplit=1)
    if len(parts) == 2:
        value = parts[0].strip()
        if parts[1].strip().lower() not in _EMPTY_GRAPH:
            value += "\n【图形信息】\n" + parts[1].strip()
    return "\n".join(re.sub(r"[^\S\n]+", " ", line).strip() for line in value.split("\n")).strip()


def _owner_scope():
    # Accounts are stable across browsers; guests remain isolated by the
    # existing HttpOnly browser owner. No account/browser identity is retained.
    from flask import current_app, g, has_request_context, request, session
    if has_request_context():
        principal = session.get("user_id")
        if type(principal) is int:
            secret = str(current_app.secret_key or "").encode()
            import hmac
            return hmac.new(secret, ("question-account:" + str(principal)).encode(), hashlib.sha256).hexdigest()
        token = request.cookies.get("dm_graph_owner")
        if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{64}", token):
            import secrets
            token = getattr(g, "_graph_owner_cookie", None) or secrets.token_hex(32)
            g._graph_owner_cookie = token
        return hashlib.sha256((token + ":guest").encode()).hexdigest()
    return "standalone-local-classification"


def _path():
    configured = os.environ.get("DMATE_QUESTION_CLASSIFICATION_DB")
    return Path(configured) if configured else Path(__file__).with_name("instance") / "question-classifications.sqlite3"


def _validated_record(record, allowed):
    if not isinstance(record, dict) or record.get("version") != VERSION:
        return None
    nodes, focus = record.get("node_ids"), record.get("focus_node_ids")
    if (not isinstance(nodes, list) or not isinstance(focus, list)
            or any(not isinstance(value, str) or value not in allowed for value in nodes + focus)
            or len(nodes) != len(set(nodes)) or len(focus) != len(set(focus))
            or not set(focus).issubset(nodes) or record.get("difficulty") not in _DIFFICULTIES):
        return None
    return {"version": VERSION, "node_ids": sorted(nodes), "focus_node_ids": focus[:2],
            "difficulty": record["difficulty"]}


def question_classification(question, catalog, factory):
    """Return the insert-once projection for this exact normalized problem.

    The deterministic factory sees only the question. A semantic review, a
    different solution, a model change, a cache expiry or a late worker cannot
    overwrite a registered judgment. A changed catalog gets its own namespace.
    """
    canonical = canonical_question(question)
    by_id = {node["id"]: node for node in catalog}
    serialized_catalog = json.dumps(sorted((identifier, node["name"], node["category"])
        for identifier, node in by_id.items()), ensure_ascii=False, separators=(",", ":"))
    revision = hashlib.sha256(serialized_catalog.encode()).hexdigest()
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    scoped_digest = hashlib.sha256((_owner_scope() + ":" + digest).encode()).hexdigest()
    candidate = None

    def create():
        nonlocal candidate
        if candidate is None:
            candidate = _validated_record({"version": VERSION, **factory(canonical)}, by_id)
            if candidate is None:
                raise ValueError("Invalid question classification projection")
        return candidate

    path = _path()
    connection = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path), timeout=5)
        os.chmod(path, 0o600)
        with connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS question_classifications (
                question_key TEXT NOT NULL, catalog_revision TEXT NOT NULL,
                projection TEXT NOT NULL, PRIMARY KEY (question_key, catalog_revision))""")
            row = connection.execute("SELECT projection FROM question_classifications WHERE question_key=? AND catalog_revision=?",
                                     (scoped_digest, revision)).fetchone()
            record = _validated_record(json.loads(row[0]), by_id) if row else None
            if record is None:
                payload = json.dumps(create(), ensure_ascii=False, separators=(",", ":"))
                connection.execute("INSERT OR IGNORE INTO question_classifications VALUES (?, ?, ?)",
                                   (scoped_digest, revision, payload))
                row = connection.execute("SELECT projection FROM question_classifications WHERE question_key=? AND catalog_revision=?",
                                         (scoped_digest, revision)).fetchone()
                record = _validated_record(json.loads(row[0]), by_id) or create()
    except (OSError, sqlite3.Error, ValueError, TypeError):
        # Read-only deployments still give the same deterministic judgment;
        # persistence is an additional guarantee, never an inference fallback.
        record = create()
    finally:
        if connection is not None:
            connection.close()

    nodes = [by_id[identifier] for identifier in record["node_ids"]]
    counts = {node["category"]: sum(item["category"] == node["category"] for item in nodes) for node in nodes}
    categories = sorted(counts, key=lambda name: (-counts[name], name))
    primary = categories[0] if categories else "待识别"
    return {**record, "question": str(question or ""), "question_sha256": digest,
            "catalog_revision": revision, "category": primary, "related_categories": categories[1:],
            "knowledge_points": [node["name"] for node in nodes if node["category"] == primary],
            "related_knowledge_points": [node["name"] for node in nodes if node["category"] != primary],
            "focus_points": [by_id[identifier]["name"] for identifier in record["focus_node_ids"]],
            "classification_source": "question_snapshot", "classification_status": "fixed"}
