#!/bin/sh
set -e

# TradingAgents-polytact Studio 容器入口：
#   默认/`cron`   -> 报告服务(后台) + 飞书入站 bot(后台，自动重启) + 常驻调度器(前台)
#   其他命令      -> 透传给 studio（如 docker compose run studio studio doctor）
if [ "$#" -eq 0 ] || { [ "$#" -eq 1 ] && [ "$1" = "cron" ]; }; then
    studio report serve --port "${STUDIO_REPORT_PORT:-8890}" &
    # 飞书长连接必须单实例（多实例随机投递）；崩了自动重启
    (while true; do studio bot run || true; sleep 5; done) &
    exec studio cron
fi

exec studio "$@"
