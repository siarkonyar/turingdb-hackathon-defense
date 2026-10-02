"""Offline tests for the JSON action protocol parsing and model-selection fallbacks (no network)."""

from __future__ import annotations

import pytest

from agents.llm import parse_action, strip_reasoning


def test_parses_plain_object():
    a = parse_action('{"thought": "x", "action": "query", "args": {"cypher": "MATCH (n) RETURN n"}}')
    assert a["action"] == "query" and a["args"]["cypher"].startswith("MATCH")


def test_parses_fenced_json():
    a = parse_action('Here is my move:\n```json\n{"action": "finish", "args": {"ok": true}}\n```')
    assert a["action"] == "finish" and a["args"] == {"ok": True}


def test_strips_reasoning_block():
    reply = '<think>let me think hard</think>\n{"action": "impact", "args": {"branch": "main"}}'
    assert "think" not in strip_reasoning(reply)
    assert parse_action(reply)["action"] == "impact"


def test_recovers_from_trailing_comma():
    a = parse_action('{"action": "finish", "args": {"a": 1,}}')
    assert a["args"]["a"] == 1


def test_missing_args_becomes_empty_dict():
    a = parse_action('{"action": "scout_targets"}')
    assert a["action"] == "scout_targets" and a["args"] == {}


def test_prose_only_raises():
    with pytest.raises(ValueError):
        parse_action("I think I should look at the suppliers first.")


def test_picks_object_with_action_among_many():
    reply = '{"note": "not this"} then {"thought":"go","action":"query","args":{"cypher":"MATCH (n) RETURN n"}}'
    assert parse_action(reply)["action"] == "query"
