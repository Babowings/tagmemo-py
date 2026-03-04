from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class AuditLogger:
    """Structured audit logger for memory/query/delete observability.

    Persists each event to:
    1) Daily JSONL file (append-only raw log)
    2) SQLite index DB for fast querying and dashboard usage
    """

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.log_dir / "observability.sqlite"
        self._lock = threading.Lock()
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS query_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    timestamp_iso TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    message TEXT,
                    diary_name TEXT,
                    history_size INTEGER NOT NULL DEFAULT 0,
                    use_rerank INTEGER NOT NULL DEFAULT 0,
                    memory_context TEXT,
                    metrics_json TEXT,
                    results_json TEXT,
                    result_count INTEGER NOT NULL DEFAULT 0,
                    search_vector_count INTEGER NOT NULL DEFAULT 0,
                    cache_hit INTEGER NOT NULL DEFAULT 0,
                    latency_ms REAL,
                    duration_ms REAL,
                    client_ip TEXT,
                    user_agent TEXT,
                    status TEXT NOT NULL,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_query_events_ts ON query_events(ts DESC);
                CREATE INDEX IF NOT EXISTS idx_query_events_endpoint ON query_events(endpoint);
                CREATE INDEX IF NOT EXISTS idx_query_events_request ON query_events(request_id);
                CREATE INDEX IF NOT EXISTS idx_query_events_status ON query_events(status);
                """
            )
            conn.commit()
            conn.close()
            self._initialized = True

    def _daily_jsonl_path(self, ts: float) -> Path:
        date_str = time.strftime("%Y%m%d", time.localtime(ts))
        return self.log_dir / f"audit-{date_str}.jsonl"

    @staticmethod
    def _json_dump(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    def log_query_event(
        self,
        *,
        endpoint: str,
        request_id: str,
        message: str | None,
        diary_name: str | None,
        history_size: int,
        use_rerank: bool,
        memory_context: str,
        metrics: dict | None,
        results: list | None,
        duration_ms: float,
        client_ip: str | None,
        user_agent: str | None,
        status: str,
        error: str | None,
    ) -> None:
        self.initialize()

        metrics = metrics or {}
        results = results or []
        ts = time.time()
        timestamp_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts))

        result_count = int(metrics.get("result_count", len(results) if isinstance(results, list) else 0) or 0)
        search_vector_count = int(metrics.get("search_vector_count", 0) or 0)
        cache_hit = 1 if bool(metrics.get("cache_hit", False)) else 0
        latency_ms = metrics.get("latency_ms")
        latency_ms_num = float(latency_ms) if isinstance(latency_ms, (int, float)) else None

        payload = {
            "ts": ts,
            "timestamp_iso": timestamp_iso,
            "endpoint": endpoint,
            "request_id": request_id,
            "message": message or "",
            "diary_name": diary_name,
            "history_size": int(history_size),
            "use_rerank": bool(use_rerank),
            "memory_context": memory_context,
            "metrics": metrics,
            "results": results,
            "result_count": result_count,
            "search_vector_count": search_vector_count,
            "cache_hit": bool(cache_hit),
            "latency_ms": latency_ms_num,
            "duration_ms": float(duration_ms),
            "client_ip": client_ip,
            "user_agent": user_agent,
            "status": status,
            "error": error,
        }

        jsonl_path = self._daily_jsonl_path(ts)
        with self._lock:
            with jsonl_path.open("a", encoding="utf-8") as f:
                f.write(self._json_dump(payload) + "\n")

            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """
                INSERT INTO query_events (
                    ts, timestamp_iso, endpoint, request_id, message, diary_name,
                    history_size, use_rerank, memory_context, metrics_json, results_json,
                    result_count, search_vector_count, cache_hit, latency_ms, duration_ms,
                    client_ip, user_agent, status, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    timestamp_iso,
                    endpoint,
                    request_id,
                    message or "",
                    diary_name,
                    int(history_size),
                    1 if use_rerank else 0,
                    memory_context,
                    self._json_dump(metrics),
                    self._json_dump(results),
                    result_count,
                    search_vector_count,
                    cache_hit,
                    latency_ms_num,
                    float(duration_ms),
                    client_ip,
                    user_agent,
                    status,
                    error,
                ),
            )
            conn.commit()
            conn.close()

    def query_recent(
        self,
        *,
        limit: int = 200,
        endpoint: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        self.initialize()
        clauses = []
        params: list[Any] = []

        if endpoint:
            clauses.append("endpoint = ?")
            params.append(endpoint)
        if status:
            clauses.append("status = ?")
            params.append(status)

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT id, ts, timestamp_iso, endpoint, request_id, message, diary_name, history_size, "
            "use_rerank, memory_context, metrics_json, results_json, result_count, search_vector_count, "
            "cache_hit, latency_ms, duration_ms, client_ip, user_agent, status, error "
            f"FROM query_events {where_clause} ORDER BY ts DESC LIMIT ?"
        )
        params.append(max(1, min(limit, 2000)))

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(sql, tuple(params)).fetchall()
        conn.close()

        parsed: list[dict] = []
        for r in rows:
            parsed.append(
                {
                    "id": r[0],
                    "ts": r[1],
                    "timestamp_iso": r[2],
                    "endpoint": r[3],
                    "request_id": r[4],
                    "message": r[5],
                    "diary_name": r[6],
                    "history_size": r[7],
                    "use_rerank": bool(r[8]),
                    "memory_context": r[9],
                    "metrics": json.loads(r[10] or "{}"),
                    "results": json.loads(r[11] or "[]"),
                    "result_count": r[12],
                    "search_vector_count": r[13],
                    "cache_hit": bool(r[14]),
                    "latency_ms": r[15],
                    "duration_ms": r[16],
                    "client_ip": r[17],
                    "user_agent": r[18],
                    "status": r[19],
                    "error": r[20],
                }
            )
        return parsed

    def list_jsonl_files(self) -> list[dict]:
        files = sorted(self.log_dir.glob("audit-*.jsonl"), reverse=True)
        result: list[dict] = []
        for fp in files:
            stat = fp.stat()
            result.append(
                {
                    "name": fp.name,
                    "size": stat.st_size,
                    "updated_at": stat.st_mtime,
                }
            )
        return result

    def read_jsonl_file(self, file_name: str, limit: int = 200) -> list[dict]:
        target = (self.log_dir / file_name).resolve()
        if not target.exists() or target.parent != self.log_dir.resolve():
            return []

        lines = target.read_text(encoding="utf-8").splitlines()
        selected = lines[-max(1, min(limit, 2000)):]
        result: list[dict] = []
        for line in selected:
            try:
                result.append(json.loads(line))
            except Exception:
                continue
        return result
