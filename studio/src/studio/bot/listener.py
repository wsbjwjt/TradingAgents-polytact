"""飞书入站机器人：长连接接收消息并触发分析管道。

设计约束（来自 research/feishu-long-connection.md）：
- 仅支持企业自建应用；多实例随机投递，生产环境必须只跑单实例。
- 用 message_id 做幂等去重（写入 core/store 的 SQLite）。
- 只响应 sender_type=user 的文本消息；可配 chat_id 白名单。
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from typing import Optional

import lark_oapi as lark
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

from ..core.config import Config
from ..core.store import Store
from ..notify.scheduler import run_pipeline

# 飞书 @ 机器人时会在文本里插入 @_user_N 占位符
_AT_PLACEHOLDER = re.compile(r"@_user_\d+")
# 中英文逗号、空白
_SPLIT_PATTERN = re.compile(r"[,\s，]+")


def _feishu_app_credentials(cfg: Config) -> tuple[str, str]:
    """优先读 studio.yaml notify.channels.feishu，否则读环境变量。"""
    feishu_cfg = cfg.get("notify.channels.feishu", {}) or {}
    app_id = str(feishu_cfg.get("app_id", "") or os.environ.get("FEISHU_APP_ID", ""))
    app_secret = str(
        feishu_cfg.get("app_secret", "") or os.environ.get("FEISHU_APP_SECRET", "")
    )
    return app_id, app_secret


def _allowed_chat_ids(cfg: Config) -> set[str]:
    feishu_cfg = cfg.get("notify.channels.feishu", {}) or {}
    raw = feishu_cfg.get("allowed_chat_ids") or []
    return {str(x) for x in raw if x}


def _clean_at_placeholders(text: str) -> str:
    return _AT_PLACEHOLDER.sub("", text).strip()


def parse_message_text(raw_text: str) -> list[str]:
    """清洗占位符后按逗号/空白切分，返回可识别的代码/名称列表（纯函数，可单测）。

    规则：
      - 6 位数字直接接受；
      - 包含中文的 token 原样透传（engine 会解析中文名）；
      - 其余 token 丢弃。
    """
    text = _clean_at_placeholders(raw_text)
    if not text:
        return []
    codes: list[str] = []
    for part in _SPLIT_PATTERN.split(text):
        part = part.strip()
        if not part:
            continue
        if re.fullmatch(r"\d{6}", part):
            codes.append(part)
        elif re.search(r"[一-鿿]", part):
            codes.append(part)
    return codes


def _build_card(title: str, markdown: str, template: str = "blue") -> str:
    return json.dumps(
        {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "elements": [{"tag": "markdown", "content": markdown}],
        },
        ensure_ascii=False,
    )


def _send_card(
    client: lark.Client, chat_id: str, title: str, markdown: str, template: str = "blue"
) -> None:
    content = _build_card(title, markdown, template)
    req = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("interactive")
            .content(content)
            .build()
        )
        .build()
    )
    resp = client.im.v1.message.create(req)
    if not resp.success():
        raise RuntimeError(f"飞书发消息失败: {getattr(resp, 'msg', resp)}")


def _help_md() -> str:
    return (
        "请发送要分析的股票代码或中文名，多个用逗号/空格分隔。\n\n"
        "示例：`600519, 000001，贵州茅台`\n\n"
        "- 6 位数字代码直接识别\n"
        "- 中文股票名原样透传给引擎解析\n"
        "- 预计每只分析 5-15 分钟"
    )


def _confirm_md(codes: list[str]) -> str:
    joined = ", ".join(codes)
    return (
        f"已收到 **{len(codes)} 只**：{joined}\n\n"
        "开始分析，预计每只 5-15 分钟。完成后会把开盘前简报推送到配置的飞书群。"
    )


def _sender_id(sender) -> str:
    """安全取发送者 open_id。"""
    sid = getattr(sender, "sender_id", None)
    return str(getattr(sid, "open_id", "") or "")


def _make_message_handler(cfg: Config, store: Store, lark_client: lark.Client):
    """返回长连接 on_message 回调（闭包持有 cfg/store/client）。"""
    allowed = _allowed_chat_ids(cfg)

    def on_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        event = getattr(data, "event", None)
        if event is None:
            return
        sender = getattr(event, "sender", None)
        msg = getattr(event, "message", None)
        if not sender or not msg:
            return

        # 只响应用户消息
        if getattr(sender, "sender_type", "") != "user":
            return

        chat_id = getattr(msg, "chat_id", "")
        if allowed and chat_id not in allowed:
            return

        if getattr(msg, "message_type", "") != "text":
            return

        message_id = getattr(msg, "message_id", "")
        if not message_id:
            return

        # 幂等去重：先写入再处理，避免重投递时重复跑分析
        if store.is_message_processed(message_id):
            return
        content_json = getattr(msg, "content", "{}") or "{}"
        raw_text = ""
        try:
            raw_text = json.loads(content_json).get("text", "")
        except (json.JSONDecodeError, TypeError):
            pass
        store.mark_message_processed(
            message_id,
            chat_id=chat_id,
            sender_id=_sender_id(sender),
            content=raw_text,
        )

        codes = parse_message_text(raw_text)
        if not codes:
            _send_card(lark_client, chat_id, "使用说明", _help_md(), template="grey")
            return

        _send_card(
            lark_client, chat_id, f"已收到 {len(codes)} 只代码",
            _confirm_md(codes), template="green",
        )

        today = date.today().isoformat()
        for symbol in codes:
            try:
                run_pipeline(
                    cfg,
                    store,
                    symbol,
                    depth="标准",
                    pipeline=["digest", "notify"],
                    analysis_date=today,
                )
            except Exception as exc:  # 单只失败不影响下一只
                print(f"[bot] 分析 {symbol} 失败: {exc}")

    return on_message


def serve(cfg: Config) -> None:
    """启动飞书长连接机器人（阻塞主线程）。"""
    app_id, app_secret = _feishu_app_credentials(cfg)
    if not app_id or not app_secret:
        raise ValueError(
            "飞书机器人缺少 app_id/app_secret；"
            "请在 studio.yaml notify.channels.feishu 配置或设置 "
            "FEISHU_APP_ID / FEISHU_APP_SECRET 环境变量"
        )

    store = Store(cfg.store_path())
    lark_client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_make_message_handler(cfg, store, lark_client))
        .build()
    )

    ws = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )
    try:
        print(f"[bot] 飞书长连接启动（app_id={app_id[:6]}...）")
        ws.start()
    except KeyboardInterrupt:
        pass
    finally:
        store.close()
