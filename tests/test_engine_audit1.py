from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tagmemo.engine import TagMemoEngine
from tagmemo.knowledge_base import KnowledgeBaseManager


class _FakeEmbeddingService:
    async def embed(self, text: str):
        if "工作" in text and "生活" not in text:
            return [1.0, 0.0]
        if "生活" in text and "工作" not in text:
            return [0.0, 1.0]
        return [0.6, 0.4]


def _build_kb(tmp_path: Path) -> KnowledgeBaseManager:
    root = tmp_path / "data" / "dailynote"
    store = tmp_path / "VectorStore"
    root.mkdir(parents=True, exist_ok=True)
    store.mkdir(parents=True, exist_ok=True)

    kb = KnowledgeBaseManager(
        {
            "root_path": str(root),
            "store_path": str(store),
            "dimension": 2,
            "full_scan_on_startup": False,
        }
    )
    kb.db = sqlite3.connect(store / "knowledge_base.sqlite", check_same_thread=False)
    kb._init_schema()
    return kb


def test_build_and_save_cache_creates_enhanced_vectors(tmp_path: Path):
    engine = TagMemoEngine(
        {
            "root_path": str(tmp_path / "data" / "dailynote"),
            "store_path": str(tmp_path / "VectorStore"),
        }
    )
    engine.embedding_service = _FakeEmbeddingService()
    engine.rag_params = {
        "RAGDiaryPlugin": {
            "diary_tags": {
                "工作": {"tags": ["项目:2", "会议"]},
                "生活": {"tags": ["家庭", "运动:2"]},
            }
        }
    }

    cache_path = Path(engine.config["store_path"]) / "enhanced_vector_cache.json"

    import asyncio

    asyncio.run(engine._build_and_save_cache(cache_path=cache_path))

    assert engine.enhanced_vector_cache["工作"] == [1.0, 0.0]
    assert engine.enhanced_vector_cache["生活"] == [0.0, 1.0]
    disk_cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert set(disk_cache["vectors"].keys()) == {"工作", "生活"}


def test_engine_extracts_context_diary_prefixes_and_filters_duplicates() -> None:
    engine = TagMemoEngine()
    messages = [
        {
            "role": "assistant",
            "content": (
                "<<<[TOOL_REQUEST]>>>\n"
                "tool_name:「始」DailyNote「末」,\n"
                "command:「始」create「末」,\n"
                "content:「始」今天推进了记忆重构并补齐缓存逻辑。\n后续继续完善测试。」「末」\n"
                "<<<[END_TOOL_REQUEST]>>>"
            ),
        }
    ]
    prefixes = engine._extract_context_diary_prefixes(messages)

    assert prefixes

    filtered = engine._filter_context_duplicates(
        [
            {"text": "[2026-03-10] - 小克\n今天推进了记忆重构并补齐缓存逻辑。\n这是额外内容。", "score": 0.9},
            {"text": "另一条无关记忆", "score": 0.8},
        ],
        prefixes,
    )

    assert filtered == [{"text": "另一条无关记忆", "score": 0.8}]


def test_get_chunks_by_file_paths_returns_joined_chunk_rows(tmp_path: Path):
    kb = _build_kb(tmp_path)
    assert kb.db is not None
    kb.db.execute(
        "INSERT INTO files (id, path, diary_name, checksum, mtime, size, updated_at) VALUES (1, ?, 'DiaryA', 'c1', 1, 1, 123)",
        ("DiaryA/2026-03-10.md",),
    )
    kb.db.execute(
        "INSERT INTO chunks (id, file_id, content, chunk_index, vector) VALUES (101, 1, 'hello chunk', 0, ?)",
        (b"\x00\x00\x80?\x00\x00\x00@",),
    )
    kb.db.commit()

    rows = kb.get_chunks_by_file_paths(["DiaryA/2026-03-10.md"])

    assert len(rows) == 1
    assert rows[0]["id"] == 101
    assert rows[0]["text"] == "hello chunk"
    assert rows[0]["sourceFile"] == "DiaryA/2026-03-10.md"