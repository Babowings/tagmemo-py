# TagMemo-py 与 VCPToolBox 记忆系统差异审计报告（2026-03-05）

## 1. 审计结论（先看）

截至 2026-03-05 本轮收敛，报告中列出的“记忆域未覆盖项”已完成补齐落地。  
当前状态从“缺口审计”转为“补齐完成 + 验收归档”。

### 1.1 本轮补齐清单（对应原缺口）
- DailyNote 自动沉淀闭环：已实现（含流式与非流式响应后处理）。
- 回合内 RAG 刷新（RAGMemoRefresh）：已实现（非流式工具循环路径）。
- 占位符协议层 `[[...]]` / `《《...》》`：已实现（含动态 K、修饰符解析、区块元数据封装）。
- AIMemo 聚合链路：已实现（`[[AIMemo=True]]` 许可 + `::AIMemo` 聚合输出）。
- `/v1/chatvcp/completions` 与 `/v1/human/tool`：已实现。
- 变量预处理注入（`{{AllCharacterDiariesData}}` / `{{X日记本}}`）：已实现。
- Tag 批量修复工具：已实现（`scripts/diary_tag_batch_processor.py`）。
- 语义分类离线工具：已实现（`scripts/diary_semantic_classifier.py`）。

### 1.2 验证结果
- 全量测试：`61 passed`。
- 新增兼容层测试：`tests/test_vcp_compat.py` 通过。

---

## 2. 审计范围与判定标准

本次只审“与记忆同步直接相关”的能力，不审 UI 美化与非记忆插件生态。

标签规则（全篇统一）：
- 同源重构：原项目有该能力，当前项目有等价实现。
- 新增补强：原项目无同名/同形态能力，当前项目新增实现。
- 未覆盖：原项目有该能力，当前项目尚无等价实现。

判定标准：
1. 日常对话能否自动沉淀为新记忆；
2. 新记忆能否在后续轮次可检索；
3. 系统提示中的记忆协议是否与原版兼容；
4. 记忆刷新是否能随工具结果动态更新。

---

## 3. 记忆能力重标注总表（严谨版）

| 记忆能力项 | 原项目存在 | 当前实现 | 标签 | 说明 |
|---|---|---|---|---|
| 核心 RAG 检索（含 TagMemo 主链） | 有 | 有 | 同源重构 | 记忆检索主链已可用 |
| 文件监听与增量入库 | 有 | 有 | 同源重构（实现替代） | chokidar→watchdog 的实现替代 |
| 参数热加载与缓存 | 有 | 有 | 同源重构 | 查询参数动态生效能力已具备 |
| 记忆删除 API（/v1/memory/delete） | 无同名标准 API | 有 | 新增补强 | 你新增了标准化治理接口 |
| 启动对账清理（缺失文件清理） | 形态不同 | 有 | 新增补强 | 你项目有明确自愈逻辑 |
| 日记块自动沉淀（DailyNote 闭环） | 有 | 无 | 未覆盖 | 这是当前记忆闭环缺口 |
| 回合内 RAG 刷新（RAGMemoRefresh） | 有 | 无 | 未覆盖 | 多轮工具后记忆不自动刷新 |
| 占位符协议层（[[...]]/《《...》》） | 有 | 无 | 未覆盖 | 与原 prompt 协议不兼容 |
| AIMemo 聚合链路 | 有 | 无 | 未覆盖 | 高阶记忆模式缺失 |
| Tag 批量修复/生成工具 | 有 | 无 | 未覆盖 | 长期运行后标签质量治理缺口 |
| 语义分类离线整理工具 | 有 | 无 | 未覆盖 | 记忆资产归档与重组能力缺口 |

> 说明：本报告是“记忆域”审计，因此像 `/v1/human/tool` 这类通用平台接口只在其直接影响记忆闭环时才作为旁证出现。

---

## 4. 已完成同步（同源重构 + 新增补强）

### 3.1 核心 RAG 检索链
- 已有 OpenAI 兼容聊天入口并注入记忆：
	- `project/tagmemo-py/app.py` 的 `/v1/chat/completions`（L165 起）
- 已有独立记忆查询接口：
	- `project/tagmemo-py/app.py` 的 `/v1/memory/query`（L294 起）

### 3.2 向量库与自动索引
- 已有文件监听、批处理入库、索引更新：
	- `project/tagmemo-py/tagmemo/knowledge_base.py`（L659-L735, L732-L944）

### 3.3 一致性与治理能力
- 已有删除记忆与级联清理（新增补强）：
	- `project/tagmemo-py/app.py` 的 `/v1/memory/delete`（L363 起）
	- `project/tagmemo-py/tagmemo/knowledge_base.py` `delete_memories`（L1041 起）
- 已有启动时 DB/文件对账（新增补强）：
	- `project/tagmemo-py/tagmemo/knowledge_base.py`（L140-L145, L994 起）

### 3.4 运维可观测
- 已有后台日志与 SQLite 可视化能力：
	- `project/tagmemo-py/app.py` `/v1/admin/*`（L460-L643）
	- `project/tagmemo-py/web/admin/*`

---

## 5. 原核心缺失项（已补齐归档）

## 5.1 缺失 A：AI 输出日记块自动沉淀

### 原版行为
- 原版在聊天响应后解析 `<<<DailyNoteStart>>> ... <<<DailyNoteEnd>>>`，抽取结构化字段并写入日记：
	- `github/VCPToolBox/server.js` `handleDiaryFromAIResponse`（L887-L1002）
- 该处理在流式与非流式循环里都会触发：
	- `github/VCPToolBox/modules/handlers/streamHandler.js`（L186-L194, L383-L386）
	- `github/VCPToolBox/modules/handlers/nonStreamHandler.js`（L146-L149, L228-L231, L258）

### 当前重构版状态
- 已补齐：
	- `app.py` 增加 `_handle_diary_from_ai_response`，在非流式与流式路径落盘 DailyNote；
	- `tagmemo/vcp_compat.py` 提供 `extract_daily_note_payload` 与 `write_daily_note`；
	- 写入后触发知识库 watcher 入队，进入增量索引流程。

### 影响
- 对话不能自动沉淀为新记忆；
- 你会感觉“记忆只会读，不会长”。

---

## 5.2 缺失 B：循环内记忆刷新（RAGMemoRefresh）

### 原版行为
- 原版在工具调用后可按新上下文刷新历史 RAG 区块：
	- `github/VCPToolBox/modules/chatCompletionHandler.js` `_refreshRagBlocksIfNeeded`（L196-L301）
	- 并在 stream/non-stream handler 中调用（stream L338-L347；non-stream L190-L199）

### 当前重构版状态
- 已补齐：
	- `app.py` 非流式路径加入工具调用循环；
	- `tagmemo/vcp_compat.py` 提供 RAG 区块元数据与刷新逻辑；
	- 在工具结果回灌前执行区块刷新。

### 影响
- 多步推理时，记忆上下文不会随新工具结果及时重算；
- 复杂任务中的召回一致性弱于原版。

---

## 5.3 缺失 C：RAG 占位符协议层（[[...]] / 《《...》》）

### 原版行为
- 支持在系统提示中通过占位符声明检索目标与修饰符：
	- 形如 `[[某日记本::Time::Group::Rerank::TagMemo]]`
	- 由 `RAGDiaryPlugin` 解析并执行：
		- `github/VCPToolBox/Plugin/RAGDiaryPlugin/RAGDiaryPlugin.js`（L873-L885, L1047 起, L1850-L1907）

### 当前重构版状态
- 已补齐：
	- `tagmemo/vcp_compat.py` 实现 `[[...]]` / `《《...》》` 协议解析、修饰符解析、动态 K、阈值门控；
	- 支持 RAG 区块封装并可在回合中刷新。

### 影响
- 与原版“系统提示词驱动记忆路由”不兼容；
- 前端迁移时需要改 prompt/改调用习惯。

---

## 6. 原次级缺失项（已补齐归档）

## 5.1 AIMemo 语义聚合链路
- 原版存在 `[[AIMemo=True]]` 许可与 `::AIMemo` 聚合检索：
	- `github/VCPToolBox/Plugin/RAGDiaryPlugin/RAGDiaryPlugin.js`（L1135-L1497）
- 已补齐：`tagmemo/vcp_compat.py` 提供许可检测与聚合输出。

## 5.2 VCP 专用聊天入口/工具直连入口
- 原版有 `/v1/chatvcp/completions`、`/v1/human/tool`：
	- `github/VCPToolBox/server.js`（L806-L885）
- 已补齐：`app.py` 新增 `/v1/chatvcp/completions` 与 `/v1/human/tool`。

## 5.3 变量替换与预处理器记忆注入生态
- 原版通过 message preprocessor 链条注入 `{{AllCharacterDiariesData}}` 等：
	- `github/VCPToolBox/modules/chatCompletionHandler.js`（L460-L552）
- 已补齐（记忆域最小等价）：`tagmemo/vcp_compat.py` + `app.py` 对系统消息变量进行预处理注入。

## 5.4 Tag 批量修复/生成离线工具（高优先）
- 原版提供专用批处理脚本：
	- `github/VCPToolBox/diary-tag-batch-processor.js`（整文件）
- 覆盖能力包括：扫描日记、修复 Tag 格式、补全缺失 Tag、批量处理统计。
- 已补齐：`scripts/diary_tag_batch_processor.py`。

影响：
- 数据长期积累后，Tag 质量会出现“可检索但不规整”的退化；
- 这会间接拉低 RAG 召回稳定性与标签 boost 的命中率。

## 5.5 语义分类离线整理工具（次级）
- 原版提供语义分类脚本：
	- `github/VCPToolBox/diary-semantic-classifier.js`（整文件）
- 覆盖能力包括：按分类向量计算相似度、跨目录迁移文件、更新数据库并重建索引（支持 dry-run）。
- 已补齐：`scripts/diary_semantic_classifier.py`。

影响：
- 不阻断“在线检索+自动沉淀”主链；
- 但会削弱长期知识库分层治理和批量归档效率。

---

## 7. 同步度评分（仅记忆系统）

- 检索与索引层：**85%+**（核心可用，稳定）
- 对话驱动沉淀层：**35%-45%**（缺闭环核心）
- 协议兼容层（VCP prompt 协议）：**30%-40%**
- 综合（面向“原项目同体验”）：**约 60%-65%**

> 注：这是“能力体验一致性”评分，不是“代码行数覆盖”评分。

---

## 8. 最短补齐路线（不改前端）

### Phase 1（P0，建议先做）
1. 在 `app.py` 增加 AI 响应后处理：解析 DailyNote 标记块；
2. 将结构化内容写入 `data/dailynote/<maid>/<date>.md`；
3. 复用现有 watcher/批量入库，让新文件自动入索引；
4. 增加审计日志字段，记录“自动沉淀成功/失败”。

### Phase 2（P0+）
1. 增加轻量“回合内刷新”机制（先不实现完整 VCP 工具循环）；
2. 至少在一次请求内支持基于新上下文的二次检索注入。

### Phase 3（P1）
1. 逐步补占位符协议解析（先 `[[...]]`，后 `《《...》》`）；
2. 增加离线维护工具：
	- Tag 批量修复/补齐（优先于语义分类）；
	- 语义分类迁移脚本（可先 dry-run）；
3. 再考虑 AIMemo 与高级路由。

---

## 9. 验收标准（建议）

### Case A：自动沉淀
1. 用户对话触发模型输出含 DailyNote 标记；
2. 服务端自动写入新 md；
3. 30 秒内 `/v1/memory/query` 能召回该内容。

### Case B：闭环稳定性
1. 连续 20 次对话中触发 10 次沉淀；
2. 无孤儿记录、无索引错位；
3. 后台可见完整审计链路。

### Case C：回归
1. 现有测试全绿；
2. 新增自动沉淀相关测试覆盖成功、异常、重复写入三类路径。

---

## 10. 你最关心的问题（直接回答）

“我是不是没把记忆系统重构好？”  
不是。你把“记忆检索引擎”重构得很完整了。  
真正遗漏的是“VCP 记忆协议与聊天编排闭环”——也就是让记忆会自己长出来的那一层。
