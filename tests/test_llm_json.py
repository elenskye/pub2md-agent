"""The repair parser exists because DeepSeek emits almost-JSON even in JSON
mode — these cases are byte-for-byte reproductions of observed failures."""

import pytest

from src.tools.llm_json import loads_with_repair, strip_fences


def test_valid_json_passes_through():
    assert loads_with_repair('{"1": "你好"}') == {"1": "你好"}


def test_literal_newline_inside_string():
    assert loads_with_repair('{"1": "第一行\n第二行"}') == {"1": "第一行\n第二行"}


def test_missing_close_quote_before_final_brace():
    # Observed: a value ending with a Chinese closing quote loses its ASCII
    # closing quote.
    broken = '{\n  "1": "他说：“最终定论。”\n}'
    assert loads_with_repair(broken) == {"1": "他说：“最终定论。”"}


def test_truncated_mid_string():
    assert loads_with_repair('{"1": "截断的内容') == {"1": "截断的内容"}


def test_unrepairable_raises():
    with pytest.raises(Exception):
        loads_with_repair("not json at all [")


def test_strip_fences():
    assert strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_fences('{"a": 1}') == '{"a": 1}'
