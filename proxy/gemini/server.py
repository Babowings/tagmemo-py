from __future__ import annotations

import argparse
import json
import logging
import os
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger("proxy.gemini")
app = FastAPI(title="TagMemo Gemini Proxy")

TAGMEMO_BASE_URL = os.environ.get("TAGMEMO_BASE_URL", "http://127.0.0.1:3100").rstrip("/")
TAGMEMO_MEMORY_PATH = os.environ.get("TAGMEMO_MEMORY_PATH", "/v1/memory/query")
GEMINI_UPSTREAM_BASE_URL = os.environ.get("GEMINI_UPSTREAM_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/")
GEMINI_UPSTREAM_API_KEY = os.environ.get("GEMINI_UPSTREAM_API_KEY", "")
PROXY_TIMEOUT_SECONDS = float(os.environ.get("PROXY_TIMEOUT_SECONDS", "180"))


def _join_text_parts(parts: list[dict[str, Any]] | None) -> str:
    text_segments: list[str] = []
    for part in parts or []:
        if isinstance(part, dict) and part.get("text"):
            text_segments.append(str(part["text"]))
    return "\n".join(segment for segment in text_segments if segment).strip()


def _normalize_role(role: str | None) -> str:
    if role == "model":
        return "assistant"
    if role == "user":
        return "user"
    return "user"


def gemini_contents_to_messages(body: dict[str, Any]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    for item in body.get("contents") or []:
        if not isinstance(item, dict):
            continue
        text = _join_text_parts(item.get("parts"))
        if not text:
            continue
        messages.append({"role": _normalize_role(item.get("role")), "content": text})

    return messages


def extract_query_and_history(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    last_user_idx = -1
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx].get("role") == "user":
            last_user_idx = idx
            break

    if last_user_idx == -1:
        return "", messages
    return messages[last_user_idx].get("content", ""), messages[:last_user_idx]


def build_memory_block(memory_context: str) -> str:
    return (
        "--- 以下是与当前对话相关的记忆信息 ---\n"
        f"{memory_context}\n"
        "--- 记忆信息结束 ---"
    )


def inject_memory_into_gemini_request(body: dict[str, Any], memory_context: str) -> dict[str, Any]:
    cloned = json.loads(json.dumps(body))
    if not memory_context or memory_context == "没有找到相关的记忆片段。":
        return cloned

    memory_text = build_memory_block(memory_context)
    system_instruction = cloned.get("systemInstruction")

    if isinstance(system_instruction, dict):
        parts = system_instruction.get("parts")
        if not isinstance(parts, list):
            parts = []
        parts.append({"text": memory_text})
        system_instruction["parts"] = parts
        if not system_instruction.get("role"):
            system_instruction["role"] = "user"
        cloned["systemInstruction"] = system_instruction
    else:
        cloned["systemInstruction"] = {
            "role": "user",
            "parts": [{"text": memory_text}],
        }

    return cloned


def sanitize_gemini_request(payload: dict[str, Any]) -> dict[str, Any]:
    cloned = json.loads(json.dumps(payload))
    generation_config = cloned.get("generationConfig")
    if not isinstance(generation_config, dict):
        return cloned

    thinking_config = generation_config.get("thinkingConfig")
    if isinstance(thinking_config, dict):
        budget = thinking_config.get("thinkingBudget")
        if isinstance(budget, int):
            thinking_config["thinkingBudget"] = max(512, min(24576, budget))
        elif budget is not None:
            thinking_config.pop("thinkingBudget", None)
        generation_config["thinkingConfig"] = thinking_config

    cloned["generationConfig"] = generation_config
    return cloned


def build_upstream_path(request: Request) -> str:
    path = request.url.path
    if path.startswith("/chat/"):
        return path[5:]
    return path


def build_gemini_upstream_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    hop_by_hop = {"host", "content-length", "connection"}
    for key, value in request.headers.items():
        if key.lower() in hop_by_hop:
            continue
        headers[key] = value

    api_key = GEMINI_UPSTREAM_API_KEY or request.headers.get("x-goog-api-key", "")
    if api_key:
        headers["x-goog-api-key"] = api_key
    return headers


def _truncate_text(value: str, limit: int = 240) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "..."


def summarize_gemini_payload(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "top_level_keys": sorted(payload.keys()),
        "contents_count": len(payload.get("contents") or []),
    }

    contents_summary = []
    for item in payload.get("contents") or []:
        if not isinstance(item, dict):
            continue
        contents_summary.append({
            "role": item.get("role"),
            "parts_count": len(item.get("parts") or []),
            "text_preview": _truncate_text(_join_text_parts(item.get("parts"))),
        })
    summary["contents"] = contents_summary

    system_instruction = payload.get("systemInstruction") or {}
    if isinstance(system_instruction, dict):
        summary["system_instruction"] = {
            "role": system_instruction.get("role"),
            "parts_count": len(system_instruction.get("parts") or []),
            "text_preview": _truncate_text(_join_text_parts(system_instruction.get("parts"))),
        }

    generation_config = payload.get("generationConfig") or {}
    if isinstance(generation_config, dict):
        summary["generation_config_keys"] = sorted(generation_config.keys())
        summary["response_mime_type"] = generation_config.get("responseMimeType")

    return summary


async def query_memory_from_tagmemo(body: dict[str, Any]) -> dict[str, Any]:
    messages = gemini_contents_to_messages(body)
    message, history = extract_query_and_history(messages)
    if not message:
        return {"memory_context": "", "metrics": {}, "results": []}

    async with httpx.AsyncClient(timeout=PROXY_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{TAGMEMO_BASE_URL}{TAGMEMO_MEMORY_PATH}",
            json={"message": message, "history": history},
        )

    if response.status_code != 200:
        raise httpx.HTTPStatusError(
            f"TagMemo memory query failed with status {response.status_code}",
            request=response.request,
            response=response,
        )
    return response.json()


async def forward_json_to_gemini(request: Request, payload: dict[str, Any]) -> httpx.Response:
    upstream_path = build_upstream_path(request)
    upstream_url = f"{GEMINI_UPSTREAM_BASE_URL}{upstream_path}"
    headers = build_gemini_upstream_headers(request)
    logger.info("[GeminiProxy] Forwarding JSON request to %s with payload summary: %s", upstream_url, json.dumps(summarize_gemini_payload(payload), ensure_ascii=False))
    async with httpx.AsyncClient(timeout=PROXY_TIMEOUT_SECONDS) as client:
        response = await client.post(upstream_url, params=request.query_params, headers=headers, json=payload)
    if response.status_code >= 400:
        logger.error("[GeminiProxy] Gemini upstream error %s: %s", response.status_code, _truncate_text(response.text, 1200))
    return response


async def stream_gemini_events(request: Request, payload: dict[str, Any]):
    upstream_path = build_upstream_path(request)
    upstream_url = f"{GEMINI_UPSTREAM_BASE_URL}{upstream_path}"
    headers = build_gemini_upstream_headers(request)
    logger.info("[GeminiProxy] Forwarding stream request to %s with payload summary: %s", upstream_url, json.dumps(summarize_gemini_payload(payload), ensure_ascii=False))
    async with httpx.AsyncClient(timeout=PROXY_TIMEOUT_SECONDS) as client:
        upstream_request = client.build_request(
            "POST",
            upstream_url,
            params=request.query_params,
            headers=headers,
            json=payload,
        )
        response = await client.send(upstream_request, stream=True)
        try:
            if response.status_code >= 400:
                error_text = (await response.aread()).decode("utf-8", errors="replace")
                logger.error("[GeminiProxy] Gemini upstream stream error %s: %s", response.status_code, _truncate_text(error_text, 1200))
                yield httpx.Response(response.status_code, headers=response.headers, request=response.request, content=error_text.encode("utf-8", errors="replace"))
                return
            yield response
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()


async def _handle_generate_content(request: Request, model_name: str):
    body = await request.json()
    try:
        memory_result = await query_memory_from_tagmemo(body)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:1000] if exc.response is not None else str(exc)
        return JSONResponse(status_code=502, content={"detail": detail})

    memory_context = memory_result.get("memory_context", "")
    logger.info("[GeminiProxy] Memory query done. context_length=%d results=%d", len(memory_context), len(memory_result.get("results") or []))
    payload = inject_memory_into_gemini_request(body, memory_context)
    payload = sanitize_gemini_request(payload)
    response = await forward_json_to_gemini(request, payload)

    if response.status_code != 200:
        detail = response.text[:1000]
        return JSONResponse(status_code=response.status_code, content={"detail": detail})

    content_type = response.headers.get("content-type", "application/json")
    return Response(content=response.content, status_code=response.status_code, media_type=content_type)


async def _handle_stream_generate_content(request: Request, model_name: str):
    body = await request.json()
    try:
        memory_result = await query_memory_from_tagmemo(body)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:1000] if exc.response is not None else str(exc)
        return JSONResponse(status_code=502, content={"detail": detail})

    memory_context = memory_result.get("memory_context", "")
    logger.info("[GeminiProxy] Memory query done. context_length=%d results=%d", len(memory_context), len(memory_result.get("results") or []))
    payload = inject_memory_into_gemini_request(body, memory_context)
    payload = sanitize_gemini_request(payload)

    async def _generator():
        response: httpx.Response | None = None
        async for item in stream_gemini_events(request, payload):
            if isinstance(item, httpx.Response):
                response = item
                if response.status_code != 200:
                    error_text = (await response.aread()).decode("utf-8", errors="replace")[:1000]
                    yield error_text.encode("utf-8", errors="replace")
                    return
                continue
            yield item

    return StreamingResponse(_generator(), media_type="text/event-stream")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "gemini-proxy",
        "tagmemo_base_url": TAGMEMO_BASE_URL,
        "tagmemo_memory_path": TAGMEMO_MEMORY_PATH,
        "gemini_upstream_base_url": GEMINI_UPSTREAM_BASE_URL,
    }


@app.post("/v1beta/models/{model_name}:generateContent")
async def generate_content(request: Request, model_name: str):
    return await _handle_generate_content(request, model_name)


@app.post("/chat/v1beta/models/{model_name}:generateContent")
async def generate_content_chat_prefix(request: Request, model_name: str):
    return await _handle_generate_content(request, model_name)


@app.post("/v1beta/models/{model_name}:streamGenerateContent")
async def stream_generate_content(request: Request, model_name: str):
    return await _handle_stream_generate_content(request, model_name)


@app.post("/chat/v1beta/models/{model_name}:streamGenerateContent")
async def stream_generate_content_chat_prefix(request: Request, model_name: str):
    return await _handle_stream_generate_content(request, model_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini-to-TagMemo proxy")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3102)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
