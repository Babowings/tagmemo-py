"""time_expressions.py — 时间表达式配置数据，替代 timeExpressions.config.js (90 行)。

纯数据模块，不含逻辑。patterns 中的 regex 使用 Python re 语法。
"""

from __future__ import annotations

import re

TIME_EXPRESSIONS: dict[str, dict] = {
    "zh-CN": {
        "hardcoded": {
            # 基础时间词
            "今天": {"days": 0},
            "昨天": {"days": 1},
            "前天": {"days": 2},
            "大前天": {"days": 3},
            # 模糊时间词
            "之前": {"days": 3},
            "最近": {"days": 5},
            "前几天": {"days": 5},
            "前一阵子": {"days": 15},
            "近期": {"days": 7},
            # 周/月相关
            "上周": {"type": "lastWeek"},
            "上个月": {"type": "lastMonth"},
            "本周": {"type": "thisWeek"},
            "这周": {"type": "thisWeek"},
            "本月": {"type": "thisMonth"},
            "这个月": {"type": "thisMonth"},
            "月初": {"type": "thisMonthStart"},
            "上个月初": {"type": "lastMonthStart"},
            "上个月中": {"type": "lastMonthMid"},
            "上个月末": {"type": "lastMonthEnd"},
        },
        "patterns": [
            {
                # 匹配 "3天前" 或 "三天前"
                "regex": re.compile(r"(\d+|[一二三四五六七八九十]+)天前"),
                "type": "daysAgo",
            },
            {
                # 匹配 "上周一" ... "上周日/天"
                "regex": re.compile(r"上周([一二三四五六日天])"),
                "type": "lastWeekday",
            },
            {
                # 匹配 "x周前"
                "regex": re.compile(r"(\d+|[一二三四五六七八九十]+)周前"),
                "type": "weeksAgo",
            },
            {
                # 匹配 "x个月前"
                "regex": re.compile(r"(\d+|[一二三四五六七八九十]+)个月前"),
                "type": "monthsAgo",
            },
        ],
    },
    "en-US": {
        "hardcoded": {
            "today": {"days": 0},
            "yesterday": {"days": 1},
            "recently": {"days": 5},
            "lately": {"days": 7},
            "a while ago": {"days": 15},
            "last week": {"type": "lastWeek"},
            "last month": {"type": "lastMonth"},
            "this week": {"type": "thisWeek"},
            "this month": {"type": "thisMonth"},
        },
        "patterns": [
            {
                "regex": re.compile(r"(\d+) days? ago", re.IGNORECASE),
                "type": "daysAgo",
            },
            {
                "regex": re.compile(
                    r"last (monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
                    re.IGNORECASE,
                ),
                "type": "lastWeekday",
            },
            {
                "regex": re.compile(r"(\d+) weeks? ago", re.IGNORECASE),
                "type": "weeksAgo",
            },
            {
                "regex": re.compile(r"(\d+) months? ago", re.IGNORECASE),
                "type": "monthsAgo",
            },
        ],
    },
}
