# -*- coding: utf-8 -*-
"""Dedicated tests for the ``v2ex`` channel.

V2EX rides the public JSON API and reshapes each endpoint: hot/node topic
lists, a single-topic view that must tolerate the list-or-dict response
shape and a failing replies fetch, a user profile with avatar/url
fallbacks, and a search method that is intentionally offline (the public
API has no search endpoint). These tests stub the shared ``_get_json`` so
the shaping logic runs offline. Follow-up to #331 — extends dedicated
channel coverage after rss (#360), github (#361), web (#363),
reddit (#364) and xueqiu (#365).
"""

import subprocess
from unittest.mock import patch

import pytest
import requests

from agent_reach.channels import v2ex as v2
from agent_reach.channels.v2ex import V2EXChannel

# --- can_handle ---


class _FakeResponse:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        assert chunk_size == 64 * 1024
        yield from self.chunks

    def close(self):
        self.closed = True


def test_get_json_streams_and_closes_bounded_response(monkeypatch):
    response = _FakeResponse([b'[{"id":', b" 1}]"])
    captured = {}

    def fake_get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return response

    monkeypatch.setattr(v2.requests, "get", fake_get)

    assert v2._get_json("https://www.v2ex.com/api/topics/hot.json") == [
        {"id": 1}
    ]
    assert captured["stream"] is True
    assert captured["timeout"] == v2._TIMEOUT
    assert response.closed is True


def test_get_json_falls_back_to_resolved_curl_only_for_tls_errors(monkeypatch):
    curl_path = r"C:\Windows\System32\curl.exe"
    calls = []

    monkeypatch.setattr(
        v2.requests,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            requests.exceptions.SSLError("unexpected EOF")
        ),
    )
    monkeypatch.setattr(v2.shutil, "which", lambda name: curl_path)

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=b'[{"id": 1}]',
            stderr=b"",
        )

    monkeypatch.setattr(v2.subprocess, "run", fake_run)

    assert v2._get_json("https://www.v2ex.com/api/topics/hot.json") == [
        {"id": 1}
    ]
    assert calls[0][0][0] == curl_path
    assert "--max-filesize" in calls[0][0]
    assert calls[0][1]["timeout"] > v2._TIMEOUT


def test_get_json_falls_back_when_tls_fails_while_streaming(monkeypatch):
    curl_path = "/usr/bin/curl"

    class StreamingTlsFailure(_FakeResponse):
        def iter_content(self, chunk_size):
            raise requests.exceptions.SSLError("unexpected EOF")
            yield b""  # pragma: no cover

    response = StreamingTlsFailure([])
    monkeypatch.setattr(v2.requests, "get", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(v2.shutil, "which", lambda _name: curl_path)
    monkeypatch.setattr(
        v2.subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(
            args,
            0,
            stdout=b'{"ok": true}',
            stderr=b"",
        ),
    )

    assert v2._get_json("https://www.v2ex.com/api/topics/hot.json") == {
        "ok": True
    }
    assert response.closed is True


def test_get_json_never_falls_back_for_non_tls_http_errors(monkeypatch):
    def fail_http(*_args, **_kwargs):
        raise requests.exceptions.HTTPError("HTTP 503")

    monkeypatch.setattr(v2.requests, "get", fail_http)
    monkeypatch.setattr(
        v2.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail(
            "curl fallback must be limited to TLS failures"
        ),
    )

    with pytest.raises(requests.exceptions.HTTPError, match="503"):
        v2._get_json("https://www.v2ex.com/api/topics/hot.json")

def test_can_handle_matches_v2ex_hosts():
    ch = V2EXChannel()
    for url in ["https://www.v2ex.com/t/123", "https://V2EX.COM/go/python"]:
        assert ch.can_handle(url) is True, url
    for url in ["https://example.com", "https://twitter.com", ""]:
        assert ch.can_handle(url) is False, url


# --- check() ---

def test_check_ok_sets_active_backend():
    ch = V2EXChannel()
    with patch.object(v2, "_get_json", return_value=[{"id": 1}]):
        status, message = ch.check()
    assert status == "ok"
    assert ch.active_backend == ch.backends[0]


def test_check_warn_on_exception_clears_backend():
    ch = V2EXChannel()
    ch.active_backend = "stale"
    with patch.object(v2, "_get_json", side_effect=OSError("no proxy")):
        status, message = ch.check()
    assert status == "warn"
    assert "连接失败" in message
    assert ch.active_backend is None


# --- get_hot_topics / get_node_topics ---

def test_get_hot_topics_maps_node_and_truncates_content():
    ch = V2EXChannel()
    items = [{
        "id": 9, "title": "T", "url": "https://www.v2ex.com/t/9",
        "replies": 12, "content": "x" * 300,
        "node": {"name": "python", "title": "Python"},
    }]
    with patch.object(v2, "_get_json", return_value=items):
        topics = ch.get_hot_topics(limit=5)
    t = topics[0]
    assert t["node_name"] == "python"
    assert t["node_title"] == "Python"
    assert len(t["content"]) == 200
    assert t["replies"] == 12


def test_get_hot_topics_respects_limit():
    ch = V2EXChannel()
    items = [{"id": i} for i in range(10)]
    with patch.object(v2, "_get_json", return_value=items):
        assert len(ch.get_hot_topics(limit=3)) == 3


def test_get_node_topics_falls_back_to_requested_node_name():
    ch = V2EXChannel()
    # node missing in the payload -> node_name falls back to the requested one
    with patch.object(v2, "_get_json", return_value=[{"id": 1, "title": "x"}]):
        topics = ch.get_node_topics("jobs")
    assert topics[0]["node_name"] == "jobs"


# --- get_topic: list-or-dict shape + replies fetch + fallbacks ---

def test_get_topic_unwraps_list_and_maps_replies():
    ch = V2EXChannel()
    topic = [{
        "id": 42, "title": "Hello", "url": "https://www.v2ex.com/t/42",
        "content": "body", "replies": 2,
        "node": {"name": "tech", "title": "Tech"},
        "member": {"username": "op"},
    }]
    replies = [
        {"member": {"username": "alice"}, "content": "nice", "created": 1},
        {"member": {"username": "bob"}, "content": "+1", "created": 2},
    ]
    with patch.object(v2, "_get_json", side_effect=[topic, replies]):
        result = ch.get_topic(42)
    assert result["id"] == 42
    assert result["author"] == "op"
    assert result["node_name"] == "tech"
    assert len(result["replies"]) == 2
    assert result["replies"][0] == {"author": "alice", "content": "nice", "created": 1}


def test_get_topic_survives_failing_replies_fetch():
    ch = V2EXChannel()
    topic = {"id": 7, "title": "x"}  # dict shape (not a list)
    with patch.object(v2, "_get_json", side_effect=[topic, OSError("boom")]):
        result = ch.get_topic(7)
    assert result["id"] == 7
    assert result["replies"] == []  # failed replies fetch degrades to empty


def test_get_topic_url_fallback_when_missing():
    ch = V2EXChannel()
    with patch.object(v2, "_get_json", side_effect=[[], []]):
        result = ch.get_topic(99)
    assert result["id"] == 99
    assert result["url"] == "https://www.v2ex.com/t/99"


# --- get_user: field mapping + avatar/url fallbacks ---

def test_get_user_maps_fields_and_prefers_large_avatar():
    ch = V2EXChannel()
    data = {
        "id": 1, "username": "neo", "github": "neo-gh",
        "avatar_large": "/large.png", "avatar_normal": "/normal.png",
    }
    with patch.object(v2, "_get_json", return_value=data):
        user = ch.get_user("neo")
    assert user["github"] == "neo-gh"
    assert user["avatar"] == "/large.png"


def test_get_user_avatar_falls_back_to_normal():
    ch = V2EXChannel()
    with patch.object(v2, "_get_json", return_value={"avatar_normal": "/normal.png"}):
        user = ch.get_user("neo")
    assert user["avatar"] == "/normal.png"
    # url + username fall back to the requested handle
    assert user["username"] == "neo"
    assert user["url"] == "https://www.v2ex.com/member/neo"


# --- search: intentionally offline (no public search endpoint) ---

def test_search_returns_guidance_without_network():
    ch = V2EXChannel()
    with patch.object(v2, "_get_json", side_effect=AssertionError("must not hit network")):
        results = ch.search("python")
    assert len(results) == 1
    assert "error" in results[0]
    assert "python" in results[0]["error"]
