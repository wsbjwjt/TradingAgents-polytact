# -*- coding: utf-8 -*-
"""P1 晨报原型：对单只票跑 astock 全流程，再用 LLM 浓缩为晨报简报。

用法（用 astock 的 venv 运行）：
    D:/aicodes/TradingAgents-astock/.venv/Scripts/python.exe scripts/p1_morning_sample.py

环境变量（可选）：PROTO_TICKER / PROTO_DATE / PROTO_DEEP / PROTO_QUICK / PROTO_DIGEST_MODEL
产物：.prototype/state_<ticker>_<date>.json 与 .prototype/morning_report_<ticker>_<date>.md
"""
import datetime
import json
import os
import sys
import time
import traceback

TICKER = os.environ.get("PROTO_TICKER", "600519")
TRADE_DATE = os.environ.get("PROTO_DATE", "2026-08-19")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".prototype")
ENV_PATH = r"D:\aicodes\TradingAgents-astock\.env"

REPORT_KEYS = [
    "market_report", "news_report", "sentiment_report", "fundamentals_report",
    "policy_report", "hot_money_report", "lockup_report",
    "investment_plan", "trader_investment_plan", "final_trade_decision",
]


def log(*a):
    print(f"[{datetime.datetime.now():%H:%M:%S}]", *a, flush=True)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    config = dict(DEFAULT_CONFIG)
    config["llm_provider"] = "openai_compatible"
    config["backend_url"] = os.environ["BACKEND_URL"]
    config["deep_think_llm"] = os.environ.get("PROTO_DEEP", "qwen3.7-plus")
    config["quick_think_llm"] = os.environ.get("PROTO_QUICK", "qwen3.5-plus")

    log(f"init engine: deep={config['deep_think_llm']} quick={config['quick_think_llm']}")
    ta = TradingAgentsGraph(debug=False, config=config)
    t0 = time.time()
    final_state, signal = ta.propagate(TICKER, TRADE_DATE)
    log(f"propagate done in {time.time() - t0:.0f}s, signal={signal}")

    state_path = os.path.join(OUT_DIR, f"state_{TICKER}_{TRADE_DATE}.json")
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(final_state, f, ensure_ascii=False, indent=2, default=str)
    log("state dumped:", state_path)

    parts = []
    for k in REPORT_KEYS:
        v = final_state.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(f"## {k}\n{v[:6000]}")
    blob = "\n\n".join(parts)
    log(f"digest input chars={len(blob)}")

    from openai import OpenAI
    client = OpenAI(
        base_url=os.environ["BACKEND_URL"],
        api_key=os.environ.get("OPENAI_COMPATIBLE_API_KEY") or os.environ.get("OPENAI_API_KEY"),
    )
    prompt = f"""你是一位专业的 A 股投资晨报编辑。以下是投研系统对 {TICKER} 在 {TRADE_DATE} 的多智能体分析产物（七位分析师报告、牛熊辩论、交易员计划、最终决策）。

请浓缩为一份**晨报简报**，要求：
1. 开头一行：评级（Buy/Overweight/Hold/Underweight/Sell 之一，与最终决策一致）+ 一句话总评；
2. 「核心逻辑」不超过 3 条（每条一句话，只留最重要的论据）；
3. 「风险提示」不超过 2 条；
4. 「今日关注」1-2 条（开盘前值得盯的具体事件/价位/数据）；
5. 全文 300 字以内（不含栏目标题），中文，专业、克制、不堆砌。

分析产物如下：

{blob}"""
    digest_model = os.environ.get("PROTO_DIGEST_MODEL", "qwen3.7-plus")
    log(f"digest with {digest_model} ...")
    resp = client.chat.completions.create(
        model=digest_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    digest = resp.choices[0].message.content
    report_path = os.path.join(OUT_DIR, f"morning_report_{TICKER}_{TRADE_DATE}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# 晨报样例 {TICKER} {TRADE_DATE}\n\n**系统评级：{signal}**\n\n")
        f.write(digest or "")
        f.write("\n")
    log("digest saved:", report_path)
    print("\n===== 晨报简报 =====")
    print(digest)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
