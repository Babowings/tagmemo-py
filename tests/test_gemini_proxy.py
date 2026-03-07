from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from proxy.gemini import server


def test_gemini_contents_to_messages_maps_roles():
    body = {
        "contents": [
            {"role": "user", "parts": [{"text": "你好"}]},
            {"role": "model", "parts": [{"text": "之前回复"}]},
        ],
    }

    result = server.gemini_contents_to_messages(body)

    assert result[0] == {"role": "user", "content": "你好"}
    assert result[1] == {"role": "assistant", "content": "之前回复"}


def test_extract_query_and_history():
    message, history = server.extract_query_and_history(
        [
            {"role": "user", "content": "第一句"},
            {"role": "assistant", "content": "回复"},
            {"role": "user", "content": "最后问题"},
        ]
    )
    assert message == "最后问题"
    assert history == [
        {"role": "user", "content": "第一句"},
        {"role": "assistant", "content": "回复"},
    ]


def test_inject_memory_into_gemini_request_appends_system_instruction():
    body = {
        "contents": [{"role": "user", "parts": [{"text": "我的学历是什么？"}]}],
        "systemInstruction": {"parts": [{"text": "原始系统提示"}], "role": "user"},
    }
    result = server.inject_memory_into_gemini_request(body, "你是硕士在读。")
    system_parts = result["systemInstruction"]["parts"]
    assert system_parts[0]["text"] == "原始系统提示"
    assert "记忆信息" in system_parts[1]["text"]
    assert "你是硕士在读" in system_parts[1]["text"]


def test_sanitize_gemini_request_clamps_thinking_budget():
    payload = {
        "generationConfig": {
            "thinkingConfig": {
                "thinkingBudget": 128,
            }
        }
    }
    result = server.sanitize_gemini_request(payload)
    assert result["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 512


def test_generate_content_route_forwards_memory_enhanced_request(monkeypatch):
    captured = {}

    async def fake_memory_query(body):
        captured["memory_body"] = body
        return {"memory_context": "你是硕士在读。", "metrics": {}, "results": []}

    async def fake_forward(request, payload):
        captured["upstream_payload"] = payload
        class _Resp:
            status_code = 200
            headers = {"content-type": "application/json"}
            content = b'{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}'

            text = ""

        return _Resp()

    monkeypatch.setattr(server, "query_memory_from_tagmemo", fake_memory_query)
    monkeypatch.setattr(server, "forward_json_to_gemini", fake_forward)

    client = TestClient(server.app)
    resp = client.post(
        "/v1beta/models/gemini-2.5-flash-lite:generateContent",
        json={"contents": [{"role": "user", "parts": [{"text": "我的学历是什么？"}]}]},
    )

    assert resp.status_code == 200
    assert captured["memory_body"]["contents"][0]["parts"][0]["text"] == "我的学历是什么？"
    system_parts = captured["upstream_payload"]["systemInstruction"]["parts"]
    assert "你是硕士在读。" in system_parts[-1]["text"]


def test_stream_generate_content_route_streams_raw_upstream(monkeypatch):
    async def fake_memory_query(body):
        return {"memory_context": "命中的记忆", "metrics": {}, "results": []}

    async def fake_stream(request, payload):
        yield httpx.Response(200, request=httpx.Request("POST", "http://testserver/mock"))
        yield 'data: {"candidates":[{"content":{"parts":[{"text":"你"}]}}]}\n\n'.encode("utf-8")
        yield b'data: [DONE]\n\n'

    monkeypatch.setattr(server, "query_memory_from_tagmemo", fake_memory_query)
    monkeypatch.setattr(server, "stream_gemini_events", fake_stream)

    client = TestClient(server.app)
    resp = client.post(
        "/v1beta/models/gemini-2.5-flash-lite:streamGenerateContent?alt=sse",
        json={"contents": [{"role": "user", "parts": [{"text": "hello"}]}]},
    )

    assert resp.status_code == 200
    assert '"text":"你"' in resp.text
    assert 'data: [DONE]' in resp.text
