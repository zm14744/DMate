"""Bounded source-bound OCR receipts shared by workers, without original images."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time


class OcrTaskConflict(ValueError):
    pass


class OcrTaskCapacity(RuntimeError):
    pass


class OcrTaskRegistry:
    def __init__(self, path=None, *, clock=time.time, lease_seconds=360,
                 ttl_seconds=7 * 24 * 3600, capacity=128, max_bytes=16 * 1024 * 1024):
        self.path, self.clock = path, clock
        self.lease_seconds, self.ttl_seconds = lease_seconds, ttl_seconds
        self.capacity, self.max_bytes = capacity, max_bytes

    @contextmanager
    def connection(self, *, write=False):
        path = Path(self.path or os.environ.get('DMATE_OCR_TASK_DB')
                    or Path(tempfile.gettempdir()) / 'dmate-ocr-task-receipts.sqlite3')
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(path), timeout=5, isolation_level=None)
        try:
            os.chmod(path, 0o600)
            db.execute('''CREATE TABLE IF NOT EXISTS ocr_tasks (
                owner TEXT NOT NULL, request_id TEXT NOT NULL, source_sha256 TEXT NOT NULL,
                status TEXT NOT NULL, lease_token TEXT, lease_until REAL NOT NULL,
                expires REAL NOT NULL, updated REAL NOT NULL,
                result_json TEXT, http_status INTEGER,
                PRIMARY KEY(owner, request_id))''')
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write:
                db.commit()
        except Exception:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def _trim(self, db, *, reserve=0, protected=None):
        now = self.clock()
        db.execute('DELETE FROM ocr_tasks WHERE expires <= ?', (now,))
        db.execute("""DELETE FROM ocr_tasks WHERE status='processing' AND lease_until<=?
            AND NOT (owner=? AND request_id=?)""", (now, *(protected or ('', ''))))
        while True:
            count, size = db.execute('SELECT COUNT(*),COALESCE(SUM(LENGTH(CAST(result_json AS BLOB))),0) FROM ocr_tasks').fetchone()
            if count + reserve <= self.capacity and size <= self.max_bytes:
                return
            row = db.execute('''SELECT owner,request_id FROM ocr_tasks
                WHERE status != 'processing' AND NOT (owner=? AND request_id=?)
                ORDER BY updated,owner,request_id LIMIT 1''', protected or ('', '')).fetchone()
            if row is None:
                if count + reserve > self.capacity:
                    raise OcrTaskCapacity('ocr_task_capacity')
                return
            db.execute('DELETE FROM ocr_tasks WHERE owner=? AND request_id=?', row)

    @staticmethod
    def _receipt(request_id, sha, row):
        value = {'request_id': request_id, 'source_sha256': sha, 'status': row[1]}
        if row[1] == 'processing':
            value['retry_after'] = 2
        else:
            value.update(result=json.loads(row[4]), http_status=row[5])
        return value

    def get(self, owner, request_id, source_sha256):
        with self.connection() as db:
            row = db.execute('''SELECT source_sha256,status,lease_until,expires,result_json,http_status
                FROM ocr_tasks WHERE owner=? AND request_id=?''', (owner, request_id)).fetchone()
        now = self.clock()
        if row is None or row[3] <= now:
            return {'request_id': request_id, 'source_sha256': source_sha256, 'status': 'missing'}
        if row[0] != source_sha256:
            raise OcrTaskConflict('task_source_mismatch')
        if row[1] == 'processing' and row[2] <= now:
            return {'request_id': request_id, 'source_sha256': source_sha256, 'status': 'missing'}
        return self._receipt(request_id, source_sha256, row)

    def claim(self, owner, request_id, source_sha256):
        now = self.clock()
        with self.connection(write=True) as db:
            self._trim(db, protected=(owner, request_id))
            row = db.execute('''SELECT source_sha256,status,lease_until,expires,result_json,http_status
                FROM ocr_tasks WHERE owner=? AND request_id=?''', (owner, request_id)).fetchone()
            if row is not None:
                if row[0] != source_sha256:
                    raise OcrTaskConflict('task_source_mismatch')
                if row[1] != 'processing' or row[2] > now:
                    return self._receipt(request_id, source_sha256, row)
            else:
                self._trim(db, reserve=1)
            token = secrets.token_hex(24)
            db.execute('''INSERT INTO ocr_tasks(owner,request_id,source_sha256,status,lease_token,
                lease_until,expires,updated) VALUES(?,?,?,'processing',?,?,?,?)
                ON CONFLICT(owner,request_id) DO UPDATE SET status='processing',lease_token=excluded.lease_token,
                lease_until=excluded.lease_until,expires=excluded.expires,updated=excluded.updated,
                result_json=NULL,http_status=NULL''',
                (owner, request_id, source_sha256, token, now + self.lease_seconds, now + self.ttl_seconds, now))
            return {'status': 'claimed', 'token': token}

    def finish(self, owner, request_id, token, result, http_status):
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        if len(encoded.encode()) > self.max_bytes:
            raise OcrTaskCapacity('ocr_result_too_large')
        status = ('cancelled' if result.get('cancelled') else
                  'failed' if http_status >= 400 or result.get('error')
                  or result.get('recognition_status') == 'failed' else 'completed')
        now = self.clock()
        with self.connection(write=True) as db:
            cursor = db.execute('''UPDATE ocr_tasks SET status=?,result_json=?,http_status=?,
                expires=?,updated=?,lease_until=0 WHERE owner=? AND request_id=?
                AND status='processing' AND lease_token=?''',
                (status, encoded, http_status, now + self.ttl_seconds, now, owner, request_id, token))
            self._trim(db, protected=(owner, request_id))
            return cursor.rowcount == 1

    def abandon(self, owner, request_id, token):
        with self.connection(write=True) as db:
            db.execute("DELETE FROM ocr_tasks WHERE owner=? AND request_id=? AND status='processing' AND lease_token=?",
                       (owner, request_id, token))


OCR_TASKS = OcrTaskRegistry()
