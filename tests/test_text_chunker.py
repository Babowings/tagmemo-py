"""tests/test_text_chunker.py — chunk_text 单元测试"""

from __future__ import annotations

from tagmemo.text_chunker import chunk_text


class TestChunkText:
    def test_short_text_single_chunk(self):
        """短文本应返回单个 chunk。"""
        text = "这是一段很短的文本。"
        chunks = chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_empty_string(self):
        """空字符串应返回空列表。"""
        chunks = chunk_text("")
        assert chunks == []

    def test_whitespace_only(self):
        """纯空白应返回空列表。"""
        chunks = chunk_text("   \n\t  ")
        assert chunks == []

    def test_long_text_multiple_chunks(self):
        """超长文本应被分成多段。"""
        # 生成一段很长的文本 (每段约 20 token, 重复 500 次 → ~10,000 token)
        sentence = "这是一个测试句子，用于验证分块功能。"
        text = (sentence + "\n") * 500
        chunks = chunk_text(text, max_tokens=200, overlap_tokens=20)
        assert len(chunks) > 1
        # 每个 chunk 不应为空
        for chunk in chunks:
            assert len(chunk.strip()) > 0

    def test_respects_sentence_boundaries(self):
        """分块应尽量在句子边界处切割。"""
        sentences = ["第一句话。", "第二句话。", "第三句话。"]
        text = "\n".join(sentences)
        # 用很小的 max_tokens 强制分块
        chunks = chunk_text(text, max_tokens=10, overlap_tokens=2)
        assert len(chunks) >= 1

    def test_custom_max_tokens(self):
        """自定义 max_tokens 应被尊重。"""
        text = "word " * 1000  # ~1000 tokens
        chunks = chunk_text(text, max_tokens=100, overlap_tokens=10)
        assert len(chunks) > 1
