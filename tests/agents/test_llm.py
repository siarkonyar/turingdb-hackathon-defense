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


def test_concurrency_limit_429_is_waited_out_not_fatal(monkeypatch):
    """A 429 'concurrency limit' (another caller of the same key mid-request) is retried patiently."""
    import httpx

    from agents import llm as llm_mod
    from agents.config import AgentSettings

    replies = [httpx.Response(429, json={"error": "Concurrency limit exceeded"}, headers={"retry-after": "1"})] * 7
    replies.append(httpx.Response(200, json={"choices": [{"message": {"content": '{"action": "finish"}'}}]}))
    calls = iter(replies)
    sleeps: list[float] = []
    monkeypatch.setattr(llm_mod.time, "sleep", sleeps.append)

    client = llm_mod.FeatherlessLLM(AgentSettings("k", "http://x", "m", "", "", 1, False, None))
    client._http = httpx.Client(transport=httpx.MockTransport(lambda req: next(calls)))
    assert client.chat([{"role": "user", "content": "hi"}]) == '{"action": "finish"}'
    assert sleeps == [1.0] * 7  # more 429s than the 5 error retries, honouring Retry-After


def test_malformed_provider_json_is_retried_without_logging_payload(monkeypatch):
    import httpx
    from agents import llm as llm_mod
    from agents.config import AgentSettings

    replies = iter([httpx.Response(200, content=b'{"choices": []}{"extra": true}'),
                    httpx.Response(200, json={"choices": [{"message": {"content": '{"action":"wait"}'}}]})])
    sleeps = []
    monkeypatch.setattr(llm_mod.time, "sleep", sleeps.append)
    client = llm_mod.FeatherlessLLM(AgentSettings("k", "http://x", "m", "", "", 1, False, None))
    client._http = httpx.Client(transport=httpx.MockTransport(lambda req: next(replies)))
    assert client.chat([{"role": "user", "content": "move"}]) == '{"action":"wait"}'
    assert sleeps == [2.0] and client.usage.calls == 1


def test_bounded_blue_chat_does_not_retry_or_switch_models(monkeypatch):
    import httpx
    from agents import llm as llm_mod
    from agents.config import AgentSettings
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(429, json={"error": "capacity"})
    monkeypatch.setattr(llm_mod.time, "sleep", lambda _: pytest.fail("bounded call must not sleep"))
    client = llm_mod.FeatherlessLLM(AgentSettings("k", "http://x", "m", "", "", 1, False, None))
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(llm_mod.LLMError):
        client.chat([{"role": "user", "content": "propose"}], bounded=True)
    assert len(requests) == 1 and client.usage.requests == 1
    assert requests[0].extensions["timeout"]["read"] == 30
