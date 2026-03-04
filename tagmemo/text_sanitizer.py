"""text_sanitizer.py — 文本净化工具，替代 TextSanitizer.js (123 行)。

提供 HTML 剥离、Emoji 清理、工具标记净化功能。
"""

from __future__ import annotations

import re

try:
    from bs4 import BeautifulSoup

    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False


class TextSanitizer:
    """文本净化静态工具类，1:1 对应原 JS TextSanitizer。"""

    # ------------------------------------------------------------------
    # HTML 剥离
    # ------------------------------------------------------------------

    @staticmethod
    def strip_html(html: str) -> str:
        """剥离 HTML 标签，提取纯文本。"""
        if not html:
            return ""
        if not isinstance(html, str):
            html = str(html)

        if not _HAS_BS4:
            # fallback：简单正则剥离（与 JS cheerio 不可用时行为一致）
            text = re.sub(r"<[^>]*>", "", html)
            text = re.sub(r"^[ \t]+", "", text, flags=re.MULTILINE)
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text.strip()

        try:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["style", "script"]):
                tag.decompose()
            plain = soup.get_text()
            plain = re.sub(r"^[ \t]+", "", plain, flags=re.MULTILINE)
            plain = re.sub(r"\n{3,}", "\n\n", plain)
            return plain.strip()
        except Exception:
            return html

    # ------------------------------------------------------------------
    # Emoji 移除
    # ------------------------------------------------------------------

    # 合并为一个正则（对应原版 10 条 .replace() 链）
    _EMOJI_RE = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002600-\U000026FF"  # misc symbols
        "\U00002700-\U000027BF"  # dingbats
        "\U0001F900-\U0001F9FF"  # supplemental symbols
        "\U0001FA00-\U0001FA6F"  # chess symbols
        "\U0001FA70-\U0001FAFF"  # symbols extended-A
        "\U0000FE00-\U0000FE0F"  # variation selectors
        "\U0000200D"             # zero width joiner
        "]+",
        flags=re.UNICODE,
    )

    @staticmethod
    def strip_emoji(text: str) -> str:
        """移除 Emoji 和特殊符号。"""
        if not text or not isinstance(text, str):
            return text or ""
        return TextSanitizer._EMOJI_RE.sub("", text).strip()

    # ------------------------------------------------------------------
    # 工具标记净化
    # ------------------------------------------------------------------

    _BLACKLISTED_KEYS = {"tool_name", "command", "archery", "maid"}
    _BLACKLISTED_VALUES = {"dailynote", "update", "create", "no_reply"}

    # 匹配 <<<[TOOL_REQUEST]>>> ... <<<[END_TOOL_REQUEST]>>> 整体块
    _TOOL_BLOCK_RE = re.compile(
        r"<<<\[?TOOL_REQUEST\]?>>>([\s\S]*?)<<<\[?END_TOOL_REQUEST\]?>>>",
        re.IGNORECASE,
    )
    # 匹配键值对  key: 「始」value「末」
    _KV_RE = re.compile(r"(\w+):\s*[「『]始[」』]([\s\S]*?)[「『]末[」』]")

    @classmethod
    def strip_tool_markers(cls, text: str) -> str:
        """净化工具调用标记。"""
        if not text or not isinstance(text, str):
            return text or ""

        def _replace_block(m: re.Match) -> str:
            block = m.group(1)
            results: list[str] = []
            for kv in cls._KV_RE.finditer(block):
                key = kv.group(1).lower()
                val = kv.group(2).strip()
                val_lower = val.lower()
                is_tech_key = key in cls._BLACKLISTED_KEYS
                is_tech_val = any(bv in val_lower for bv in cls._BLACKLISTED_VALUES)
                if not is_tech_key and not is_tech_val and len(val) > 1:
                    results.append(val)

            if not results:
                # fallback：逐行清理
                lines: list[str] = []
                for line in block.split("\n"):
                    clean = re.sub(r"\w+:\s*[「『]始[」』]", "", line)
                    clean = re.sub(r"[「『]末[」』]", "", clean).strip()
                    lower = clean.lower()
                    if any(bv in lower for bv in cls._BLACKLISTED_VALUES):
                        continue
                    if clean:
                        lines.append(clean)
                return "\n".join(lines)
            return "\n".join(results)

        processed = cls._TOOL_BLOCK_RE.sub(_replace_block, text)

        # 清理残留标记
        processed = re.sub(r"<<<\[?TOOL_REQUEST\]?>>>", "", processed, flags=re.IGNORECASE)
        processed = re.sub(r"<<<\[?END_TOOL_REQUEST\]?>>>", "", processed, flags=re.IGNORECASE)
        processed = re.sub(r"[「」『』]始[「」『』]", "", processed)
        processed = re.sub(r"[「」『』]末[「」『』]", "", processed)
        processed = re.sub(r"[「」『』]", "", processed)
        processed = re.sub(r"[ \t]+", " ", processed)
        processed = re.sub(r"\n{3,}", "\n\n", processed)
        return processed.strip()

    # ------------------------------------------------------------------
    # 完整净化流水线
    # ------------------------------------------------------------------

    @classmethod
    def sanitize(cls, text: str) -> str:
        """完整净化流水线：HTML → Emoji → Tool Markers。"""
        if not text:
            return ""
        result = cls.strip_html(text)
        result = cls.strip_emoji(result)
        result = cls.strip_tool_markers(result)
        return result
