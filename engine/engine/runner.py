"""分析执行器：包装 astock 引擎，延迟导入 tradingagents。"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Optional

from engine.config import build_engine_config, settings
from engine.schemas import AnalysisParameters

if TYPE_CHECKING:
    from engine.tasks import TaskManager

logger = logging.getLogger(__name__)

# astock 合法的 7 个分析师键
VALID_ANALYST_KEYS = frozenset({"market", "social", "news", "fundamentals", "policy", "hot_money", "lockup"})

# 阶段到进度的映射（基于 web/progress.py 的 PIPELINE_STAGES）
_PROGRESS_BY_STAGE = {
    "market": 8,
    "social": 16,
    "news": 24,
    "fundamentals": 32,
    "policy": 40,
    "hot_money": 48,
    "lockup": 56,
    "quality_gate": 64,
    "debate": 72,
    "trader": 80,
    "risk": 88,
    "pm": 95,
}


def _normalize_selected_analysts(selected: list[str]) -> list[str]:
    """过滤到 astock 合法键，空列表返回全部 7 个。"""
    normalized = [a.lower().strip() for a in selected]
    filtered = [a for a in normalized if a in VALID_ANALYST_KEYS]
    if not filtered:
        return list(VALID_ANALYST_KEYS)
    return filtered


def _analysis_date_str(parameters: AnalysisParameters) -> str:
    """返回分析日期字符串，默认今天。"""
    if parameters.analysis_date:
        return parameters.analysis_date.isoformat()
    return date.today().isoformat()


def _name_from_tencent(symbol: str) -> str:
    """腾讯行情 qt.gtimg.cn：实测服务器 0.18s 返回，GBK 编码，v_代码="市场~名称~代码~..." """
    try:
        import requests

        prefix = "sh" if symbol.startswith("6") else "sz"
        r = requests.get(f"https://qt.gtimg.cn/q={prefix}{symbol}", timeout=8)
        r.encoding = "gbk"
        parts = r.text.split("~")
        if len(parts) > 2 and parts[2] == symbol:
            return parts[1].strip()
    except Exception as exc:
        logger.warning("腾讯名称查询失败 %s: %s", symbol, exc)
    return ""


def _name_from_eastmoney(symbol: str) -> str:
    """东财 push2 备用：f58 字段即名称（引擎侧低频调用，不进 vendor 的 _em_get 节流链）。"""
    try:
        import requests

        market_code = 1 if symbol.startswith("6") else 0
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={"fltt": "2", "invt": "2", "fields": "f57,f58",
                    "secid": f"{market_code}.{symbol}"},
            timeout=8,
        )
        d = r.json().get("data") or {}
        if str(d.get("f57") or "") == symbol:
            return str(d.get("f58") or "").strip()
    except Exception as exc:
        logger.warning("东财名称查询失败 %s: %s", symbol, exc)
    return ""


def _lookup_name_http(symbol: str) -> str:
    """HTTP 单票名称兜底：腾讯主用 → 东财备用。

    mootdx 全市场名称表从云服务器实测不可用（探测 54s 后内部 TypeError），
    代码→名称这种单票查询不该付出全市场建表的代价。新浪 hq.sinajs.cn
    实测被反爬（403 Forbidden），不用。
    """
    if not re.fullmatch(r"\d{6}", symbol or ""):
        return ""
    return _name_from_tencent(symbol) or _name_from_eastmoney(symbol)


def resolve_stock_name(symbol: str) -> str:
    """解析股票代码对应的名称；mock 模式返回占位名。

    名称表只在已建好时才查（绝不为了单个名字触发 mootdx 全市场建表），
    未建好/查不到时走 HTTP 单票兜底（腾讯主用，东财备用）。
    """
    if settings.is_mock:
        return f"{symbol}（模拟）"
    # 延迟导入 astock；用模块属性访问而非 from-import 绑定
    # （_build_name_code_map 会重新赋值 _code_to_name 全局，from-import 拿到的旧绑定永远是 None）
    from tradingagents.dataflows import a_stock

    if a_stock._code_to_name:
        name = a_stock._code_to_name.get(symbol, "")
        if name:
            return name
    return _lookup_name_http(symbol)


def _warm_name_map_async() -> None:
    """后台线程建名称映射表（首次 mootdx 全市场拉取很慢，绝不阻塞请求路径）。"""
    import threading

    def _w():
        try:
            from tradingagents.dataflows.a_stock import _build_name_code_map

            _build_name_code_map()
            logger.info("股票名称映射表预热完成")
        except Exception as exc:
            logger.warning("名称映射表预热失败（下次请求重试）: %s", exc)

    threading.Thread(target=_w, daemon=True).start()


def resolve_stock(query: str) -> tuple[str, str]:
    """把用户输入（6 位代码 / 带市场前缀代码 / 中文名）解析为 (代码, 名称)。

    无法解析时抛 ValueError（消息已带面向用户的说明，可直接透传）。
    mock 模式只接受 6 位数字代码。

    性能约束：6 位代码走 astock 纯本地规范化，**不触发名称表构建**（mootdx
    全市场建表从云服务器实测不可用）；名称先查已建好的表，查不到走 HTTP
    单票兜底（腾讯主用，东财备用，亚秒级）。中文名必须查表，同步等。
    """
    q = (query or "").strip()
    if not q:
        raise ValueError("输入不能为空")
    if settings.is_mock:
        if re.fullmatch(r"\d{6}", q):
            return q, f"{q}（模拟）"
        raise ValueError(f"找不到股票 '{q}'（mock 模式只接受 6 位代码）")

    # 延迟导入 astock；resolve_ticker 覆盖代码规范化与中文名精确/唯一模糊匹配
    from tradingagents.dataflows import a_stock

    code = a_stock.resolve_ticker(q)
    name = ""
    if a_stock._code_to_name is not None:
        name = a_stock._code_to_name.get(code, "")
    else:
        _warm_name_map_async()
    if not name:
        name = _lookup_name_http(code)
    return code, name


# 上游评级词汇表（vendor/astock portfolio_manager.py 提示词规定的 Rating Scale）
_RATING_MAP = {
    "strong buy": "买入", "buy": "买入", "买入": "买入",
    "overweight": "增持", "增持": "增持",
    "hold": "持有", "neutral": "持有", "持有": "持有",
    "underweight": "减持", "减持": "减持",
    "strong sell": "卖出", "sell": "卖出", "卖出": "卖出",
}
_RATING_RE = re.compile(
    r"(?:rating|recommendation|评级|建议)\s*\*{0,2}\s*[:：]\s*\*{0,2}\s*"
    r"(strong buy|strong sell|overweight|underweight|neutral|buy|sell|hold|买入|增持|持有|减持|卖出)",
    re.IGNORECASE,
)
_KEYWORD_RE = re.compile(r"买入|增持|卖出|减持|持有")
_NEGATORS = "不无無勿非莫未"
_CONF_RE = re.compile(r"(?:置信度|信心度?|confidence)\D{0,12}(\d+(?:\.\d+)?)\s*%?", re.IGNORECASE)


def _trade_decision_to_dict(decision_text: str) -> dict[str, Any]:
    """从 final_trade_decision 文本中尽力解析决策字段。

    优先读模型按提示词输出的 "Rating: X" 行；回落到关键词扫描时检查
    前一个窗口的否定词（避免 "不构成买入理由" 误判为买入）。
    """
    text = decision_text or ""
    decision = {
        "action": "持有",
        "confidence": 0.0,
        "risk_score": 0.0,
        "target_price": None,
        "reasoning": text,
    }

    m = _RATING_RE.search(text)
    if m:
        decision["action"] = _RATING_MAP[m.group(1).lower()]
    else:
        for kw in _KEYWORD_RE.finditer(text):
            window = text[max(0, kw.start() - 6):kw.start()]
            if not any(neg in window for neg in _NEGATORS):
                decision["action"] = _RATING_MAP[kw.group(0)]
                break

    # 置信度只认"置信度/confidence"附近的数字，不抓随机百分比
    conf_match = _CONF_RE.search(text)
    if conf_match:
        conf = float(conf_match.group(1))
        decision["confidence"] = conf * 100 if conf <= 1 else conf

    # 目标价
    price_match = re.search(r"(?:目标价|target price)[^\d]*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if price_match:
        decision["target_price"] = float(price_match.group(1))

    return decision


def _extract_reports(final_state: dict[str, Any], analysts: list[str]) -> dict[str, str]:
    """按 R3 §5.2 提取 reports 字段。"""
    reports: dict[str, str] = {}

    # 分析师报告
    if "market" in analysts:
        reports["market_report"] = str(final_state.get("market_report", "") or "")
    if "social" in analysts:
        reports["sentiment_report"] = str(final_state.get("sentiment_report", "") or "")
    if "news" in analysts:
        reports["news_report"] = str(final_state.get("news_report", "") or "")
    if "fundamentals" in analysts:
        reports["fundamentals_report"] = str(final_state.get("fundamentals_report", "") or "")
    if "policy" in analysts:
        reports["policy_report"] = str(final_state.get("policy_report", "") or "")
    if "hot_money" in analysts:
        reports["hot_money_report"] = str(final_state.get("hot_money_report", "") or "")
    if "lockup" in analysts:
        reports["lockup_report"] = str(final_state.get("lockup_report", "") or "")

    # 计划与决策
    reports["investment_plan"] = str(final_state.get("investment_plan", "") or "")
    reports["trader_investment_plan"] = str(final_state.get("trader_investment_plan", "") or "")
    reports["final_trade_decision"] = str(final_state.get("final_trade_decision", "") or "")

    # 辩论详情
    debate = final_state.get("investment_debate_state") or {}
    if isinstance(debate, dict):
        reports["bull_researcher"] = str(debate.get("bull_history", "") or "")
        reports["bear_researcher"] = str(debate.get("bear_history", "") or "")
        reports["research_team_decision"] = str(debate.get("judge_decision", "") or "")

    risk = final_state.get("risk_debate_state") or {}
    if isinstance(risk, dict):
        reports["risky_analyst"] = str(risk.get("aggressive_history", "") or "")
        reports["safe_analyst"] = str(risk.get("conservative_history", "") or "")
        reports["neutral_analyst"] = str(risk.get("neutral_history", "") or "")
        reports["risk_management_decision"] = str(risk.get("judge_decision", "") or "")

    return reports


def _build_result(
    task_id: str,
    symbol: str,
    parameters: AnalysisParameters,
    final_state: dict[str, Any],
    execution_time: float,
    tokens_used: int,
) -> dict[str, Any]:
    """构造 /api/analysis/tasks/{id}/result 需要的 data 对象。"""
    analysts = _normalize_selected_analysts(parameters.selected_analysts)
    analysis_date = _analysis_date_str(parameters)
    decision_text = str(final_state.get("final_trade_decision", "") or "")
    decision = _trade_decision_to_dict(decision_text)
    reports = _extract_reports(final_state, analysts)

    summary_parts = []
    if decision["action"]:
        summary_parts.append(f"综合建议：{decision['action']}")
    summary_parts.append(decision["reasoning"][:200] + "..." if len(decision["reasoning"]) > 200 else decision["reasoning"])

    return {
        "analysis_id": task_id,
        "stock_symbol": symbol,
        "stock_code": symbol,
        "analysis_date": analysis_date,
        "summary": "\n".join(summary_parts),
        "recommendation": decision["action"],
        "confidence_score": decision["confidence"],
        "risk_level": "中等",
        "key_points": [decision["reasoning"][:120]] if decision["reasoning"] else [],
        "execution_time": execution_time,
        "tokens_used": tokens_used,
        "analysts": analysts,
        "research_depth": parameters.research_depth,
        "detailed_analysis": final_state,
        "state": final_state,
        "decision": decision,
        "reports": reports,
    }


async def run_mock_analysis(
    task_id: str,
    symbol: str,
    parameters: AnalysisParameters,
    task_manager: "TaskManager",
) -> tuple[dict[str, Any], int]:
    """Mock 模式：sleep 3 秒，发若干 progress 事件，返回合成 final_state。"""
    stages = ["market", "social", "news", "fundamentals", "policy", "hot_money", "lockup", "debate", "trader", "risk", "pm"]
    analysis_date = _analysis_date_str(parameters)

    for stage in stages:
        progress = _PROGRESS_BY_STAGE.get(stage, 50)
        await task_manager.update_progress(
            task_id,
            status=None,
            progress=progress,
            message=f"mock 阶段: {stage}",
            current_step=stage,
        )
        await asyncio.sleep(0.25)

    final_state = {
        "company_of_interest": symbol,
        "trade_date": analysis_date,
        "market_report": f"{symbol} 技术面走势稳健（mock）。",
        "sentiment_report": "市场情绪中性偏乐观（mock）。",
        "news_report": "近期无重大利空（mock）。",
        "fundamentals_report": "基本面指标正常（mock）。",
        "policy_report": "政策面无显著变化（mock）。",
        "hot_money_report": "游资关注度一般（mock）。",
        "lockup_report": "解禁压力可控（mock）。",
        "investment_debate_state": {
            "bull_history": "看多观点：估值合理，业绩改善（mock）。",
            "bear_history": "看空观点：宏观环境仍有不确定性（mock）。",
            "history": [],
            "current_response": "",
            "judge_decision": "多空双方观点基本平衡，建议观望（mock）。",
        },
        "trader_investment_plan": "交易员建议：轻仓试多（mock）。",
        "risk_debate_state": {
            "aggressive_history": "激进：可逢低加仓（mock）。",
            "conservative_history": "保守：等待更明确信号（mock）。",
            "neutral_history": "中性：控制仓位（mock）。",
            "history": [],
            "judge_decision": "风险中等，建议持有（mock）。",
        },
        "investment_plan": "研究团队建议：持有观望（mock）。",
        "final_trade_decision": "Signal: Hold。综合多空与风控意见，建议继续持有（mock）。",
    }

    result = _build_result(task_id, symbol, parameters, final_state, 3.0, 0)

    # mock 模式也走兼容落盘，便于 docker 联调
    from engine.reports import save_compatible_reports

    save_compatible_reports(
        final_state=final_state,
        symbol=symbol,
        analysis_date=analysis_date,
        parameters=parameters,
        analysts=_normalize_selected_analysts(parameters.selected_analysts),
    )

    return result, 0


async def run_real_analysis(
    task_id: str,
    symbol: str,
    parameters: AnalysisParameters,
    task_manager: "TaskManager",
) -> tuple[dict[str, Any], int]:
    """真实模式：调用 astock TradingAgentsGraph。"""
    import traceback

    # 延迟导入：只在真实执行路径上 import tradingagents
    from cli.stats_handler import StatsCallbackHandler
    from tradingagents.dataflows.utils import safe_ticker_component
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    analysis_date = _analysis_date_str(parameters)
    analysts = _normalize_selected_analysts(parameters.selected_analysts)

    # 路径安全校验 + 中文名解析
    safe_symbol = safe_ticker_component(symbol)

    config = build_engine_config(parameters)
    stats = StatsCallbackHandler()

    graph = TradingAgentsGraph(
        selected_analysts=analysts,
        debug=False,
        config=config,
        callbacks=[stats],
    )

    start = time.time()
    last_chunk: dict[str, Any] = {}

    loop = asyncio.get_event_loop()

    def _sync_run() -> tuple[dict[str, Any], dict[str, int], str]:
        """在线程中执行同步图调用。"""
        init_state, args, _ = graph.prepare_graph_run(safe_symbol, analysis_date, callbacks=[stats])
        stream = graph.graph.stream(init_state, **args)
        nonlocal last_chunk
        for chunk in stream:
            last_chunk = chunk
            # 根据 chunk 中节点名推断进度
            _update_progress_from_chunk(task_id, chunk, task_manager, loop)
        if not last_chunk:
            raise RuntimeError("分析没有返回任何结果")
        signal = graph.finalize_graph_run(safe_symbol, analysis_date, last_chunk)
        return last_chunk, stats.get_stats(), signal

    try:
        final_state, usage, signal = await asyncio.to_thread(_sync_run)
    except Exception as e:
        traceback.print_exc()
        raise
    finally:
        await asyncio.to_thread(graph.close_graph_run)

    execution_time = time.time() - start
    tokens_used = usage.get("tokens_in", 0) + usage.get("tokens_out", 0)

    # 保存兼容落盘
    from engine.reports import save_compatible_reports

    save_compatible_reports(
        final_state=final_state,
        symbol=safe_symbol,
        analysis_date=analysis_date,
        parameters=parameters,
        analysts=analysts,
    )

    # 记录 token 用量
    from engine.usage import record_usage

    record_usage({
        "task_id": task_id,
        "provider": "openai_compatible",
        "model_name": config.get("deep_think_llm", "unknown"),
        "tokens_used": tokens_used,
        "llm_calls": usage.get("llm_calls", 0),
        "tool_calls": usage.get("tool_calls", 0),
        "tokens_in": usage.get("tokens_in", 0),
        "tokens_out": usage.get("tokens_out", 0),
    })

    result = _build_result(task_id, safe_symbol, parameters, final_state, execution_time, tokens_used)
    return result, tokens_used


def _update_progress_from_chunk(
    task_id: str,
    chunk: dict[str, Any],
    task_manager: "TaskManager",
    loop: asyncio.AbstractEventLoop,
) -> None:
    """根据 stream chunk 推断当前阶段并异步更新进度。"""
    # chunk 是 dict，key 通常是节点名
    node_name = None
    if isinstance(chunk, dict) and chunk:
        # 取第一个非 messages 的 key 作为节点名
        for key in chunk:
            if key != "messages":
                node_name = key
                break

    if not node_name:
        return

    # 节点名到阶段的映射：尝试直接匹配，或取 report key
    stage = node_name
    progress = _PROGRESS_BY_STAGE.get(stage)
    if progress is None:
        # 尝试用 report_key 反查
        from web.progress import PIPELINE_STAGES

        for s in PIPELINE_STAGES:
            if s["report_key"] == node_name:
                stage = s["id"]
                progress = _PROGRESS_BY_STAGE.get(stage, 50)
                break
        if progress is None:
            progress = 50

    # 异步更新进度：在 to_thread 里不能 await，用 run_coroutine_threadsafe
    asyncio.run_coroutine_threadsafe(
        task_manager.update_progress(
            task_id,
            status=None,
            progress=progress,
            message=f"正在执行: {stage}",
            current_step=stage,
            tokens_used=None,
        ),
        loop,
    )
