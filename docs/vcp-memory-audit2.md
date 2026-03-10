# 记忆数据源与管道扩展支持脚本 — 审计复核报告

**日期**: 2026-03-10

---

## `rag-tuning.js` → 无对应文件

### 未实现 → 复核结果

| 函数 | 复核 | 是否需要实现 |
|------|------|------------|
| `handleSave()` | ❌ **确认未实现** | ⚠️ **建议实现**。保存 RAG 参数到 rag_params.json。你的项目目前可通过手动编辑文件 + `/v1/params/reload` 替代，但没有 Web UI 编辑能力 |
| `initializeRAGTuning()` | ❌ **确认未实现** | 🟢 **不需要实现**。前端 UI 初始化 |
| `loadParams()` | ❌ **确认未实现** | ⚠️ 已有 `engine.reload_params` + `knowledge_base.load_rag_params`，功能已覆盖。**无需额外实现** |
| `renderParams()` | ❌ **确认未实现** | 🟢 **不需要实现**。前端渲染 |

---

## `dailynote.js` → 无对应文件

### 未实现 → 复核结果

| 函数 | 复核 | 是否需要实现 |
|------|------|------------|
| `handleCreateCommand()` | ⚠️ **部分已实现！** | `vcp_compat.write_daily_note` (第77行) + `app._handle_diary_from_ai_response` (第1125行) 实现了创建日记的核心逻辑。**你漏检了** |
| `handleUpdateCommand()` | ❌ **确认未实现** | ⚠️ **建议实现**。追加/更新已有日记内容 |
| `detectTagLine()` | ❌ **在 tagmemo 核心中未实现** | ⚠️ **建议实现**。在 `scripts/diary_tag_batch_processor.py` 中有，但未集成到日记写入流程。写入日记时不会自动检测/生成标签 |
| `fixTagFormat()` | ❌ **同上** | 同上 |
| `processTags()` | ❌ **同上** | 同上 |
| `sanitizePathComponent()` | ⚠️ **已实现！** | `vcp_compat._safe_name` (第102行)。**你漏检了** |
| `sanitizeServerFilename()` | ⚠️ **已实现！** | `vcp_compat._safe_asset_name` (第106行)。**你漏检了** |
| `isPathWithinBase()` | ❌ **确认未实现** | 🔵 低优先级。安全检查，FastAPI 已有类似路径校验 |
| `processLocalFiles()` | ❌ **确认未实现** | 🟢 **不需要实现**。处理上传的本地文件，VCP 特有功能 |
| `debugLog()` | ❌ **确认未实现** | 🟢 **不需要实现**。调试日志，Python 有 logging |
| `main()` | ❌ **确认未实现** | 🟢 **不需要实现**。入口点，已被 app.py 替代 |

---

## `daily-note-manager.js` → 无对应文件

| 函数 | 复核 | 是否需要实现 |
|------|------|------------|
| `processDailyNotes()` | ❌ **确认未实现** | 🟢 **不需要实现**。前端管理面板批处理功能 |
| `saveCurrentNote()` | ❌ **确认未实现** | 🟢 **不需要实现**。前端管理面板保存 |

---

## `daily-note-write.js` → 无对应文件

### 未实现 → 复核结果

| 函数 | 复核 | 是否需要实现 |
|------|------|------------|
| `writeDiary()` | ⚠️ **已实现！** | `vcp_compat.write_daily_note` (第77行)。**你漏检了** |
| `generateTagsWithAI()` | ❌ **核心流程中未实现** | 🔴 **需要实现**。写入日记时自动调用 AI 生成标签，这是 TagMemo 的核心功能 |
| `processTagsInContent()` | ❌ **确认未实现** | 🔴 **需要实现**。与上面配套 |
| `detectTagLine()` | ❌ **核心流程中未实现** | ⚠️ **建议实现**。写入时检测已有标签行 |
| `extractTagFromAIResponse()` | ❌ **核心流程中未实现** | ⚠️ **建议实现**。从 AI 响应中提取标签 |
| `fixTagFormat()` | ❌ **核心流程中未实现** | ⚠️ **建议实现**。标准化标签格式 |
| `sanitizePathComponent()` | ⚠️ **已实现！** | 同上 `_safe_name`。**你漏检了** |
| `sendOutput()` | ❌ **确认未实现** | 🟢 **不需要实现**。原版向 stdout 输出 JSON 给宿主进程 |
| `debugLog()` | ❌ **确认未实现** | 🟢 **不需要实现**。Python logging 替代 |
| `delay()` | ❌ **确认未实现** | 🟢 **不需要实现**。`asyncio.sleep` 替代 |
| `main()` | ❌ **确认未实现** | 🟢 **不需要实现**。入口点 |

---

## Stork/PubMed 论文管道脚本

以下脚本均为**论文检索管道**，与 TagMemo 核心记忆功能无关：

- `extract_stork_links.js` — 🟢 **不需要实现**。论文 DOI 提取
- `fetch_stork_pages.js` — 🟢 **不需要实现**。论文页面抓取
- `html_to_md.js` — 🟢 **不需要实现**。HTML 转 Markdown
- `md_to_txt.js` — 🟢 **不需要实现**。Markdown 转 TXT
- `fetch_pubmed_similars.js` — 🟢 **不需要实现**。PubMed 相似论文检索

这些是原项目特有的论文数据源管道，你的 tagmemo-py 项目不需要这些。如果以后有需求，可以作为独立脚本补充。

---

## `LightMemo.js` → 无对应文件

### 未实现 → 复核结果

**LightMemo 是一个独立的轻量级记忆插件**，与 TagMemo RAG 引擎并行存在。它使用 BM25 + TF-IDF 做粗检索，向量做精排。

| 结论 | 说明 |
|------|------|
| ❌ **全部未实现** | 确认所有 18 个函数都未实现 |
| 🔵 **建议延期** | LightMemo 是独立系统，不影响 TagMemo 核心功能。建议上线后再考虑 |

---

## `AIMemoHandler.js` → `proxy/common/request_inspector.py`

### 已实现 — 复核结果

| 函数 | 复核 | 说明 |
|------|------|------|
| `processAIMemo()` | ⚠️ **名义上已实现，但实质不同** | `request_inspector.py` 只是一个请求拦截/日志工具，并非真正的 AIMemo 实现。原版 AIMemo 会调用 AI Model 从全量日记中提炼记忆 |
| `processAIMemoAggregated()` | ⚠️ **同上** | 同上 |

### 未实现 — 复核结果

| 函数 | 复核 | 是否需要实现 |
|------|------|------------|
| 全部 17 个子函数 | ❌ **确认未实现** | 🔵 **建议延期**。AIMemo 是一个完整的独立子系统（AI 驱动的记忆提炼），实现工量大。核心 RAG 检索不依赖它 |

---

## `MetaThinkingManager.js` → 无对应文件

| 函数 | 复核 | 是否需要实现 |
|------|------|------------|
| 全部 6 个函数 | ❌ **确认未实现** | 🔵 **建议延期**。元思考链是递归 RAG 的高级功能，不影响基础记忆检索 |

---

## `test_reranker.js` → ✅ 无异议

## `timeExpressions.config.js` → ✅ 无异议

---

## `SemanticGroupEditor.js` → 无对应文件

| 函数 | 复核 | 是否需要实现 |
|------|------|------------|
| `readSemanticGroupsFile()` | ⚠️ **已实现！** | `semantic_groups._load_groups` (第136行)。**你漏检了** |
| `writeSemanticGroupsFile()` | ⚠️ **已实现！** | `semantic_groups._save_groups` (第175行)。**你漏检了** |
| `updateGroups()` | ⚠️ **已实现！** | `semantic_groups.update_groups_data` (第197行)。**你漏检了** |
| `queryGroups()` | ❌ **确认未实现** | 🔵 低优先级。CLI 查询工具 |
| `main()` | ❌ **确认未实现** | 🟢 **不需要实现**。CLI 入口 |

---

## `dailyNotesRoutes.js` → `tagmemo/vcp_compat.py`

### 已实现 — 复核结果

| 函数 | 复核 |
|------|------|
| `constructor()` | ✅ **正确** |
| `executeSearch()` | ✅ **正确** — `engine.query` |
| `searchPromise()` | ✅ **正确** — 底层统一封装 |

### 未实现 → 复核结果

| 函数 | 复核 | 是否需要实现 |
|------|------|------------|
| `acquire() / release()` | ❌ **确认未实现** | 🟢 **不需要实现**。JS 信号量并发控制，Python 用 `asyncio.Semaphore` 可在需要时添加 |
| `checkAbort()` | ❌ **确认未实现** | 🟢 **不需要实现**。请求取消检测，FastAPI 原生支持 |
| `hashSearchParams()` | ❌ **确认未实现** | ⚠️ 已由 `engine._generate_cache_key` 覆盖。**无需额外实现** |
| `isPathSafe() / isSymlink()` | ❌ **确认未实现** | 🔵 低优先级。安全检查 |
| `onClose()` | ❌ **确认未实现** | 🟢 **不需要实现**。HTTP 连接关闭回调 |
| `queuedSearch()` | ❌ **确认未实现** | 🟢 **不需要实现**。队列化搜索，Python asyncio 天然串行 |
| `yieldToEventLoop()` | ❌ **确认未实现** | 🟢 **不需要实现**。JS 特有的事件循环让步 |

---

## `index.js` → `tagmemo/vector_index.py`

| 函数 | 复核 | 是否需要实现 |
|------|------|------------|
| `isMusl()` | ❌ **确认未实现** | 🟢 **不需要实现**。检测 musl/glibc 以加载不同 native addon。Python 项目使用不同的构建机制 |

---

## `test.js` → 🟢 **不需要实现**。测试文件

