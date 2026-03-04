from __future__ import annotations

from app import _json_safe_sql_value


def test_json_safe_sql_value_keeps_text():
    assert _json_safe_sql_value("hello") == "hello"


def test_json_safe_sql_value_converts_blob():
    out = _json_safe_sql_value(b"\xed\x01\x02abc")
    assert isinstance(out, dict)
    assert out["_type"] == "blob"
    assert out["size"] == 6
    assert isinstance(out["preview_base64"], str)
    assert len(out["preview_base64"]) > 0
