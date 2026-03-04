"""tests/test_time_parser.py — TimeExpressionParser 单元测试"""

from __future__ import annotations

from datetime import datetime, timezone

from tagmemo.time_parser import TimeExpressionParser


class TestTimeExpressionParser:
    def setup_method(self):
        self.parser = TimeExpressionParser(locale="zh-CN", default_timezone="Asia/Shanghai")

    # ---- 基础解析 ----

    def test_parse_today(self):
        results = self.parser.parse("今天发生了什么")
        assert len(results) >= 1
        r = results[0]
        assert "start" in r and "end" in r

    def test_parse_yesterday(self):
        results = self.parser.parse("昨天的记录")
        assert len(results) >= 1

    def test_parse_this_week(self):
        results = self.parser.parse("这周的总结")
        assert len(results) >= 1

    def test_parse_last_month(self):
        results = self.parser.parse("上个月的日记")
        assert len(results) >= 1

    # ---- 无匹配 ----

    def test_no_time_expression(self):
        results = self.parser.parse("向量数据库的原理是什么")
        assert results == []

    def test_empty_string(self):
        results = self.parser.parse("")
        assert results == []

    # ---- 相对日期 ----

    def test_n_days_ago(self):
        results = self.parser.parse("3天前的事情")
        assert len(results) >= 1

    def test_last_week(self):
        results = self.parser.parse("上周发生了什么")
        assert len(results) >= 1

    # ---- Locale ----

    def test_set_locale(self):
        self.parser.set_locale("en-US")
        results = self.parser.parse("yesterday")
        assert len(results) >= 1

    def test_en_today(self):
        self.parser.set_locale("en-US")
        results = self.parser.parse("what happened today")
        assert len(results) >= 1

    # ---- 返回结构 ----

    def test_result_structure(self):
        results = self.parser.parse("今天的内容")
        if results:
            r = results[0]
            assert isinstance(r["start"], datetime)
            assert isinstance(r["end"], datetime)
            assert r["start"] <= r["end"]
