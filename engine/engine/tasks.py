"""任务管理：内存状态机 + 文件持久化 + asyncio 串行 worker。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from engine.config import settings
from engine.schemas import AnalysisParameters

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务状态机。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisTask:
    """单个分析任务的数据模型。"""

    def __init__(self, task_id: str, symbol: str, parameters: AnalysisParameters) -> None:
        self.task_id = task_id
        self.symbol = symbol
        self.parameters = parameters
        self.status = TaskStatus.PENDING
        self.progress = 0
        self.message = "任务已创建，等待执行"
        self.current_step: Optional[str] = None
        self.start_time: Optional[str] = None
        self.end_time: Optional[str] = None
        self.result: Optional[dict[str, Any]] = None
        self.error: Optional[str] = None
        self.created_at = _now_iso()
        self.execution_time = 0.0
        self.tokens_used = 0
        self.sse_queues: set[asyncio.Queue[dict[str, Any]]] = set()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "symbol": self.symbol,
            "parameters": self.parameters.model_dump(mode="json"),
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "current_step": self.current_step,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "created_at": self.created_at,
            "execution_time": self.execution_time,
            "tokens_used": self.tokens_used,
            "error": self.error,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalysisTask":
        params = AnalysisParameters(**data.get("parameters", {}))
        task = cls(data["task_id"], data["symbol"], params)
        task.status = TaskStatus(data.get("status", "pending"))
        task.progress = data.get("progress", 0)
        task.message = data.get("message", "")
        task.current_step = data.get("current_step")
        task.start_time = data.get("start_time")
        task.end_time = data.get("end_time")
        task.created_at = data.get("created_at", _now_iso())
        task.execution_time = data.get("execution_time", 0.0)
        task.tokens_used = data.get("tokens_used", 0)
        task.error = data.get("error")
        task.result = data.get("result")
        return task

    def _sse_snapshot(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "current_step": self.current_step,
            "execution_time": self.execution_time,
        }


class TaskManager:
    """任务管理器：串行 worker + 内存缓存 + 文件持久化。"""

    def __init__(self) -> None:
        self._tasks: dict[str, AnalysisTask] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._lock = asyncio.Lock()
        self._persistence_dir = settings.tasks_dir

    async def start(self) -> None:
        """启动 worker 并加载残留任务。"""
        self._load_existing_tasks()
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        """停止 worker。"""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    def _load_existing_tasks(self) -> None:
        """启动时加载 /data/tasks 下的任务；非终态标为 failed。"""
        if not self._persistence_dir.exists():
            return
        for path in self._persistence_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                task = AnalysisTask.from_dict(data)
                if task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    task.status = TaskStatus.FAILED
                    task.message = "服务重启，任务被标记为失败"
                    task.end_time = _now_iso()
                    self._persist(task)
                self._tasks[task.task_id] = task
            except Exception as e:
                logger.warning("加载任务文件 %s 失败: %s", path, e)

    def create_task(self, symbol: str, parameters: AnalysisParameters) -> AnalysisTask:
        """创建新任务并入队。"""
        task_id = str(uuid.uuid4())
        task = AnalysisTask(task_id, symbol, parameters)
        self._tasks[task_id] = task
        self._persist(task)
        asyncio.get_event_loop().call_soon_threadsafe(self._queue.put_nowait, task_id)
        return task

    def get_task(self, task_id: str) -> Optional[AnalysisTask]:
        return self._tasks.get(task_id)

    def get_status(self, task_id: str) -> Optional[dict[str, Any]]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "progress": task.progress,
            "message": task.message,
            "current_step": task.current_step,
            "stock_code": task.symbol,
            "stock_symbol": task.symbol,
            "start_time": task.start_time,
            "end_time": task.end_time,
        }

    def get_result(self, task_id: str) -> Optional[dict[str, Any]]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        return task.result

    def subscribe_sse(self, task_id: str) -> Optional[asyncio.Queue[dict[str, Any]]]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        task.sse_queues.add(queue)
        return queue

    def unsubscribe_sse(self, task_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.sse_queues.discard(queue)

    def _persist(self, task: AnalysisTask) -> None:
        """把任务写入 /data/tasks/{task_id}.json。"""
        try:
            path = self._persistence_dir / f"{task.task_id}.json"
            path.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("持久化任务 %s 失败: %s", task.task_id, e)

    def _emit_sse(self, task: AnalysisTask, event: str, data: dict[str, Any]) -> None:
        """向所有订阅者发送 SSE 事件。"""
        payload = {"event": event, "data": data}
        for queue in list(task.sse_queues):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    async def update_progress(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        current_step: Optional[str] = None,
        tokens_used: Optional[int] = None,
    ) -> None:
        """运行器调用此接口更新进度并持久化。"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            if status is not None:
                task.status = status
            if progress is not None:
                task.progress = progress
            if message is not None:
                task.message = message
            if current_step is not None:
                task.current_step = current_step
            if tokens_used is not None:
                task.tokens_used = tokens_used
            if status == TaskStatus.RUNNING and task.start_time is None:
                task.start_time = _now_iso()
            if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                task.end_time = _now_iso()
            self._persist(task)

        # 在锁外发 SSE
        if task:
            self._emit_sse(task, "progress", task._sse_snapshot())

    async def complete_task(
        self,
        task_id: str,
        result: dict[str, Any],
        execution_time: float,
        tokens_used: int,
    ) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.status = TaskStatus.COMPLETED
            task.progress = 100
            task.result = result
            task.execution_time = execution_time
            task.tokens_used = tokens_used
            task.message = "分析完成"
            task.end_time = _now_iso()
            self._persist(task)
        self._emit_sse(task, "completed", task._sse_snapshot())

    async def fail_task(self, task_id: str, error: str) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.status = TaskStatus.FAILED
            task.error = error
            task.message = f"分析失败: {error}"
            task.end_time = _now_iso()
            self._persist(task)
        self._emit_sse(task, "failed", task._sse_snapshot())

    async def _worker_loop(self) -> None:
        """串行 worker：每次只处理一个任务。"""
        while True:
            try:
                task_id = await self._queue.get()
                await self._run_one(task_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("worker 循环异常: %s", e)

    async def _run_one(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if not task:
            return

        await self.update_progress(
            task_id,
            status=TaskStatus.RUNNING,
            message="开始分析",
            current_step="初始化",
            progress=0,
        )

        start = time.time()
        try:
            if settings.is_mock:
                from engine.runner import run_mock_analysis

                result, tokens_used = await run_mock_analysis(task_id, task.symbol, task.parameters, self)
            else:
                from engine.runner import run_real_analysis

                result, tokens_used = await run_real_analysis(task_id, task.symbol, task.parameters, self)

            execution_time = time.time() - start
            await self.complete_task(task_id, result, execution_time, tokens_used)
        except Exception as e:
            logger.exception("任务 %s 执行失败", task_id)
            await self.fail_task(task_id, str(e))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
