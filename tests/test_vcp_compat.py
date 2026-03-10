from __future__ import annotations

from pathlib import Path

import pytest

from tagmemo.vcp_compat import (
    VCPPlaceholderProcessor,
    _get_average_threshold,
    _parse_aggregate_syntax,
    _strip_system_notification,
    detect_tag_line,
    extract_daily_note_payload,
    extract_tag_from_ai_response,
    fix_tag_format,
    parse_tool_requests,
    process_tags_in_content,
    replace_variable_placeholders,
    build_tool_payload_for_rag,
    update_daily_note,
    write_daily_note,
)


class _DummyEmbedding:
    async def embed(self, text: str):
        if "无关" in text:
            return [0.0, 1.0, 0.0]
        if "NO_VECTOR" in text:
            return None
        return [1.0, 0.0, 0.0]


class _DummyKB:
    def __init__(self, root_path: Path | None = None):
        self.config = {"root_path": str(root_path) if root_path else ""}

    def get_diary_name_vector(self, diary_name: str):
        if diary_name == "工作":
            return [1.0, 0.0, 0.0]
        return [0.0, 0.0, 1.0]


class _DummyKBWithPluginCache(_DummyKB):
    def __init__(self, root_path: Path | None = None):
        super().__init__(root_path)
        self.plugin_vector_calls: list[str] = []

    async def get_plugin_description_vector(self, desc_text: str, get_embedding_fn):
        self.plugin_vector_calls.append(desc_text)
        return [1.0, 0.0, 0.0]


class _DummyEngine:
    def __init__(self, root_path: Path | None = None):
        self.embedding_service = _DummyEmbedding()
        self.knowledge_base = _DummyKB(root_path)
        self.enhanced_vector_cache: dict[str, list[float]] = {}
        self.query_calls: list[dict] = []

    def get_enhanced_diary_vector(self, diary_name: str):
        return self.enhanced_vector_cache.get(diary_name)

    async def query(self, user_message, history, options=None):
        self.query_calls.append(
            {
                "user_message": user_message,
                "history": history,
                "options": dict(options or {}),
            }
        )
        diary = (options or {}).get("diary_name") or "unknown"
        return {
            "memory_context": f"[{diary}] {user_message}",
            "metrics": {},
            "results": [],
        }


class _DummyEngineWithPluginCache(_DummyEngine):
    def __init__(self, root_path: Path | None = None):
        super().__init__(root_path)
        self.knowledge_base = _DummyKBWithPluginCache(root_path)


class _DummyAIMemoHandler:
    def __init__(self):
        self.calls: list[dict] = []

    async def process_aimemo_aggregated(self, db_names, user_content, ai_content, combined_query_for_display):
        self.calls.append(
            {
                "db_names": list(db_names),
                "user_content": user_content,
                "ai_content": ai_content,
                "combined_query_for_display": combined_query_for_display,
            }
        )
        return f"[跨库联合检索: {' + '.join(db_names)}]\n这是我获取的所有相关知识/记忆[[AI总结结果]]"


class _DummyMetaThinkingManager:
    def __init__(self):
        self.calls: list[dict] = []

    async def process_meta_thinking_chain(
        self,
        chain_name,
        query_vector,
        user_content,
        ai_content,
        combined_query_for_display,
        k_sequence,
        use_group,
        is_auto_mode=False,
        auto_threshold=0.65,
    ):
        self.calls.append(
            {
                "chain_name": chain_name,
                "query_vector": query_vector,
                "user_content": user_content,
                "ai_content": ai_content,
                "combined_query_for_display": combined_query_for_display,
                "k_sequence": k_sequence,
                "use_group": use_group,
                "is_auto_mode": is_auto_mode,
                "auto_threshold": auto_threshold,
            }
        )
        return "[--- VCP元思考链: \"default\" ---]\n【阶段1: 前思维簇】\n  * 测试推理结果\n[--- 元思考链结束 ---]"


class _DummyEngineWithAdvancedHandlers(_DummyEngine):
    def __init__(self, root_path: Path | None = None):
        super().__init__(root_path)
        self.ai_memo_handler = _DummyAIMemoHandler()
        self.meta_thinking_manager = _DummyMetaThinkingManager()


def test_extract_daily_note_payload():
    payload = extract_daily_note_payload(
        """
        hello
        <<<DailyNoteStart>>>
        Maid: 小克
        Date: 2026-03-05
        Content: 今天完成了协议层补齐。
        <<<DailyNoteEnd>>>
        world
        """
    )
    assert payload is not None
    assert payload["maid_name"] == "小克"
    assert payload["date_string"] == "2026-03-05"
    assert "协议层" in payload["content_text"]


def test_parse_tool_requests():
    text = """
    <<<[TOOL_REQUEST]>>>
    tool_name:「始」TagMemoMemoryQuery「末」,
    message:「始」你好「末」
    <<<[END_TOOL_REQUEST]>>>
    """
    calls = parse_tool_requests(text)
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "TagMemoMemoryQuery"
    assert calls[0]["params"]["message"] == "你好"


def test_detect_and_fix_tag_line_helpers() -> None:
    has_tag, last_line, body = detect_tag_line("正文\nTag: 系统设计，记忆检索")

    assert has_tag is True
    assert last_line == "Tag: 系统设计，记忆检索"
    assert body == "正文"
    assert fix_tag_format(last_line) == "Tag: 系统设计, 记忆检索"
    assert extract_tag_from_ai_response("[[Tag: 记忆系统, Python]]") == "Tag: 记忆系统, Python"


def test_strip_system_notification_removes_appended_notice() -> None:
    text = "原始问题\n[系统通知]\n这里是追加的系统通知\n[系统通知结束]"
    assert _strip_system_notification(text) == "原始问题"


def test_build_tool_payload_for_rag_converts_json_to_markdown() -> None:
    payload = build_tool_payload_for_rag(
        [
            {
                "title": "工具结果",
                "data": {
                    "summary": "已完成",
                    "blob": "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=" * 8,
                },
            }
        ]
    )

    assert "title" in payload.lower()
    assert "已完成" in payload
    assert "blob" in payload.lower()
    assert "[Data Omitted]" in payload
    assert "QUJD" not in payload


def test_parse_aggregate_syntax_and_average_threshold() -> None:
    parsed = _parse_aggregate_syntax("工作|生活", "::TIME:2")

    assert parsed["is_aggregate"] is True
    assert parsed["diary_names"] == ["工作", "生活"]
    assert parsed["k_multiplier"] == 2.0

    threshold = _get_average_threshold(
        ["工作", "生活"],
        {
            "工作": {"threshold": 0.2},
            "生活": {"threshold": 0.6},
        },
        default_threshold=0.3,
    )
    assert threshold == pytest.approx(0.4)


@pytest.mark.asyncio
async def test_placeholder_processor_replaces_rag_and_aimemo():
    processor = VCPPlaceholderProcessor(_DummyEngine())
    messages = [
        {"role": "system", "content": "[[AIMemo=True]]\nA:[[知识日记本::AIMemo]]\nB:[[工作日记本::Rerank]]"},
        {"role": "user", "content": "总结一下"},
    ]
    out = await processor.process_system_messages(messages, user_content="总结一下", ai_content="")
    content = out[0]["content"]
    assert "AIMemo=True" not in content
    assert "VCP_RAG_BLOCK_START" in content
    assert "这是我获取的所有相关知识/记忆[[" in content
    assert "[工作]" in content


@pytest.mark.asyncio
async def test_placeholder_processor_aimemo_delegates_to_handler_instead_of_engine_query() -> None:
    engine = _DummyEngineWithAdvancedHandlers()
    processor = VCPPlaceholderProcessor(engine)
    messages = [
        {"role": "system", "content": "[[AIMemo=True]]\nA:[[知识日记本::AIMemo]]\nB:[[工作日记本::Rerank]]"},
        {"role": "user", "content": "总结一下"},
    ]

    out = await processor.process_system_messages(messages, user_content="总结一下", ai_content="上一轮回复")

    content = out[0]["content"]
    assert "AI总结结果" in content
    assert engine.ai_memo_handler.calls == [
        {
            "db_names": ["知识"],
            "user_content": "总结一下",
            "ai_content": "上一轮回复",
            "combined_query_for_display": "[AI]: 上一轮回复\n[User]: 总结一下",
        }
    ]
    assert len(engine.query_calls) == 1
    assert engine.query_calls[0]["options"]["diary_name"] == "工作"


@pytest.mark.asyncio
async def test_placeholder_processor_resolves_meta_thinking_placeholder() -> None:
    engine = _DummyEngineWithAdvancedHandlers()
    processor = VCPPlaceholderProcessor(engine)
    messages = [
        {"role": "system", "content": "前缀[[VCP元思考::Group]]后缀"},
        {"role": "user", "content": "帮我分析这个决定"},
    ]

    out = await processor.process_system_messages(messages, user_content="帮我分析这个决定", ai_content="上一轮回复")

    assert "VCP元思考链" in out[0]["content"]
    assert engine.meta_thinking_manager.calls == [
        {
            "chain_name": "default",
            "query_vector": [1.0, 0.0, 0.0],
            "user_content": "帮我分析这个决定",
            "ai_content": "上一轮回复",
            "combined_query_for_display": "[AI]: 上一轮回复\n[User]: 帮我分析这个决定",
            "k_sequence": None,
            "use_group": True,
            "is_auto_mode": False,
            "auto_threshold": 0.65,
        }
    ]


@pytest.mark.asyncio
async def test_placeholder_processor_strips_system_notification_before_query() -> None:
    engine = _DummyEngine()
    processor = VCPPlaceholderProcessor(engine)
    messages = [
        {"role": "system", "content": "A:[[工作日记本]]"},
        {"role": "user", "content": "总结一下"},
    ]

    await processor.process_system_messages(
        messages,
        user_content="真正的问题\n[系统通知]\n不要参与向量化\n[系统通知结束]",
        ai_content="",
    )

    assert engine.query_calls[0]["user_message"] == "真正的问题"


@pytest.mark.asyncio
async def test_placeholder_processor_resolves_dynamic_fold_protocol() -> None:
    processor = VCPPlaceholderProcessor(_DummyEngine())
    fold_payload = {
        "vcp_dynamic_fold": True,
        "plugin_description": "工作",
        "fold_blocks": [
            {"threshold": 0.7, "content": "展开后的详细说明"},
            {"threshold": 0.0, "content": "基础说明"},
        ],
    }
    messages = [
        {
            "role": "system",
            "content": f"前缀<<<FOLD>>>{fold_payload}<<<UNFOLD>>>后缀".replace("'", '"'),
        }
    ]

    out = await processor.process_system_messages(messages, user_content="请总结我的工作", ai_content="")

    assert out[0]["content"] == "前缀展开后的详细说明后缀"


@pytest.mark.asyncio
async def test_placeholder_processor_dynamic_fold_falls_back_to_base_block() -> None:
    processor = VCPPlaceholderProcessor(_DummyEngine())
    fold_payload = {
        "vcp_dynamic_fold": True,
        "plugin_description": "工作",
        "fold_blocks": [
            {"threshold": 0.7, "content": "展开后的详细说明"},
            {"threshold": 0.0, "content": "基础说明"},
        ],
    }
    messages = [
        {
            "role": "system",
            "content": f"前缀<<<FOLD>>>{fold_payload}<<<UNFOLD>>>后缀".replace("'", '"'),
        }
    ]

    out = await processor.process_system_messages(messages, user_content="这是无关问题", ai_content="")

    assert out[0]["content"] == "前缀基础说明后缀"


@pytest.mark.asyncio
async def test_placeholder_processor_dynamic_fold_uses_persistent_plugin_cache() -> None:
    engine = _DummyEngineWithPluginCache()
    processor = VCPPlaceholderProcessor(engine)
    fold_payload = {
        "vcp_dynamic_fold": True,
        "plugin_description": "工作",
        "fold_blocks": [
            {"threshold": 0.7, "content": "展开后的详细说明"},
            {"threshold": 0.0, "content": "基础说明"},
        ],
    }
    messages = [
        {
            "role": "system",
            "content": f"前缀<<<FOLD>>>{fold_payload}<<<UNFOLD>>>后缀".replace("'", '"'),
        }
    ]

    out = await processor.process_system_messages(messages, user_content="请总结我的工作", ai_content="")

    assert out[0]["content"] == "前缀展开后的详细说明后缀"
    assert engine.knowledge_base.plugin_vector_calls == ["工作"]


@pytest.mark.asyncio
async def test_placeholder_processor_fulltext_gate_injects_diary_content(tmp_path: Path):
    note_root = tmp_path / "data" / "dailynote"
    work_dir = note_root / "工作"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "2026-03-10.md").write_text(
        "今天推进了同步工作。\n[[其他日记本::TagMemo]]\n<<其他日记本>>\n{{其他日记本}}",
        encoding="utf-8",
    )

    processor = VCPPlaceholderProcessor(_DummyEngine(note_root))
    messages = [{"role": "system", "content": "参考：<<工作日记本>>"}]

    out = await processor.process_system_messages(messages, user_content="帮我总结工作进展", ai_content="")

    content = out[0]["content"]
    assert "今天推进了同步工作" in content
    assert "[循环占位符已移除]" in content
    assert "[[其他日记本::TagMemo]]" not in content
    assert "<<其他日记本>>" not in content
    assert "{{其他日记本}}" not in content


@pytest.mark.asyncio
async def test_placeholder_processor_fulltext_gate_uses_enhanced_vector_cache(tmp_path: Path):
    note_root = tmp_path / "data" / "dailynote"
    work_dir = note_root / "工作"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "2026-03-10.md").write_text("今天推进了同步工作。", encoding="utf-8")

    engine = _DummyEngine(note_root)
    engine.enhanced_vector_cache = {"工作": [0.0, 1.0, 0.0]}
    processor = VCPPlaceholderProcessor(engine)
    messages = [{"role": "system", "content": "参考：<<工作日记本>>"}]

    out = await processor.process_system_messages(messages, user_content="这是无关问题", ai_content="")

    assert "今天推进了同步工作。" in out[0]["content"]


@pytest.mark.asyncio
async def test_placeholder_processor_fulltext_gate_skips_irrelevant_query(tmp_path: Path):
    note_root = tmp_path / "data" / "dailynote"
    work_dir = note_root / "工作"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "2026-03-10.md").write_text("今天推进了同步工作。", encoding="utf-8")

    processor = VCPPlaceholderProcessor(_DummyEngine(note_root))
    messages = [{"role": "system", "content": "参考：<<工作日记本>>"}]

    out = await processor.process_system_messages(messages, user_content="这是无关问题", ai_content="")

    assert out[0]["content"] == "参考："


@pytest.mark.asyncio
async def test_placeholder_processor_fulltext_gate_clears_placeholder_on_vector_failure(tmp_path: Path):
    note_root = tmp_path / "data" / "dailynote"
    work_dir = note_root / "工作"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "2026-03-10.md").write_text("今天推进了同步工作。", encoding="utf-8")

    processor = VCPPlaceholderProcessor(_DummyEngine(note_root))
    messages = [{"role": "system", "content": "参考：<<工作日记本>>"}]

    out = await processor.process_system_messages(messages, user_content="NO_VECTOR", ai_content="")

    assert out[0]["content"] == "参考："


def test_replace_variable_placeholders_strips_nested_diary_placeholders(tmp_path: Path):
    note_root = tmp_path / "data" / "dailynote"
    source_dir = note_root / "小克"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "2026-03-10.md").write_text(
        "正文\n[[其他日记本::TagMemo]]\n<<其他日记本>>\n《《其他日记本::TagMemo》》\n{{其他日记本}}",
        encoding="utf-8",
    )

    result = replace_variable_placeholders("前缀{{小克日记本}}后缀", str(note_root))

    assert "正文" in result
    assert result.count("[循环占位符已移除]") == 4
    assert "[[其他日记本::TagMemo]]" not in result
    assert "<<其他日记本>>" not in result
    assert "《《其他日记本::TagMemo》》" not in result
    assert "{{其他日记本}}" not in result


@pytest.mark.asyncio
async def test_process_tags_in_content_appends_generated_tag_line() -> None:
    async def _fake_generator(content: str) -> str | None:
        assert "今天完成了记忆模块重构" in content
        return "[[Tag: 系统设计，记忆检索]]"

    updated = await process_tags_in_content(
        "今天完成了记忆模块重构。",
        generator=_fake_generator,
    )

    assert updated.endswith("Tag: 系统设计, 记忆检索")


@pytest.mark.asyncio
async def test_process_tags_in_content_fixes_existing_tag_line() -> None:
    updated = await process_tags_in_content("正文\nTag: 系统设计，记忆检索")

    assert updated == "正文\nTag: 系统设计, 记忆检索"


def test_update_daily_note_appends_content_to_existing_file(tmp_path: Path) -> None:
    note_root = tmp_path / "data" / "dailynote"
    target = write_daily_note(
        str(note_root),
        "小克",
        "2026-03-10",
        "第一段记录\nTag: 记忆系统, Python",
    )

    updated_path = update_daily_note(
        str(note_root),
        "小克",
        "2026-03-10",
        "第二段记录",
    )

    body = updated_path.read_text(encoding="utf-8")
    assert updated_path == target
    assert "第一段记录" in body
    assert "第二段记录" in body


def test_write_daily_note_rewrites_local_file_urls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    project_base = tmp_path / "project"
    note_root = tmp_path / "data" / "dailynote"
    local_dir = tmp_path / "local"
    local_dir.mkdir(parents=True, exist_ok=True)

    image_path = local_dir / "demo image.png"
    image_path.write_bytes(b"fake-image")
    doc_path = local_dir / "notes.txt"
    doc_path.write_text("attached doc", encoding="utf-8")

    monkeypatch.setenv("PROJECT_BASE_PATH", str(project_base))
    monkeypatch.setenv("SERVER_PORT", "3100")
    monkeypatch.setenv("VarHttpUrl", "http://127.0.0.1")
    monkeypatch.setenv("IMAGESERVER_IMAGE_KEY", "img-key")
    monkeypatch.setenv("IMAGESERVER_FILE_KEY", "file-key")

    file_url_image = image_path.resolve().as_uri()
    file_url_doc = doc_path.resolve().as_uri()
    target = write_daily_note(
        str(note_root),
        "小克",
        "2026-03-09",
        f"![图]({file_url_image})\n[附件]({file_url_doc})",
    )

    body = target.read_text(encoding="utf-8")

    assert "file://" not in body
    assert "/images/dailynote/" in body
    assert "/files/dailynote/" in body
    assert list((project_base / "image" / "dailynote").iterdir())
    assert list((project_base / "file" / "dailynote").iterdir())
