"""engine 客户端的提交退避重试与轮询容错。

背景：部署重启 engine 时有 ~30s 停机窗口，bot 提交撞窗口即 Connection refused 丢票
（603038 案例）。只重试"连接未建立"类错误；ReadTimeout 可能已建仓，重试会重复分析。
"""

from __future__ import annotations

import httpx
import pytest

from studio.core.client import APIError, SUBMIT_RETRIES, TradingAgentsClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("studio.core.client.time.sleep", lambda s: None)  # 不真睡
    return TradingAgentsClient({})


def _connect_failures(n, then=None):
    """生成 n 次 ConnectError 后跟 then 的可调用。"""
    calls = {"n": 0}

    def fake(*a, **kw):
        calls["n"] += 1
        if calls["n"] <= n:
            raise httpx.ConnectError("Connection refused")
        return then

    return fake, calls


def test_submit_retries_on_connect_error(client, monkeypatch):
    """前两次连接被拒、第三次成功 → 返回 task_id，共 3 次调用。"""
    ok = {"data": {"task_id": "t-123"}}
    fake, calls = _connect_failures(2, then=ok)
    monkeypatch.setattr(client, "_request", fake)
    assert client.submit_analysis("603038") == "t-123"
    assert calls["n"] == 3


def test_submit_exhausts_retries(client, monkeypatch):
    """引擎一直不可达 → 首次 + SUBMIT_RETRIES 次后抛 APIError。"""
    fake, calls = _connect_failures(99)
    monkeypatch.setattr(client, "_request", fake)
    with pytest.raises(APIError, match="引擎不可达"):
        client.submit_analysis("603038")
    assert calls["n"] == SUBMIT_RETRIES + 1


def test_submit_no_retry_on_read_timeout(client, monkeypatch):
    """读超时可能已建仓，绝不重试（防重复分析烧双份 token）。"""
    calls = {"n": 0}

    def fake(*a, **kw):
        calls["n"] += 1
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(client, "_request", fake)
    with pytest.raises(httpx.ReadTimeout):
        client.submit_analysis("603038")
    assert calls["n"] == 1


def test_wait_tolerates_transient_poll_errors(client, monkeypatch):
    """等待期间引擎短暂重启：前两次轮询连接被拒，第三次看到 completed。"""
    seq = [httpx.ConnectError("down"), httpx.ConnectError("down"), {"status": "completed"}]

    def fake_status(task_id):
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(client, "get_status", fake_status)
    status = client.wait_for_task("t-1", poll_interval=0)
    assert status["status"] == "completed"


def test_wait_gives_up_after_consecutive_errors(client, monkeypatch):
    """连续传输错误超过容忍上限 → 抛出（真故障不无限等）。"""
    def fake_status(task_id):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(client, "get_status", fake_status)
    with pytest.raises(httpx.ConnectError):
        client.wait_for_task("t-1", poll_interval=0)
