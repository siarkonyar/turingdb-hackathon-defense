"""The .env loader: parsing, and real environment variables always winning."""

from __future__ import annotations

from api.env import load_env, parse_env


def test_parse_env_handles_comments_quotes_and_export():
    text = '# comment\n\nexport A=1\nB = "two words"\nC=\'x\'\nD=plain # trailing\nnot a line\nE=\n'
    assert parse_env(text) == {"A": "1", "B": "two words", "C": "x", "D": "plain", "E": ""}


def test_load_env_never_overrides_and_skips_empty(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("OPSMAP_TEST_NEW=from-file\nOPSMAP_TEST_SET=from-file\nOPSMAP_TEST_EMPTY=\n")
    monkeypatch.setenv("OPSMAP_TEST_SET", "real")
    monkeypatch.delenv("OPSMAP_TEST_NEW", raising=False)
    monkeypatch.delenv("OPSMAP_TEST_EMPTY", raising=False)

    added = load_env(env)

    import os
    assert added == ["OPSMAP_TEST_NEW"]
    assert os.environ["OPSMAP_TEST_NEW"] == "from-file" and os.environ["OPSMAP_TEST_SET"] == "real"
    assert "OPSMAP_TEST_EMPTY" not in os.environ
    monkeypatch.delenv("OPSMAP_TEST_NEW")


def test_missing_env_file_is_fine(tmp_path):
    assert load_env(tmp_path / "nope") == []
