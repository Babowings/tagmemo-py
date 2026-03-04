from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tagmemo.audit_logger import AuditLogger


def test_audit_logger_persists_jsonl_and_sqlite(tmp_path: Path):
    logger = AuditLogger(tmp_path)
    logger.initialize()

    logger.log_query_event(
        endpoint="/v1/memory/query",
        request_id="req-1",
        message="向量数据库",
        diary_name="VCP开发",
        history_size=1,
        use_rerank=True,
        memory_context="记忆片段",
        metrics={"result_count": 2, "latency_ms": 12.3},
        results=[{"score": 0.9, "content": "chunk-a"}],
        duration_ms=12.3,
        client_ip="127.0.0.1",
        user_agent="pytest",
        status="ok",
        error=None,
    )

    files = sorted(tmp_path.glob("audit-*.jsonl"))
    assert len(files) == 1

    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["request_id"] == "req-1"
    assert payload["metrics"]["result_count"] == 2

    db_path = tmp_path / "observability.sqlite"
    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT endpoint, request_id, message, result_count, duration_ms, status FROM query_events WHERE request_id = ?",
        ("req-1",),
    ).fetchone()
    conn.close()

    assert row == ("/v1/memory/query", "req-1", "向量数据库", 2, 12.3, "ok")


def test_audit_logger_query_recent(tmp_path: Path):
    logger = AuditLogger(tmp_path)
    logger.initialize()

    logger.log_query_event(
        endpoint="/v1/memory/query",
        request_id="req-older",
        message="a",
        diary_name=None,
        history_size=0,
        use_rerank=False,
        memory_context="",
        metrics={"result_count": 0, "latency_ms": 1},
        results=[],
        duration_ms=1,
        client_ip=None,
        user_agent=None,
        status="ok",
        error=None,
    )
    logger.log_query_event(
        endpoint="/v1/memory/delete",
        request_id="req-newer",
        message="",
        diary_name="DiaryA",
        history_size=0,
        use_rerank=False,
        memory_context="",
        metrics={"result_count": 0, "latency_ms": 2},
        results=[],
        duration_ms=2,
        client_ip=None,
        user_agent=None,
        status="ok",
        error=None,
    )

    rows = logger.query_recent(limit=1)
    assert len(rows) == 1
    assert rows[0]["request_id"] == "req-newer"
    assert rows[0]["endpoint"] == "/v1/memory/delete"
