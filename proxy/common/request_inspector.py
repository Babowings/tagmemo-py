from __future__ import annotations

import argparse
import json
import logging
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("proxy.request_inspector")
app = FastAPI(title="Proxy Request Inspector")


def _mask_headers(headers: dict[str, str]) -> dict[str, str]:
    masked: dict[str, str] = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower in {"authorization", "x-goog-api-key", "proxy-authorization"}:
            masked[key] = "***masked***"
        else:
            masked[key] = value
    return masked


async def _read_body(request: Request) -> tuple[Any, str]:
    try:
        payload = await request.json()
        return payload, "json"
    except Exception:
        raw = await request.body()
        try:
            return raw.decode("utf-8", errors="replace"), "text"
        except Exception:
            return repr(raw), "binary"


@app.post("/{path:path}")
async def catch_all_post(path: str, request: Request):
    headers = _mask_headers(dict(request.headers))
    body, body_kind = await _read_body(request)

    logger.info("Detected POST request: /%s", path)
    logger.info("Headers: %s", json.dumps(headers, ensure_ascii=False, indent=2))
    if body_kind == "json":
        logger.info("Body(JSON): %s", json.dumps(body, ensure_ascii=False, indent=2))
    else:
        logger.info("Body(%s): %s", body_kind, body)

    print(f"检测到请求！路径是: /{path}")
    print(f"请求头: {json.dumps(headers, ensure_ascii=False)}")
    if body_kind == "json":
        print(f"请求体内容: {json.dumps(body, ensure_ascii=False)}")
    else:
        print(f"请求体不是 JSON 格式，原始内容: {body}")

    return JSONResponse(
        content={
            "message": "我收到了，但我还没转发给上游",
            "path": f"/{path}",
            "method": request.method,
            "body_kind": body_kind,
        }
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "request-inspector"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Catch-all request inspector for proxy debugging")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3101)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
