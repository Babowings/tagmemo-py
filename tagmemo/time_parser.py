"""time_parser.py — 时间表达式解析器，替代 TimeExpressionParser.js (214 行)。

支持中文 / 英文时间表达式解析，返回 UTC datetime 范围列表。
dayjs → datetime + zoneinfo + dateutil.relativedelta。
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from .time_expressions import TIME_EXPRESSIONS


class TimeExpressionParser:
    """时间表达式解析器，1:1 对应原 JS TimeExpressionParser。"""

    def __init__(
        self, locale: str = "zh-CN", default_timezone: str = "Asia/Shanghai"
    ) -> None:
        self.default_timezone = default_timezone
        self._tz = ZoneInfo(default_timezone)
        self.locale = locale
        self.expressions = TIME_EXPRESSIONS.get(locale, TIME_EXPRESSIONS["zh-CN"])

    def set_locale(self, locale: str) -> None:
        self.locale = locale
        self.expressions = TIME_EXPRESSIONS.get(locale, TIME_EXPRESSIONS["zh-CN"])

    # ------------------------------------------------------------------
    # 日期边界
    # ------------------------------------------------------------------

    def _get_day_boundaries(self, dt: datetime) -> dict:
        """返回某天在配置时区下的开始/结束 (datetime, UTC-aware)。"""
        local = dt.astimezone(self._tz)
        start = datetime.combine(local.date(), time.min, tzinfo=self._tz)
        end = datetime.combine(local.date(), time(23, 59, 59, 999999), tzinfo=self._tz)
        return {"start": start, "end": end}

    # ------------------------------------------------------------------
    # 核心解析函数 (V2 多表达式)
    # ------------------------------------------------------------------

    def parse(self, text: str) -> list[dict]:
        """解析文本中所有时间表达式，返回 [{start, end}] 列表（去重）。"""
        now = datetime.now(self._tz)
        remaining = text
        results: list[dict] = []

        # 1. 硬编码表达式（从长到短，避免短匹配吞噬长匹配）
        sorted_keys = sorted(
            self.expressions["hardcoded"].keys(), key=len, reverse=True
        )
        for expr in sorted_keys:
            if expr in remaining:
                config = self.expressions["hardcoded"][expr]
                result = None
                if "days" in config:
                    target = now - timedelta(days=config["days"])
                    result = self._get_day_boundaries(target)
                elif "type" in config:
                    result = self._get_special_range(now, config["type"])
                if result:
                    results.append(result)
                    remaining = remaining.replace(expr, "", 1)

        # 2. 动态模式
        for pattern_cfg in self.expressions["patterns"]:
            regex: re.Pattern = pattern_cfg["regex"]
            for m in regex.finditer(remaining):
                result = self._handle_dynamic_pattern(m, pattern_cfg["type"], now)
                if result:
                    results.append(result)
            # 清除已匹配部分
            remaining = regex.sub("", remaining)

        if not results:
            return []

        # 去重（基于 start+end 时间戳）
        seen: set[str] = set()
        unique: list[dict] = []
        for r in results:
            key = f"{r['start'].isoformat()}|{r['end'].isoformat()}"
            if key not in seen:
                seen.add(key)
                unique.append(r)

        return unique

    # ------------------------------------------------------------------
    # 特殊范围
    # ------------------------------------------------------------------

    def _get_special_range(self, now: datetime, range_type: str) -> dict | None:
        """处理 thisWeek / lastWeek / thisMonth / lastMonth 等特殊类型。"""
        # 周起始日说明：
        # 原版 dayjs startOf('week') 在无 locale 插件时默认周日=0（本周 = 周日～周六），
        # 但原版代码注释明确写了 "希望周一为一周的开始 (locale: zh-cn)"，
        # 说明原版意图就是 Monday-start，只是未通过 locale 插件生效。
        # Python 版采用 ISO 标准 + 中文习惯：Monday-start（本周 = 周一～周日），
        # 这同时修复了原版注释与行为不一致的问题。
        if range_type == "thisWeek":
            # 本周一 ~ 本周日（ISO / 中文习惯）
            weekday = now.weekday()  # Mon=0 ... Sun=6
            start = now - timedelta(days=weekday)
            end = start + timedelta(days=6)
        elif range_type == "lastWeek":
            weekday = now.weekday()
            this_monday = now - timedelta(days=weekday)
            start = this_monday - timedelta(days=7)
            end = start + timedelta(days=6)
        elif range_type == "thisMonth":
            start = now.replace(day=1)
            # 月末：下月1号 - 1天
            next_month = start + relativedelta(months=1)
            end = next_month - timedelta(days=1)
        elif range_type == "lastMonth":
            first_this = now.replace(day=1)
            end_last = first_this - timedelta(days=1)
            start = end_last.replace(day=1)
            end = end_last
        elif range_type == "thisMonthStart":
            # 本月1-10号
            start = now.replace(day=1)
            end = now.replace(day=10)
        elif range_type == "lastMonthStart":
            first_this = now.replace(day=1)
            last_month_end = first_this - timedelta(days=1)
            start = last_month_end.replace(day=1)
            end = start.replace(day=10)
        elif range_type == "lastMonthMid":
            first_this = now.replace(day=1)
            last_month_end = first_this - timedelta(days=1)
            start = last_month_end.replace(day=11)
            end = last_month_end.replace(day=20)
        elif range_type == "lastMonthEnd":
            first_this = now.replace(day=1)
            last_month_end = first_this - timedelta(days=1)
            start = last_month_end.replace(day=21)
            end = last_month_end
        else:
            return None

        # 转为边界
        start_dt = datetime.combine(start.date(), time.min, tzinfo=self._tz)
        end_dt = datetime.combine(end.date(), time(23, 59, 59, 999999), tzinfo=self._tz)
        return {"start": start_dt, "end": end_dt}

    # ------------------------------------------------------------------
    # 动态模式处理
    # ------------------------------------------------------------------

    def _handle_dynamic_pattern(
        self, match: re.Match, pattern_type: str, now: datetime
    ) -> dict | None:
        num_str = match.group(1)

        if pattern_type == "lastWeekday":
            return self._handle_last_weekday(num_str, now)

        num = self._chinese_to_number(num_str)

        if pattern_type == "daysAgo":
            target = now - timedelta(days=num)
            return self._get_day_boundaries(target)

        if pattern_type == "weeksAgo":
            ref = now - timedelta(weeks=num)
            weekday = ref.weekday()
            start = ref - timedelta(days=weekday)
            end = start + timedelta(days=6)
            start_dt = datetime.combine(start.date(), time.min, tzinfo=self._tz)
            end_dt = datetime.combine(end.date(), time(23, 59, 59, 999999), tzinfo=self._tz)
            return {"start": start_dt, "end": end_dt}

        if pattern_type == "monthsAgo":
            ref = now - relativedelta(months=num)
            start = ref.replace(day=1)
            end = start + relativedelta(months=1) - timedelta(days=1)
            start_dt = datetime.combine(start.date(), time.min, tzinfo=self._tz)
            end_dt = datetime.combine(end.date(), time(23, 59, 59, 999999), tzinfo=self._tz)
            return {"start": start_dt, "end": end_dt}

        return None

    def _handle_last_weekday(self, weekday_str: str, now: datetime) -> dict | None:
        """处理 '上周一' / 'last monday' 等。"""
        # 中文映射
        zh_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
        # 英文映射
        en_map = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6,
        }

        target_weekday = zh_map.get(weekday_str) if weekday_str in zh_map else en_map.get(weekday_str.lower())
        if target_weekday is None:
            return None

        # Python weekday: Mon=0 ... Sun=6
        diff = (now.weekday() - target_weekday) % 7
        if diff == 0:
            diff = 7  # 如果是同一天，回退一周
        target = now - timedelta(days=diff)
        return self._get_day_boundaries(target)

    # ------------------------------------------------------------------
    # 中文数字转换
    # ------------------------------------------------------------------

    @staticmethod
    def _chinese_to_number(chinese: str) -> int:
        """将中文数字转为阿拉伯数字（与原版 chineseToNumber 一致）。"""
        num_map = {
            "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
            "日": 7, "天": 7,
        }

        if chinese in num_map:
            return num_map[chinese]

        if chinese == "十":
            return 10

        # 处理 "十一"～"九十九"
        if "十" in chinese:
            parts = chinese.split("十", 1)
            tens_part = parts[0]
            ones_part = parts[1] if len(parts) > 1 else ""

            if tens_part == "":
                total = 10  # "十三" → 13
            else:
                total = num_map.get(tens_part, 1) * 10

            if ones_part:
                total += num_map.get(ones_part, 0)

            return total

        # fallback：尝试直接 int()
        try:
            return int(chinese)
        except ValueError:
            return 0
