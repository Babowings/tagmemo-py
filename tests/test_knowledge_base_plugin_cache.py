from __future__ import annotations

import pytest

from tagmemo.knowledge_base import KnowledgeBaseManager


@pytest.mark.asyncio
async def test_get_plugin_description_vector_persists_and_reuses_cache(memory_db) -> None:
    manager = KnowledgeBaseManager({"dimension": 3})
    manager.db = memory_db
    embed_calls: list[str] = []

    async def embed(text: str) -> list[float] | None:
        embed_calls.append(text)
        return [1.0, 0.0, 0.0]

    first = await manager.get_plugin_description_vector("工作", embed)
    second = await manager.get_plugin_description_vector("工作", embed)

    row = memory_db.execute("SELECT key, vector FROM kv_store").fetchone()

    assert first == [1.0, 0.0, 0.0]
    assert second == [1.0, 0.0, 0.0]
    assert embed_calls == ["工作"]
    assert row is not None
    assert row[0].startswith("plugin_desc_hash:")
    assert row[1] is not None