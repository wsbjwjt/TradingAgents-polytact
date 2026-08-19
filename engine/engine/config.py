"""配置管理：全部走环境变量。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


class Settings:
    """引擎配置，纯环境变量驱动。"""

    def __init__(self) -> None:
        self.port = int(os.getenv("ENGINE_PORT", "8000"))
        self.username = os.getenv("ENGINE_USERNAME", "admin")
        self.password = os.getenv("ENGINE_PASSWORD", "admin123")
        self.jwt_secret = os.getenv("JWT_SECRET", "change-me-in-production")
        self.access_token_expire_minutes = int(os.getenv("ENGINE_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

        # 数据目录：默认 /data，Windows 下会自然落到当前盘符的 /data
        self.data_dir = Path(os.getenv("TA_DATA_DIR", "/data"))
        self.results_dir = os.getenv("TRADINGAGENTS_RESULTS_DIR", str(self.data_dir / "logs"))
        self.cache_dir = os.getenv("TRADINGAGENTS_CACHE_DIR", str(self.data_dir / "cache"))

        # LLM 配置
        self.backend_url = os.getenv("BACKEND_URL", "")
        self.openai_compatible_api_key = os.getenv(
            "OPENAI_COMPATIBLE_API_KEY",
            os.getenv("OPENAI_API_KEY", ""),
        )
        self.deep_model = os.getenv("ENGINE_DEEP_MODEL", "qwen3.7-plus")
        self.quick_model = os.getenv("ENGINE_QUICK_MODEL", "qwen3.5-plus")

        # 东财限流间隔，透传给 astock
        self.em_min_interval = float(os.getenv("EM_MIN_INTERVAL", "1.0"))

        # Mock 开关
        self.is_mock = os.getenv("POLYTACT_ENGINE_MOCK", "0").strip() in ("1", "true", "True", "TRUE")

    @property
    def tasks_dir(self) -> Path:
        return self.data_dir / "tasks"

    @property
    def usage_path(self) -> Path:
        return self.data_dir / "usage.jsonl"

    def ensure_dirs(self) -> None:
        """确保持久化目录存在。"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        Path(self.results_dir).mkdir(parents=True, exist_ok=True)
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()


def build_engine_config(parameters: Optional[object] = None) -> dict:
    """根据请求参数与环境变量生成 astock 配置字典。"""
    from engine.schemas import AnalysisParameters

    params = parameters or AnalysisParameters()

    config = {
        "project_dir": str(Path(__file__).parent),
        "results_dir": settings.results_dir,
        "data_cache_dir": settings.cache_dir,
        "memory_log_path": str(settings.data_dir / "memory" / "trading_memory.md"),
        "memory_log_max_entries": None,
        # 固定走 openai_compatible，端点由 BACKEND_URL 决定
        "llm_provider": "openai_compatible",
        "deep_think_llm": params.deep_analysis_model or settings.deep_model,
        "quick_think_llm": params.quick_analysis_model or settings.quick_model,
        "backend_url": settings.backend_url or None,
        "max_tokens": None,
        "role_llms": {},
        "google_thinking_level": None,
        "openai_reasoning_effort": None,
        "anthropic_effort": None,
        "deep_think_provider_override": None,
        "quick_think_provider_override": None,
        "agent_sdk_model": "opus",
        "agent_sdk_quick_model": "sonnet",
        "agent_sdk_fallback_provider": None,
        "agent_sdk_fallback_model": None,
        "checkpoint_enabled": False,
        "output_language": "Chinese",
        "market_lookback_days": None,
        "max_debate_rounds": params.max_debate_rounds,
        "max_risk_discuss_rounds": params.max_risk_discuss_rounds,
        "max_recur_limit": 100,
        "data_vendors": {
            "core_stock_apis": "a_stock",
            "technical_indicators": "a_stock",
            "fundamental_data": "a_stock",
            "news_data": "a_stock",
            "signal_data": "a_stock",
        },
        "tool_vendors": {},
    }

    # 透传东财限流环境变量
    os.environ.setdefault("EM_MIN_INTERVAL", str(settings.em_min_interval))
    # 透传 API key
    if settings.openai_compatible_api_key:
        os.environ.setdefault("OPENAI_API_KEY", settings.openai_compatible_api_key)
        os.environ.setdefault("OPENAI_COMPATIBLE_API_KEY", settings.openai_compatible_api_key)

    return config
