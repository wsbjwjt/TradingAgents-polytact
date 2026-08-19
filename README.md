# TradingAgents-polytact

飞书驱动的 A 股晨报系统：每天早上在飞书发送逗号分隔的股票代码列表，系统逐票完成多智能体投研分析，并将浓缩晨报简报推回飞书。

- 引擎：[TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock)（git subtree vendor，FastAPI 包装为独立服务）
- 外壳：移植自 [TradingAgents-CN-studio](https://github.com/frank-quant/TradingAgents-CN-studio)（digest / notify / compare / replay / cron / 报告服务，通知渠道仅保留飞书 + 新增飞书长连接入站）
- 部署：云服务器 Docker Compose，或本机无 Docker 裸跑

## 项目地图

设计与决策路线图见 Wayfinder 地图 issue：https://github.com/wsbjwjt/TradingAgents-polytact/issues/1

## 本机运行（无 Docker，Windows/macOS/Linux）

一次性准备：

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows git-bash；其他平台相应调整
pip install -e ./vendor/astock -e ./engine -e ./studio
cp .env.example .env       # 填百炼 key、飞书凭据；密钥项留空会自动生成本机临时随机串
cp studio/studio.yaml.example studio.yaml   # 缺省时 run_local.py 也会自动生成
```

启动全部进程（engine :8000 + 报告服务 :8890 + 飞书 bot + cron 调度）：

```bash
python scripts/run_local.py            # 真实模式
python scripts/run_local.py --mock     # 引擎 3 秒假跑，管道联调用
python scripts/run_local.py --no-bot   # 不起飞书 bot
```

Ctrl+C 停止全部进程。数据落 `./data/`（已 gitignore）。

> ⚠️ 飞书长连接全局只允许单实例（多实例随机投递）：本机起 bot 前，先停服务器端
> `ssh polytact "cd /opt/polytact-morning && docker compose stop studio"`。

## 服务器部署（Docker Compose）

```bash
git archive HEAD | ssh <server> "tar -x -C /opt/polytact-morning"
# 服务器上准备 .env（参考 .env.example）与 studio.yaml（参考 studio.yaml.example）
cd /opt/polytact-morning && docker compose up -d --build
```

engine 只暴露 compose 内网 + 宿主机 `127.0.0.1:8000`（运维调试）；报告服务 `8890` 公网开放但所有链接带 HMAC 令牌（fail-closed）。

## 测试

```bash
cd engine && python -m pytest tests/          # mock 模式 API 测试
cd studio && python -m pytest tests/          # 外壳与集成层测试
```
