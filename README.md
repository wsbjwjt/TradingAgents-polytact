# TradingAgents-polytact

飞书驱动的 A 股晨报系统：早上在飞书里发一行逗号分隔的股票代码，系统逐票完成多智能体投研分析（7 分析师 + 多空辩论 + 交易员 + 风控 + 裁决），把浓缩成约 200 字的开盘前简报推回飞书，卡片按钮直达完整报告与多空辩论回放。

- 引擎：[TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock)（git subtree vendor 进本仓库，FastAPI 包装为独立 HTTP 服务）
- 外壳（本仓库 `studio/`）：晨报提炼、飞书推送与入站机器人、多模型对比、辩论回放、定时调度、报告服务
- 部署：云服务器 Docker Compose（两个容器），或本机无 Docker 裸跑

## 目录

- [1. 背景](#1-背景)
- [2. 功能](#2-功能)
  - [2.1 bot 飞书入站：发代码就开工](#21-bot-飞书入站发代码就开工)
  - [2.2 digest 开盘前简报](#22-digest-开盘前简报)
  - [2.3 报告三页：完整报告 / 多空辩论 / 推演回放](#23-报告三页完整报告--多空辩论--推演回放)
  - [2.4 cron 兜底提醒](#24-cron-兜底提醒)
  - [2.5 compare 多模型对比](#25-compare-多模型对比)
- [3. 架构](#3-架构)
- [4. 安装](#4-安装)
  - [4.1 本机运行（无 Docker）](#41-本机运行无-docker)
  - [4.2 服务器部署（Docker Compose）](#42-服务器部署docker-compose)
- [5. 使用](#5-使用)
- [6. 配置](#6-配置)
  - [6.1 飞书应用配置（一次性）](#61-飞书应用配置一次性)
  - [6.2 环境变量与 studio.yaml](#62-环境变量与-studioyaml)
- [7. 开发](#7-开发)
- [8. 项目地图](#8-项目地图)
- [9. 致谢](#9-致谢)

## 1. 背景

多智能体投研框架（市场/基本面/新闻/情绪/政策/游资/解禁七个分析师轮番上阵，多空辩论，交易员拍板，风控三方辩论，组合经理裁决）产出的报告极有深度，但日常用起来有四个痛点：

1. **启动太繁琐**：开盘前时间宝贵，还要开网页、登录、贴代码、点按钮
2. **等待无感知**：一只票十几分钟，不知道跑到哪了、还要等多久
3. **报告读不完**：十几份子报告上万字，开盘前只有几分钟
4. **辩论没法看**：多空交锋是最有价值的部分，却埋在终端日志里

polytact 的解法：**入口搬到飞书**（发一行代码列表就走），**等待全程可见**（排队 ETA + 进度卡原地刷新），**结论先行**（200 字简报卡片），**过程可回放**（辩论对垒页 + 完整时间线）。

## 2. 功能

| 模块 | 解决的问题 | 一句话效果 |
|---|---|---|
| **bot** | 启动繁琐 | 飞书发 `600519,300311，比亚迪` 即触发逐票分析，代码/中文名都认 |
| **排队与进度** | 等待无感知 | 确认卡给出每只预计完成时刻；每只一张进度卡随分析阶段原地刷新 |
| **digest** | 报告读不完 | 上万字报告提炼成约 200 字开盘前简报（结论/信号/风险/动作四段式） |
| **报告三页** | 细节与过程没法看 | 完整报告（17 节中文导航）/ 多空辩论对垒 / 全时间线推演回放，链接带 HMAC 令牌 |
| **cron** | 忘了发 | 工作日 07:30 没收到代码列表就往飞书发提醒 |
| **compare** | 换模型太麻烦 | 一条命令让 N 个模型同题分析，产出耗时/token/决策对比表 |

### 2.1 bot 飞书入站：发代码就开工

自建应用长连接（WebSocket）接收消息，**不需要公网回调地址**：

- 逗号/空格分隔的混合输入：`600519, 300311，比亚迪`——6 位代码、`sh600519`、`600519.SH`、中文名都识别；识别不了的带原因列入回复
- 同一只股票（代码和中文名解析到同一只）自动去重
- **确认卡即排队视图**：

```
已受理 2 只，逐只分析、即完即推（每只约 16 分钟）：

1. 任子行（300311）— 预计 07:12 完成
2. 贵州茅台（600519）— 预计 07:28 完成
```

- **每只一张进度卡，原地刷新**（不是刷屏）：`▶️ [1/2] 任子行（300311）分析中 — 当前阶段：多空辩论（72%）`，完成转绿 `✅`、失败转红 `❌` 带原因
- 分析串行执行（数据接口限频与 LLM RPM 约束下的稳定选择），即发完即走，不用盯着

> ⚠️ 长连接全局只允许**单实例**（多实例消息随机投递）：本机起 bot 前，先停服务器端 studio。

### 2.2 digest 开盘前简报

从分析产物中取全文（自动处理转义残留与 dict 转储），用 OpenAI 兼容接口的大模型提炼成四段式简报，卡片标题带名称、代码与多空判断：

```
📊 任子行（300311）开盘前简报（看空）
```

### 2.3 报告三页：完整报告 / 多空辩论 / 推演回放

简报卡片按钮直达两个页面，辩论页内可再跳转完整时间线：

- **完整报告**：17 份子报告按叙事顺序排列（7 分析师 → 多空研究员 → 研究团队裁决 → 交易员 → 风控三方辩论 → 风控经理 → 组合经理），左侧导航右侧内容，手机抽屉式目录；各节标题统一归一为「中文名（代码）×××报告」
- **多空辩论回放**：从引擎落盘的辩论原始状态（JSON）精确解析轮次发言——多头（红·右）空头（绿·左）一来一回，底部是研究经理裁决
- **推演回放**：完整分析时间线（各 agent 产出按阶段分组）

报告服务公网开放（默认 `8890`），但所有链接带 **HMAC 无状态令牌，fail-closed**：无令牌/错令牌一律 403。

### 2.4 cron 兜底提醒

调度器常驻，工作日 07:30 检查当天是否已有运行记录，没有则向飞书发提醒——晨报的触发权在人，系统只兜底提醒，不擅自烧 token。

### 2.5 compare 多模型对比

同一支股票、同一深度、同一批行情数据，N 个模型同题分析，产出耗时/token/决策硬指标对比表（终端表格 + markdown + CSV + SQLite 回溯）：

```bash
studio compare run 002594 -m kimi-k2.5,glm-5 -d 标准 --dry-run   # 先验证计划
studio compare run 002594 -m kimi-k2.5,glm-5 -d 标准             # 真实消耗，token 按 key 计费
```

模型也可用引擎 `.env` 的 `ENGINE_QUICK_MODEL` / `ENGINE_DEEP_MODEL` 设默认（quick 干分析师取数等 80% 的活，deep 定辩论与裁决质量；实测 kimi-k2.5+glm-5 比 qwen3.5-plus+qwen3.7-plus 快约 40%，结论一致）。

## 3. 架构

两个进程（或两个容器），共享一份数据卷：

```
飞书用户 ──长连接──▶ studio(bot) ──HTTP──▶ engine(FastAPI + vendored astock)
                        │                        │
                        │  ◀── 共享数据卷 analysis_results/<代码>/<日期>/reports/ ──┘
                        │
                        ├──▶ digest 提炼（OpenAI 兼容 LLM）
                        ├──▶ 飞书推送（确认卡/进度卡/简报卡）
                        └──▶ 报告服务 :8890（HMAC 令牌）
```

- engine 只暴露 compose 内网 + 宿主机 `127.0.0.1:8000`（运维调试）；对外公网只有报告服务
- 引擎任务落盘持久化：服务重启不丢任务状态，报告页对历史任务仍可打开
- studio 产物（SQLite/导出页/配置）与引擎产物（分析报告）分离

## 4. 安装

### 4.1 本机运行（无 Docker）

Windows / macOS / Linux 均可，Python ≥ 3.10：

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows git-bash；其他平台相应调整
pip install -e ./vendor/astock -e ./engine -e ./studio
cp .env.example .env                    # 填百炼 key、飞书凭据；密钥项留空自动生成本机临时随机串
cp studio/studio.yaml.example studio.yaml   # 缺省时 run_local.py 也会自动生成
```

启动全部进程（engine :8000 + 报告服务 :8890 + 飞书 bot + cron 调度）：

```bash
python scripts/run_local.py            # 真实模式
python scripts/run_local.py --mock     # 引擎 3 秒假跑，管道联调用
python scripts/run_local.py --no-bot   # 不起飞书 bot
```

Ctrl+C 停止全部进程（Windows 下树杀清理，不留孤儿进程）。数据落 `./data/`（已 gitignore）。

### 4.2 服务器部署（Docker Compose）

```bash
git archive HEAD | ssh <server> "tar -x -C /opt/polytact-morning"
# 服务器上准备 .env（参考 .env.example）与 studio.yaml（参考 studio.yaml.example）
cd /opt/polytact-morning && docker compose up -d --build
```

要点：

- compose 项目名 `polytact-morning`，两个容器：`polytact-engine` + `polytact-studio`
- 国内构建已内置阿里云 apt/pypi 镜像；服务器访问 GitHub 受限时用上面的 `git archive | ssh tar` 直传
- **engine 有任务在跑时不要 `compose up`**（重建会杀任务）；升级前先确认任务队列空闲
- 报告服务端口需安全组放行（默认 8890）

## 5. 使用

主流程就是**在飞书给机器人发代码列表**，其余都是锦上添花：

```bash
studio doctor                    # 自检：API/登录/数据卷/LLM/渠道
studio digest run --symbol 002594   # 提炼该股最近一次分析
studio notify test               # 向飞书发测试消息
studio compare run <代码> -m a,b    # 多模型同题对比
studio replay debate <task-id>   # 导出辩论回放页
studio replay export <task-id>   # 导出完整时间线回放
studio report serve --port 8890  # 报告服务（卡片按钮落点；容器里常驻的就是它）
studio bot run                   # 飞书入站机器人（容器里常驻）
studio cron                      # 常驻调度（07:30 兜底提醒）
```

## 6. 配置

### 6.1 飞书应用配置（一次性）

系统与飞书的全部交互（收消息、发卡片）都走一个**企业自建应用**，不需要公网回调地址。按以下顺序配置（本项目实测验证过的步骤）：

**① 创建应用**：[飞书开放平台](https://open.feishu.cn/) → 开发者后台 → 创建**企业自建应用** → 在「凭证与基础信息」页拿到 **App ID** 和 **App Secret**。

**② 启用机器人能力**：应用能力 → 添加「机器人」。

**③ 授权三个权限**（权限管理 → 搜索开通）：

| Scope | 用途 |
|---|---|
| `im:message.p2p_msg:readonly` | 接收与机器人的单聊消息 |
| `im:message.group_at_msg:readonly` | 接收群聊中 @机器人 的消息 |
| `im:message:send_as_bot` | 以机器人身份发消息（确认卡/进度卡/简报卡） |

**④ 事件订阅**：事件订阅 → 订阅方式选「**使用长连接接收事件**」→ 添加事件 **`im.message.receive_v1`**（接收消息）。

**⑤ 发布版本**：版本管理与发布 → 创建版本并发布。⚠️ **任何权限/事件改动必须发版后才生效**——这是实测最常踩的坑。

**⑥ 填凭据**：App ID / Secret 写入 `.env`（或 `studio.yaml` 的 `notify.channels.feishu`）。**chat_id 不用手工配**——发布后在飞书里给机器人发任意一条消息，bot 会自动学习并把会话设为晨报推送目标。

补充说明：

- 群聊中需要 **@机器人** 才会收到消息（`group_at_msg` 的含义）；与机器人单聊则直接发即可
- 长连接最多 50 条且**多实例随机投递**——生产环境只跑一个 bot 实例（本机调试前先停服务器端）
- 简报卡片的按钮链接指向报告服务（`notify.report_url_prefix`，公网 IP/域名 + 端口 8890，需安全组放行）；链接本身带 HMAC 令牌，无令牌访问一律 403

### 6.2 环境变量与 studio.yaml

`.env`（引擎与密钥，**绝不入库**）：

| 项 | 作用 |
|---|---|
| 百炼 `DASHSCOPE_API_KEY` | 分析引擎的大模型 key（Coding Plan） |
| `ENGINE_QUICK_MODEL` / `ENGINE_DEEP_MODEL` | 默认 quick/deep 模型（当前实测推荐 `kimi-k2.5` / `glm-5`） |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书自建应用凭据（长连接 + 推送） |
| `ENGINE_USERNAME` / `ENGINE_PASSWORD` / `JWT_SECRET` | engine API 鉴权 |
| `REPORT_TOKEN_SECRET` | 报告链接 HMAC 签名密钥 |

`studio.yaml`（外壳行为）：

| 段 | 作用 |
|---|---|
| `api` | engine 地址与登录账号 |
| `llm` | digest 提炼用的大模型（OpenAI 兼容） |
| `data.ta_dir` | 引擎 `data/` 目录路径（报告/辩论数据源） |
| `notify.channels.feishu` | app 模式（app_id/app_secret）；chat_id 由 bot 自动学习 |
| `notify.report_url_prefix` | 卡片按钮指向的报告服务地址（服务器填公网 IP/域名） |
| `bot.est_minutes_per_stock` | 确认卡排队 ETA 的单票预估分钟数（默认 16） |
| `cron.jobs` | 定时任务；内置 07:30 兜底提醒 |

## 7. 开发

```bash
pip install -e ./vendor/astock -e ./engine -e ./studio
python -m pytest engine/tests/ studio/tests/    # 66 项：mock 模式 API + 外壳集成，不依赖真实数据源
```

目录结构：`engine/`（FastAPI 包装：任务管理/分析执行/报告落盘）、`studio/src/studio/`（`bot` 飞书入站、`digest` 提炼、`notify` 推送与报告服务、`replay` 回放、`core` 配置/客户端/存储）、`vendor/astock`（引擎本体，git subtree 管理）、`scripts/run_local.py`（本机四进程编排）、`docker/`（镜像与入口）。

vendor 更新：`git subtree pull --prefix=vendor/astock <上游> main --squash`；本地对 vendor 的补丁（如风控辩手中文提示词）在 pull 时需留意冲突。

## 8. 项目地图

设计与决策路线图见 Wayfinder 地图 issue：https://github.com/wsbjwjt/TradingAgents-polytact/issues/1

## 9. 致谢

- [TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock)（A 股分析引擎）
- [TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) 及其上游 [TradingAgents](https://github.com/TauricResearch/TradingAgents)
