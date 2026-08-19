"""兼容落盘层：把 final_state 写成 hsliuping 的目录结构。"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from engine.config import settings
from engine.schemas import AnalysisParameters

logger = logging.getLogger(__name__)


def save_compatible_reports(
    final_state: dict[str, Any],
    symbol: str,
    analysis_date: str,
    parameters: AnalysisParameters,
    analysts: Optional[list[str]] = None,
) -> Path:
    """把分析结果保存为 hsliuping 布局。

    目录结构：
        {TA_DATA_DIR}/analysis_results/{symbol}/{analysis_date}/
            message_tool.log
            analysis_metadata.json
            reports/
                market_report.md
                sentiment_report.md
                news_report.md
                fundamentals_report.md
                investment_plan.md
                trader_investment_plan.md
                final_trade_decision.md
                research_team_decision.md
                risk_management_decision.md
                policy_report.md
                hot_money_report.md
                lockup_report.md
    """
    base_dir = Path(settings.data_dir) / "analysis_results" / symbol / analysis_date
    reports_dir = base_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # 分析师报告
    report_files = {
        "market_report": "market_report.md",
        "sentiment_report": "sentiment_report.md",
        "news_report": "news_report.md",
        "fundamentals_report": "fundamentals_report.md",
        "policy_report": "policy_report.md",
        "hot_money_report": "hot_money_report.md",
        "lockup_report": "lockup_report.md",
        "investment_plan": "investment_plan.md",
        "trader_investment_plan": "trader_investment_plan.md",
        "final_trade_decision": "final_trade_decision.md",
    }

    for key, filename in report_files.items():
        content = final_state.get(key, "")
        if content:
            (reports_dir / filename).write_text(str(content), encoding="utf-8")

    # 辩论文件
    debate = final_state.get("investment_debate_state") or {}
    if isinstance(debate, dict):
        if debate.get("bull_history"):
            (reports_dir / "bull_researcher.md").write_text(str(debate["bull_history"]), encoding="utf-8")
        if debate.get("bear_history"):
            (reports_dir / "bear_researcher.md").write_text(str(debate["bear_history"]), encoding="utf-8")
        if debate.get("judge_decision"):
            (reports_dir / "research_team_decision.md").write_text(str(debate["judge_decision"]), encoding="utf-8")
        # 原始辩论状态（JSON）：studio 多空辩论回放页的数据源
        # （.md 是渲染文本，轮次信息已消化；回放需要带 history 的结构化数据）
        if debate:
            (reports_dir / "investment_debate_state.json").write_text(
                json.dumps(debate, ensure_ascii=False, default=str), encoding="utf-8")

    risk = final_state.get("risk_debate_state") or {}
    if isinstance(risk, dict):
        if risk.get("aggressive_history"):
            (reports_dir / "risky_analyst.md").write_text(str(risk["aggressive_history"]), encoding="utf-8")
        if risk.get("conservative_history"):
            (reports_dir / "safe_analyst.md").write_text(str(risk["conservative_history"]), encoding="utf-8")
        if risk.get("neutral_history"):
            (reports_dir / "neutral_analyst.md").write_text(str(risk["neutral_history"]), encoding="utf-8")
        if risk.get("judge_decision"):
            (reports_dir / "risk_management_decision.md").write_text(str(risk["judge_decision"]), encoding="utf-8")
        if risk:
            (reports_dir / "risk_debate_state.json").write_text(
                json.dumps(risk, ensure_ascii=False, default=str), encoding="utf-8")

    # metadata
    metadata = {
        "stock_symbol": symbol,
        "analysis_date": analysis_date,
        "research_depth": parameters.research_depth,
        "analysts": analysts or [],
        "status": "completed",
        "reports_count": len([p for p in reports_dir.glob("*.md") if p.is_file()]),
        "report_types": [p.stem for p in reports_dir.glob("*.md") if p.is_file()],
        "generated_at": datetime.now().isoformat(),
    }
    (base_dir / "analysis_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    # 如果 astock 有 message_tool.log，复制过来
    astock_log = Path(settings.results_dir) / symbol / "TradingAgentsStrategy_logs" / "message_tool.log"
    if astock_log.exists():
        try:
            shutil.copy2(astock_log, base_dir / "message_tool.log")
        except Exception as e:
            logger.warning("复制 message_tool.log 失败: %s", e)

    return base_dir
