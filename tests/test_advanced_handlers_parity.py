from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from tagmemo.ai_memo import AIMemoHandler
from tagmemo.engine import TagMemoEngine
from tagmemo.meta_thinking import MetaThinkingManager


class _StubEmbeddingService:
    async def embed(self, text: str):
        return [1.0, 0.0, 0.0]


class _StubSemanticGroupManager:
    def detect_and_activate_groups(self, text: str):
        return {"GroupA": {"strength": 0.8}}

    async def get_enhanced_vector(self, original_query, activated_groups, precomputed_query_vector=None):
        return precomputed_query_vector

    @staticmethod
    def _weighted_average_vectors(vectors, weights):
        return vectors[0]


class _StubKnowledgeBase:
    def __init__(self):
        self.calls: list[tuple[str, list[float], int]] = []

    async def search(self, diary_name: str, vector: list[float], k: int):
        self.calls.append((diary_name, vector, k))
        return [{"text": f"{diary_name}-result", "score": 0.9, "vector": [1.0, 0.0, 0.0]}]

    def get_vector_by_text(self, diary_name: str, text: str):
        return [1.0, 0.0, 0.0]


class _StubEngine:
    def __init__(self):
        self.config = {"root_path": "", "timezone": "Asia/Shanghai", "query_cache_ttl": 3600, "query_cache_max_size": 200}
        self.embedding_service = _StubEmbeddingService()
        self.semantic_group_manager = _StubSemanticGroupManager()
        self.knowledge_base = _StubKnowledgeBase()
        self.query_cache: dict[str, dict] = {}
        self.ai_memo_cache_ttl = 1800000
        self.ai_memo_cache_max_size = 50
        self.push_payloads: list[dict] = []
        self.push_vcp_info = self.push_payloads.append

    def _generate_cache_key(self, user_text, ai_text, diary_name):
        return f"{user_text}|{ai_text}|{diary_name}"

    def _get_cached(self, key):
        entry = self.query_cache.get(key)
        if entry is None:
            return None
        return entry["value"]

    def _set_cache(self, key, value):
        self.query_cache[key] = {"value": value}

    @staticmethod
    def _cosine_similarity(vec_a, vec_b):
        return 0.9


class _ExplodingAIMemoHandler(AIMemoHandler):
    def is_configured(self) -> bool:
        return True

    async def _get_diary_files(self, db_name: str):
        raise RuntimeError("boom")


class _CountingMetaThinkingManager(MetaThinkingManager):
    def __init__(self, engine, config_path: Path, cache_path: Path) -> None:
        super().__init__(engine)
        self._config_path = config_path
        self._cache_path = cache_path
        self.build_calls = 0

    async def _build_and_save_meta_chain_theme_cache(self, config_hash: str | None) -> None:
        self.build_calls += 1
        await asyncio.sleep(0.01)
        self.meta_chain_theme_vectors = {"creative": [1.0, 0.0, 0.0]}


@pytest.mark.asyncio
async def test_aimemo_wraps_aggregated_failures() -> None:
    handler = _ExplodingAIMemoHandler(_StubEngine(), {})

    result = await handler.process_aimemo_aggregated(["知识"], "问题", "回答", "[AI]: 回答\n[User]: 问题")

    assert result == "[AIMemo聚合处理失败: boom]"


@pytest.mark.asyncio
async def test_metathinking_load_config_deduplicates_parallel_loads(tmp_path: Path) -> None:
    config_path = tmp_path / "meta_thinking_chains.json"
    cache_path = tmp_path / "meta_chain_vector_cache.json"
    config_path.write_text(json.dumps({"chains": {"creative": {"clusters": ["前思维簇"], "kSequence": [1]}}}, ensure_ascii=False), encoding="utf-8")
    manager = _CountingMetaThinkingManager(_StubEngine(), config_path, cache_path)

    await asyncio.gather(manager.load_config(), manager.load_config())

    assert manager.build_calls == 1


@pytest.mark.asyncio
async def test_metathinking_publishes_vcp_info_and_cache_payload() -> None:
    engine = _StubEngine()
    manager = MetaThinkingManager(engine)
    manager.meta_thinking_chains = {"chains": {"default": {"clusters": ["前思维簇"], "kSequence": [1]}}}

    result = await manager.process_meta_thinking_chain(
        "default",
        [1.0, 0.0, 0.0],
        "用户问题",
        "AI回答",
        "[AI]: AI回答\n[User]: 用户问题",
        None,
        True,
        False,
        0.65,
    )

    assert "VCP元思考链" in result
    assert engine.push_payloads
    assert engine.push_payloads[0]["type"] == "META_THINKING_CHAIN"
    cache_entry = next(iter(engine.query_cache.values()))["value"]
    assert cache_entry["vcpInfo"]["type"] == "META_THINKING_CHAIN"


def test_engine_evicts_expired_ai_memo_cache() -> None:
    engine = TagMemoEngine()
    engine.ai_memo_cache = {
        "expired": {"timestamp": 0, "result": {"content": "old"}},
        "fresh": {"timestamp": 9999999999999, "result": {"content": "new"}},
    }
    engine.ai_memo_cache_ttl = 1000

    engine._evict_expired_ai_memo_cache()

    assert "expired" not in engine.ai_memo_cache
    assert "fresh" in engine.ai_memo_cache