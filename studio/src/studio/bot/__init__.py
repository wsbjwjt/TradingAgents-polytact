"""飞书入站机器人：长连接接收 im.message.receive_v1 并触发分析管道。"""
from __future__ import annotations

from .listener import parse_message_text, serve

__all__ = ["parse_message_text", "serve"]
