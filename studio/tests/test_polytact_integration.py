"""polytact 集成层测试：报告令牌、飞书 app 模式出站、chat_id 学习与注入。"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest
import yaml


# ---------- 报告链接令牌 ----------

def test_report_token_roundtrip(monkeypatch):
    monkeypatch.setenv("REPORT_TOKEN_SECRET", "test-secret")
    from studio.notify import tokens

    t = tokens.sign("task-123")
    assert tokens.verify("task-123", t)
    assert tokens.sign("task-123") == t  # 无状态：同 scope 稳定
    assert not tokens.verify("task-123", "wrong")
    assert not tokens.verify("other-task", t)


def test_report_token_index_scope(monkeypatch):
    monkeypatch.setenv("REPORT_TOKEN_SECRET", "s")
    from studio.notify import tokens

    assert tokens.verify(tokens.INDEX_SCOPE, tokens.sign(tokens.INDEX_SCOPE))


def test_report_token_missing_secret_fails_closed(monkeypatch):
    monkeypatch.delenv("REPORT_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    from studio.notify import tokens

    with pytest.raises(RuntimeError):
        tokens.sign("x")
    assert not tokens.verify("x", "y")


# ---------- 飞书渠道 app 模式 ----------

class _FakeResp:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


def _patch_httpx(monkeypatch, calls):
    import httpx

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers})
        if "tenant_access_token" in url:
            return _FakeResp({"code": 0, "tenant_access_token": "tok-1", "expire": 7200})
        return _FakeResp({"code": 0})

    monkeypatch.setattr(httpx, "post", fake_post)


def test_feishu_app_mode_send(monkeypatch):
    monkeypatch.delenv("FEISHU_CHAT_ID", raising=False)
    calls = []
    _patch_httpx(monkeypatch, calls)

    from studio.notify.channels.feishu import FeishuChannel

    ch = FeishuChannel({"app_id": "cli_x", "app_secret": "sec", "chat_id": "oc_1"})
    ch.send("标题", "正文", buttons=[("查看完整报告", "http://1.2.3.4:8890/report/abc?token=t")])

    assert len(calls) == 2
    assert "tenant_access_token" in calls[0]["url"]
    send = calls[1]
    assert send["headers"]["Authorization"] == "Bearer tok-1"
    assert send["json"]["receive_id"] == "oc_1"
    card = json.loads(send["json"]["content"])
    assert card["header"]["title"]["content"] == "标题"
    assert card["elements"][0]["tag"] == "markdown"
    assert card["elements"][1]["actions"][0]["url"].endswith("token=t")


def test_feishu_app_mode_token_cached(monkeypatch):
    monkeypatch.delenv("FEISHU_CHAT_ID", raising=False)
    calls = []
    _patch_httpx(monkeypatch, calls)

    from studio.notify.channels.feishu import FeishuChannel

    ch = FeishuChannel({"app_id": "cli_x", "app_secret": "sec", "chat_id": "oc_1"})
    ch.send("t1", "b")
    ch.send("t2", "b")
    token_calls = [c for c in calls if "tenant_access_token" in c["url"]]
    assert len(token_calls) == 1  # 第二次复用缓存 token


def test_feishu_webhook_fallback(monkeypatch):
    calls = []
    _patch_httpx(monkeypatch, calls)

    from studio.notify.channels.feishu import FeishuChannel

    ch = FeishuChannel({"webhook": "https://hook.example/x"})
    ch.send("标题", "正文")
    assert len(calls) == 1
    assert calls[0]["url"] == "https://hook.example/x"
    assert calls[0]["json"]["msg_type"] == "interactive"


def test_feishu_app_mode_requires_chat_id(monkeypatch):
    monkeypatch.delenv("FEISHU_CHAT_ID", raising=False)
    from studio.notify.channels.feishu import FeishuChannel

    ch = FeishuChannel({"app_id": "a", "app_secret": "b"})
    with pytest.raises(RuntimeError, match="chat_id"):
        ch.send("t", "b")


def test_feishu_requires_some_config(monkeypatch):
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    monkeypatch.delenv("FEISHU_CHAT_ID", raising=False)
    from studio.notify.channels.feishu import FeishuChannel

    with pytest.raises(ValueError):
        FeishuChannel({})


# ---------- chat_id 学习与注入 ----------

def _cfg(tmp_path, feishu_opts):
    p = tmp_path / "studio.yaml"
    p.write_text(yaml.safe_dump({
        "api": {"base_url": "http://x", "username": "u", "password": "p"},
        "notify": {"channels": {"feishu": feishu_opts}},
    }), encoding="utf-8")
    from studio.core.config import Config
    return Config.load(p)


def test_store_kv_roundtrip(tmp_path):
    from studio.core.store import Store

    st = Store(tmp_path / "x.db")
    assert st.get_kv("k") is None
    st.set_kv("k", "v1")
    st.set_kv("k", "v2")
    assert st.get_kv("k") == "v2"
    st.close()


def test_bot_learns_chat_id_and_dedupes(tmp_path, monkeypatch):
    monkeypatch.delenv("FEISHU_CHAT_ID", raising=False)
    cfg = _cfg(tmp_path, {"app_id": "a", "app_secret": "b", "allowed_chat_ids": []})

    from studio.bot.listener import _make_message_handler
    from studio.core.store import Store

    store = Store(cfg.store_path())
    sent = []
    fake_msg_api = NS(create=lambda req: sent.append(req) or NS(success=lambda: True))
    fake_client = NS(im=NS(v1=NS(message=fake_msg_api)))
    fake_engine = NS(resolve_stock=lambda tok: None)  # 全部无法识别 → 只回帮助卡
    handler = _make_message_handler(cfg, store, fake_client, engine_client=fake_engine)

    def ev(mid):
        return NS(event=NS(
            sender=NS(sender_type="user", sender_id=NS(open_id="ou_1")),
            message=NS(chat_id="oc_42", message_type="text", message_id=mid,
                       content=json.dumps({"text": "你好"})),  # 无代码 → 只回帮助卡
        ))

    handler(ev("m1"))
    assert store.get_kv("feishu_chat_id") == "oc_42"  # 学到了 chat_id
    assert len(sent) == 1                              # 回了一张帮助卡
    handler(ev("m1"))                                  # 重复投递
    assert len(sent) == 1                              # 幂等去重生效
    store.close()


def test_build_channels_injects_learned_chat_id(tmp_path, monkeypatch):
    monkeypatch.delenv("FEISHU_CHAT_ID", raising=False)
    cfg = _cfg(tmp_path, {"app_id": "cli_x", "app_secret": "s"})

    from studio.core.store import Store
    st = Store(cfg.store_path())
    st.set_kv("feishu_chat_id", "oc_learned")
    st.close()

    from studio.notify.scheduler import build_channels
    chans = build_channels(cfg)
    assert chans and chans[0].chat_id == "oc_learned"


# ---------- 消息解析与入站校验 ----------

def _text_event(mid: str, chat_id: str, text: str):
    return NS(event=NS(
        sender=NS(sender_type="user", sender_id=NS(open_id="ou_1")),
        message=NS(chat_id=chat_id, message_type="text", message_id=mid,
                   content=json.dumps({"text": text})),
    ))


def _capture_cards(monkeypatch):
    """拦截 _send_card，返回 [(title, markdown, template)] 记录列表。"""
    import studio.bot.listener as listener_mod

    cards = []
    monkeypatch.setattr(
        listener_mod, "_send_card",
        lambda client, chat_id, title, md, template="blue": cards.append((title, md, template)),
    )
    return cards


def test_bot_resolves_candidates_and_runs_pipeline(tmp_path, monkeypatch):
    monkeypatch.delenv("FEISHU_CHAT_ID", raising=False)
    cfg = _cfg(tmp_path, {"app_id": "a", "app_secret": "b"})

    import studio.bot.listener as listener_mod
    from studio.core.store import Store

    cards = _capture_cards(monkeypatch)
    runs = []
    monkeypatch.setattr(
        listener_mod, "run_pipeline",
        lambda cfg_, store_, symbol, **kw: runs.append(symbol),
    )

    table = {"600519": ("600519", "贵州茅台"), "贵州茅台": ("600519", "贵州茅台")}
    fake_engine = NS(resolve_stock=lambda tok: table.get(tok))
    store = Store(cfg.store_path())
    handler = listener_mod._make_message_handler(cfg, store, None, engine_client=fake_engine)

    handler(_text_event("m1", "oc_1", "600519，贵州茅台 你好"))
    # 600519 与 贵州茅台解析到同一只 → 只跑一次；你好未识别
    assert runs == ["600519"]
    assert len(cards) == 1
    title, md, template = cards[0]
    assert template == "green"
    assert "贵州茅台(600519)" in md
    assert "未识别：你好" in md
    store.close()


def test_bot_all_unrecognized_replies_help(tmp_path, monkeypatch):
    monkeypatch.delenv("FEISHU_CHAT_ID", raising=False)
    cfg = _cfg(tmp_path, {"app_id": "a", "app_secret": "b"})

    import studio.bot.listener as listener_mod
    from studio.core.store import Store

    cards = _capture_cards(monkeypatch)
    runs = []
    monkeypatch.setattr(
        listener_mod, "run_pipeline",
        lambda *a, **kw: runs.append(a),
    )
    fake_engine = NS(resolve_stock=lambda tok: None)
    store = Store(cfg.store_path())
    handler = listener_mod._make_message_handler(cfg, store, None, engine_client=fake_engine)

    handler(_text_event("m1", "oc_1", "你好"))
    assert runs == []
    assert len(cards) == 1
    title, md, template = cards[0]
    assert template == "grey"
    assert "未能识别：你好" in md
    store.close()


def test_bot_engine_down_replies_red_card(tmp_path, monkeypatch):
    monkeypatch.delenv("FEISHU_CHAT_ID", raising=False)
    cfg = _cfg(tmp_path, {"app_id": "a", "app_secret": "b"})

    import studio.bot.listener as listener_mod
    from studio.core.store import Store

    cards = _capture_cards(monkeypatch)
    runs = []
    monkeypatch.setattr(
        listener_mod, "run_pipeline",
        lambda *a, **kw: runs.append(a),
    )

    def _boom(tok):
        raise ConnectionError("engine unreachable")

    fake_engine = NS(resolve_stock=_boom)
    store = Store(cfg.store_path())
    handler = listener_mod._make_message_handler(cfg, store, None, engine_client=fake_engine)

    handler(_text_event("m1", "oc_1", "600519"))
    assert runs == []
    assert len(cards) == 1
    title, md, template = cards[0]
    assert title == "引擎连接失败"
    assert template == "red"
    store.close()


@pytest.mark.parametrize("raw,expected", [
    ("600519,000001", ["600519", "000001"]),
    ("@_user_1 600519", ["600519"]),
    ("600519，贵州茅台 300750", ["600519", "贵州茅台", "300750"]),
    ("你好", ["你好"]),          # 中文 token 收为候选；是否真股票由引擎 resolve 判定
    ("", []),
    ("12345", []),              # 5 位数字（港股形状）不收
    ("sh600519", ["sh600519"]), # 市场前缀形式收为候选，引擎负责规范化
    ("600519.SH", ["600519.SH"]),
])
def test_parse_message_text(raw, expected):
    from studio.bot.listener import parse_message_text
    assert parse_message_text(raw) == expected
