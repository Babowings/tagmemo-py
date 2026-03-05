"""app.py — TagMemo 智能对话服务器，替代 app.js (369 行)。

提供 OpenAI 兼容的 Chat Completions API，自动注入 TagMemo 记忆上下文。

工作流程：
  1. 接收 /v1/chat/completions 请求
  2. 从对话中提取最近用户消息
  3. 调用 TagMemoEngine 检索相关记忆
  4. 将记忆注入 system prompt
  5. 转发给上游 Chat LLM
  6. 返回 LLM 响应

用法：
  python app.py             — 启动 HTTP 服务
  python app.py --cli       — 交互式命令行模式
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import uuid
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import sqlite3
import sys
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from tagmemo.audit_logger import AuditLogger
from tagmemo.engine import TagMemoEngine
from tagmemo.vcp_compat import (
    VCPPlaceholderProcessor,
    build_tool_payload_for_rag,
    extract_ai_text_from_response_payload,
    extract_daily_note_payload,
    parse_tool_requests,
    replace_variable_placeholders,
    write_daily_note,
)

# --------------- 环境变量 ---------------
_config_env = Path(__file__).resolve().parent / "config.env"
if _config_env.exists():
    load_dotenv(_config_env)

PORT = int(os.environ.get("PORT", "3100"))
CHAT_API_URL: str = os.environ.get("CHAT_API_URL", "")
CHAT_API_KEY: str = os.environ.get("CHAT_API_KEY") or os.environ.get("API_Key", "")
CHAT_MODEL: str = os.environ.get("CHAT_MODEL", "gpt-4o-mini")

_DEFAULT_SYSTEM_PROMPT = (
    "你是一个有记忆能力的智能助手。"
    "在回答时，请自然地参考以下记忆片段中的信息来丰富你的回答。"
    "如果记忆片段与当前话题无关，可以忽略它们。"
    '不要提及"记忆片段"或"检索"等技术实现细节。'
)
SYSTEM_PROMPT_TEMPLATE: str = os.environ.get("SYSTEM_PROMPT", "") or _DEFAULT_SYSTEM_PROMPT

MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB

logger = logging.getLogger("tagmemo.app")

LOG_DIR = Path(__file__).resolve().parent / "log"
LOG_DIR.mkdir(exist_ok=True)
BASE_DIR = Path(__file__).resolve().parent
WEB_ADMIN_DIR = BASE_DIR / "web" / "admin"
WEB_CHAT_DIR = BASE_DIR / "web" / "chat"
KB_DB_PATH = BASE_DIR / "VectorStore" / "knowledge_base.sqlite"

# --------------- Engine (全局单例) ---------------
engine = TagMemoEngine()
audit_logger = AuditLogger(LOG_DIR)
vcp_placeholder_processor = VCPPlaceholderProcessor(engine)

MAX_VCP_LOOP_NONSTREAM = int(os.environ.get("MAX_VCP_LOOP_NONSTREAM", "5"))
MAX_VCP_LOOP_STREAM = int(os.environ.get("MAX_VCP_LOOP_STREAM", "5"))
RAG_MEMO_REFRESH = os.environ.get("RAG_MEMO_REFRESH", "true").lower() == "true"
SSE_KEEPALIVE_SECONDS = float(os.environ.get("SSE_KEEPALIVE_SECONDS", "5"))


# =================================================================
# FastAPI lifespan（替代 Express listen + shutdown）
# =================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化引擎，关闭时优雅 shutdown。"""
    audit_logger.initialize()
    await engine.initialize()
    logger.info("TagMemo Server ready on http://localhost:%d", PORT)
    yield
    await engine.shutdown()


app = FastAPI(title="TagMemo", lifespan=lifespan)

if WEB_ADMIN_DIR.exists():
    app.mount("/admin/static", StaticFiles(directory=str(WEB_ADMIN_DIR)), name="admin-static")
if WEB_CHAT_DIR.exists():
    app.mount("/chat/static", StaticFiles(directory=str(WEB_CHAT_DIR)), name="chat-static")

# CORS（对应 app.use(cors())）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =================================================================
# 请求体大小限制中间件（替代 express.json({ limit: '10mb' })）
# =================================================================

@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"error": {"message": "Request body too large (max 10MB)"}},
        )
    return await call_next(request)


# =================================================================
# Routes
# =================================================================

@app.get("/status")
async def status():
    """Health check。"""
    return {
        "status": "ok",
        "engine": "ready" if engine.initialized else "initializing",
        "cache": engine.get_cache_stats(),
        "rerank": engine.get_rerank_status(),
        "uptime": time.monotonic(),
    }


@app.post("/v1/cache/clear")
async def cache_clear():
    """清空查询缓存。"""
    engine.clear_cache()
    return {"status": "ok", "message": "Query cache cleared"}


@app.post("/v1/params/reload")
async def params_reload():
    """手动重新加载 RAG 参数。"""
    try:
        await engine.reload_params()
        return {"status": "ok", "message": "RAG params reloaded"}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": {"message": str(exc)}})


@app.get("/admin")
async def admin_dashboard():
    if not WEB_ADMIN_DIR.exists():
        return JSONResponse(status_code=404, content={"error": {"message": "Admin UI not found"}})
    index_path = WEB_ADMIN_DIR / "index.html"
    if not index_path.exists():
        return JSONResponse(status_code=404, content={"error": {"message": "Admin index missing"}})
    return FileResponse(index_path)


@app.get("/chat")
async def chat_frontend():
    if not WEB_CHAT_DIR.exists():
        return JSONResponse(status_code=404, content={"error": {"message": "Chat UI not found"}})
    index_path = WEB_CHAT_DIR / "index.html"
    if not index_path.exists():
        return JSONResponse(status_code=404, content={"error": {"message": "Chat index missing"}})
    return FileResponse(index_path)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    return await _chat_completions_impl(request, force_show_vcp=False)


@app.post("/v1/chatvcp/completions")
async def chatvcp_completions(request: Request):
    return await _chat_completions_impl(request, force_show_vcp=True)


async def _chat_completions_impl(request: Request, force_show_vcp: bool):
    """OpenAI 兼容的 Chat Completions 端点。"""
    request_id = str(uuid.uuid4())
    start_ts = time.perf_counter()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Invalid JSON body"}},
        )

    messages = body.get("messages")
    if not isinstance(messages, list):
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "messages array is required"}},
        )

    # 提取最新用户消息
    last_user_idx = _find_last_index(messages, lambda m: m.get("role") == "user")
    if last_user_idx == -1:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "No user message found"}},
        )

    raw_content = messages[last_user_idx].get("content", "")
    if isinstance(raw_content, str):
        user_message = raw_content
    elif isinstance(raw_content, list):
        user_message = next(
            (p.get("text", "") for p in raw_content if p.get("type") == "text"), ""
        )
    else:
        user_message = ""

    conversation_history = [
        m for m in messages[:last_user_idx] if m.get("role") != "system"
    ]

    system_messages = [m for m in messages if m.get("role") == "system" and isinstance(m.get("content"), str)]
    if system_messages:
        preprocessed = []
        root_path = engine.config.get("root_path") or os.environ.get("KNOWLEDGEBASE_ROOT_PATH", "")
        for msg in messages:
            cloned = json.loads(json.dumps(msg))
            if cloned.get("role") == "system" and isinstance(cloned.get("content"), str):
                cloned["content"] = replace_variable_placeholders(cloned["content"], root_path)
            preprocessed.append(cloned)
        last_ai_before_user = _extract_last_assistant_before(preprocessed, last_user_idx)
        messages = await vcp_placeholder_processor.process_system_messages(
            preprocessed,
            user_content=user_message,
            ai_content=last_ai_before_user,
        )

    # TagMemo 记忆检索
    logger.info('[App] Query: "%s..."', user_message[:80])
    try:
        result = await engine.query(user_message, conversation_history)
    except Exception as exc:
        duration_ms = (time.perf_counter() - start_ts) * 1000
        await asyncio.to_thread(
            _audit_query_event,
            endpoint="/v1/chat/completions",
            request_id=request_id,
            message=user_message,
            diary_name=None,
            history=conversation_history,
            use_rerank=False,
            response_payload={"memory_context": "", "metrics": {}, "results": []},
            duration_ms=duration_ms,
            request=request,
            status="error",
            error=str(exc),
        )
        return JSONResponse(status_code=500, content={"error": {"message": str(exc)}})

    memory_context: str = result["memory_context"]
    metrics: dict = result["metrics"]

    duration_ms = (time.perf_counter() - start_ts) * 1000
    await asyncio.to_thread(
        _audit_query_event,
        endpoint="/v1/chat/completions",
        request_id=request_id,
        message=user_message,
        diary_name=None,
        history=conversation_history,
        use_rerank=False,
        response_payload=result,
        duration_ms=duration_ms,
        request=request,
        status="ok",
        error=None,
    )

    # 构建增强消息数组
    enhanced_messages = _build_enhanced_messages(messages, memory_context)

    model = body.get("model") or CHAT_MODEL
    stream = body.get("stream", False)

    # 构建上游请求体（排除已处理的字段）
    upstream_body = {
        k: v for k, v in body.items() if k not in ("messages",)
    }
    upstream_body["messages"] = enhanced_messages
    upstream_body["model"] = model
    upstream_body["stream"] = stream

    if CHAT_API_URL:
        if stream:
            return await _handle_stream_response(upstream_body, metrics, force_show_vcp=force_show_vcp)
        else:
            return await _handle_normal_response(upstream_body, metrics, force_show_vcp=force_show_vcp)
    else:
        # 调试模式：无上游 API，直接返回记忆检索结果
        return {
            "id": f"tagmemo-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "tagmemo-debug",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": (
                            "[TagMemo Debug Mode - No CHAT_API_URL configured]\n\n"
                            f"**Memory Context:**\n{memory_context}\n\n"
                            f"**Metrics:**\n```json\n{json.dumps(metrics, indent=2, ensure_ascii=False)}\n```"
                        ),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "tagmemo_metrics": metrics,
        }


@app.post("/v1/memory/query")
async def memory_query(request: Request):
    """直接查询 TagMemo 记忆（不调用 LLM）。"""
    request_id = str(uuid.uuid4())
    start_ts = time.perf_counter()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Invalid JSON body"}},
        )

    message = body.get("message")
    if not message:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "message is required"}},
        )

    history = body.get("history") or []
    diary_name = body.get("diaryName")
    use_rerank = bool(body.get("useRerank", False))

    try:
        result = await engine.query(
            message,
            history,
            {
                "diary_name": diary_name,
                "use_rerank": use_rerank,
            },
        )
        duration_ms = (time.perf_counter() - start_ts) * 1000
        await asyncio.to_thread(
            _audit_query_event,
            endpoint="/v1/memory/query",
            request_id=request_id,
            message=message,
            diary_name=diary_name,
            history=history,
            use_rerank=use_rerank,
            response_payload=result,
            duration_ms=duration_ms,
            request=request,
            status="ok",
            error=None,
        )
        return result
    except Exception as exc:
        duration_ms = (time.perf_counter() - start_ts) * 1000
        await asyncio.to_thread(
            _audit_query_event,
            endpoint="/v1/memory/query",
            request_id=request_id,
            message=message,
            diary_name=diary_name,
            history=history,
            use_rerank=use_rerank,
            response_payload={"memory_context": "", "metrics": {}, "results": []},
            duration_ms=duration_ms,
            request=request,
            status="error",
            error=str(exc),
        )
        return JSONResponse(status_code=500, content={"error": {"message": str(exc)}})


@app.post("/v1/human/tool")
async def human_tool(request: Request):
    raw_body = (await request.body()).decode("utf-8", errors="replace")
    if not raw_body.strip():
        return JSONResponse(status_code=400, content={"error": "Request body must be non-empty plain text."})

    tool_calls = parse_tool_requests(raw_body)
    if not tool_calls:
        return JSONResponse(status_code=400, content={"error": "Malformed request: Missing TOOL_REQUEST markers."})

    first = tool_calls[0]
    result = await _execute_compatible_tool(first["tool_name"], first.get("params") or {})
    return result


@app.post("/v1/memory/delete")
async def memory_delete(request: Request):
    """删除记忆数据（按路径或 diaryName）。"""
    request_id = str(uuid.uuid4())
    start_ts = time.perf_counter()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Invalid JSON body"}},
        )

    file_paths = body.get("paths")
    single_path = body.get("path")
    diary_name = body.get("diaryName")
    dry_run = bool(body.get("dryRun", False))
    cleanup_orphans = bool(body.get("cleanupOrphans", True))

    if file_paths is None:
        file_paths = []
    if isinstance(file_paths, str):
        file_paths = [file_paths]
    if single_path:
        file_paths = [*file_paths, single_path]
    if not isinstance(file_paths, list):
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "paths must be an array or string"}},
        )
    file_paths = [str(p) for p in file_paths if p]

    if not file_paths and not diary_name:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "path(s) or diaryName is required"}},
        )

    try:
        result = await engine.delete_memory(
            file_paths=file_paths,
            diary_name=diary_name,
            dry_run=dry_run,
            cleanup_orphans=cleanup_orphans,
        )
        payload = {
            "status": "ok",
            "mode": "dry-run" if dry_run else "delete",
            **result,
        }
        duration_ms = (time.perf_counter() - start_ts) * 1000
        metrics = {
            "result_count": int(payload.get("deleted_files", 0)),
            "deleted_chunks": int(payload.get("deleted_chunks", 0)),
            "deleted_tags": int(payload.get("deleted_tags", 0)),
        }
        await asyncio.to_thread(
            _audit_query_event,
            endpoint="/v1/memory/delete",
            request_id=request_id,
            message="",
            diary_name=diary_name,
            history=[],
            use_rerank=False,
            response_payload={
                "memory_context": "",
                "metrics": metrics,
                "results": payload.get("target_files", []),
            },
            duration_ms=duration_ms,
            request=request,
            status="ok",
            error=None,
        )
        return payload
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": {"message": str(exc)}})
    except Exception as exc:
        duration_ms = (time.perf_counter() - start_ts) * 1000
        await asyncio.to_thread(
            _audit_query_event,
            endpoint="/v1/memory/delete",
            request_id=request_id,
            message="",
            diary_name=diary_name,
            history=[],
            use_rerank=False,
            response_payload={"memory_context": "", "metrics": {}, "results": []},
            duration_ms=duration_ms,
            request=request,
            status="error",
            error=str(exc),
        )
        return JSONResponse(status_code=500, content={"error": {"message": str(exc)}})


@app.get("/v1/admin/overview")
async def admin_overview():
    kb_exists = KB_DB_PATH.exists()
    overview = {
        "knowledge_db": {
            "exists": kb_exists,
            "path": str(KB_DB_PATH),
            "files": 0,
            "chunks": 0,
            "tags": 0,
            "file_tags": 0,
            "diaries": 0,
        },
        "observability": {
            "path": str(audit_logger.db_path),
            "events": 0,
            "jsonl_files": len(audit_logger.list_jsonl_files()),
        },
    }

    if kb_exists:
        conn = sqlite3.connect(KB_DB_PATH)
        overview["knowledge_db"]["files"] = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        overview["knowledge_db"]["chunks"] = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        overview["knowledge_db"]["tags"] = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        overview["knowledge_db"]["file_tags"] = conn.execute("SELECT COUNT(*) FROM file_tags").fetchone()[0]
        overview["knowledge_db"]["diaries"] = conn.execute("SELECT COUNT(DISTINCT diary_name) FROM files").fetchone()[0]
        conn.close()

    obs_conn = sqlite3.connect(audit_logger.db_path)
    overview["observability"]["events"] = obs_conn.execute("SELECT COUNT(*) FROM query_events").fetchone()[0]
    obs_conn.close()

    return overview


@app.get("/v1/admin/logs/recent")
async def admin_logs_recent(limit: int = 200, endpoint: str | None = None, status: str | None = None):
    return {
        "items": audit_logger.query_recent(limit=max(1, min(limit, 1000)), endpoint=endpoint, status=status)
    }


@app.get("/v1/admin/logs/files")
async def admin_logs_files():
    return {"items": audit_logger.list_jsonl_files()}


@app.get("/v1/admin/logs/file/{file_name}")
async def admin_logs_file(file_name: str, limit: int = 200):
    return {"items": audit_logger.read_jsonl_file(file_name, limit=limit)}


@app.get("/v1/admin/db/tables")
async def admin_db_tables(source: str = "kb"):
    db_path = _resolve_db_path(source)
    if not db_path.exists():
        return {"tables": []}
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    conn.close()
    return {"tables": [r[0] for r in rows]}


@app.get("/v1/admin/db/table/{table}")
async def admin_db_table(
    table: str,
    source: str = "kb",
    page: int = 1,
    page_size: int = 50,
    search: str = "",
):
    db_path = _resolve_db_path(source)
    if not db_path.exists():
        return {"columns": [], "rows": [], "total": 0, "page": page, "page_size": page_size}

    try:
        table = _validate_table_name(table)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": {"message": str(exc)}})
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    offset = (page - 1) * page_size

    conn = sqlite3.connect(db_path)
    columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if not columns:
        conn.close()
        return JSONResponse(status_code=404, content={"error": {"message": "Table not found"}})

    where_clause = ""
    params: list = []
    if search:
        like_parts = [f"CAST({c} AS TEXT) LIKE ?" for c in columns]
        where_clause = f"WHERE {' OR '.join(like_parts)}"
        params.extend([f"%{search}%"] * len(columns))

    total = conn.execute(f"SELECT COUNT(*) FROM {table} {where_clause}", tuple(params)).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM {table} {where_clause} LIMIT ? OFFSET ?",
        tuple([*params, page_size, offset]),
    ).fetchall()
    conn.close()

    items = [
        {col: _json_safe_sql_value(val) for col, val in zip(columns, row)}
        for row in rows
    ]
    return {
        "columns": columns,
        "rows": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/v1/admin/diaries")
async def admin_diaries():
    if engine.knowledge_base is not None:
        engine.knowledge_base.reconcile_missing_files(dry_run=False)

    if not KB_DB_PATH.exists():
        return {"items": []}
    conn = sqlite3.connect(KB_DB_PATH)
    rows = conn.execute(
        """
        SELECT diary_name, COUNT(*) AS file_count, MIN(updated_at) AS first_seen, MAX(updated_at) AS last_seen
        FROM files
        GROUP BY diary_name
        ORDER BY file_count DESC, diary_name ASC
        """
    ).fetchall()
    conn.close()
    return {
        "items": [
            {
                "diary_name": r[0],
                "file_count": r[1],
                "first_seen": r[2],
                "last_seen": r[3],
            }
            for r in rows
        ]
    }


@app.get("/v1/admin/diaries/files")
async def admin_diary_files(diary_name: str):
    if not KB_DB_PATH.exists():
        return {"items": []}
    conn = sqlite3.connect(KB_DB_PATH)
    rows = conn.execute(
        "SELECT id, path, checksum, mtime, size, updated_at FROM files WHERE diary_name = ? ORDER BY updated_at DESC, path ASC",
        (diary_name,),
    ).fetchall()
    conn.close()
    return {
        "items": [
            {
                "id": r[0],
                "path": r[1],
                "checksum": r[2],
                "mtime": r[3],
                "size": r[4],
                "updated_at": r[5],
            }
            for r in rows
        ]
    }


@app.get("/v1/admin/diaries/content")
async def admin_diary_content(path: str):
    root = Path(engine.config.get("root_path") or os.environ.get("KNOWLEDGEBASE_ROOT_PATH", "")).resolve()
    target = (root / path).resolve()
    if not target.exists() or target.is_dir() or root not in target.parents:
        return JSONResponse(status_code=404, content={"error": {"message": "File not found"}})
    return {"path": path, "content": target.read_text(encoding="utf-8", errors="replace")}


@app.post("/v1/admin/memory/preview")
async def admin_memory_preview(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": {"message": "Invalid JSON body"}})

    message = body.get("message")
    if not message:
        return JSONResponse(status_code=400, content={"error": {"message": "message is required"}})

    result = await engine.query(
        message,
        body.get("history") or [],
        {
            "diary_name": body.get("diaryName"),
            "use_rerank": True,
        },
    )
    return result


def _resolve_db_path(source: str) -> Path:
    source_norm = (source or "kb").lower()
    if source_norm == "audit":
        return audit_logger.db_path
    return KB_DB_PATH


def _validate_table_name(table: str) -> str:
    if not table:
        raise ValueError("table is required")
    if not table.replace("_", "").isalnum():
        raise ValueError("Invalid table name")
    return table


def _json_safe_sql_value(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        preview = base64.b64encode(raw[:96]).decode("ascii")
        return {
            "_type": "blob",
            "size": len(raw),
            "preview_base64": preview,
        }
    return value


def _audit_query_event(
    *,
    endpoint: str,
    request_id: str,
    message: str,
    diary_name: str | None,
    history: list,
    use_rerank: bool,
    response_payload: dict,
    duration_ms: float,
    request: Request,
    status: str,
    error: str | None,
) -> None:
    metrics = response_payload.get("metrics", {}) if isinstance(response_payload, dict) else {}
    results = response_payload.get("results", []) if isinstance(response_payload, dict) else []
    memory_context = response_payload.get("memory_context", "") if isinstance(response_payload, dict) else ""
    audit_logger.log_query_event(
        endpoint=endpoint,
        request_id=request_id,
        message=message,
        diary_name=diary_name,
        history_size=len(history or []),
        use_rerank=use_rerank,
        memory_context=memory_context,
        metrics=metrics,
        results=results,
        duration_ms=duration_ms,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", ""),
        status=status,
        error=error,
    )


# =================================================================
# Upstream Proxy
# =================================================================

async def _handle_normal_response(body: dict, tagmemo_metrics: dict, *, force_show_vcp: bool = False):
    """非流式转发：向上游 Chat API 发送请求并返回 JSON 响应。"""
    current_messages = json.loads(json.dumps(body.get("messages") or []))
    latest_data: dict | None = None
    vcp_history: list[str] = []

    for depth in range(MAX_VCP_LOOP_NONSTREAM + 1):
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                resp = await client.post(
                    CHAT_API_URL,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {CHAT_API_KEY}",
                    },
                    json={**body, "messages": current_messages, "stream": False},
                )
            except httpx.RequestError as exc:
                logger.error("[App] Upstream request failed: %s", exc)
                return JSONResponse(
                    status_code=502,
                    content={"error": {"message": f"Upstream connection error: {exc}"}},
                )

        if resp.status_code != 200:
            error_text = resp.text[:500]
            logger.error("[App] Upstream error %d: %s", resp.status_code, error_text[:200])
            return JSONResponse(
                status_code=resp.status_code,
                content={
                    "error": {
                        "message": f"Upstream API error: {resp.status_code}",
                        "detail": error_text,
                    }
                },
            )

        latest_data = resp.json()
        choices = latest_data.get("choices") or []
        assistant_content = ""
        if choices:
            assistant_content = ((choices[0].get("message") or {}).get("content")) or ""

        await _handle_diary_from_ai_response(assistant_content)
        vcp_history.append(assistant_content)
        tool_calls = parse_tool_requests(assistant_content)
        if not tool_calls or depth >= MAX_VCP_LOOP_NONSTREAM:
            break

        current_messages.append({"role": "assistant", "content": assistant_content})
        tool_outputs = []
        for tc in tool_calls:
            output = await _execute_compatible_tool(tc["tool_name"], tc.get("params") or {})
            tool_outputs.append({
                "tool_name": tc["tool_name"],
                "status": "success" if not output.get("error") else "error",
                "content": output,
            })

        if RAG_MEMO_REFRESH:
            current_messages = await vcp_placeholder_processor.refresh_rag_blocks_if_needed(
                current_messages,
                new_context={
                    "lastAiMessage": assistant_content,
                    "toolResultsText": build_tool_payload_for_rag(tool_outputs),
                },
            )

        tool_payload = f"<!-- VCP_TOOL_PAYLOAD -->\n{build_tool_payload_for_rag(tool_outputs)}"
        current_messages.append({"role": "user", "content": tool_payload})

        if force_show_vcp:
            vcp_history.append(f"\n[VCP_TOOL_RESULTS]\n{build_tool_payload_for_rag(tool_outputs)}")

    if latest_data is None:
        return JSONResponse(status_code=500, content={"error": {"message": "Upstream returned empty response"}})

    latest_data["tagmemo_metrics"] = tagmemo_metrics
    if force_show_vcp and latest_data.get("choices"):
        final_msg = latest_data["choices"][0].get("message") or {}
        final_content = final_msg.get("content") or ""
        final_msg["content"] = "".join(vcp_history[:-1]) + final_content
        latest_data["choices"][0]["message"] = final_msg
    return latest_data


def _build_sse_data(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\\n\\n".encode("utf-8")


def _build_sse_comment(comment: str) -> bytes:
    safe = (comment or "keepalive").replace("\n", " ").replace("\r", " ")
    return f": {safe}\\n\\n".encode("utf-8")


def _build_sse_text_chunk(text: str, *, finish_reason=None) -> bytes:
    payload = {
        "id": f"chatcmpl-vcp-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": {"content": text},
                "finish_reason": finish_reason,
            }
        ],
    }
    return _build_sse_data(payload)


async def _handle_stream_response(body: dict, tagmemo_metrics: dict, *, force_show_vcp: bool = False):
    """流式转发 + VCP 工具循环（对齐 streamHandler.js 核心行为）。"""
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-TagMemo-Metrics": json.dumps(tagmemo_metrics, ensure_ascii=True),
    }

    async def _stream_generator():
        current_messages = json.loads(json.dumps(body.get("messages") or []))
        request_template = {k: v for k, v in body.items() if k != "messages"}

        async with httpx.AsyncClient(timeout=120.0) as client:
            for depth in range(MAX_VCP_LOOP_STREAM + 1):
                try:
                    req = client.build_request(
                        "POST",
                        CHAT_API_URL,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {CHAT_API_KEY}",
                        },
                        json={**request_template, "messages": current_messages, "stream": True},
                    )
                    resp = await client.send(req, stream=True)
                except httpx.RequestError as exc:
                    logger.error("[App] Upstream stream request failed: %s", exc)
                    payload = {"error": {"message": f"Upstream connection error: {exc}"}}
                    yield _build_sse_data(payload)
                    break

                if resp.status_code != 200:
                    error_text = (await resp.aread()).decode(errors="replace")[:500]
                    await resp.aclose()
                    payload = {
                        "error": {
                            "message": f"Upstream API error: {resp.status_code}",
                            "detail": error_text,
                        }
                    }
                    yield _build_sse_data(payload)
                    break

                assistant_content_parts: list[str] = []
                raw_text_parts: list[str] = []
                line_buffer = ""

                try:
                    stream_iter = resp.aiter_bytes().__aiter__()
                    while True:
                        try:
                            chunk = await asyncio.wait_for(stream_iter.__anext__(), timeout=SSE_KEEPALIVE_SECONDS)
                        except asyncio.TimeoutError:
                            yield _build_sse_comment("vcp-keepalive")
                            continue
                        except StopAsyncIteration:
                            break

                        chunk_text = chunk.decode("utf-8", errors="replace")
                        raw_text_parts.append(chunk_text)
                        line_buffer += chunk_text

                        while "\n" in line_buffer:
                            line, line_buffer = line_buffer.split("\n", 1)
                            line = line.rstrip("\r")

                            if line.startswith("data: "):
                                payload_text = line[6:].strip()
                                if payload_text == "[DONE]":
                                    continue
                                try:
                                    obj = json.loads(payload_text)
                                    delta = ((obj.get("choices") or [{}])[0].get("delta") or {})
                                    msg = ((obj.get("choices") or [{}])[0].get("message") or {})
                                    content_piece = delta.get("content") or msg.get("content") or ""
                                    if content_piece:
                                        assistant_content_parts.append(content_piece)
                                except Exception:
                                    pass

                            yield (line + "\n").encode("utf-8")

                    if line_buffer:
                        line = line_buffer.rstrip("\r")
                        if line.startswith("data: "):
                            payload_text = line[6:].strip()
                            if payload_text and payload_text != "[DONE]":
                                try:
                                    obj = json.loads(payload_text)
                                    delta = ((obj.get("choices") or [{}])[0].get("delta") or {})
                                    msg = ((obj.get("choices") or [{}])[0].get("message") or {})
                                    content_piece = delta.get("content") or msg.get("content") or ""
                                    if content_piece:
                                        assistant_content_parts.append(content_piece)
                                except Exception:
                                    pass
                        yield (line + "\n").encode("utf-8")
                finally:
                    await resp.aclose()

                raw_text = "".join(raw_text_parts)
                assistant_content = "".join(assistant_content_parts)
                try:
                    await _handle_diary_from_ai_response(raw_text)
                except Exception as exc:
                    logger.warning("[App] Failed to handle diary from stream response: %s", exc)

                tool_calls = parse_tool_requests(assistant_content)
                if not tool_calls or depth >= MAX_VCP_LOOP_STREAM:
                    break

                current_messages.append({"role": "assistant", "content": assistant_content})
                tool_outputs = []
                for tc in tool_calls:
                    if force_show_vcp:
                        yield _build_sse_text_chunk(f"\n🔍 正在执行工具: {tc['tool_name']}\n")

                    tool_task = asyncio.create_task(_execute_compatible_tool(tc["tool_name"], tc.get("params") or {}))
                    while not tool_task.done():
                        try:
                            await asyncio.wait_for(asyncio.shield(tool_task), timeout=SSE_KEEPALIVE_SECONDS)
                        except asyncio.TimeoutError:
                            yield _build_sse_comment("vcp-keepalive")
                    output = await tool_task
                    tool_outputs.append({
                        "tool_name": tc["tool_name"],
                        "status": "success" if not output.get("error") else "error",
                        "content": output,
                    })

                if RAG_MEMO_REFRESH:
                    current_messages = await vcp_placeholder_processor.refresh_rag_blocks_if_needed(
                        current_messages,
                        new_context={
                            "lastAiMessage": assistant_content,
                            "toolResultsText": build_tool_payload_for_rag(tool_outputs),
                        },
                    )

                tool_payload_text = build_tool_payload_for_rag(tool_outputs)
                if force_show_vcp:
                    yield _build_sse_text_chunk(f"\n[VCP_TOOL_RESULTS]\n{tool_payload_text}\n")

                tool_payload = f"<!-- VCP_TOOL_PAYLOAD -->\n{tool_payload_text}"
                current_messages.append({"role": "user", "content": tool_payload})

                yield _build_sse_text_chunk("\n")

            yield b"data: [DONE]\n\n"

    return StreamingResponse(
        _stream_generator(),
        media_type="text/event-stream",
        headers=headers,
    )


# =================================================================
# Message Builder
# =================================================================

def _build_enhanced_messages(
    original_messages: list[dict], memory_context: str
) -> list[dict]:
    """将记忆上下文注入 system prompt。1:1 对应原 buildEnhancedMessages。"""
    enhanced = json.loads(json.dumps(original_messages))  # deep copy

    if not memory_context or memory_context == "没有找到相关的记忆片段。":
        return enhanced

    memory_block = (
        f"\n\n--- 以下是与当前对话相关的记忆信息 ---\n"
        f"{memory_context}\n"
        f"--- 记忆信息结束 ---"
    )

    system_idx = next(
        (i for i, m in enumerate(enhanced) if m.get("role") == "system"), -1
    )

    if system_idx >= 0:
        enhanced[system_idx]["content"] += memory_block
    else:
        enhanced.insert(0, {
            "role": "system",
            "content": SYSTEM_PROMPT_TEMPLATE + memory_block,
        })

    return enhanced


# =================================================================
# Helpers
# =================================================================

def _find_last_index(arr: list, predicate) -> int:
    """Python 无内置 findLastIndex，手动实现。"""
    for i in range(len(arr) - 1, -1, -1):
        if predicate(arr[i]):
            return i
    return -1


def _extract_last_assistant_before(messages: list[dict], idx: int) -> str:
    for i in range(idx - 1, -1, -1):
        m = messages[i]
        if m.get("role") == "assistant":
            content = m.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return next((p.get("text", "") for p in content if p.get("type") == "text"), "")
    return ""


async def _handle_diary_from_ai_response(response_text: str) -> None:
    ai_text = extract_ai_text_from_response_payload(response_text)
    payload = extract_daily_note_payload(ai_text)
    if not payload:
        return

    root_path = engine.config.get("root_path") or os.environ.get("KNOWLEDGEBASE_ROOT_PATH", "")
    if not root_path:
        return

    target = await asyncio.to_thread(
        write_daily_note,
        root_path,
        payload["maid_name"],
        payload["date_string"],
        payload["content_text"],
    )
    logger.info("[DailyNote] Saved %s", str(target))

    if engine.knowledge_base is not None:
        try:
            engine.knowledge_base._on_file_event(str(target))
        except Exception as exc:
            logger.warning("[DailyNote] Queue ingestion failed: %s", exc)


async def _execute_compatible_tool(tool_name: str, params: dict[str, str]) -> dict:
    name = (tool_name or "").strip().lower()
    try:
        if name in {"tagmemomemoryquery", "memoryquery", "tagmemo_query", "tagmemo.memory.query"}:
            message = params.get("message") or params.get("query") or ""
            history = []
            result = await engine.query(
                message,
                history,
                {
                    "diary_name": params.get("diaryName") or params.get("diary_name") or None,
                    "use_rerank": str(params.get("useRerank", "false")).lower() == "true",
                },
            )
            return {"status": "success", "result": result}

        if name in {"tagmemomemorydelete", "memorydelete", "tagmemo_delete", "tagmemo.memory.delete"}:
            paths_raw = params.get("paths") or params.get("path") or ""
            if paths_raw.strip().startswith("["):
                try:
                    parsed = json.loads(paths_raw)
                    file_paths = [str(x) for x in parsed if x]
                except Exception:
                    file_paths = [p.strip() for p in paths_raw.split(",") if p.strip()]
            else:
                file_paths = [p.strip() for p in paths_raw.split(",") if p.strip()]
            result = await engine.delete_memory(
                file_paths=file_paths,
                diary_name=params.get("diaryName") or params.get("diary_name") or None,
                dry_run=str(params.get("dryRun", "false")).lower() == "true",
                cleanup_orphans=True,
            )
            return {"status": "success", "result": result}

        return {
            "error": "ToolNotSupported",
            "details": f"Unsupported tool_name: {tool_name}",
        }
    except Exception as exc:
        return {
            "error": "ToolExecutionError",
            "details": str(exc),
            "trace": traceback.format_exc(limit=2),
        }


# =================================================================
# CLI Mode
# =================================================================

async def run_cli() -> None:
    """交互式命令行模式，替代原 runCLI()。"""
    print("\nTagMemo Interactive Chat")
    print("─" * 50)
    print("Type your message and press Enter.")
    print("Commands: /status, /clear, /quit\n")

    await engine.initialize()
    history: list[dict] = []

    while True:
        try:
            user_input = await asyncio.to_thread(input, "\nYou: ")
        except (EOFError, KeyboardInterrupt):
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input in ("/quit", "/exit"):
            print("Bye!")
            break

        if user_input == "/clear":
            history.clear()
            print("History cleared.")
            continue

        if user_input == "/status":
            print(json.dumps(
                {
                    "engine": engine.initialized,
                    "embedding": (
                        engine.embedding_service.get_stats()
                        if engine.embedding_service else None
                    ),
                    "history_length": len(history),
                },
                indent=2,
                ensure_ascii=False,
            ))
            continue

        try:
            result = await engine.query(user_input, history)
            memory_context = result["memory_context"]
            metrics = result["metrics"]

            print(
                f"\nMetrics: K={metrics.get('k')}, "
                f"TagWeight={metrics.get('tag_weight', 0):.3f}, "
                f"Results={metrics.get('result_count')}, "
                f"{metrics.get('latency_ms', 0):.0f}ms"
            )
            core_tags = metrics.get("core_tags")
            if core_tags:
                print(f"Tags: {', '.join(core_tags)}")

            if CHAT_API_URL:
                cli_messages = _build_enhanced_messages(
                    [
                        {"role": "system", "content": SYSTEM_PROMPT_TEMPLATE},
                        *history,
                        {"role": "user", "content": user_input},
                    ],
                    memory_context,
                )

                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(
                        CHAT_API_URL,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {CHAT_API_KEY}",
                        },
                        json={"model": CHAT_MODEL, "messages": cli_messages},
                    )

                if resp.status_code == 200:
                    data = resp.json()
                    reply = (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "(empty response)")
                    )
                    print(f"\nAI: {reply}")
                    history.append({"role": "user", "content": user_input})
                    history.append({"role": "assistant", "content": reply})
                else:
                    print(f"\nLLM Error: {resp.status_code}")
            else:
                print(f"\nMemory:\n{memory_context}")
                history.append({"role": "user", "content": user_input})

        except Exception as exc:
            print(f"\nError: {exc}")

    await engine.shutdown()


# =================================================================
# Entry Point
# =================================================================

def _configure_app_logging() -> None:
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-5s %(name)s [%(threadName)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    app_file = RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=20 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    app_file.setFormatter(formatter)
    root.addHandler(app_file)

    error_file = RotatingFileHandler(
        LOG_DIR / "error.log",
        maxBytes=20 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    error_file.setLevel(logging.ERROR)
    error_file.setFormatter(formatter)
    root.addHandler(error_file)


def main() -> None:
    """入口：--cli 进入交互模式，否则启动 HTTP 服务。"""
    parser = argparse.ArgumentParser(description="TagMemo Server")
    parser.add_argument("--cli", action="store_true", help="Run interactive CLI mode")
    parser.add_argument("--port", type=int, default=PORT, help=f"HTTP port (default: {PORT})")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    args = parser.parse_args()

    _configure_app_logging()

    if args.cli:
        asyncio.run(run_cli())
    else:
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level="info",
        )


if __name__ == "__main__":
    main()
