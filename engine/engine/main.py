"""FastAPI 服务入口：暴露与 TradingAgents-CN 形状一致的 HTTP API。"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from engine.auth import create_token_response, get_current_user
from engine.config import settings
from engine.schemas import (
    AnalysisParameters,
    BasicInfoResponse,
    LoginRequest,
    SingleAnalysisRequest,
    StandardResponse,
    TaskResultResponse,
    TaskStatusResponse,
    UsageQueryParams,
    UsageRecordsResponse,
)
from engine.tasks import TaskManager, TaskStatus
from engine.usage import query_usage_records, record_usage

logger = logging.getLogger(__name__)

# 全局单例：任务管理器
task_manager: TaskManager = TaskManager()

# 安全依赖
security = HTTPBearer(auto_error=False)


async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """校验 Bearer Token，失败时抛 401。"""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Authorization 头",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return get_current_user(credentials.credentials)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期：启动 worker，关闭时清理。"""
    await task_manager.start()
    logger.info("Engine 服务已启动，mock=%s", settings.is_mock)
    yield
    await task_manager.stop()
    logger.info("Engine 服务已关闭")


app = FastAPI(
    title="TradingAgents Engine",
    description="包装 TradingAgents-astock 的 FastAPI 服务",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """把业务 ValueError 转成标准失败响应。"""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"success": False, "data": None, "message": str(exc)},
    )


@app.get("/api/health")
async def health() -> dict[str, Any]:
    """健康检查，无需鉴权。"""
    return {"status": "ok", "mock": settings.is_mock}


@app.post("/api/auth/login", response_model=StandardResponse)
async def login(request: LoginRequest) -> dict[str, Any]:
    """单用户登录，返回 JWT access_token / refresh_token。"""
    if request.username != settings.username or request.password != settings.password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    return create_token_response(request.username)


@app.post("/api/analysis/single", response_model=StandardResponse)
async def single_analysis(
    request: SingleAnalysisRequest,
    user: str = Depends(require_auth),
) -> dict[str, Any]:
    """提交单股分析任务，返回 task_id。"""
    symbol = request.symbol or request.stock_code
    if not symbol:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="必须提供 symbol 或 stock_code")

    task = task_manager.create_task(
        symbol=symbol,
        parameters=request.parameters or AnalysisParameters(),
    )
    return {
        "success": True,
        "data": {
            "task_id": task.task_id,
            "status": task.status.value,
            "message": "任务已创建，等待执行",
        },
        "message": "分析任务已在后台启动",
    }


@app.get("/api/analysis/tasks/{task_id}/status", response_model=StandardResponse)
async def task_status(
    task_id: str,
    user: str = Depends(require_auth),
) -> dict[str, Any]:
    """查询任务状态。"""
    status_obj = task_manager.get_status(task_id)
    if status_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return {"success": True, "data": status_obj, "message": "任务状态获取成功"}


@app.get("/api/analysis/tasks/{task_id}/result", response_model=StandardResponse)
async def task_result(
    task_id: str,
    user: str = Depends(require_auth),
) -> dict[str, Any]:
    """查询任务结果（仅 completed / failed 返回有效结果）。"""
    result = task_manager.get_result(task_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在或尚未完成")
    return {"success": True, "data": result, "message": "分析结果获取成功"}


async def _sse_event_stream(task_id: str) -> AsyncGenerator[str, None]:
    """SSE 事件生成器：connected / progress / heartbeat / error。"""
    yield f"event: connected\ndata: {__json_dumps({'task_id': task_id, 'message': '已连接进度流'})}\n\n"

    queue = task_manager.subscribe_sse(task_id)
    if queue is None:
        yield f"event: error\ndata: {__json_dumps({'error': '任务不存在'})}\n\n"
        return

    heartbeat_interval = 10.0
    last_event_time = asyncio.get_event_loop().time()
    try:
        while True:
            timeout = heartbeat_interval - (asyncio.get_event_loop().time() - last_event_time)
            if timeout <= 0:
                timeout = heartbeat_interval
            try:
                event = await asyncio.wait_for(queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                now = datetime.now(timezone.utc).isoformat()
                yield f"event: heartbeat\ndata: {__json_dumps({'timestamp': now})}\n\n"
                last_event_time = asyncio.get_event_loop().time()
                continue

            last_event_time = asyncio.get_event_loop().time()
            event_type = event.get("event", "progress")
            yield f"event: {event_type}\ndata: {__json_dumps(event.get('data', {}))}\n\n"

            # 终态事件后关闭流
            if event_type in ("completed", "failed", "error"):
                return
    finally:
        task_manager.unsubscribe_sse(task_id, queue)


def __json_dumps(obj: Any) -> str:
    """SSE 用的紧凑 JSON 序列化。"""
    import json

    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


@app.get("/api/stream/tasks/{task_id}")
async def stream_task(
    task_id: str,
    user: str = Depends(require_auth),
) -> StreamingResponse:
    """SSE 进度流。"""
    return StreamingResponse(
        _sse_event_stream(task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# 使用记录双路径别名，兼容 client.py 的两种写法
@app.get("/api/usage/records", response_model=StandardResponse)
@app.get("/api/usage-statistics/records", response_model=StandardResponse)
async def usage_records(
    params: UsageQueryParams = Depends(),
    user: str = Depends(require_auth),
) -> dict[str, Any]:
    """查询 LLM token 使用记录。"""
    records, total = query_usage_records(
        provider=params.provider,
        model_name=params.model_name,
        start_date=params.start_date,
        end_date=params.end_date,
        limit=params.limit,
    )
    return {
        "success": True,
        "data": {"records": records, "total": total},
        "message": "获取使用记录成功",
    }


@app.get("/api/stock-data/basic-info/{symbol}", response_model=StandardResponse)
async def stock_basic_info(
    symbol: str,
    user: str = Depends(require_auth),
) -> dict[str, Any]:
    """返回股票代码与名称映射。mock 模式下返回占位数据。"""
    from engine.runner import resolve_stock_name

    name = resolve_stock_name(symbol)
    return {
        "success": True,
        "data": {"symbol": symbol, "name": name},
        "message": "获取股票基本信息成功",
    }


@app.get("/api/stock-data/resolve/{query}", response_model=StandardResponse)
async def stock_resolve(
    query: str,
    user: str = Depends(require_auth),
) -> dict[str, Any]:
    """把代码或中文名解析为 (代码, 名称)，供飞书 bot 入站校验。

    无法识别时返回 success=False（消息面向用户，可直接展示），HTTP 状态仍为 200。
    """
    from engine.runner import resolve_stock

    try:
        code, name = resolve_stock(query)
    except ValueError as exc:
        return {"success": False, "data": None, "message": str(exc)}
    return {
        "success": True,
        "data": {"symbol": code, "name": name, "query": query},
        "message": "解析成功",
    }
