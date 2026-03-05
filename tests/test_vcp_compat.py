from __future__ import annotations

import pytest

from tagmemo.vcp_compat import (
    VCPPlaceholderProcessor,
    extract_daily_note_payload,
    parse_tool_requests,
)


class _DummyEmbedding:
    async def embed(self, text: str):
        return [1.0, 0.0, 0.0]


class _DummyKB:
    def get_diary_name_vector(self, diary_name: str):
        return [1.0, 0.0, 0.0]


class _DummyEngine:
    def __init__(self):
        self.embedding_service = _DummyEmbedding()
        self.knowledge_base = _DummyKB()

    async def query(self, user_message, history, options=None):
        diary = (options or {}).get("diary_name") or "unknown"
        return {
            "memory_context": f"[{diary}] {user_message}",
            "metrics": {},
            "results": [],
        }


def test_extract_daily_note_payload():
    payload = extract_daily_note_payload(
        """
        hello
        <<<DailyNoteStart>>>
        Maid: 小克
        Date: 2026-03-05
        Content: 今天完成了协议层补齐。
        <<<DailyNoteEnd>>>
        world
        """
    )
    assert payload is not None
    assert payload["maid_name"] == "小克"
    assert payload["date_string"] == "2026-03-05"
    assert "协议层" in payload["content_text"]


def test_parse_tool_requests():
    text = """
    <<<[TOOL_REQUEST]>>>
    tool_name:「始」TagMemoMemoryQuery「末」,
    message:「始」你好「末」
    <<<[END_TOOL_REQUEST]>>>
    """
    calls = parse_tool_requests(text)
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "TagMemoMemoryQuery"
    assert calls[0]["params"]["message"] == "你好"


@pytest.mark.asyncio
async def test_placeholder_processor_replaces_rag_and_aimemo():
    processor = VCPPlaceholderProcessor(_DummyEngine())
    messages = [
        {"role": "system", "content": "[[AIMemo=True]]\nA:[[知识日记本::AIMemo]]\nB:[[工作日记本::Rerank]]"},
        {"role": "user", "content": "总结一下"},
    ]
    out = await processor.process_system_messages(messages, user_content="总结一下", ai_content="")
    content = out[0]["content"]
    assert "AIMemo=True" not in content
    assert "VCP_RAG_BLOCK_START" in content
    assert "这是我获取的所有相关知识/记忆[[" in content
    assert "[工作]" in content
