# TradingAgents-polytact Studio

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](pyproject.toml)

TradingAgents-polytact 的增强套件，**对接 polytact engine（astock 引擎的兼容 API）**，为 A 股晨报场景补齐「读得完、推得出、比得了、看得见、收得到」五种能力。

## 1. 背景

polytact engine 实现了 hsliuping 版 TradingAgents-CN 的 API 形状，并把分析报告落盘到 `analysis_results/{symbol}/{date}/reports/*.md` + `analysis_metadata.json`。Studio 不修改 engine 任何文件，只通过 HTTP API 和只读数据卷集成，把 engine 的分析结果变成：

1. **读得完**：十几万字深度报告 → 200 字开盘前简报
2. **推得出**：简报自动推送到飞书卡片
3. **比得了**：同一股票让 N 个模型同题对比
4. **看得见**：多空辩论过程渲染成可分享的 HTML 回放
5. **收得到**：飞书机器人接收代码列表，自动触发分析管道

## 2. 功能

| 模块 | 解决的问题 | 一句话效果 |
|---|---|---|
| **digest** | 报告读不完 | 深度报告提炼成约 200 字开盘前简报（结论/信号/风险/动作四段式） |
| **notify** | 跑完不吭声 | 飞书卡片主动推送（股票名称 + 简报 + 详情按钮），cron 定时全管道自动化 |
| **compare** | 换模型太麻烦 | 一条命令让 N 个模型同题分析，产出耗时/token/成本/决策硬指标对比表 |
| **replay** | 辩论没法看 | 智能体辩论渲染成回放页：聊天流 + 多空对垒 |
| **bot** | 每天要手动找代码 | 飞书机器人收到代码列表后，串行触发分析 → digest → 推送 |
| **reminder** | 早上忘了发代码 | 07:30 检查今天是否已有运行，没有则飞书提醒 |

## 3. 架构

```
┌─────────────────┐   HTTP API（auth/analysis/status/result/SSE/usage）
│   polytact      │◀── analysis_results/{symbol}/{date}/reports/*.md
│    engine       │
└────────┬────────┘
         │
┌────────▼────────┐
│      studio     │──▶ 飞书卡片 / HTML 回放 / SQLite / CSV / markdown
│  (this package) │
└─────────────────┘
```

- 不修改 engine 代码，不写入 engine 数据目录。
- 推送渠道只保留飞书（群机器人 webhook + 企业自建应用长连接）。

## 4. 安装

```bash
cd studio
pip install -e ".[dev]"
cp studio.yaml.example studio.yaml   # 填 engine 账号 / llm key / 飞书凭证
studio doctor                        # 自检：API/数据卷/LLM/飞书
```

要求：Python ≥ 3.10，能访问到 polytact engine（默认 `http://localhost:8000`）。

`studio.yaml` 关键配置：

| 段 | 作用 |
|---|---|
| `api` | engine 地址与登录账号（密码可用 `${ENV}` 引用） |
| `llm` | digest/对垒配对用的大模型（OpenAI 兼容） |
| `data.ta_dir` | engine 报告落盘根目录，需包含 `analysis_results/` |
| `notify.channels.feishu` | 群机器人 webhook + 自建应用 app_id/app_secret |
| `notify.channels.feishu.allowed_chat_ids` | bot 响应白名单，空=不限制 |
| `notify.report_url_prefix` | 卡片按钮指向的报告服务地址 |
| `cron.jobs` | 定时任务；`type: reminder` 为兜底提醒 |

## 5. 使用

```bash
studio doctor                                  # 自检
studio bot run                                 # 启动飞书入站机器人（常驻）
studio digest run --symbol 002594              # 提炼该股最近一次分析
studio notify test                             # 向飞书发测试消息
studio notify send <task-id>                   # 推送简报卡片
studio compare run 002594 -m a,b,c --dry-run   # 对比（先 dry-run 验证计划）
studio replay debate <task-id>                 # 导出辩论回放
studio replay export <task-id>                 # 导出完整时间线回放
studio report serve --port 8890                # 报告详情服务（卡片按钮落点）
studio cron                                    # 常驻调度（容器里跑的就是它）
```

### 5.1 飞书机器人用法

在群里 @机器人或私聊发送：

```
600519, 000001，贵州茅台
```

机器人会：

1. 立即回复确认卡片；
2. 按 6 位代码 / 中文名解析，串行调用 `分析 → digest → 推送`；
3. 用 `message_id` 去重，同一条消息不会重复分析。

### 5.2 07:30 兜底提醒

在 `studio.yaml` 里打开注释：

```yaml
cron:
  timezone: Asia/Shanghai
  jobs:
    - name: 07:30 兜底提醒
      type: reminder
      schedule: 30 7 * * 1-5
```

到点若当天还没有运行记录，会向配置的飞书渠道发送提醒。

## 6. 开发

```bash
pip install -e ".[dev]"
pytest tests/                    # 冒烟测试：配置/存储/SSE/签名/裁剪/bot 解析
```

目录结构：`src/studio/core`（配置 / API 客户端 / SQLite / 事件模型 / 文本清洗），`digest`、`notify`、`compare`、`replay`、`bot` 业务模块与之平级。

## 7. License

MIT
