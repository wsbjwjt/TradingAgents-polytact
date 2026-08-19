"""Pydantic 请求/响应模型。"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str
    password: str


class AnalysisParameters(BaseModel):
    """单股分析参数。"""

    market_type: str = "A股"
    analysis_date: Optional[date] = None
    research_depth: str = "标准"
    selected_analysts: List[str] = Field(default_factory=lambda: ["market", "fundamentals", "news", "social"])
    custom_prompt: Optional[str] = None
    include_sentiment: bool = True
    include_risk: bool = True
    language: str = "zh-CN"
    quick_analysis_model: Optional[str] = None
    deep_analysis_model: Optional[str] = None

    @field_validator("research_depth", mode="before")
    @classmethod
    def _normalize_depth(cls, v: Any) -> str:
        mapping = {
            "1": "快速",
            "2": "基础",
            "3": "标准",
            "4": "深度",
            "5": "全面",
        }
        if isinstance(v, int) and 1 <= v <= 5:
            return mapping[str(v)]
        if isinstance(v, str) and v in mapping:
            return mapping[v]
        return v

    @property
    def max_debate_rounds(self) -> int:
        mapping = {
            "快速": 1,
            "基础": 1,
            "标准": 2,
            "深度": 2,
            "全面": 3,
        }
        return mapping.get(self.research_depth, 2)

    @property
    def max_risk_discuss_rounds(self) -> int:
        mapping = {
            "快速": 1,
            "基础": 1,
            "标准": 1,
            "深度": 2,
            "全面": 3,
        }
        return mapping.get(self.research_depth, 1)


class SingleAnalysisRequest(BaseModel):
    """提交单股分析请求。"""

    symbol: Optional[str] = Field(None, description="6位股票代码")
    stock_code: Optional[str] = Field(None, description="股票代码(已废弃,使用symbol)")
    parameters: Optional[AnalysisParameters] = None


class TaskStatusResponse(BaseModel):
    """任务状态对象。"""

    task_id: str
    status: str
    progress: int = 0
    message: str = ""
    current_step: Optional[str] = None
    stock_code: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class TaskResultResponse(BaseModel):
    """任务结果对象。"""

    analysis_id: str
    stock_symbol: str
    stock_code: str
    analysis_date: str
    summary: str
    recommendation: str
    confidence_score: float = 0.0
    risk_level: str = ""
    key_points: List[str] = Field(default_factory=list)
    execution_time: float = 0.0
    tokens_used: int = 0
    analysts: List[str]
    research_depth: str
    detailed_analysis: dict = Field(default_factory=dict)
    state: dict = Field(default_factory=dict)
    decision: dict = Field(default_factory=dict)
    reports: dict = Field(default_factory=dict)


class UsageQueryParams(BaseModel):
    """使用记录查询参数。"""

    provider: Optional[str] = None
    model_name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    limit: int = Field(100, ge=1, le=1000)


class UsageRecordsResponse(BaseModel):
    """使用记录响应。"""

    records: List[dict]
    total: int


class BasicInfoResponse(BaseModel):
    """股票基本信息响应。"""

    symbol: str
    name: str


class StandardResponse(BaseModel):
    """统一响应包装。"""

    success: bool
    data: Optional[Any] = None
    message: str
