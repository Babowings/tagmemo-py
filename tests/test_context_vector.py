from __future__ import annotations

import numpy as np
import pytest

from tagmemo.context_vector import ContextVectorManager


def test_compute_semantic_width_is_normalized_entropy() -> None:
    focused = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    broad = np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float32)

    focused_width = ContextVectorManager.compute_semantic_width(focused)
    broad_width = ContextVectorManager.compute_semantic_width(broad)

    assert focused_width == 0.0
    assert broad_width == 1.0


def test_compute_logic_depth_uses_topk_energy_concentration() -> None:
    broad = np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float32)
    focused = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    broad_depth = ContextVectorManager.compute_logic_depth(broad, top_k=2)
    focused_depth = ContextVectorManager.compute_logic_depth(focused, top_k=2)

    assert broad_depth == 0.0
    assert focused_depth == 1.0


@pytest.mark.asyncio
async def test_update_context_exposes_history_vectors_and_aggregate() -> None:
    vectors = {
        "u0": [1.0, 0.0],
        "a0": [0.0, 1.0],
        "u1": [0.5, 0.5],
        "a1": [0.2, 0.8],
        "u2": [0.25, 0.75],
        "a2": [0.8, 0.2],
        "current": [0.9, 0.1],
    }
    manager = ContextVectorManager(get_cached_embedding=lambda text: vectors.get(text))

    messages = [
        {"role": "user", "content": "u0"},
        {"role": "assistant", "content": "a0"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "current"},
    ]

    await manager.update_context(messages, allow_api=False)

    assert manager.get_history_assistant_vectors() == [[0.0, 1.0], [0.2, 0.8]]
    assert manager.get_history_user_vectors() == [[1.0, 0.0], [0.5, 0.5], [0.25, 0.75]]

    aggregated = manager.aggregate_context("assistant")
    assert aggregated is not None
    assert aggregated == pytest.approx([0.1142857143, 0.8857142857], abs=1e-6)
