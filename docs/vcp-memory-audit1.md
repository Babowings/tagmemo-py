## ContextVectorManager.js → `tagmemo/context_vector.py`

### 已实现 — 复核结果

| 函数 | 用户判断 | 复核 | 说明 |
|------|---------|------|------|
| `_calculateSimilarity()` | ✅ | ✅ **正确** | `_calculate_similarity` — Dice 系数 bigram |
| `_cosineSimilarity()` | ✅ | ✅ **正确** | `_cosine_similarity` |
| `_finalizeSegment()` | ✅ | ✅ **正确** | `_finalize_segment` |
| `_findFuzzyMatch()` | ✅ | ✅ **正确** | `_find_fuzzy_match` |
| `_generateHash()` | ✅ | ✅ **正确** | `_generate_hash` |
| `_normalize()` | ✅ | ✅ **正确** | `_normalize` |
| `cleanup()` | ✅ | ✅ **正确** | `cleanup` |
| `computeLogicDepth()` | ✅ | ✅ **正确** | `compute_logic_depth` |
| `computeSemanticWidth()` | ✅ | ✅ **正确** | `compute_semantic_width` |
| `constructor()` | ✅ | ✅ **正确** | `__init__` |
| `segmentContext()` | ✅ | ✅ **正确** | `segment_context` |
| `updateContext()` | ✅ | ✅ **正确** | `update_context` |

### 未实现 — 复核结果

| 函数 | 用户判断 | 复核 | 是否需要实现 |
|------|---------|------|------------|
| `aggregateContext()` | ❌ | ❌ **确认未实现** | ⚠️ **建议实现**。原版用于衰减聚合历史向量，被 `_calculateDynamicParams` 调用来计算上下文聚合向量。不实现会影响动态参数精度 |
| `getBigrams()` | ❌ | ⚠️ **已内联实现** | `_calculate_similarity` 内部直接生成 bigram set，没有独立函数但功能已覆盖。**无需额外实现** |
| `getHistoryAssistantVectors()` | ❌ | ❌ **确认未实现** | ⚠️ **建议实现**。原版在 Shotgun Query 中获取历史 AI 输出向量作为多查询源 |
| `getHistoryUserVectors()` | ❌ | ❌ **确认未实现** | ⚠️ **建议实现**。同上，获取历史用户输入向量 |
| `getVectorsByRange()` | ❌ | ❌ **确认未实现** | 🔵 **优先级低**。按索引范围取向量，目前没有调用路径 |

---

## RAGDiaryPlugin.js → `tagmemo/engine.py` + `tagmemo/vcp_compat.py`

### 已实现 — 复核结果

| 函数 | 用户判断 | 复核 | 实际位置 |
|------|---------|------|---------|
| `_calculateDynamicParams()` | ✅ | ✅ **正确** | `engine._calculate_dynamic_params` |
| `_generateCacheKey()` | ✅ | ✅ **正确** | `engine._generate_cache_key` |
| `_sigmoid()` | ✅ | ✅ **正确** | `engine._sigmoid` |
| `_stripEmoji()` | ✅ | ✅ **正确** | `text_sanitizer.strip_emoji` |
| `_stripHtml()` | ✅ | ✅ **正确** | `text_sanitizer.strip_html` |
| `_stripToolMarkers()` | ✅ | ✅ **正确** | `text_sanitizer.strip_tool_markers` |
| `_truncateCoreTags()` | ✅ | ✅ **正确** | `engine._truncate_core_tags` |
| `constructor()` | ✅ | ✅ **正确** | `engine.__init__` |
| `getCacheStats()` | ✅ | ✅ **正确** | `engine.get_cache_stats` |
| `getTimeRangeDiaries()` | ✅ | ✅ **正确** | `engine._get_time_range_diaries` |
| `initialize()` | ✅ | ✅ **正确** | `engine.initialize` |
| `processMessages()` | ✅ | ✅ **正确** | `vcp_compat.VCPPlaceholderProcessor.process_system_messages` |
| `shutdown()` | ✅ | ✅ **正确** | app.py lifespan 中处理 |

### 未实现 — 复核结果

| 函数 | 用户判断 | 复核 | 是否需要实现 |
|------|---------|------|------------|
| `_aggregateTagStats()` | ❌ | ⚠️ **已在 engine._format_results 中内联实现** | 在格式化结果时已统计 tag 信息。**无需额外实现** |
| `_buildAndSaveCache()` | ❌ | ❌ **确认未实现** | 🔴 **需要实现**。构建 enhancedVectorCache，门控逻辑依赖它 |
| `_calculateDynamicK()` | ❌ | ⚠️ **已合并到 `_calculate_dynamic_params`** | 原版是独立函数，重构合并了。**无需额外实现** |
| `_cleanResultsForBroadcast()` | ❌ | ❌ **确认未实现** | 🟢 **不需要实现**。WebSocket 广播相关，你的项目不需要 |
| `_estimateTokens()` | ❌ | ⚠️ **reranker.py 中有 `_estimate_tokens`** | 已在 Reranker 中实现。AIMemoHandler 也需要但那是独立系统。**核心路径已覆盖** |
| `_extractContextDiaryPrefixes()` | ❌ | ❌ **确认未实现** | ⚠️ **建议实现**。V4.1 上下文日记去重前缀提取 |
| `_extractKMultiplier()` | ❌ | ⚠️ **已实现！** | `vcp_compat._extract_k_multiplier` (第567行)。**你漏检了** |
| `_filterContextDuplicates()` | ❌ | ❌ **确认未实现** | ⚠️ **建议实现**。V4.1 上下文日记去重过滤 |
| `_getAverageThreshold()` | ❌ | ❌ **确认未实现** | ⚠️ **建议实现**（如果用多日记本聚合检索） |
| `_getAverageVector()` | ❌ | ⚠️ **已内联实现** | 多处使用 numpy mean 计算均值向量。**无需独立函数** |
| `_getCachedResult()` | ❌ | ⚠️ **已实现！** | `engine._get_cached` (第766行)。**你漏检了** |
| `_getEmbeddingFromCacheOnly()` | ❌ | ⚠️ **已实现！** | `embedding_service.get_from_cache_only` (第68行)。**你漏检了** |
| `_getFileHash()` | ❌ | ❌ **确认未实现** | 🟢 **不需要实现**。原版用于缓存文件变更检测，重构用 watchdog 替代 |
| `_getTimeRangeFilePaths()` | ❌ | ⚠️ **已合并到 `_get_time_range_diaries`** | 原版拆成两个函数，重构合并了。**无需额外实现** |
| `_getWeightedAverageVector()` | ❌ | ⚠️ **已实现！** | `semantic_groups._weighted_average_vectors` (第334行)。**你漏检了** |
| `_isLikelyBase64()` | ❌ | ❌ **确认未实现** | ⚠️ **建议实现**。避免 Base64 图片内容被向量化 |
| `_jsonToMarkdown()` | ❌ | ❌ **确认未实现** | ⚠️ **建议实现**。将工具返回的 JSON 转为可读 Markdown |
| `_parseAggregateSyntax()` | ❌ | ❌ **确认未实现** | ⚠️ **建议实现**（如果用多日记本聚合语法） |
| `_processAggregateRetrieval()` | ❌ | ❌ **确认未实现** | ⚠️ **建议实现**（同上，Softmax K 分配） |
| `_processRAGPlaceholder()` | ❌ | ⚠️ **已实现！** | `vcp_compat._resolve_placeholder` + `engine.query` 组合实现了核心逻辑。**你漏检了** |
| `_rerankDocuments()` | ❌ | ⚠️ **已实现！** | `reranker.py` 的 `Reranker.rerank`。**你漏检了** |
| `_setCachedResult()` | ❌ | ⚠️ **已实现！** | `engine._set_cache` (第780行)。**你漏检了** |
| `_startAiMemoCacheCleanupTask()` | ❌ | ❌ **确认未实现** | 🟢 **不需要实现**。AIMemo 整体未实现，缓存清理自然不需要 |
| `_startCacheCleanupTask()` | ❌ | ⚠️ **已实现！** | `engine._periodic_cache_cleanup` (第788行)。**你漏检了** |
| `_startEmbeddingCacheCleanupTask()` | ❌ | ⚠️ **已实现！** | `embedding_service.cleanup_cache` 被 engine 定期调用。**你漏检了** |
| `_startRagParamsWatcher()` | ❌ | ⚠️ **已实现！** | `engine._watch_rag_params` (第873行)。**你漏检了** |
| `_stripSystemNotification()` | ❌ | ❌ **确认未实现** | 🔴 **需要实现**。移除用户消息末尾系统追加的通知文本 |
| `clearEmbeddingCache()` | ❌ | ⚠️ **已实现！** | `embedding_service.cleanup_cache` (第78行)。**你漏检了** |
| `clearQueryCache()` | ❌ | ⚠️ **已实现！** | `engine.clear_cache` (第810行)。**你漏检了** |
| `cosineSimilarity()` | ❌ | ⚠️ **已实现！** | `vcp_compat._cosine_similarity` (第587行)。**你漏检了** |
| `formatCombinedTimeAwareResults()` | ❌ | ⚠️ **已合并实现！** | `engine._format_results` (第664行) 统一处理了三种格式化。**你漏检了** |
| `formatDate()` | ❌ | ⚠️ **已内联实现！** | `engine._format_results._fmt_date` (第685行)。**你漏检了** |
| `formatGroupRAGResults()` | ❌ | ⚠️ **已合并实现！** | 同上，`_format_results` 统一处理。**你漏检了** |
| `formatStandardResults()` | ❌ | ⚠️ **已合并实现！** | 同上。**你漏检了** |
| `getDiaryContent()` | ❌ | ⚠️ **已实现！** | `vcp_compat._read_full_diary` (第184行)。**你漏检了** |
| `getSingleEmbedding()` | ❌ | ⚠️ **已实现！** | `embedding_service.embed` (第46行)。**你漏检了** |
| `getSingleEmbeddingCached()` | ❌ | ⚠️ **已实现！** | `embedding_service.embed` 本身带缓存。**你漏检了** |
| `loadConfig()` | ❌ | ⚠️ **已合并到 `__init__`** | 原版独立加载配置，重构合并到构造函数。**无需额外实现** |
| `loadRagParams()` | ❌ | ⚠️ **已实现！** | `engine.reload_params` (第907行) + `knowledge_base.load_rag_params` (第220行)。**你漏检了** |
| `refreshRagBlock()` | ❌ | ⚠️ **已实现！** | `vcp_compat.VCPPlaceholderProcessor.refresh_rag_blocks_if_needed` (第285行)。**你漏检了** |

---

## SemanticGroupManager.js → `tagmemo/semantic_groups.py`

### 已实现 — 复核结果

| 函数 | 用户判断 | 复核 |
|------|---------|------|
| `_getWordsHash()` | ✅ | ✅ **正确** |
| `_mergeGroupData()` | ✅ | ✅ **正确** |
| `constructor()` | ✅ | ✅ **正确** |
| `detectAndActivateGroups()` | ✅ | ✅ **正确** |
| `flexibleMatch()` | ✅ | ✅ **正确** |
| `getEnhancedVector()` | ✅ | ✅ **正确** |
| `initialize()` | ✅ | ✅ **正确** |
| `loadGroups()` | ✅ | ✅ **正确** |
| `precomputeGroupVectors()` | ✅ | ✅ **正确** |
| `saveGroups()` | ✅ | ✅ **正确** |
| `synchronizeFromEditFile()` | ✅ | ✅ **正确** |
| `updateGroupStats()` | ✅ | ✅ **正确** |
| `updateGroupsData()` | ✅ | ✅ **正确** |
| `weightedAverageVectors()` | ✅ | ✅ **正确** |

### 未实现 — 复核结果

| 函数 | 用户判断 | 复核 | 是否需要实现 |
|------|---------|------|------------|
| `_areCoreGroupDataDifferent()` | ❌ | ⚠️ **已实现！** | `semantic_groups._are_core_different` (第90行)。**你漏检了** |

---

## TimeExpressionParser.js — 全部 ✅ 无异议

## diary-semantic-classifier.js — 全部 ✅ 无异议

## diary-tag-batch-processor.js — 全部 ✅ 无异议

## EmbeddingUtils.js — 全部 ✅ 无异议

## EPAModule.js — 全部 ✅ 无异议

---

## KnowledgeBaseManager.js → `tagmemo/knowledge_base.py`

### 已实现 — 复核结果

全部 ✅ 确认正确，无异议。

### 未实现 — 复核结果

| 函数 | 用户判断 | 复核 | 是否需要实现 |
|------|---------|------|------------|
| `_fetchAndCacheDiaryNameVector()` | ❌ | ⚠️ **已合并到 `_hydrate_diary_name_cache`** | 原版拆成 hydrate + fetchAndCache，重构合并了。**无需额外实现** |
| `_hydrateDiaryNameCacheSync()` | ❌ | ⚠️ **已实现！** | `knowledge_base._hydrate_diary_name_cache` (第310行)。**你漏检了** |
| `_recoverIndexFromDB()` | ❌ | ⚠️ **已合并到 `_load_or_build_index`** | 恢复逻辑在加载索引时内联处理。**无需额外实现** |
| `_recoverTagsAsync()` | ❌ | ⚠️ **已实现！** | `knowledge_base._recover_tags` (第300行)。**你漏检了** |
| `_startRagParamsWatcher()` | ❌ | ⚠️ **已实现！** | 合并到 `engine._watch_rag_params`。**你漏检了** |
| `getChunksByFilePaths()` | ❌ | ❌ **确认未实现** | ⚠️ 建议实现。Time 模式按文件路径获取分块向量做二次排序 |
| `getPluginDescriptionVector()` | ❌ | ❌ **确认未实现** | 🟢 **不需要实现**。为 LightMemo 缓存插件描述向量 |
| `getVectorByText()` | ❌ | ❌ **确认未实现** | 🔵 优先级低。兼容性 API |
| `searchSimilarTags()` | ❌ | ❌ **确认未实现** | 🔵 优先级低。LightMemo 使用 |

---

## rebuild_tag_index_custom.js — 确认未实现，运维工具，建议后续补充

## rebuild_vector_indexes.js — 确认未实现，运维工具，建议后续补充

## repair_database.js — 确认未实现，运维工具，建议后续补充

## ResidualPyramid.js — 全部 ✅ 无异议

## ResultDeduplicator.js — 全部 ✅ 无异议

## sync_missing_tags.js — 确认未实现，运维工具，建议后续补充

## TextChunker.js — 全部 ✅ 无异议
