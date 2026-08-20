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
    fake_engine = NS(resolve_stock=lambda tok: ("", "", "找不到股票"))  # 全部无法识别 → 只回帮助卡
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
        lambda cfg_, store_, symbol, **kw: runs.append((symbol, kw.get("stock_name"))),
    )

    table = {
        "600519": ("600519", "贵州茅台", ""),
        "贵州茅台": ("600519", "贵州茅台", ""),
    }
    fake_engine = NS(resolve_stock=lambda tok: table.get(tok, ("", "", "找不到股票")))
    store = Store(cfg.store_path())
    handler = listener_mod._make_message_handler(cfg, store, None, engine_client=fake_engine)

    handler(_text_event("m1", "oc_1", "600519，贵州茅台 你好"))
    # 600519 与 贵州茅台解析到同一只 → 只跑一次；你好未识别
    # 入站 resolve 的名称要随管道传递（盘后二次查询会落空）
    assert runs == [("600519", "贵州茅台")]
    # 确认卡 + 每只一张进度初始卡
    assert len(cards) == 2
    title, md, template = cards[0]
    assert template == "green"
    assert "贵州茅台（600519）" in md          # 全角括号队列格式
    assert "预计" in md                        # 排队 ETA 可见
    assert "未识别：`你好`（找不到股票）" in md
    ptitle, _pmd, ptemplate = cards[1]
    assert ptitle.startswith("▶️") and "分析中" in ptitle and ptemplate == "wathet"
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
    fake_engine = NS(resolve_stock=lambda tok: ("", "", "找不到股票，请检查代码或名称"))
    store = Store(cfg.store_path())
    handler = listener_mod._make_message_handler(cfg, store, None, engine_client=fake_engine)

    handler(_text_event("m1", "oc_1", "你好"))
    assert runs == []
    assert len(cards) == 1
    title, md, template = cards[0]
    assert template == "grey"
    assert "未能识别：`你好`（找不到股票，请检查代码或名称）" in md
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

    def _health_boom():
        raise ConnectionError("engine unreachable")

    fake_engine = NS(resolve_stock=_boom, health=_health_boom)
    store = Store(cfg.store_path())
    handler = listener_mod._make_message_handler(cfg, store, None, engine_client=fake_engine)

    handler(_text_event("m1", "oc_1", "600519"))
    assert runs == []
    assert len(cards) == 1
    title, md, template = cards[0]
    assert title == "引擎连接失败"
    assert template == "red"
    store.close()


def test_bot_resolve_timeout_degrades_code_passthrough(tmp_path, monkeypatch):
    """resolve 超时但引擎活着（health 通）：6 位代码降级透传，中文名进未识别。"""
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

    def _slow(tok):
        raise TimeoutError("read timed out")

    fake_engine = NS(resolve_stock=_slow, health=lambda: {"status": "ok"})
    store = Store(cfg.store_path())
    handler = listener_mod._make_message_handler(cfg, store, None, engine_client=fake_engine)

    handler(_text_event("m1", "oc_1", "600619，贵州茅台"))
    assert runs == ["600619"]           # 代码降级透传
    assert len(cards) == 2              # 确认卡 + 进度初始卡
    title, md, template = cards[0]
    assert template == "green"
    assert "名称校验" in md              # 降级提示可见
    assert "未识别：`贵州茅台`（名称校验暂不可用" in md  # 中文名无法校验，带原因
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


# ---------- 多空辩论回放数据解析 ----------

def test_debate_parse_json_state(tmp_path):
    """engine 写的 investment_debate_state.json 能解析出辩论轮次。"""
    state = {
        "history": "Bull Analyst: 看多理由\n\nBear Analyst: 看空理由",
        "bull_history": "Bull Analyst: 看多理由",
        "bear_history": "Bear Analyst: 看空理由",
        "judge_decision": "持有",
    }
    p = tmp_path / "investment_debate_state.json"
    p.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    from studio.replay.debate import load_debate_from_file

    d = load_debate_from_file(p, "research")
    assert d is not None
    assert [t.speaker for t in d.turns] == ["Bull", "Bear"]
    assert d.verdict == "持有"


def test_debate_parse_risk_aggressive_prefix(tmp_path):
    """astock 风控辩论的 Aggressive/Conservative 前缀也能切轮次。"""
    state = {
        "aggressive_history": "Aggressive Analyst: 冲",
        "conservative_history": "Conservative Analyst: 稳",
        "judge_decision": "风险中等",
    }
    p = tmp_path / "risk_debate_state.json"
    p.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    from studio.replay.debate import load_debate_from_file

    d = load_debate_from_file(p, "risk")
    assert d is not None
    assert {t.side for t in d.turns} == {"risky", "safe"}


def test_debate_parse_hsliuping_repr(tmp_path):
    """hsliuping 原版 dict repr 格式仍能解析（回落路径）。"""
    p = tmp_path / "research_team_decision.md"
    p.write_text(repr({"judge_decision": "买入", "history": "Bull Analyst: 多"}), encoding="utf-8")
    from studio.replay.debate import load_debate_from_file

    d = load_debate_from_file(p)
    assert d is not None and d.verdict == "买入" and len(d.turns) == 1


def test_debate_markdown_narrative_returns_none(tmp_path):
    """渲染后的 markdown（无 dict 结构）不误判为辩论数据。"""
    p = tmp_path / "research_team_decision.md"
    p.write_text("# 投资决议\n\n**最终评级：买入**", encoding="utf-8")
    from studio.replay.debate import load_debate_from_file

    assert load_debate_from_file(p) is None


# ---------- fetch_report：result 丢失后的文件卷兜底 ----------

def test_fetch_report_falls_back_to_status_and_disk(tmp_path):
    """get_result 404（引擎重启 result 丢）→ 走 get_status 拿 symbol → 文件卷命中。"""
    from studio.digest.fetcher import fetch_report

    reports = tmp_path / "analysis_results" / "600619" / "2026-08-19" / "reports"
    reports.mkdir(parents=True)
    (reports / "final_trade_decision.md").write_text("买入，目标价 12 元", encoding="utf-8")

    class FakeClient:
        def get_result(self, task_id):
            raise RuntimeError("404")
        def get_status(self, task_id):
            return {"stock_code": "600619", "status": "completed"}

    doc = fetch_report(FakeClient(), "tid-x", ta_dir=tmp_path)
    assert doc.source == "file"
    assert doc.symbol == "600619"
    assert doc.date == "2026-08-19"
    assert "买入" in doc.text


def test_fetch_report_two_level_dir_scan_without_symbol(tmp_path):
    """symbol 也拿不到时，全市场两层扫描仍能找到（symbol/日期/reports）。"""
    from studio.digest.fetcher import fetch_report

    reports = tmp_path / "analysis_results" / "600519" / "2026-08-18" / "reports"
    reports.mkdir(parents=True)
    (reports / "research_team_decision.md").write_text("持有", encoding="utf-8")

    class FakeClient:
        def get_result(self, task_id):
            return {}
        def get_status(self, task_id):
            return {}

    doc = fetch_report(FakeClient(), "tid-y", ta_dir=tmp_path)
    assert doc.source == "file"
    assert doc.symbol == "600519"
    assert "持有" in doc.text


def test_fetch_report_raises_when_nothing_found(tmp_path):
    """API 与文件卷都没有 → FileNotFoundError，消息带 task_id。"""
    import pytest as _pytest
    from studio.digest.fetcher import fetch_report

    class FakeClient:
        def get_result(self, task_id):
            raise RuntimeError("404")
        def get_status(self, task_id):
            raise RuntimeError("404")

    with _pytest.raises(FileNotFoundError, match="tid-z"):
        fetch_report(FakeClient(), "tid-z", ta_dir=tmp_path)


# ---------- 报告页：中文节名 + H1 标题归一 ----------

def test_report_sections_all_stems_have_chinese_labels():
    """17 个报告 stem 都有中文展示名，不漏出裸英文 stem。"""
    from studio.notify.report_server import split_sections

    stems = ["market_report", "fundamentals_report", "news_report", "sentiment_report",
             "policy_report", "hot_money_report", "lockup_report", "bull_researcher",
             "bear_researcher", "research_team_decision", "trader_investment_plan",
             "investment_plan", "risky_analyst", "safe_analyst", "neutral_analyst",
             "risk_management_decision", "final_trade_decision"]
    md = "\n\n".join(f"## {s}\n内容{s}" for s in stems)
    sections = split_sections(md)
    labels = [label for label, _ in sections]
    assert len(sections) == len(stems)
    for stem in stems:
        assert stem not in labels, f"{stem} 缺中文标签"


def test_normalize_h1_code_only_title():
    """"# 300311 技术面分析报告" → "# 任子行（300311）技术面分析报告"。"""
    from studio.notify.report_server import split_sections

    [(label, body)] = split_sections("## market_report\n# 300311 技术面分析报告\n\n正文",
                                     symbol="300311", name="任子行")
    assert label == "市场分析师"
    assert body.startswith("# 任子行（300311）技术面分析报告")


def test_normalize_h1_code_name_order_title():
    """"# 300311 任子行 新闻与政策分析报告" → 统一格式。"""
    from studio.notify.report_server import split_sections

    [(_, body)] = split_sections("## news_report\n# 300311 任子行 新闻与政策分析报告\n\n正文",
                                 symbol="300311", name="任子行")
    assert body.startswith("# 任子行（300311）新闻与政策分析报告")


def test_normalize_h1_already_good_or_absent_untouched():
    """已规范的 H1 重建后与原文一致（幂等）；无 H1 正文、无名可查时都不动。"""
    from studio.notify.report_server import split_sections

    [(_, body)] = split_sections("## bull_researcher\n# 任子行（300311）牛市投资论点\n\n正文",
                                 symbol="300311", name="任子行")
    assert body.startswith("# 任子行（300311）牛市投资论点")

    # emoji 前缀归一到「名字（代码）」之后，前缀统一优先于保留原始语序
    [(_, body_emoji)] = split_sections("## bull_researcher\n# 🐂 任子行（300311）牛市投资论点\n\n正文",
                                       symbol="300311", name="任子行")
    assert body_emoji.startswith("# 任子行（300311）🐂 牛市投资论点")

    [(_, body2)] = split_sections("## fundamentals_report\n根据获取到的数据，直接开头",
                                  symbol="300311", name="任子行")
    assert body2.startswith("根据获取到的数据")

    [(_, body3)] = split_sections("## market_report\n# 300311 技术面分析报告",
                                  symbol="300311", name="")
    assert body3.startswith("# 300311 技术面分析报告")


def test_normalize_h1_spaced_name_no_duplication():
    """002165 红宝丽案例：名称带对齐空格 + 模型写紧凑名 → 不得重复、不留空括号。"""
    from studio.notify.report_server import split_sections

    [(_, body)] = split_sections("## fundamentals_report\n# 红宝丽（002165）基本面分析报告\n\n正文",
                                 symbol="002165", name="红 宝 丽")
    assert body.startswith("# 红宝丽（002165）基本面分析报告")
    assert body.count("红宝丽") == 1 and "（）" not in body.splitlines()[0]


def test_normalize_h1_code_first_parens_and_suffix():
    """"代码（名字）"乱序、"名字（代码.SZ)" 后缀都归一，不留空括号与 .SZ 残渣。"""
    from studio.notify.report_server import split_sections

    [(_, b1)] = split_sections("## sentiment_report\n# 600758（辽宁能源）市场情绪分析报告\n\n正文",
                               symbol="600758", name="辽宁能源")
    assert b1.startswith("# 辽宁能源（600758）市场情绪分析报告")

    [(_, b2)] = split_sections("## policy_report\n# 平安银行（000001.SZ）政策分析报告\n\n正文",
                               symbol="000001", name="平安银行")
    assert b2.startswith("# 平安银行（000001）政策分析报告")


def test_display_uses_fullwidth_parens():
    from studio.notify.render import _display

    assert _display("300311", "任子行") == "任子行（300311）"
    assert _display("300311", "") == "300311"


def test_bot_progress_card_updates_on_stage_change(tmp_path, monkeypatch):
    """进度卡生命周期：开始发卡 → 阶段变化原地 PATCH（同阶段去重）→ 完成收尾。"""
    monkeypatch.delenv("FEISHU_CHAT_ID", raising=False)
    cfg = _cfg(tmp_path, {"app_id": "a", "app_secret": "b"})

    import studio.bot.listener as listener_mod
    from studio.core.store import Store

    sent = []
    patches = []
    monkeypatch.setattr(
        listener_mod, "_send_card",
        lambda c, ch, title, md, template="blue": sent.append((title, md, template)) or "om_x",
    )
    monkeypatch.setattr(
        listener_mod, "_patch_card",
        lambda c, mid, title, md, template="blue": patches.append((mid, title, md, template)),
    )

    def fake_pipeline(cfg_, store_, symbol, **kw):
        cb = kw["on_progress"]
        cb({"current_step": "market", "progress": 8})
        cb({"current_step": "market", "progress": 10})   # 同阶段不重复播报
        cb({"current_step": "debate", "progress": 72})

    monkeypatch.setattr(listener_mod, "run_pipeline", fake_pipeline)
    fake_engine = NS(resolve_stock=lambda tok: ("300311", "任子行", ""))
    store = Store(cfg.store_path())
    handler = listener_mod._make_message_handler(cfg, store, None, engine_client=fake_engine)
    handler(_text_event("m1", "oc_1", "300311"))

    assert [s[2] for s in sent] == ["green", "wathet"]   # 确认卡 + 进度卡
    assert "任子行（300311）" in sent[0][1] and "预计" in sent[0][1]
    assert sent[1][0].startswith("▶️") and "分析中" in sent[1][0]

    assert all(p[0] == "om_x" for p in patches)          # 全部更新同一张卡
    stage_patches = [p for p in patches if "当前阶段" in p[2]]
    assert len(stage_patches) == 2                        # market 重复被去重
    assert "市场分析" in stage_patches[0][2] and "8%" in stage_patches[0][2]
    assert "多空辩论" in stage_patches[1][2] and "72%" in stage_patches[1][2]
    assert patches[-1][1].startswith("✅") and patches[-1][3] == "green"
    store.close()


def test_bot_pipeline_failure_marks_card_red(tmp_path, monkeypatch):
    """分析失败：进度卡收尾为红色失败态，不静默。"""
    monkeypatch.delenv("FEISHU_CHAT_ID", raising=False)
    cfg = _cfg(tmp_path, {"app_id": "a", "app_secret": "b"})

    import studio.bot.listener as listener_mod
    from studio.core.store import Store

    patches = []
    monkeypatch.setattr(listener_mod, "_send_card",
                        lambda c, ch, title, md, template="blue": "om_x")
    monkeypatch.setattr(listener_mod, "_patch_card",
                        lambda c, mid, title, md, template="blue": patches.append((title, md, template)))

    def _boom(*a, **kw):
        raise RuntimeError("引擎超时")

    monkeypatch.setattr(listener_mod, "run_pipeline", _boom)
    fake_engine = NS(resolve_stock=lambda tok: ("300311", "任子行", ""))
    store = Store(cfg.store_path())
    handler = listener_mod._make_message_handler(cfg, store, None, engine_client=fake_engine)
    handler(_text_event("m1", "oc_1", "300311"))

    assert len(patches) == 1
    title, md, template = patches[0]
    assert title.startswith("❌") and template == "red" and "引擎超时" in md
    store.close()


# ---------- 简报标题五级裁决（替代旧三态 看多/看空/中性） ----------

def test_digest_title_uses_engine_five_level_verdict():
    """引擎裁决优先：裁决"减持"时标题（减持），不受简报首行"看空"影响。"""
    from studio.notify.render import render_digest_message

    title, _, _, _ = render_digest_message(
        "603406", "【结论】看空：业绩承压", name="天富龙", verdict="减持")
    assert title == "📊 天富龙（603406） 开盘前简报（减持）"


def test_digest_title_fallback_scans_five_levels():
    """未传裁决时回落扫描首行，五级词优先于旧三态。"""
    from studio.notify.render import render_digest_message

    title, _, _, _ = render_digest_message("600519", "【结论】增持：估值修复")
    assert "（增持）" in title
    # 旧三态简报兼容
    title2, _, _, _ = render_digest_message("600519", "【结论】中性：观望")
    assert "（中性）" in title2


def test_fetch_report_carries_recommendation(tmp_path):
    """文件卷路径也带上引擎裁决：recommendation 优先，decision.action 兜底。"""
    from studio.digest.fetcher import fetch_report

    reports = tmp_path / "analysis_results" / "603406" / "2026-08-20" / "reports"
    reports.mkdir(parents=True)
    (reports / "final_trade_decision.md").write_text("Rating: Underweight", encoding="utf-8")

    class FakeClient:
        def get_result(self, task_id):
            return {"stock_code": "603406", "recommendation": "减持"}
        def get_status(self, task_id):
            return {}

    doc = fetch_report(FakeClient(), "tid-r", ta_dir=tmp_path)
    assert doc.recommendation == "减持"

    class FakeClient2(FakeClient):
        def get_result(self, task_id):
            return {"stock_code": "603406", "decision": {"action": "卖出"}}

    assert fetch_report(FakeClient2(), "tid-r", ta_dir=tmp_path).recommendation == "卖出"


def test_build_user_anchors_rating():
    """裁决评级进入提炼提示词，锚定【结论】行。"""
    from studio.digest.templates import build_user

    out = build_user("603406", "标准", "报告正文", rating="减持")
    assert "组合经理裁决评级：减持" in out
    assert "【结论】行以此评级开头" in out
    assert build_user("603406", "标准", "报告正文").count("裁决评级") == 0
