"""Token 使用记录：追加写 /data/usage.jsonl，支持过滤查询。"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from engine.config import settings

logger = logging.getLogger(__name__)


def record_usage(record: dict[str, Any]) -> None:
    """追加一条使用记录到 usage.jsonl。"""
    record.setdefault("timestamp", datetime.now().isoformat())
    path = settings.usage_path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("写入 usage 记录失败: %s", e)


def query_usage_records(
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
) -> tuple[list[dict[str, Any]], int]:
    """查询使用记录。"""
    path = settings.usage_path
    if not path.exists():
        return [], 0

    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if provider and rec.get("provider") != provider:
                    continue
                if model_name and rec.get("model_name") != model_name:
                    continue

                rec_date = _extract_date(rec.get("timestamp", ""))
                if start_date and rec_date and rec_date < start_date:
                    continue
                if end_date and rec_date and rec_date > end_date:
                    continue

                records.append(rec)
    except Exception as e:
        logger.warning("读取 usage 记录失败: %s", e)
        return [], 0

    total = len(records)
    # 按时间倒序，取前 limit 条
    records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return records[:limit], total


def _extract_date(timestamp: str) -> Optional[str]:
    """从 ISO 时间戳中提取 YYYY-MM-DD。"""
    if not timestamp:
        return None
    try:
        return timestamp[:10]
    except Exception:
        return None
