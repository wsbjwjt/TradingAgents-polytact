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


def date_today() -> str:
    from datetime import date

    return date.today().isoformat()
