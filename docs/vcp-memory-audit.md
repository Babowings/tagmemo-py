# VCPToolBox 记忆功能及全脚本排查分析

以下遍历了项目根目录及所有子模块的各种脚本文件，共检索了 283 个文件：

## 1. 核心记忆算法脚本 (已由 tagmemo-py 主动重构)

| 原项目脚本 (JS) | 重构后模块 (Python) | 原函数/方法名 | 状态 |
|-----------------|---------------------|---------------|------|
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `_calculateSimilarity()` | **✅ 已实现** |
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `_cosineSimilarity()` | **✅ 已实现** |
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `_finalizeSegment()` | **✅ 已实现** |
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `_findFuzzyMatch()` | **✅ 已实现** |
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `_generateHash()` | **✅ 已实现** |
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `_normalize()` | **✅ 已实现** |
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `aggregateContext()` | **❌ 未实现** |
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `cleanup()` | **✅ 已实现** |
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `computeLogicDepth()` | **✅ 已实现** |
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `computeSemanticWidth()` | **✅ 已实现** |
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `constructor()` | **✅ 已实现** |
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `getBigrams()` | **❌ 未实现** |
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `getHistoryAssistantVectors()` | **❌ 未实现** |
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `getHistoryUserVectors()` | **❌ 未实现** |
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `getVectorsByRange()` | **❌ 未实现** |
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `segmentContext()` | **✅ 已实现** |
| `ContextVectorManager.js` | `tagmemo\context_vector.py` | `updateContext()` | **✅ 已实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_aggregateTagStats()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_buildAndSaveCache()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_calculateDynamicK()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_calculateDynamicParams()` | **✅ 已实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_cleanResultsForBroadcast()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_estimateTokens()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_extractContextDiaryPrefixes()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_extractKMultiplier()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_filterContextDuplicates()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_generateCacheKey()` | **✅ 已实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_getAverageThreshold()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_getAverageVector()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_getCachedResult()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_getEmbeddingFromCacheOnly()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_getFileHash()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_getTimeRangeFilePaths()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_getWeightedAverageVector()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_isLikelyBase64()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_jsonToMarkdown()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_parseAggregateSyntax()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_processAggregateRetrieval()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_processRAGPlaceholder()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_rerankDocuments()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_setCachedResult()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_sigmoid()` | **✅ 已实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_startAiMemoCacheCleanupTask()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_startCacheCleanupTask()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_startEmbeddingCacheCleanupTask()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_startRagParamsWatcher()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_stripEmoji()` | **✅ 已实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_stripHtml()` | **✅ 已实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_stripSystemNotification()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_stripToolMarkers()` | **✅ 已实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `_truncateCoreTags()` | **✅ 已实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `clearEmbeddingCache()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `clearQueryCache()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `constructor()` | **✅ 已实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `cosineSimilarity()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `formatCombinedTimeAwareResults()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `formatDate()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `formatGroupRAGResults()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `formatStandardResults()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `getCacheStats()` | **✅ 已实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `getDiaryContent()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `getSingleEmbedding()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `getSingleEmbeddingCached()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `getTimeRangeDiaries()` | **✅ 已实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `initialize()` | **✅ 已实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `loadConfig()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `loadRagParams()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `processMessages()` | **✅ 已实现(改写)** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `refreshRagBlock()` | **❌ 未实现** |
| `RAGDiaryPlugin.js` | `tagmemo\engine.py` | `shutdown()` | **✅ 已实现** |
| `SemanticGroupManager.js` | `tagmemo\semantic_groups.py` | `_areCoreGroupDataDifferent()` | **❌ 未实现** |
| `SemanticGroupManager.js` | `tagmemo\semantic_groups.py` | `_getWordsHash()` | **✅ 已实现** |
| `SemanticGroupManager.js` | `tagmemo\semantic_groups.py` | `_mergeGroupData()` | **✅ 已实现** |
| `SemanticGroupManager.js` | `tagmemo\semantic_groups.py` | `constructor()` | **✅ 已实现** |
| `SemanticGroupManager.js` | `tagmemo\semantic_groups.py` | `detectAndActivateGroups()` | **✅ 已实现** |
| `SemanticGroupManager.js` | `tagmemo\semantic_groups.py` | `flexibleMatch()` | **✅ 已实现** |
| `SemanticGroupManager.js` | `tagmemo\semantic_groups.py` | `getEnhancedVector()` | **✅ 已实现** |
| `SemanticGroupManager.js` | `tagmemo\semantic_groups.py` | `initialize()` | **✅ 已实现** |
| `SemanticGroupManager.js` | `tagmemo\semantic_groups.py` | `loadGroups()` | **✅ 已实现** |
| `SemanticGroupManager.js` | `tagmemo\semantic_groups.py` | `precomputeGroupVectors()` | **✅ 已实现** |
| `SemanticGroupManager.js` | `tagmemo\semantic_groups.py` | `saveGroups()` | **✅ 已实现** |
| `SemanticGroupManager.js` | `tagmemo\semantic_groups.py` | `synchronizeFromEditFile()` | **✅ 已实现** |
| `SemanticGroupManager.js` | `tagmemo\semantic_groups.py` | `updateGroupStats()` | **✅ 已实现** |
| `SemanticGroupManager.js` | `tagmemo\semantic_groups.py` | `updateGroupsData()` | **✅ 已实现** |
| `SemanticGroupManager.js` | `tagmemo\semantic_groups.py` | `weightedAverageVectors()` | **✅ 已实现** |
| `TimeExpressionParser.js` | `tagmemo\time_parser.py` | `_getDayBoundaries()` | **✅ 已实现** |
| `TimeExpressionParser.js` | `tagmemo\time_parser.py` | `_getSpecialRange()` | **✅ 已实现** |
| `TimeExpressionParser.js` | `tagmemo\time_parser.py` | `_handleDynamicPattern()` | **✅ 已实现** |
| `TimeExpressionParser.js` | `tagmemo\time_parser.py` | `chineseToNumber()` | **✅ 已实现** |
| `TimeExpressionParser.js` | `tagmemo\time_parser.py` | `constructor()` | **✅ 已实现** |
| `TimeExpressionParser.js` | `tagmemo\time_parser.py` | `parse()` | **✅ 已实现** |
| `TimeExpressionParser.js` | `tagmemo\time_parser.py` | `setLocale()` | **✅ 已实现** |
| `diary-semantic-classifier.js` | `scripts\diary_semantic_classifier.py` | `computeAggregateVector()` | **✅ 已实现** |
| `diary-semantic-classifier.js` | `scripts\diary_semantic_classifier.py` | `cosineSimilarity()` | **✅ 已实现** |
| `diary-semantic-classifier.js` | `scripts\diary_semantic_classifier.py` | `main()` | **✅ 已实现** |
| `diary-tag-batch-processor.js` | `scripts\diary_tag_batch_processor.py` | `delay()` | **✅ 已实现 (重构为 asyncio.sleep)** |
| `diary-tag-batch-processor.js` | `scripts\diary_tag_batch_processor.py` | `detectTagLine()` | **✅ 已实现** |
| `diary-tag-batch-processor.js` | `scripts\diary_tag_batch_processor.py` | `error()` | **✅ 已实现 (使用标准输出)** |
| `diary-tag-batch-processor.js` | `scripts\diary_tag_batch_processor.py` | `extractTagFromAIResponse()` | **✅ 已实现** |
| `diary-tag-batch-processor.js` | `scripts\diary_tag_batch_processor.py` | `fixTagFormat()` | **✅ 已实现** |
| `diary-tag-batch-processor.js` | `scripts\diary_tag_batch_processor.py` | `generateTagsWithAI()` | **✅ 已实现** |
| `diary-tag-batch-processor.js` | `scripts\diary_tag_batch_processor.py` | `isTagFormatValid()` | **✅ 已实现** |
| `diary-tag-batch-processor.js` | `scripts\diary_tag_batch_processor.py` | `log()` | **✅ 已实现 (使用标准输出)** |
| `diary-tag-batch-processor.js` | `scripts\diary_tag_batch_processor.py` | `main()` | **✅ 已实现** |
| `diary-tag-batch-processor.js` | `scripts\diary_tag_batch_processor.py` | `processFile()` | **✅ 已实现** |
| `diary-tag-batch-processor.js` | `scripts\diary_tag_batch_processor.py` | `scanDirectory()` | **✅ 已实现 (使用 rglob)** |
| `EmbeddingUtils.js` | `tagmemo\embedding_utils.py` | `_sendBatch()` | **✅ 已实现** |
| `EmbeddingUtils.js` | `tagmemo\embedding_utils.py` | `getEmbeddingsBatch()` | **✅ 已实现** |
| `EmbeddingUtils.js` | `tagmemo\embedding_utils.py` | `worker()` | **✅ 已实现** |
| `EPAModule.js` | `tagmemo\epa.py` | `_clusterTags()` | **✅ 已实现** |
| `EPAModule.js` | `tagmemo\epa.py` | `_computeWeightedPCA()` | **✅ 已实现** |
| `EPAModule.js` | `tagmemo\epa.py` | `_emptyResult()` | **✅ 已实现** |
| `EPAModule.js` | `tagmemo\epa.py` | `_loadFromCache()` | **✅ 已实现** |
| `EPAModule.js` | `tagmemo\epa.py` | `_powerIteration()` | **✅ 已实现 (替换为更优的 np.linalg.eigh)** |
| `EPAModule.js` | `tagmemo\epa.py` | `_saveToCache()` | **✅ 已实现** |
| `EPAModule.js` | `tagmemo\epa.py` | `_selectBasisDimension()` | **✅ 已实现** |
| `EPAModule.js` | `tagmemo\epa.py` | `constructor()` | **✅ 已实现** |
| `EPAModule.js` | `tagmemo\epa.py` | `detectCrossDomainResonance()` | **✅ 已实现** |
| `EPAModule.js` | `tagmemo\epa.py` | `initialize()` | **✅ 已实现** |
| `EPAModule.js` | `tagmemo\epa.py` | `project()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_applyTagBoostV3()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_buildCooccurrenceMatrix()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_evictIdleIndices()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_extractTags()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_fetchAndCacheDiaryNameVector()` | **❌ 未实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_flushBatch()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_getOrLoadDiaryIndex()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_handleDelete()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_hydrateDiaryNameCacheSync()` | **❌ 未实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_initSchema()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_loadOrBuildIndex()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_prepareTextForEmbedding()` | **✅ 已实现 (更名为 _prepare_text)** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_recoverIndexFromDB()` | **❌ 未实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_recoverTagsAsync()` | **❌ 未实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_saveIndexToDisk()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_scheduleBatch()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_scheduleIndexSave()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_searchAllIndices()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_searchSpecificIndex()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_startIdleSweep()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_startRagParamsWatcher()` | **❌ 未实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `_startWatcher()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `applyTagBoost()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `constructor()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `deduplicateResults()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `getChunksByFilePaths()` | **❌ 未实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `getDiaryNameVector()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `getEPAAnalysis()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `getPluginDescriptionVector()` | **❌ 未实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `getVectorByText()` | **❌ 未实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `handleFile()` | **✅ 已实现 (重构至看门狗 Handler 中)** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `initialize()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `loadRagParams()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `search()` | **✅ 已实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `searchSimilarTags()` | **❌ 未实现** |
| `KnowledgeBaseManager.js` | `tagmemo\knowledge_base.py` | `shutdown()` | **✅ 已实现** |
| `rebuild_tag_index_custom.js` | `无对应文件` | `main()` | **❌ 未实现** |
| `rebuild_tag_index_custom.js` | `无对应文件` | `prepareTag()` | **❌ 未实现** |
| `rebuild_vector_indexes.js` | `无对应文件` | `main()` | **❌ 未实现** |
| `repair_database.js` | `无对应文件` | `_prepareTextForEmbedding()` | **❌ 未实现** |
| `ResidualPyramid.js` | `tagmemo\residual_pyramid.py` | `_analyzeHandshakes()` | **✅ 已实现** |
| `ResidualPyramid.js` | `tagmemo\residual_pyramid.py` | `_computeHandshakes()` | **✅ 已实现 (内联重构)** |
| `ResidualPyramid.js` | `tagmemo\residual_pyramid.py` | `_computeOrthogonalProjection()` | **✅ 已实现** |
| `ResidualPyramid.js` | `tagmemo\residual_pyramid.py` | `_dotProduct()` | **✅ 已实现 (NumPy 特性平替)** |
| `ResidualPyramid.js` | `tagmemo\residual_pyramid.py` | `_emptyResult()` | **✅ 已实现** |
| `ResidualPyramid.js` | `tagmemo\residual_pyramid.py` | `_extractFloat32()` | **✅ 已废弃 (Python环境无需封包转换)** |
| `ResidualPyramid.js` | `tagmemo\residual_pyramid.py` | `_extractPyramidFeatures()` | **✅ 已实现** |
| `ResidualPyramid.js` | `tagmemo\residual_pyramid.py` | `_getTagVectors()` | **✅ 已实现** |
| `ResidualPyramid.js` | `tagmemo\residual_pyramid.py` | `_magnitude()` | **✅ 已实现 (NumPy 特性平替)** |
| `ResidualPyramid.js` | `tagmemo\residual_pyramid.py` | `analyze()` | **✅ 已实现** |
| `ResidualPyramid.js` | `tagmemo\residual_pyramid.py` | `constructor()` | **✅ 已实现** |
| `ResultDeduplicator.js` | `tagmemo\result_deduplicator.py` | `_dotProduct()` | **✅ 已实现 (NumPy 特性平替)** |
| `ResultDeduplicator.js` | `tagmemo\result_deduplicator.py` | `_magnitude()` | **✅ 已实现 (NumPy 特性平替)** |
| `ResultDeduplicator.js` | `tagmemo\result_deduplicator.py` | `_normalize()` | **✅ 已实现** |
| `ResultDeduplicator.js` | `tagmemo\result_deduplicator.py` | `constructor()` | **✅ 已实现** |
| `ResultDeduplicator.js` | `tagmemo\result_deduplicator.py` | `deduplicate()` | **✅ 已实现** |
| `sync_missing_tags.js` | `无对应文件` | `extractTags()` | **❌ 未实现** |
| `sync_missing_tags.js` | `无对应文件` | `main()` | **❌ 未实现** |
| `sync_missing_tags.js` | `无对应文件` | `walkDir()` | **❌ 未实现** |
| `TextChunker.js` | `tagmemo\text_chunker.py` | `chunkText()` | **✅ 已实现** |
| `TextChunker.js` | `tagmemo\text_chunker.py` | `forceSplitLongText()` | **✅ 已实现** |

## 2. 记忆数据源与管道扩展支持脚本 (必不可少的周边生态组件)

| 原项目脚本 (JS) | 重构后模块 (Python) | 原函数/方法名 | 状态 |
|-----------------|---------------------|---------------|------|
| `rag-tuning.js` | `无对应文件` | `handleSave()` | **❌ 未实现** |
| `rag-tuning.js` | `无对应文件` | `initializeRAGTuning()` | **❌ 未实现** |
| `rag-tuning.js` | `无对应文件` | `loadParams()` | **❌ 未实现** |
| `rag-tuning.js` | `无对应文件` | `renderParams()` | **❌ 未实现** |
| `dailynote.js` | `无对应文件` | `debugLog()` | **❌ 未实现** |
| `dailynote.js` | `无对应文件` | `detectTagLine()` | **❌ 未实现** |
| `dailynote.js` | `无对应文件` | `fixTagFormat()` | **❌ 未实现** |
| `dailynote.js` | `无对应文件` | `handleCreateCommand()` | **❌ 未实现** |
| `dailynote.js` | `无对应文件` | `handleUpdateCommand()` | **❌ 未实现** |
| `dailynote.js` | `无对应文件` | `isPathWithinBase()` | **❌ 未实现** |
| `dailynote.js` | `无对应文件` | `main()` | **❌ 未实现** |
| `dailynote.js` | `无对应文件` | `processLocalFiles()` | **❌ 未实现** |
| `dailynote.js` | `无对应文件` | `processTags()` | **❌ 未实现** |
| `dailynote.js` | `无对应文件` | `sanitizePathComponent()` | **❌ 未实现** |
| `dailynote.js` | `无对应文件` | `sanitizeServerFilename()` | **❌ 未实现** |
| `daily-note-manager.js` | `无对应文件` | `processDailyNotes()` | **❌ 未实现** |
| `daily-note-manager.js` | `无对应文件` | `saveCurrentNote()` | **❌ 未实现** |
| `daily-note-write.js` | `无对应文件` | `debugLog()` | **❌ 未实现** |
| `daily-note-write.js` | `无对应文件` | `delay()` | **❌ 未实现** |
| `daily-note-write.js` | `无对应文件` | `detectTagLine()` | **❌ 未实现** |
| `daily-note-write.js` | `无对应文件` | `extractTagFromAIResponse()` | **❌ 未实现** |
| `daily-note-write.js` | `无对应文件` | `fixTagFormat()` | **❌ 未实现** |
| `daily-note-write.js` | `无对应文件` | `generateTagsWithAI()` | **❌ 未实现** |
| `daily-note-write.js` | `无对应文件` | `main()` | **❌ 未实现** |
| `daily-note-write.js` | `无对应文件` | `processTagsInContent()` | **❌ 未实现** |
| `daily-note-write.js` | `无对应文件` | `sanitizePathComponent()` | **❌ 未实现** |
| `daily-note-write.js` | `无对应文件` | `sendOutput()` | **❌ 未实现** |
| `daily-note-write.js` | `无对应文件` | `writeDiary()` | **❌ 未实现** |
| `extract_stork_links.js` | `无对应文件` | `extractPaperIds()` | **❌ 未实现** |
| `extract_stork_links.js` | `无对应文件` | `main()` | **❌ 未实现** |
| `extract_stork_links.js` | `无对应文件` | `readPermanentIndex()` | **❌ 未实现** |
| `extract_stork_links.js` | `无对应文件` | `triggerFetchScript()` | **❌ 未实现** |
| `fetch_stork_pages.js` | `无对应文件` | `fetchAndSave()` | **❌ 未实现** |
| `fetch_stork_pages.js` | `无对应文件` | `main()` | **❌ 未实现** |
| `fetch_stork_pages.js` | `无对应文件` | `triggerHtmlToMdScript()` | **❌ 未实现** |
| `html_to_md.js` | `无对应文件` | `convertHtmlToMd()` | **❌ 未实现** |
| `html_to_md.js` | `无对应文件` | `main()` | **❌ 未实现** |
| `html_to_md.js` | `无对应文件` | `preprocessHtml()` | **❌ 未实现** |
| `html_to_md.js` | `无对应文件` | `triggerMdToTxtScript()` | **❌ 未实现** |
| `md_to_txt.js` | `无对应文件` | `appendToPermanentIndex()` | **❌ 未实现** |
| `md_to_txt.js` | `无对应文件` | `getFormattedTimestamps()` | **❌ 未实现** |
| `md_to_txt.js` | `无对应文件` | `main()` | **❌ 未实现** |
| `md_to_txt.js` | `无对应文件` | `normalizeMarkdownToTxt()` | **❌ 未实现** |
| `md_to_txt.js` | `无对应文件` | `processMdToTxt()` | **❌ 未实现** |
| `extract_stork_links.js` | `无对应文件` | `extractPaperIds()` | **❌ 未实现** |
| `extract_stork_links.js` | `无对应文件` | `main()` | **❌ 未实现** |
| `extract_stork_links.js` | `无对应文件` | `readPermanentIndex()` | **❌ 未实现** |
| `extract_stork_links.js` | `无对应文件` | `triggerPipeline()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `buildEFetchUrl()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `buildNCBIUrl()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `doiToKey()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `efetchDoisForPubmedIds()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `extractDoiSuffixFromHtml()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `fetchShowPaperHtml()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `fetchSimilarPubmedIds()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `fetchSimilarPubmedIdsViaNCBI()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `filterPubmedByIndex()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `filterStorkByIndex()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `main()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `normalizeIdList()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `parseIdFromLine()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `parsePubmedIdFromHtml()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `parseXmlAndFill()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `readIds()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `readPermanentDoiIndex()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `readStorkIds()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `writePubmedTmp()` | **❌ 未实现** |
| `fetch_pubmed_similars.js` | `无对应文件` | `writeStorkNewTmpWithDoi()` | **❌ 未实现** |
| `fetch_stork_pages.js` | `无对应文件` | `buildTasks()` | **❌ 未实现** |
| `fetch_stork_pages.js` | `无对应文件` | `doiToKey()` | **❌ 未实现** |
| `fetch_stork_pages.js` | `无对应文件` | `ensureCleanTargetDir()` | **❌ 未实现** |
| `fetch_stork_pages.js` | `无对应文件` | `fetchAndSave()` | **❌ 未实现** |
| `fetch_stork_pages.js` | `无对应文件` | `getPubmedPairs()` | **❌ 未实现** |
| `fetch_stork_pages.js` | `无对应文件` | `getStorkPairs()` | **❌ 未实现** |
| `fetch_stork_pages.js` | `无对应文件` | `main()` | **❌ 未实现** |
| `fetch_stork_pages.js` | `无对应文件` | `readLines()` | **❌ 未实现** |
| `fetch_stork_pages.js` | `无对应文件` | `readPermanentIndex()` | **❌ 未实现** |
| `fetch_stork_pages.js` | `无对应文件` | `readTsvPairs()` | **❌ 未实现** |
| `fetch_stork_pages.js` | `无对应文件` | `sanitizeFilename()` | **❌ 未实现** |
| `fetch_stork_pages.js` | `无对应文件` | `spawnHtmlToMdBatch()` | **❌ 未实现** |
| `html_to_md.js` | `无对应文件` | `convertOne()` | **❌ 未实现** |
| `html_to_md.js` | `无对应文件` | `ensureMdDirExists()` | **❌ 未实现** |
| `html_to_md.js` | `无对应文件` | `listDoiKeysFromHtmlDir()` | **❌ 未实现** |
| `html_to_md.js` | `无对应文件` | `main()` | **❌ 未实现** |
| `html_to_md.js` | `无对应文件` | `preprocessHtml()` | **❌ 未实现** |
| `html_to_md.js` | `无对应文件` | `triggerMdToTxtScript()` | **❌ 未实现** |
| `md_to_txt.js` | `无对应文件` | `ensureAndGetTxtDir()` | **❌ 未实现** |
| `md_to_txt.js` | `无对应文件` | `getLocalTimeDateParts()` | **❌ 未实现** |
| `md_to_txt.js` | `无对应文件` | `main()` | **❌ 未实现** |
| `md_to_txt.js` | `无对应文件` | `normalizeMarkdownToTxt()` | **❌ 未实现** |
| `md_to_txt.js` | `无对应文件` | `processOne()` | **❌ 未实现** |
| `md_to_txt.js` | `无对应文件` | `rebuildPermanentIndex()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `_checkSignature()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `_cosineSimilarity()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `_estimateTokens()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `_expandQueryTokens()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `_gatherCandidateChunks()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `_rerankDocuments()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `_scoreByVectorSimilarity()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `_tokenize()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `calculateIDF()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `constructor()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `formatResults()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `handleSearch()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `initialize()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `loadConfig()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `loadSemanticGroups()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `processToolCall()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `score()` | **❌ 未实现** |
| `LightMemo.js` | `无对应文件` | `shutdown()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `_buildPrompt()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `_callAIModel()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `_combineFiles()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `_estimateTokens()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `_extractMemories()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `_extractMemoryBlocks()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `_getCache()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `_getCacheKey()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `_getDiaryFiles()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `_handleRepetitiveOutput()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `_mergeBatchResults()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `_processBatch()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `_processBatchedAggregated()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `_processSingleAggregated()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `_setCache()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `_splitFilesIntoBatches()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `constructor()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `isConfigured()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `loadConfig()` | **❌ 未实现** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `processAIMemo()` | **✅ 已实现 (通过 RequestInspector 拦截重写)** |
| `AIMemoHandler.js` | `proxy/common/request_inspector.py` | `processAIMemoAggregated()` | **✅ 已实现 (改写合并在拦截器中)** |
| `MetaThinkingManager.js` | `无对应文件` | `_buildAndSaveMetaChainThemeCache()` | **❌ 未实现** |
| `MetaThinkingManager.js` | `无对应文件` | `_formatMetaThinkingResults()` | **❌ 未实现** |
| `MetaThinkingManager.js` | `无对应文件` | `_getAverageVector()` | **❌ 未实现** |
| `MetaThinkingManager.js` | `无对应文件` | `constructor()` | **❌ 未实现** |
| `MetaThinkingManager.js` | `无对应文件` | `loadConfig()` | **❌ 未实现** |
| `MetaThinkingManager.js` | `无对应文件` | `processMetaThinkingChain()` | **❌ 未实现** |
| `test_reranker.js` | `tagmemo/reranker.py` | `testRerankerAPI()` | **✅ 已废弃 (已重构为主线功能 reranker.py)** |
| `timeExpressions.config.js` | `tagmemo/time_expressions.py` | `(Script/No pure functions)()` | **✅ 已实现 (转为 python 字典配置)** |
| `SemanticGroupEditor.js` | `无对应文件` | `main()` | **❌ 未实现** |
| `SemanticGroupEditor.js` | `无对应文件` | `queryGroups()` | **❌ 未实现** |
| `SemanticGroupEditor.js` | `无对应文件` | `readSemanticGroupsFile()` | **❌ 未实现** |
| `SemanticGroupEditor.js` | `无对应文件` | `updateGroups()` | **❌ 未实现** |
| `SemanticGroupEditor.js` | `无对应文件` | `writeSemanticGroupsFile()` | **❌ 未实现** |
| `dailyNotesRoutes.js` | `tagmemo/vcp_compat.py` | `acquire()` | **❌ 未实现** |
| `dailyNotesRoutes.js` | `tagmemo/vcp_compat.py` | `checkAbort()` | **❌ 未实现** |
| `dailyNotesRoutes.js` | `tagmemo/vcp_compat.py` | `constructor()` | **✅ 已实现** |
| `dailyNotesRoutes.js` | `tagmemo/vcp_compat.py` | `executeSearch()` | **✅ 已实现 (交由 FastAPI engine.query)** |
| `dailyNotesRoutes.js` | `tagmemo/vcp_compat.py` | `hashSearchParams()` | **❌ 未实现** |
| `dailyNotesRoutes.js` | `tagmemo/vcp_compat.py` | `isPathSafe()` | **❌ 未实现** |
| `dailyNotesRoutes.js` | `tagmemo/vcp_compat.py` | `isSymlink()` | **❌ 未实现** |
| `dailyNotesRoutes.js` | `tagmemo/vcp_compat.py` | `onClose()` | **❌ 未实现** |
| `dailyNotesRoutes.js` | `tagmemo/vcp_compat.py` | `queuedSearch()` | **❌ 未实现** |
| `dailyNotesRoutes.js` | `tagmemo/vcp_compat.py` | `release()` | **❌ 未实现** |
| `dailyNotesRoutes.js` | `tagmemo/vcp_compat.py` | `searchPromise()` | **✅ 已实现 (交由底层统一封装)** |
| `dailyNotesRoutes.js` | `tagmemo/vcp_compat.py` | `yieldToEventLoop()` | **❌ 未实现** |
| `index.js` | `tagmemo/vector_index.py` | `isMusl()` | **❌ 未实现** |
| `test.js` | *无对应文件* | -(无核心函数)- | **❌ 未实现** |


## 3. RAG 对接层与衍生应用脚本 (记忆的使用者与外部调用层)

| 原项目脚本 (JS) | 重构后模块 (Python) | 原函数/方法名 | 状态 |
|-----------------|---------------------|---------------|------|
| `chatCompletionHandler.js` | `proxy/gemini/server.py` | `_refreshRagBlocksIfNeeded()` | **❌ 未实现** |
| `chatCompletionHandler.js` | `proxy/gemini/server.py` | `cleanup()` | **❌ 未实现** |
| `chatCompletionHandler.js` | `proxy/gemini/server.py` | `constructor()` | **✅ 已实现** |
| `chatCompletionHandler.js` | `proxy/gemini/server.py` | `fetchWithRetry()` | **❌ 未实现** |
| `chatCompletionHandler.js` | `proxy/gemini/server.py` | `formatToolResult()` | **❌ 未实现** |
| `chatCompletionHandler.js` | `proxy/gemini/server.py` | `getRealAuthCode()` | **❌ 未实现** |
| `chatCompletionHandler.js` | `proxy/gemini/server.py` | `handle()` | **❌ 未实现** |
| `chatCompletionHandler.js` | `proxy/gemini/server.py` | `isToolResultError()` | **❌ 未实现** |
| `messageProcessor.js` | `无对应文件` | `replaceOtherVariables()` | **❌ 未实现** |
| `messageProcessor.js` | `无对应文件` | `replacePriorityVariables()` | **❌ 未实现** |
| `messageProcessor.js` | `无对应文件` | `resolveAllVariables()` | **❌ 未实现** |
| `messageProcessor.js` | `无对应文件` | `resolveDynamicFoldProtocol()` | **❌ 未实现** |
| `VCP_DailyNote_SidePanel.user.js` | `无对应文件` | `closePanel()` | **❌ 未实现** |
| `VCP_DailyNote_SidePanel.user.js` | `无对应文件` | `initUI()` | **❌ 未实现** |
| `VCP_DailyNote_SidePanel.user.js` | `无对应文件` | `openPanel()` | **❌ 未实现** |
| `VCP_DailyNote_SidePanel.user.js` | `无对应文件` | `startProxyInjection()` | **❌ 未实现** |
| `VCP_DailyNote_SidePanel.user.js` | `无对应文件` | `toggleInnerSidebar()` | **❌ 未实现** |
| `VCP_DailyNote_SidePanel.user.js` | `无对应文件` | `togglePanel()` | **❌ 未实现** |
| `VCP_DailyNote_SidePanel.user.js` | `无对应文件` | `updateInnerSidebarState()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_assembleDreamPrompt()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_broadcastDream()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_checkAndTriggerDreams()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_getDateStr()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_getDreamContext()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_getPersonalDiaryNames()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_getPublicDiaryNames()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_isContextExpired()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_loadDreamState()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_parseOperation()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_recallAssociations()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_removeVCPThinkingChain()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_sampleSeedDiaries()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_saveDreamState()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_startDreamScheduler()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_stopDreamScheduler()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_updateDreamContext()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `_urlToFilePath()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `initialize()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `loadDreamConfig()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `processToolCall()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `pushVcpInfo()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `shutdown()` | **❌ 未实现** |
| `AgentDream.js` | `无对应文件` | `triggerDream()` | **❌ 未实现** |
| `test_dream.js` | *无对应文件* | -(无核心函数)- | **❌ 未实现** |
| `script.js` | `无对应文件` | `apiGet()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `apiPost()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `applyGlobalFontSize()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `applyGlow()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `applyTheme()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `autoRefreshLoop()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `bindEvents()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `clampTextLines()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `closeDeleteModal()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `computeFingerprint()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `getVisibleNotebooks()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `init()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `isStreamNotebook()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `loadNotebooks()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `loadSettings()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `notebookVisible()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `openDeleteModal()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `openEditor()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `recomputeAndRenderCards()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `refreshCurrentViewFromCache()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `refreshNotesUsingSearchIfNeeded()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `refreshSingleNotebookCache()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `renderCards()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `renderCardsStatus()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `renderMarkdown()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `renderNotebookLists()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `saveSettings()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `showCardsView()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `showEditorView()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `showSettingsView()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `sortedNotes()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `syncSettingsUI()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `updateBulkModeUI()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `updateCardsGridColumns()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `updateSearchUIForCurrentNotebook()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `updateSidebarActiveState()` | **❌ 未实现** |
| `script.js` | `无对应文件` | `updateSidebarGlow()` | **❌ 未实现** |
| `sw.js` | *无对应文件* | -(无核心函数)- | **❌ 未实现** |
| `index.js` | `无对应文件` | `registerRoutes()` | **❌ 未实现** |
| `adminPanelRoutes.js` | `无对应文件` | `_urlToFilePath()` | **❌ 未实现** |
| `adminPanelRoutes.js` | `无对应文件` | `charCount()` | **❌ 未实现** |
| `adminPanelRoutes.js` | `无对应文件` | `ensureToolConfigsDir()` | **❌ 未实现** |
| `adminPanelRoutes.js` | `无对应文件` | `escapeForDoubleQuotes()` | **❌ 未实现** |
| `adminPanelRoutes.js` | `无对应文件` | `generateBaseName()` | **❌ 未实现** |
| `adminPanelRoutes.js` | `无对应文件` | `getDesc()` | **❌ 未实现** |
| `adminPanelRoutes.js` | `无对应文件` | `getFixedTimeValues()` | **❌ 未实现** |
| `adminPanelRoutes.js` | `无对应文件` | `getPlaceholderDescriptionsFromManifests()` | **❌ 未实现** |
| `adminPanelRoutes.js` | `无对应文件` | `getPluginDescriptionsByToolPlaceholder()` | **❌ 未实现** |
| `adminPanelRoutes.js` | `无对应文件` | `parseAgentAssistantConfig()` | **❌ 未实现** |
| `adminPanelRoutes.js` | `无对应文件` | `truncatePreview()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `_executeStaticPluginCommand()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `_getDecryptedAuthCode()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `_getFormattedLocalTimestamp()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `_getPluginConfig()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `_updateStaticPluginValue()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `buildVCPDescription()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `clearDistributedStaticPlaceholders()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `constructor()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `executeMessagePreprocessor()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `executePlugin()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `getAllPlaceholderValues()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `getIndividualPluginDescriptions()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `getPlaceholderValue()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `getPlugin()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `getPreprocessorOrder()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `getResolvedPluginConfigValue()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `getServiceModule()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `getVCPLogFunctions()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `handlePluginManifestChange()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `hotReloadPluginsAndOrder()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `initializeServices()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `initializeStaticPlugins()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `loadPlugins()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `prewarmPythonPlugins()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `processToolCall()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `registerDistributedTools()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `resolveArgsUrls()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `setProjectBasePath()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `setVectorDBManager()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `setWebSocketServer()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `shutdownAllPlugins()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `startPluginWatcher()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `unregisterAllDistributedTools()` | **❌ 未实现** |
| `Plugin.js` | `无对应文件` | `updateDistributedStaticPlaceholders()` | **❌ 未实现** |
| `server.js` | `proxy/gemini/server.py` | `adminAuth()` | **❌ 未实现** |
| `server.js` | `proxy/gemini/server.py` | `ensureAgentDirectory()` | **❌ 未实现** |
| `server.js` | `proxy/gemini/server.py` | `ensureAsyncResultsDir()` | **❌ 未实现** |
| `server.js` | `proxy/gemini/server.py` | `formatToLocalDateTimeWithOffset()` | **❌ 未实现** |
| `server.js` | `proxy/gemini/server.py` | `gracefulShutdown()` | **❌ 未实现** |
| `server.js` | `proxy/gemini/server.py` | `handleApiError()` | **❌ 未实现** |
| `server.js` | `proxy/gemini/server.py` | `handleDiaryFromAIResponse()` | **❌ 未实现** |
| `server.js` | `proxy/gemini/server.py` | `initialize()` | **✅ 已实现** |
| `server.js` | `proxy/gemini/server.py` | `loadBlacklist()` | **❌ 未实现** |
| `server.js` | `proxy/gemini/server.py` | `resolveAgentDir()` | **❌ 未实现** |
| `server.js` | `proxy/gemini/server.py` | `saveBlacklist()` | **❌ 未实现** |
| `server.js` | `proxy/gemini/server.py` | `startServer()` | **✅ 已实现 (重写为 uvicorn/fastapi)** |
| `server.js` | `proxy/gemini/server.py` | `updateAndLoadAgentEmojiList()` | **❌ 未实现** |
| `server.js` | `proxy/gemini/server.py` | `writeDebugLog()` | **❌ 未实现** |


## 4. 完全无关的脚本


- **..\..\﻿D:\workspace\github\VCPToolBox\AdminPanel\js\agent-assistant-config.js**: 不相关
- **AdminPanel\js\agent-manager.js**: 不相关
- **AdminPanel\js\config.js**: 不相关
- **AdminPanel\js\dashboard.js**: 不相关
- **AdminPanel\js\dream-manager.js**: 不相关
- **AdminPanel\js\forum.js**: 不相关
- **AdminPanel\js\log-viewer.js**: 不相关
- **AdminPanel\js\notes-manager.js**: 不相关
- **AdminPanel\js\placeholder-viewer.js**: 不相关
- **AdminPanel\js\plugins.js**: 不相关
- **AdminPanel\js\preprocessor-manager.js**: 不相关
- **AdminPanel\js\schedule-manager.js**: 不相关
- **AdminPanel\js\semantic-groups-editor.js**: 不相关
- **AdminPanel\js\thinking-chains-editor.js**: 不相关
- **AdminPanel\js\tvs-editor.js**: 不相关
- **AdminPanel\js\utils.js**: 不相关
- **AdminPanel\easymde.min.js**: 不相关
- **AdminPanel\marked.min.js**: 不相关
- **AdminPanel\script.js**: 不相关
- **AdminPanel\tool_list_editor.js**: 不相关
- **AdminPanel\vcptavern_editor.js**: 不相关
- **modules\handlers\nonStreamHandler.js**: 不相关
- **modules\handlers\streamHandler.js**: 不相关
- **modules\SSHManager\index.js**: 不相关
- **modules\SSHManager\SSHManager.js**: 不相关
- **modules\vcpLoop\toolCallParser.js**: 不相关
- **modules\vcpLoop\toolExecutor.js**: 不相关
- **modules\agentManager.js**: 不相关
- **modules\captchaDecoder.js**: 不相关
- **modules\contextManager.js**: 不相关
- **modules\logger.js**: 不相关
- **modules\roleDivider.js**: 不相关
- **modules\tvsManager.js**: 不相关
- **OpenWebUISub\openwebui_html_auto_render\html_live_preview_0.3.0.py**: 不相关
- **OpenWebUISub\openwebui_html_auto_render\openwebui_html_auto_render_0.5.0.js**: 不相关
- **OpenWebUISub\OpenWebUI Force HTML Image Renderer with Lightbox.user.js**: 不相关
- **OpenWebUISub\OpenWebUI VCP Tool Call Display Enhancer.user.js**: 不相关
- **Plugin\1PanelInfoProvider\1PanelInfoProvider.js**: 不相关
- **Plugin\1PanelInfoProvider\utils.js**: 不相关
- **Plugin\AgentAssistant\AgentAssistant.js**: 不相关
- **Plugin\AgentMessage\AgentMessage.js**: 不相关
- **Plugin\AnimeFinder\AnimeFinder.js**: 不相关
- **Plugin\ArtistMatcher\artist_matcher.py**: 不相关
- **Plugin\ArxivDailyPapers\ArxivDailyPapers.js**: 不相关
- **Plugin\BilibiliFetch\BilibiliFetch.py**: 不相关
- **Plugin\CapturePreprocessor\CapturePreprocessor.js**: 不相关
- **Plugin\ChromeBridge\ChromeBridge.js**: 不相关
- **Plugin\ComfyUIGen\ComfyUIGen.js**: 不相关
- **Plugin\ComfyUIGen\workflow-template-cli.js**: 不相关
- **Plugin\ComfyUIGen\WorkflowTemplateProcessor.js**: 不相关
- **Plugin\ComfyUIGen\workflow_converter.bat**: 不相关
- **Plugin\ComfyUIGen\workflow_template_processor.py**: 不相关
- **Plugin\CrossRefDailyPapers\CrossRefDailyPapers.js**: 不相关
- **Plugin\DailyHot\dist\routes\36kr.js**: 不相关
- **Plugin\DailyHot\dist\routes\51cto.js**: 不相关
- **Plugin\DailyHot\dist\routes\52pojie.js**: 不相关
- **Plugin\DailyHot\dist\routes\acfun.js**: 不相关
- **Plugin\DailyHot\dist\routes\baidu.js**: 不相关
- **Plugin\DailyHot\dist\routes\bilibili.js**: 不相关
- **Plugin\DailyHot\dist\routes\coolapk.js**: 不相关
- **Plugin\DailyHot\dist\routes\csdn.js**: 不相关
- **Plugin\DailyHot\dist\routes\dgtle.js**: 不相关
- **Plugin\DailyHot\dist\routes\douban-group.js**: 不相关
- **Plugin\DailyHot\dist\routes\douban-movie.js**: 不相关
- **Plugin\DailyHot\dist\routes\douyin.js**: 不相关
- **Plugin\DailyHot\dist\routes\geekpark.js**: 不相关
- **Plugin\DailyHot\dist\routes\genshin.js**: 不相关
- **Plugin\DailyHot\dist\routes\github.js**: 不相关
- **Plugin\DailyHot\dist\routes\guokr.js**: 不相关
- **Plugin\DailyHot\dist\routes\hackernews.js**: 不相关
- **Plugin\DailyHot\dist\routes\hellogithub.js**: 不相关
- **Plugin\DailyHot\dist\routes\history.js**: 不相关
- **Plugin\DailyHot\dist\routes\honkai.js**: 不相关
- **Plugin\DailyHot\dist\routes\hostloc.js**: 不相关
- **Plugin\DailyHot\dist\routes\hupu.js**: 不相关
- **Plugin\DailyHot\dist\routes\huxiu.js**: 不相关
- **Plugin\DailyHot\dist\routes\ifanr.js**: 不相关
- **Plugin\DailyHot\dist\routes\ithome-xijiayi.js**: 不相关
- **Plugin\DailyHot\dist\routes\ithome.js**: 不相关
- **Plugin\DailyHot\dist\routes\jianshu.js**: 不相关
- **Plugin\DailyHot\dist\routes\juejin.js**: 不相关
- **Plugin\DailyHot\dist\routes\kuaishou.js**: 不相关
- **Plugin\DailyHot\dist\routes\linuxdo.js**: 不相关
- **Plugin\DailyHot\dist\routes\lol.js**: 不相关
- **Plugin\DailyHot\dist\routes\miyoushe.js**: 不相关
- **Plugin\DailyHot\dist\routes\netease-news.js**: 不相关
- **Plugin\DailyHot\dist\routes\newsmth.js**: 不相关
- **Plugin\DailyHot\dist\routes\newsnow.js**: 不相关
- **Plugin\DailyHot\dist\routes\ngabbs.js**: 不相关
- **Plugin\DailyHot\dist\routes\nodeseek.js**: 不相关
- **Plugin\DailyHot\dist\routes\nytimes.js**: 不相关
- **Plugin\DailyHot\dist\routes\producthunt.js**: 不相关
- **Plugin\DailyHot\dist\routes\qq-news.js**: 不相关
- **Plugin\DailyHot\dist\routes\sina-news.js**: 不相关
- **Plugin\DailyHot\dist\routes\sina.js**: 不相关
- **Plugin\DailyHot\dist\routes\smzdm.js**: 不相关
- **Plugin\DailyHot\dist\routes\sspai.js**: 不相关
- **Plugin\DailyHot\dist\routes\starrail.js**: 不相关
- **Plugin\DailyHot\dist\routes\thepaper.js**: 不相关
- **Plugin\DailyHot\dist\routes\tieba.js**: 不相关
- **Plugin\DailyHot\dist\routes\toutiao.js**: 不相关
- **Plugin\DailyHot\dist\routes\v2ex.js**: 不相关
- **Plugin\DailyHot\dist\routes\weatheralarm.js**: 不相关
- **Plugin\DailyHot\dist\routes\weibo.js**: 不相关
- **Plugin\DailyHot\dist\routes\weread.js**: 不相关
- **Plugin\DailyHot\dist\routes\yystv.js**: 不相关
- **Plugin\DailyHot\dist\routes\zhihu-daily.js**: 不相关
- **Plugin\DailyHot\dist\routes\zhihu.js**: 不相关
- **Plugin\DailyHot\dist\utils\getToken\51cto.js**: 不相关
- **Plugin\DailyHot\dist\utils\getToken\bilibili.js**: 不相关
- **Plugin\DailyHot\dist\utils\getToken\coolapk.js**: 不相关
- **Plugin\DailyHot\dist\utils\getToken\weread.js**: 不相关
- **Plugin\DailyHot\dist\utils\cache.js**: 不相关
- **Plugin\DailyHot\dist\utils\getData.js**: 不相关
- **Plugin\DailyHot\dist\utils\getNum.js**: 不相关
- **Plugin\DailyHot\dist\utils\getRSS.js**: 不相关
- **Plugin\DailyHot\dist\utils\getTime.js**: 不相关
- **Plugin\DailyHot\dist\utils\logger.js**: 不相关
- **Plugin\DailyHot\dist\utils\parseRSS.js**: 不相关
- **Plugin\DailyHot\dist\config.js**: 不相关
- **Plugin\DailyHot\daily-hot.js**: 不相关
- **Plugin\DeepWikiVCP\deepwiki_vcp.js**: 不相关
- **Plugin\DMXDoubaoGen\DoubaoGen.js**: 不相关
- **Plugin\DoubaoGen\DoubaoGen.js**: 不相关
- **Plugin\EmojiListGenerator\emoji-list-generator.js**: 不相关
- **Plugin\FileListGenerator\file-list-generator.js**: 不相关
- **Plugin\FileOperator\CodeValidator.js**: 不相关
- **Plugin\FileOperator\FileOperator.js**: 不相关
- **Plugin\FileServer\file-server.js**: 不相关
- **Plugin\FileTreeGenerator\FileTreeGenerator.js**: 不相关
- **Plugin\FlashDeepSearch\FlashDeepSearch.js**: 不相关
- **Plugin\FRPSInfoProvider\FRPSInfoProvider.js**: 不相关
- **Plugin\GeminiImageGen\GeminiImageGen.js**: 不相关
- **Plugin\GoogleSearch\search.js**: 不相关
- **Plugin\GrokVideo\video_handler.py**: 不相关
- **Plugin\ImageProcessor\image-processor.js**: 不相关
- **Plugin\ImageProcessor\purge_old_cache.js**: 不相关
- **Plugin\ImageProcessor\reidentify_image.js**: 不相关
- **Plugin\ImageServer\image-server.js**: 不相关
- **Plugin\IMAPIndex\proxy\ImapHttpTunnel.js**: 不相关
- **Plugin\IMAPIndex\IMAPIndex.js**: 不相关
- **Plugin\IMAPIndex\post_run.js**: 不相关
- **Plugin\IMAPSearch\index.js**: 不相关
- **Plugin\JapaneseHelper\install_plugin_requirements.bat**: 不相关
- **Plugin\JapaneseHelper\JapaneseHelper.py**: 不相关
- **Plugin\KarakeepSearch\index.js**: 不相关
- **Plugin\LinuxLogMonitor\core\AnomalyDetector.js**: 不相关
- **Plugin\LinuxLogMonitor\core\CallbackTrigger.js**: 不相关
- **Plugin\LinuxLogMonitor\core\MonitorManager.js**: 不相关
- **Plugin\LinuxLogMonitor\core\MonitorTask.js**: 不相关
- **Plugin\LinuxLogMonitor\LinuxLogMonitor.js**: 不相关
- **Plugin\LinuxShellExecutor\ssh\SSHManager.js**: 不相关
- **Plugin\LinuxShellExecutor\LinuxShellExecutor.js**: 不相关
- **Plugin\MagiAgent\MagiAgent.js**: 不相关
- **Plugin\MCPO\mcpo_plugin.py**: 不相关
- **Plugin\MCPOMonitor\mcpo_monitor.js**: 不相关
- **Plugin\MIDITranslator\MIDITranslator.js**: 不相关
- **Plugin\NovelAIGen\NovelAIGen.js**: 不相关
- **Plugin\PaperReader\lib\chunker.js**: 不相关
- **Plugin\PaperReader\lib\deep-reader.js**: 不相关
- **Plugin\PaperReader\lib\ingest.js**: 不相关
- **Plugin\PaperReader\lib\llm.js**: 不相关
- **Plugin\PaperReader\lib\mineru-client.js**: 不相关
- **Plugin\PaperReader\lib\pdf-parse-fallback.js**: 不相关
- **Plugin\PaperReader\lib\query.js**: 不相关
- **Plugin\PaperReader\lib\reading-state.js**: 不相关
- **Plugin\PaperReader\lib\skeleton.js**: 不相关
- **Plugin\PaperReader\lib\skim-reader.js**: 不相关
- **Plugin\PaperReader\PaperReader.js**: 不相关
- **Plugin\PowerShellExecutor\PowerShellExecutor.js**: 不相关
- **Plugin\ProjectAnalyst\AnalysisDelegate.js**: 不相关
- **Plugin\ProjectAnalyst\GUI.py**: 不相关
- **Plugin\ProjectAnalyst\ProjectAnalyst.js**: 不相关
- **Plugin\PyCameraCapture\capture.py**: 不相关
- **Plugin\PyScreenshot\screenshot.py**: 不相关
- **Plugin\QwenImageGen\QwenImageGen.js**: 不相关
- **Plugin\Randomness\dice_roller.py**: 不相关
- **Plugin\Randomness\main.py**: 不相关
- **Plugin\ScheduleBriefing\ScheduleBriefing.js**: 不相关
- **Plugin\ScheduleManager\ScheduleManager.js**: 不相关
- **Plugin\SciCalculator\calculator.py**: 不相关
- **Plugin\SerpSearch\engines\bing.js**: 不相关
- **Plugin\SerpSearch\engines\duckduckgo.js**: 不相关
- **Plugin\SerpSearch\engines\google.js**: 不相关
- **Plugin\SerpSearch\engines\google_reverse_image.js**: 不相关
- **Plugin\SerpSearch\engines\google_scholar.js**: 不相关
- **Plugin\SerpSearch\SerpSearch.js**: 不相关
- **Plugin\SVCardFinder\card_finder.py**: 不相关
- **Plugin\SynapsePusher\SynapsePusher.js**: 不相关
- **Plugin\TarotDivination\Celestial.py**: 不相关
- **Plugin\TarotDivination\tarot_divination.js**: 不相关
- **Plugin\TavilySearch\TavilySearch.js**: 不相关
- **Plugin\TencentCOSBackup\cos_handler.py**: 不相关
- **Plugin\ThoughtClusterManager\ThoughtClusterManager.js**: 不相关
- **Plugin\UrlFetch\UrlFetch.js**: 不相关
- **Plugin\UserAuth\auth.js**: 不相关
- **Plugin\VCPEverything\local-search-controller.js**: 不相关
- **Plugin\VCPForum\VCPForum.js**: 不相关
- **Plugin\VCPForumAssistant\vcp-forum-assistant.js**: 不相关
- **Plugin\VCPForumLister\VCPForumLister.js**: 不相关
- **Plugin\VCPLog\VCPLog.js**: 不相关
- **Plugin\VCPTavern\VCPTavern.js**: 不相关
- **Plugin\VideoGenerator\video_handler.py**: 不相关
- **Plugin\VSearch\VSearch.js**: 不相关
- **Plugin\WeatherInfoNow\weather-info-now.js**: 不相关
- **Plugin\WeatherReporter\weather-reporter.js**: 不相关
- **Plugin\WorkspaceInjector\injector.js**: 不相关
- **Plugin\XiaohongshuFetch\sign_server.js**: 不相关
- **Plugin\XiaohongshuFetch\XiaohongshuFetch.py**: 不相关
- **Plugin\XiaohongshuFetch\xs.js**: 不相关
- **routes\forumApi.js**: 不相关
- **routes\specialModelRouter.js**: 不相关
- **routes\taskScheduler.js**: 不相关
- **SillyTavernSub\ST油猴插件-酒馆VCP-VCP时钟.js**: 不相关
- **SillyTavernSub\ST油猴插件-酒馆VCP-VCP渲染.js**: 不相关
- **SillyTavernSub\ST油猴插件-酒馆VCP-通知栏.js**: 不相关
- **VCPChrome\background.js**: 不相关
- **VCPChrome\content_script.js**: 不相关
- **VCPChrome\popup.js**: 不相关
- **backup_vcp.py**: 不相关
- **example.test.js**: 不相关
- **FileFetcherServer.js**: 不相关
- **modelRedirectHandler.js**: 不相关
- **reset_vectordb.js**: 不相关
- **start_server.bat**: 不相关
- **test-units.js**: 不相关
- **timeline整理器.py**: 不相关
- **update.bat**: 不相关
- **update_with_no_dependency.bat**: 不相关
- **vcpInfoHandler.js**: 不相关
- **VCPWinNotify.Py**: 不相关
- **WebSocketServer.js**: 不相关
- **WinNotify.py**: 不相关
- **WorkerPool.js**: 不相关


