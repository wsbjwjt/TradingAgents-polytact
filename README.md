# TradingAgents-polytact

飞书驱动的 A 股晨报系统：每天早上在飞书发送逗号分隔的股票代码列表，系统逐票完成多智能体投研分析，并将浓缩晨报简报推回飞书。

- 引擎：[TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock)（git subtree vendor，FastAPI 包装为独立服务）
- 外壳：移植自 [TradingAgents-CN-studio](https://github.com/frank-quant/TradingAgents-CN-studio)（digest / notify / compare / replay / cron / 报告服务，通知渠道仅保留飞书 + 新增飞书长连接入站）
- 部署：云服务器 Docker Compose

## 项目地图

设计与决策路线图见 Wayfinder 地图 issue：https://github.com/wsbjwjt/TradingAgents-polytact/issues/1

> 仓库骨架搭建中（见 issue #7）。
