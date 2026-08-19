"""报告链接令牌：无状态 HMAC 签名，免存储。

报告服务端口（默认 8890）对公网开放，链接安全全靠"不可枚举的 token"。
token = HMAC_SHA256(secret, scope)[:24]，scope 为 task_id（索引页用固定 scope）。
密钥取 REPORT_TOKEN_SECRET，缺省回落 JWT_SECRET；两者都没有时 sign() 抛错——
report server 启动即失败（fail closed），scheduler 则不带按钮链接。
"""
from __future__ import annotations

import hashlib
import hmac
import os

INDEX_SCOPE = "__index__"


def _secret() -> str:
    return os.environ.get("REPORT_TOKEN_SECRET") or os.environ.get("JWT_SECRET") or ""


def sign(scope: str) -> str:
    secret = _secret()
    if not secret:
        raise RuntimeError(
            "缺少 REPORT_TOKEN_SECRET（或 JWT_SECRET）环境变量，无法生成报告链接令牌"
        )
    return hmac.new(secret.encode(), scope.encode(), hashlib.sha256).hexdigest()[:24]


def verify(scope: str, token: str) -> bool:
    try:
        return hmac.compare_digest(sign(scope), token or "")
    except RuntimeError:
        return False
