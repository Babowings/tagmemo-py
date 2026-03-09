from __future__ import annotations

import numpy as np

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
