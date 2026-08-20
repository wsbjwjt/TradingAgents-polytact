"""Mock 模式下的 API 端到端测试。"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 强制 mock 模式与临时数据目录
os.environ["POLYTACT_ENGINE_MOCK"] = "1"
os.environ["TA_DATA_DIR"] = tempfile.mkdtemp(prefix="ta_engine_test_")
os.environ["ENGINE_USERNAME"] = "testuser"
os.environ["ENGINE_PASSWORD"] = "testpass"
os.environ["JWT_SECRET"] = "test-secret"

from engine.main import app, task_manager  # noqa: E402


@pytest.fixture(scope="module")
def client():
    """复用 TestClient。"""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    """登录并返回 Bearer 头。"""
    resp = client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    assert resp.status_code == 200
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    """健康检查无需鉴权。"""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_login_success(client):
    """登录成功返回标准响应。"""
    resp = client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "access_token" in data["data"]
    assert "refresh_token" in data["data"]
    assert data["data"]["expires_in"] == 3600
    assert data["data"]["user"]["username"] == "testuser"


def test_login_failure(client):
    """登录失败返回 401。"""
    resp = client.post("/api/auth/login", json={"username": "testuser", "password": "wrong"})
    assert resp.status_code == 401


def test_unauthorized(client):
    """未带 Token 访问受保护端点返回 401。"""
    resp = client.post("/api/analysis/single", json={"symbol": "600519"})
    assert resp.status_code == 401


def test_basic_info(client, auth_headers):
    """股票基本信息返回 symbol + name。"""
    resp = client.get("/api/stock-data/basic-info/600519", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["symbol"] == "600519"
    assert "600519" in data["data"]["name"]


def test_resolve_accepts_six_digit_code(client, auth_headers):
    """resolve 端点：mock 模式下 6 位代码解析成功。"""
    resp = client.get("/api/stock-data/resolve/600519", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["symbol"] == "600519"
    assert "模拟" in body["data"]["name"]


def test_resolve_rejects_chinese_in_mock(client, auth_headers):
    """resolve 端点：mock 模式不解析中文名，success=False 且消息面向用户。"""
    resp = client.get("/api/stock-data/resolve/%E8%8C%85%E5%8F%B0", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "茅台" in body["message"]


def test_resolve_rejects_garbage(client, auth_headers):
    """resolve 端点：非代码非中文的垃圾输入 success=False。"""
    resp = client.get("/api/stock-data/resolve/abc", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["success"] is False


def test_resolve_requires_auth(client):
    """resolve 端点需要鉴权。"""
    resp = client.get("/api/stock-data/resolve/600519")
    assert resp.status_code in (401, 403)


def test_single_analysis_lifecycle(client, auth_headers):
    """提交 -> 状态 pending -> 等待完成 -> result 形状正确。"""
    resp = client.post(
        "/api/analysis/single",
        headers=auth_headers,
        json={
            "symbol": "600519",
            "parameters": {
                "analysis_date": "2025-08-19",
                "research_depth": "标准",
                "selected_analysts": ["market", "fundamentals"],
                "quick_analysis_model": "qwen3.5-plus",
                "deep_analysis_model": "qwen3.7-plus",
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "pending"
    task_id = body["data"]["task_id"]

    # 状态流转轮询
    for _ in range(50):
        resp = client.get(f"/api/analysis/tasks/{task_id}/status", headers=auth_headers)
        assert resp.status_code == 200
        status_body = resp.json()
        if status_body["data"]["status"] in ("completed", "failed"):
            break
        asyncio.run(asyncio.sleep(0.2))
    else:
        raise AssertionError("任务未在预期时间内完成")

    assert status_body["data"]["status"] == "completed"
    assert status_body["data"]["progress"] == 100

    # 结果
    resp = client.get(f"/api/analysis/tasks/{task_id}/result", headers=auth_headers)
    assert resp.status_code == 200
    result = resp.json()
    assert result["success"] is True
    data = result["data"]
    assert data["stock_symbol"] == "600519"
    assert data["analysis_date"] == "2025-08-19"
    assert data["recommendation"] == "持有"
    assert "decision" in data
    assert "reports" in data
    assert "market_report" in data["reports"]
    assert "research_team_decision" in data["reports"]
    assert "risk_management_decision" in data["reports"]


def test_sse_progress(client, auth_headers):
    """SSE 流能收到 connected 与 progress 事件。"""
    resp = client.post(
        "/api/analysis/single",
        headers=auth_headers,
        json={"symbol": "000001", "parameters": {"research_depth": "快速"}},
    )
    task_id = resp.json()["data"]["task_id"]

    with client.stream("GET", f"/api/stream/tasks/{task_id}", headers=auth_headers) as stream:
        events = []
        for line in stream.iter_lines():
            if line.startswith("event: "):
                events.append(line[len("event: "):])
            if len(events) >= 3:
                break

    assert "connected" in events
    assert "progress" in events


def test_usage_records(client, auth_headers):
    """使用记录接口返回标准形状。"""
    resp = client.get("/api/usage/records", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "records" in data["data"]
    assert "total" in data["data"]

    # 双路径别名
    resp2 = client.get("/api/usage-statistics/records", headers=auth_headers)
    assert resp2.status_code == 200
    assert resp2.json()["success"] is True


def test_compatible_disk_layout(client, auth_headers):
    """任务完成后落盘文件符合 hsliuping 布局。"""
    resp = client.post(
        "/api/analysis/single",
        headers=auth_headers,
        json={"symbol": "600036", "parameters": {"research_depth": "基础"}},
    )
    task_id = resp.json()["data"]["task_id"]

    for _ in range(50):
        resp = client.get(f"/api/analysis/tasks/{task_id}/status", headers=auth_headers)
        if resp.json()["data"]["status"] == "completed":
            break
        asyncio.run(asyncio.sleep(0.2))

    base_dir = Path(os.environ["TA_DATA_DIR"]) / "analysis_results" / "600036" / date_today()
    reports_dir = base_dir / "reports"
    assert (reports_dir / "market_report.md").exists()
    assert (reports_dir / "research_team_decision.md").exists()
    assert (reports_dir / "risk_management_decision.md").exists()
    assert (base_dir / "analysis_metadata.json").exists()

    # 辩论回放数据源：原始 state 以 JSON 落盘（.md 是渲染文本，轮次已消化）
    import json as _json
    debate = _json.loads((reports_dir / "investment_debate_state.json").read_text(encoding="utf-8"))
    assert debate["bull_history"] and debate["judge_decision"]
    risk = _json.loads((reports_dir / "risk_debate_state.json").read_text(encoding="utf-8"))
    assert risk["aggressive_history"] and risk["judge_decision"]


def date_today() -> str:
    from datetime import date

    return date.today().isoformat()


def test_task_persist_with_unserializable_result(client, auth_headers):
    """result 混入 date/枚举等对象时 _persist 不再静默失败（重启不误判 failed）。"""
    import asyncio
    from datetime import date as _date

    from engine.main import task_manager
    from engine.schemas import AnalysisParameters
    from engine.tasks import AnalysisTask

    # 直接构造并入册：create_task 会向事件循环投递，测试尾部 loop 已关会炸
    task = AnalysisTask("testpersist-unserializable", "600519", AnalysisParameters())
    task_manager._tasks[task.task_id] = task
    result = {
        "symbol": "600519",
        "trade_date": _date(2026, 8, 19),          # json 默认无法序列化
        "decision": {"action": "持有"},
        "raw": object(),                            # 极端：完全未知对象
    }
    asyncio.run(task_manager.complete_task(task.task_id, result, 1.0, 0))

    persisted = json.loads(
        (Path(os.environ["TA_DATA_DIR"]) / "tasks" / f"{task.task_id}.json").read_text(encoding="utf-8")
    )
    assert persisted["status"] == "completed"
    assert persisted["result"]["trade_date"] == "2026-08-19"
    assert persisted["result"]["decision"]["action"] == "持有"


# ---------- 决策文本解析 ----------

def test_decision_parse_rating_line_wins_over_negated_keyword():
    """"不构成买入理由" 不得误判为买入；Rating 行优先。"""
    from engine.runner import _trade_decision_to_dict

    text = (
        "**Rating**: Underweight\n\n**Executive Summary**: 合同负债下降23%。"
        "4.4%股息率提供安全边际，但不构成买入理由。"
    )
    d = _trade_decision_to_dict(text)
    assert d["action"] == "减持"
    assert d["confidence"] == 0.0   # 无"置信度"字样，不抓随机百分比


def test_decision_parse_all_rating_levels():
    from engine.runner import _trade_decision_to_dict

    for rating, expected in [("Buy", "买入"), ("Overweight", "增持"), ("Hold", "持有"),
                             ("Underweight", "减持"), ("Sell", "卖出")]:
        assert _trade_decision_to_dict(f"**Rating**: {rating}")["action"] == expected
    assert _trade_decision_to_dict("**Recommendation**: 买入")["action"] == "买入"


def test_decision_parse_keyword_fallback_with_negation():
    from engine.runner import _trade_decision_to_dict

    d = _trade_decision_to_dict("反弹力度不足，不宜买入，建议继续持有观察。")
    assert d["action"] == "持有"


def test_decision_parse_confidence_only_near_keyword():
    from engine.runner import _trade_decision_to_dict

    d = _trade_decision_to_dict("**Rating**: Buy，置信度 75%，目标价 1500 元")
    assert d["action"] == "买入"
    assert d["confidence"] == 75.0
    assert d["target_price"] == 1500.0


# ---------- 名称解析：HTTP 兜底（腾讯主用 / 东财备用） ----------

class _FakeResp:
    def __init__(self, text="", payload=None):
        self.text = text
        self._payload = payload
        self.encoding = None

    def json(self):
        return {"data": self._payload or {}}


def _patch_requests(monkeypatch, tencent_text=None, em_payload=None, raises=False):
    """替换 requests.get：按 URL 分流到腾讯/东财的假响应。"""
    import requests as _rq

    def fake_get(url, **kw):
        if raises:
            raise ConnectionError("boom")
        if "gtimg.cn" in url:
            return _FakeResp(text=tencent_text or 'v_xx=""')
        return _FakeResp(payload=em_payload)

    monkeypatch.setattr(_rq, "get", fake_get)


def _fake_astock_map(monkeypatch, code_to_name):
    """engine 测试环境没有真 astock：注入只带 _code_to_name 的假模块。"""
    import sys
    import types

    mod_stock = types.ModuleType("tradingagents.dataflows.a_stock")
    mod_stock._code_to_name = code_to_name
    mod_df = types.ModuleType("tradingagents.dataflows")
    mod_df.a_stock = mod_stock
    mod_ta = types.ModuleType("tradingagents")
    mod_ta.dataflows = mod_df
    monkeypatch.setitem(sys.modules, "tradingagents", mod_ta)
    monkeypatch.setitem(sys.modules, "tradingagents.dataflows", mod_df)
    monkeypatch.setitem(sys.modules, "tradingagents.dataflows.a_stock", mod_stock)


def test_lookup_name_http_tencent_primary(monkeypatch):
    """腾讯格式 v_sh603406="1~天富龙~603406~..." 解析出名称。"""
    from engine.runner import _lookup_name_http

    _patch_requests(monkeypatch, tencent_text='v_sh603406="1~天富龙~603406~30.72~29.56"')
    assert _lookup_name_http("603406") == "天富龙"


def test_lookup_name_http_falls_back_to_eastmoney(monkeypatch):
    """腾讯查不到（代码校验不过）→ 东财 f58 备用。"""
    from engine.runner import _lookup_name_http

    _patch_requests(monkeypatch, tencent_text='v_sh603406="1~~~"',
                    em_payload={"f57": "603406", "f58": "天富龙"})
    assert _lookup_name_http("603406") == "天富龙"


def test_lookup_name_http_failure_returns_empty(monkeypatch):
    from engine.runner import _lookup_name_http

    _patch_requests(monkeypatch, raises=True)
    assert _lookup_name_http("603406") == ""
    assert _lookup_name_http("not-a-code") == ""   # 非 6 位代码不发请求


def test_resolve_stock_name_prefers_warm_map(monkeypatch):
    """名称表已建好时直接查表，不发 HTTP。"""
    _fake_astock_map(monkeypatch, {"600519": "贵州茅台"})
    _patch_requests(monkeypatch, raises=True)            # HTTP 全挂也不影响查表
    import engine.runner as runner
    monkeypatch.setattr(runner.settings, "is_mock", False)
    assert runner.resolve_stock_name("600519") == "贵州茅台"
    # 表里没有的票走 HTTP 兜底（这里全挂 → 空串，且不再触发 mootdx 建表）
    assert runner.resolve_stock_name("603406") == ""


def test_resolve_stock_name_http_fallback_when_map_missing(monkeypatch):
    """名称表未建（mootdx 服务器不可用）时 HTTP 兜底补上名称——603406 场景的根修。"""
    _fake_astock_map(monkeypatch, None)
    _patch_requests(monkeypatch, tencent_text='v_sh603406="1~天富龙~603406~30.72"')
    import engine.runner as runner
    monkeypatch.setattr(runner.settings, "is_mock", False)
    assert runner.resolve_stock_name("603406") == "天富龙"
