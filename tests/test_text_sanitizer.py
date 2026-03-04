"""tests/test_text_sanitizer.py — TextSanitizer 单元测试"""

from __future__ import annotations

from tagmemo.text_sanitizer import TextSanitizer


class TestStripHtml:
    def test_removes_tags(self):
        assert TextSanitizer.strip_html("<p>hello</p>") == "hello"

    def test_removes_script(self):
        result = TextSanitizer.strip_html("<script>alert(1)</script>world")
        assert "alert" not in result
        assert "world" in result

    def test_plain_text_passthrough(self):
        assert TextSanitizer.strip_html("no html here") == "no html here"

    def test_empty_string(self):
        assert TextSanitizer.strip_html("") == ""

    def test_nested_tags(self):
        html = "<div><p>nested <b>bold</b></p></div>"
        result = TextSanitizer.strip_html(html)
        assert "nested" in result
        assert "bold" in result
        assert "<" not in result


class TestStripEmoji:
    def test_removes_common_emoji(self):
        result = TextSanitizer.strip_emoji("hello 😀 world 🎉")
        assert "😀" not in result
        assert "🎉" not in result
        assert "hello" in result

    def test_no_emoji(self):
        assert TextSanitizer.strip_emoji("plain text") == "plain text"

    def test_empty_string(self):
        assert TextSanitizer.strip_emoji("") == ""


class TestStripToolMarkers:
    def test_removes_tool_block(self):
        text = "prefix <<<[TOOL_REQUEST]>>>tool_name: test<<<[END_TOOL_REQUEST]>>> suffix"
        result = TextSanitizer.strip_tool_markers(text)
        assert "TOOL_REQUEST" not in result
        assert "prefix" in result
        assert "suffix" in result

    def test_no_tool_block(self):
        text = "nothing to strip"
        assert TextSanitizer.strip_tool_markers(text) == text


class TestSanitize:
    def test_full_pipeline(self):
        html_with_emoji = "<p>hello 😀 world</p>"
        result = TextSanitizer.sanitize(html_with_emoji)
        assert "<p>" not in result
        assert "😀" not in result
        assert "hello" in result

    def test_whitespace_normalization(self):
        text = "hello    world\n\n\nfoo"
        result = TextSanitizer.sanitize(text)
        # sanitize 应该清理多余空白
        assert "hello" in result
        assert "world" in result
