"""飞书渠道：优先自建应用 API（与入站机器人同一身份），无应用凭据时回落群自定义机器人 webhook。

- app 模式：tenant_access_token 自动缓存刷新；chat_id 取 配置 > 环境变量 > 运行时学习
  （`studio bot` 收到任何用户消息时会把 chat_id 写进 store kv，见 bot/listener.py）。
- webhook 模式：CN-studio 原生行为，保留作为备用出站。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

import httpx

from .base import Channel, registry

_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_SEND_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"


def _sign(secret: str, timestamp: int) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


@registry.register
class FeishuChannel(Channel):
    name = "feishu"

    def __init__(self, options: dict):
        self.webhook: str = options.get("webhook", "") or ""
        self.secret: str = options.get("secret", "") or ""
        self.app_id: str = options.get("app_id", "") or os.environ.get("FEISHU_APP_ID", "")
        self.app_secret: str = (
            options.get("app_secret", "") or os.environ.get("FEISHU_APP_SECRET", "")
        )
        # chat_id 由 build_channels 注入（配置/环境变量/store 学习值），这里只做兜底
        self.chat_id: str = options.get("chat_id", "") or os.environ.get("FEISHU_CHAT_ID", "")
        self._token_cache: dict = {"token": "", "exp": 0.0}
        if not self.webhook and not (self.app_id and self.app_secret):
            raise ValueError("feishu 渠道缺少配置：webhook 或 app_id/app_secret 至少配一组")

    def send(self, title: str, body: str, markdown: str = "",
             buttons: list[tuple[str, str]] | None = None) -> None:
        card = {
            "header": {
                "title": {"tag": "plain_text", "content": title[:60]},
                "template": "blue",
            },
            "elements": self._elements(title, body, markdown, buttons),
        }
        if self.app_id and self.app_secret and self.chat_id:
            return self._send_via_app(card)
        if self.webhook:
            return self._send_via_webhook(card)
        raise RuntimeError(
            "feishu app 模式缺少 chat_id（配置 notify.channels.feishu.chat_id / "
            "FEISHU_CHAT_ID，或先给机器人发一条消息让它自动学习）"
        )

    @staticmethod
    def _elements(title: str, body: str, markdown: str,
                  buttons: list[tuple[str, str]] | None) -> list[dict]:
        elements: list[dict] = [
            {
                "tag": "markdown",
                # 飞书卡片单 markdown 元素保守上限（R2 研究：~3000-4000 字符）
                "content": (markdown or body)[:2800],
            }
        ]
        if buttons:
            elements.append({
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": label[:20]},
                        "type": "primary" if i == 0 else "default",
                        "url": url,
                    }
                    for i, (label, url) in enumerate(buttons[:3])
                ],
            })
        return elements

    def _tenant_token(self) -> str:
        if self._token_cache["token"] and time.time() < self._token_cache["exp"] - 60:
            return self._token_cache["token"]
        r = httpx.post(_TOKEN_URL,
                       json={"app_id": self.app_id, "app_secret": self.app_secret},
                       timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取飞书 tenant_access_token 失败: {data}")
        self._token_cache.update(
            token=data["tenant_access_token"],
            exp=time.time() + int(data.get("expire", 7200)),
        )
        return self._token_cache["token"]

    def _send_via_app(self, card: dict) -> None:
        r = httpx.post(
            _SEND_URL,
            headers={"Authorization": f"Bearer {self._tenant_token()}"},
            json={
                "receive_id": self.chat_id,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False),
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"飞书 app 发送失败: {data}")

    def _send_via_webhook(self, card: dict) -> None:
        payload: dict = {"msg_type": "interactive", "card": card}
        if self.secret:
            ts = int(time.time())
            payload["timestamp"] = str(ts)
            payload["sign"] = _sign(self.secret, ts)

        r = httpx.post(self.webhook, json=payload, timeout=15)
        r.raise_for_status()
        result = r.json()
        # 飞书永远返回 200，错误藏在 code 字段里
        if result.get("code") not in (0, None) or result.get("StatusCode") not in (0, None):
            raise RuntimeError(f"飞书返回错误: {result}")
