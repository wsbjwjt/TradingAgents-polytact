"""把 digest 结果 / 任务状态渲染成推送内容。"""
from __future__ import annotations

from typing import Optional


def _display(symbol: str, name: str) -> str:
    return f"{name}（{symbol}）" if name else symbol


def render_digest_message(symbol: str, digest_text: str, source_url: str = "",
                          name: str = "", replay_url: str = "",
                          debate_url: str = "", verdict: str = "") -> tuple[str, str, str, list]:
    """返回 (title, body, markdown, buttons)。

    verdict：引擎五级裁决（买入/增持/持有/减持/卖出），由调用方从任务结果传入；
    缺省时回落扫描简报首行（兼容旧三态简报）。
    """
    who = _display(symbol, name)
    title = f"📊 {who} 开盘前简报"
    if not verdict:
        first_line = digest_text.splitlines()[0] if digest_text else ""
        for v in ("买入", "增持", "持有", "减持", "卖出", "看多", "看空", "中性"):
            if v in first_line:
                verdict = v
                break
    if verdict:
        title += f"（{verdict}）"
    md = digest_text
    buttons = []
    if source_url:
        buttons.append(("查看完整报告", source_url))
    if debate_url:
        buttons.append(("多空辩论回放", debate_url))

    return title, digest_text, md, buttons


def render_task_event(symbol: str, status: str, error: Optional[str] = None,
                      name: str = "") -> tuple[str, str, str]:
    icon = "✅" if status == "completed" else "❌"
    who = _display(symbol, name)
    title = f"{icon} {who} 分析{ '完成' if status == 'completed' else '失败：' + (error or status) }"
    body = f"状态: {status}"
    if error:
        body += f"\n错误: {error[:500]}"
    return title, body, f"**{who}** 分析状态: `{status}`" + (f"\n\n错误：{error[:500]}" if error else "")
