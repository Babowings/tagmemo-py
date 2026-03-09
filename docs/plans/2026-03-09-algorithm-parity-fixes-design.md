# Algorithm Parity Fixes Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Align tagmemo-py with verified VCPToolBox behavior for tag boost fusion, search result hydration, embedding batch alignment, and ingestion retry handling.

**Architecture:** Keep the current Python structure and patch only behavior that is demonstrably different from upstream. Use TDD for each parity fix and avoid "helpful" divergences where the audit report does not match the real upstream implementation.

**Tech Stack:** Python 3.12, pytest, sqlite3, numpy, httpx, threading timers.

---

### Task 1: Search Result And TagBoost Parity

**Files:**
- Modify: `tagmemo/knowledge_base.py`
- Test: `tests/test_algorithm_parity.py`

**Step 1: Write the failing tests**

Add tests that verify:
- `_apply_tag_boost_v3()` clamps fusion alpha to `1.0`
- `_hydrate_results()` includes `fullPath`, `tagMatchScore`, `tagMatchCount` for specific-index style hydration
- `search()` forwards `core_boost_factor` into `_search_specific_index()` and `_search_all_indices()`
- global search results do not grow extra fields not present upstream

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_algorithm_parity.py -v`

**Step 3: Write minimal implementation**

Patch `KnowledgeBaseManager` to:
- clamp fusion alpha before mixing vectors
- include the verified upstream result fields in hydrated specific results only where upstream returns them
- add `core_boost_factor` to the public search API and internal helpers

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_algorithm_parity.py -v`

### Task 2: Embedding Batch Alignment Parity

**Files:**
- Modify: `tagmemo/embedding_utils.py`
- Test: `tests/test_algorithm_parity.py`

**Step 1: Write the failing tests**

Add tests that verify `get_embeddings_batch()`:
- returns a list with the same length as the input list
- keeps skipped oversize texts aligned as `None`
- preserves order across batches
- keeps failed batch entries aligned as `None` rather than collapsing the list

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_algorithm_parity.py -v`

**Step 3: Write minimal implementation**

Track original indices per batch and rebuild the final vector list by original position.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_algorithm_parity.py -v`

### Task 3: Batch Ingestion Retry And Alignment Parity

**Files:**
- Modify: `tagmemo/knowledge_base.py`
- Test: `tests/test_algorithm_parity.py`

**Step 1: Write the failing tests**

Add tests that verify:
- `_flush_batch()` maps chunk vectors by original embedding slot and skips `None`
- failed files are retried up to 3 times, then removed from `pending_files`
- successful files clear retry counters

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_algorithm_parity.py -v`

**Step 3: Write minimal implementation**

Patch ingestion flow to:
- preserve chunk/vector alignment with placeholder embeddings
- track `file_retry_count`
- stop infinite requeue after 3 deterministic failures

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_algorithm_parity.py -v`

### Task 4: Verification

**Files:**
- Test: `tests/test_algorithm_parity.py`
- Test: `tests/test_memory_delete.py`

**Step 1: Run targeted regression suite**

Run: `pytest tests/test_algorithm_parity.py tests/test_memory_delete.py -v`

**Step 2: Run full suite**

Run: `pytest -v`
