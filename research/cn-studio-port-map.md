# CN-studio → TradingAgents-astock 移植对照表

> 研究范围：`D:\aicodes\TradingAgents-CN-studio` 全部文件。  
> 目标引擎：`D:\aicodes\TradingAgents-astock`（本地 Python 库，无 HTTP API；核心入口 `tradingagents/graph/trading_graph.py` 的 `TradingAgentsGraph.propagate(company_name, trade_date) -> (final_state, signal)`）。  
> astock 落盘结构依据：`tradingagents/default_config.py:7`、`tradingagents/graph/trading_graph.py:728-734`、`cli/main.py:1019-1059` / `685-771`。

---

## 1. astock 实际落盘结构（fetcher / capture 改写依据）

### 1.1 JSON 全状态（`TradingAgentsGraph._log_state`）

- **路径**：`{results_dir}/{ticker}/TradingAgentsStrategy_logs/full_states_log_{trade_date}.json`
- **默认 `results_dir`**：`~/.tradingagents/logs`（`tradingagents/default_config.py:7`）
- **关键字段**（`tradingagents/graph/trading_graph.py:691-724`）：
  - `market_report`
  - `sentiment_report`
  - `news_report`
  - `fundamentals_report`
  - `policy_report`（可选）
  - `hot_money_report`（可选）
  - `lockup_report`（可选）
  - `investment_debate_state.{bull_history, bear_history, history, current_response, judge_decision}`
  - `trader_investment_decision`（即 `trader_investment_plan`）
  - `risk_debate_state.{aggressive_history, conservative_history, neutral_history, history, judge_decision}`
  - `investment_plan`
  - `final_trade_decision`
- **文件名**：`full_states_log_{trade_date}.json`，`trade_date` 为 `YYYY-MM-DD`。

### 1.2 CLI 报告目录（`save_report_to_disk`，用户确认保存后生成）

- **默认根目录**：`./reports/{ticker}_{YYYYMMDD_HHMMSS}/`（`cli/main.py:1230`）
- **子目录与文件清单**（`cli/main.py:685-771`）：

| 子目录 | 文件名 | 对应 final_state 字段 |
|---|---|---|
| `1_analysts/` | `market.md` | `market_report` |
| `1_analysts/` | `sentiment.md` | `sentiment_report` |
| `1_analysts/` | `news.md` | `news_report` |
| `1_analysts/` | `fundamentals.md` | `fundamentals_report` |
| `2_research/` | `bull.md` | `investment_debate_state.bull_history` |
| `2_research/` | `bear.md` | `investment_debate_state.bear_history` |
| `2_research/` | `manager.md` | `investment_debate_state.judge_decision` |
| `3_trading/` | `trader.md` | `trader_investment_plan` |
| `4_risk/` | `aggressive.md` | `risk_debate_state.aggressive_history` |
| `4_risk/` | `conservative.md` | `risk_debate_state.conservative_history` |
| `4_risk/` | `neutral.md` | `risk_debate_state.neutral_history` |
| `5_portfolio/` | `decision.md` | `risk_debate_state.judge_decision` |
| 根 | `complete_report.md` | 拼接后的完整报告 |

### 1.3 运行时中间产物（`run_analysis` 自动写入 `results_dir`）

- **日志**：`{results_dir}/{ticker}/{analysis_date}/message_tool.log`（`cli/main.py:1023`）
- **分报告 md**（`cli/main.py:1021`、`1056-1059`）：
  - `{results_dir}/{ticker}/{analysis_date}/reports/market_report.md`
  - `{results_dir}/{ticker}/{analysis_date}/reports/sentiment_report.md`
  - `{results_dir}/{ticker}/{analysis_date}/reports/news_report.md`
  - `{results_dir}/{ticker}/{analysis_date}/reports/fundamentals_report.md`
  - `{results_dir}/{ticker}/{analysis_date}/reports/investment_plan.md`
  - `{results_dir}/{ticker}/{analysis_date}/reports/trader_investment_plan.md`
  - `{results_dir}/{ticker}/{analysis_date}/reports/final_trade_decision.md`
- **映射关系**：`cli/main.py:64-71` 的 `REPORT_SECTIONS` 定义了 section_name → 实际落盘文件名。

---

## 2. 三分类对照表

| 文件 | 分类 | 说明 |
|---|---|---|
| `README.md` | 改写 | 全文面向 TradingAgents-CN HTTP/API 架构，需改为 astock 本地库 + 新落盘结构。 |
| `pyproject.toml` | 改写 | 依赖需增加 astock；脚本入口不变；仍保留 `typer`/`httpx`/`rich`/`croniter`/`markdown`/`pyyaml`。 |
| `studio.yaml.example` | 改写 | `api` 段失效；`data.ta_dir` 需指向 astock `results_dir` 或 CLI `reports`；`notify.channels` 仅保留 `feishu`。 |
| `.gitignore` | 原样拿走 | 无引擎耦合。 |
| `.gitattributes` | 原样拿走 | 无引擎耦合。 |
| `LICENSE` | 原样拿走 | 许可证不变。 |
| `src/studio/__init__.py` | 改写 | docstring 仍写 TradingAgents-CN，需更新为 astock。 |
| `src/studio/cli.py` | 改写 | 所有调用 `TradingAgentsClient` 的命令（doctor/digest/notify/compare/replay/report/cron）均需切到 `TradingAgentsGraph`。 |
| `src/studio/core/client.py` | 改写/替换 | 全部方法硬编码 TradingAgents-CN HTTP 端点；应删除或重命名为 astock 引擎封装。 |
| `src/studio/core/config.py` | 改写 | `DEFAULTS` 中 `api`、`data.ta_dir` 等默认值需替换为 astock 配置；`load_default` 查找路径可保留。 |
| `src/studio/core/events.py` | 原样拿走 | `Timeline`/`TimelineEvent` 抽象与引擎无关。 |
| `src/studio/core/store.py` | 改写 | `runs` 表以 `task_id` 为主键；astock 无 task_id，需引入 `(ticker, date, run_ts)` 或合成 key。 |
| `src/studio/core/textutil.py` | 原样拿走 | 文本清洗逻辑与引擎无关。 |
| `src/studio/digest/__init__.py` | 改写 | 导出 `fetch_report`/`latest_task_dir` 的签名将因落盘结构改变而改变。 |
| `src/studio/digest/condenser.py` | 原样拿走 | 仅依赖 `cfg.llm.*` 与 OpenAI 兼容接口，与引擎无关。 |
| `src/studio/digest/fetcher.py` | 改写 | 硬编码 `analysis_results/<symbol>/<date>/reports/*.md` 与 `REPORT_PRIORITY` 映射；需适配 astock 双落盘结构。 |
| `src/studio/digest/templates.py` | 原样拿走 | 提示词与引擎无关。 |
| `src/studio/notify/__init__.py` | 原样拿走 | 空文件。 |
| `src/studio/notify/channels/__init__.py` | 改写 | 需删除 `webhook`/`dingtalk`/`wecom`/`telegram` 的注册导入，仅保留 `feishu`。 |
| `src/studio/notify/channels/base.py` | 原样拿走 | 渠道抽象与引擎无关。 |
| `src/studio/notify/channels/feishu.py` | 原样拿走 | 仅保留飞书渠道。 |
| `src/studio/notify/channels/dingtalk.py` | 删除 | 按需求只留飞书。 |
| `src/studio/notify/channels/wecom.py` | 删除 | 按需求只留飞书。 |
| `src/studio/notify/channels/telegram.py` | 删除 | 按需求只留飞书。 |
| `src/studio/notify/channels/webhook.py` | 删除 | 按需求只留飞书。 |
| `src/studio/notify/render.py` | 原样拿走 | 消息渲染与引擎无关。 |
| `src/studio/notify/scheduler.py` | 改写 | `run_pipeline` 通过 HTTP 提交分析、轮询、取报告；需改为 `TradingAgentsGraph.propagate` 或读取已落盘结果。 |
| `src/studio/notify/report_server.py` | 改写 | 依赖 `fetch_report`、`replay_capture`、`client.stock_name`，均需切到 astock 状态/路径。 |
| `src/studio/compare/__init__.py` | 原样拿走 | 空文件。 |
| `src/studio/compare/runner.py` | 改写 | `run_one` 用 `TradingAgentsClient.submit_analysis` + `wait_for_task`；需改为按模型构造 `TradingAgentsGraph` 并调用 `propagate`。 |
| `src/studio/compare/metrics.py` | 改写 | `collect_tokens` 调用原项目 `/api/usage-statistics/records`；astock 无此接口，需从回调/统计对象取 token 或留空。 |
| `src/studio/compare/report.py` | 原样拿走 | 表格/CSV/markdown 输出与引擎无关。 |
| `src/studio/replay/__init__.py` | 原样拿走 | 导出不变。 |
| `src/studio/replay/capture.py` | 改写 | 硬编码 `analysis_results` 目录、`REPORT_AGENTS` 文件名、`analysis_metadata.json`、`message_tool.log`；需映射到 astock 落盘结构。 |
| `src/studio/replay/render.py` | 原样拿走 | HTML 渲染与引擎无关。 |
| `src/studio/replay/debate.py` | 改写 | `build_debate_data` 依赖 `client.get_status` 与原 `find_reports_dir`；astock 可直接从 `final_state` 或 CLI `2_research`/`4_risk` 目录读取。 |
| `src/studio/replay/debate_render.py` | 原样拿走 | HTML 渲染与引擎无关。 |
| `docker/Dockerfile` | 改写 | 当前基于 `python:3.10-slim` 只安装 studio；需同时安装 astock 及其依赖。 |
| `docker/docker-compose.studio.yml` | 改写 | 当前叠加到 TradingAgents-CN compose 网络并挂载其 `data` 卷；astock 版需独立运行，挂载 astock `results_dir` 与 studio 数据卷。 |
| `docker/entrypoint.sh` | 改写 | 启动 `studio report serve` + `studio cron`；astock 版需确保 astock 环境可用，命令不变但依赖已变。 |
| `tests/test_smoke.py` | 改写 | 包含 dingtalk/wecom/telegram/webhook 渠道测试；需删除这些用例并适配新 config。 |

---

## 3. 改写详情（含文件:行号证据）

### 3.1 引擎接入层

#### `src/studio/core/client.py`

- **现状**：整个文件是 TradingAgents-CN 的 HTTP 客户端，所有端点硬编码。
- **证据**：
  - 基地址与登录：`client.py:22`、`client.py:30-36`（`POST /api/auth/login`）
  - 健康检查：`client.py:62-65`（`GET /api/health`）
  - 提交分析：`client.py:90`（`POST /api/analysis/single`）
  - 任务状态/结果：`client.py:98`（`/api/analysis/tasks/{task_id}/status`）、`client.py:101`（`/api/analysis/tasks/{task_id}/result`）
  - SSE 实时流：`client.py:128`（`/api/stream/tasks/{task_id}`）
  - 股票名称：`client.py:160`（`/api/stock-data/basic-info/{symbol}`）
  - 用量统计：`client.py:182`（`/api/usage-statistics/records`）
- **改写方案**：
  - 删除该文件，或保留文件名但替换为 `AstockEngine` 封装。
  - 新接口：`TradingAgentsGraph.propagate(company_name, trade_date)`。
  - 状态获取优先读 `final_state`；如需持久化状态则读 JSON 全状态文件。
  - `task_id` 概念消失，后续模块以 `(ticker, trade_date, run_timestamp)` 标识一次运行。

#### `src/studio/cli.py`

- **证据**：
  - `_client` 工厂返回 HTTP 客户端：`cli.py:44-46`
  - `doctor` 检查 `/api/health` 与登录：`cli.py:61-73`
  - `digest_run` 通过 task_id 走 API：`cli.py:125-131`
  - `compare_run` 调用 `run_compare`（HTTP 提交）：`cli.py:254`
  - `replay_capture`/`replay_debate`/`replay_export`/`replay_serve` 均依赖 HTTP 客户端：`cli.py:287-361`
  - `report_serve` 依赖原报告服务：`cli.py:394-397`
  - `cron` 调用原调度器：`cli.py:404-405`
- **改写方案**：
  - `doctor`：改为检查 `data.ta_dir` 下是否存在 astock 落盘、`llm` 配置、`feishu` 配置。
  - `digest run`：`--symbol` 直接读取 astock `results_dir/{symbol}/TradingAgentsStrategy_logs/full_states_log_*.json` 或 `reports/{symbol}_{timestamp}/complete_report.md`。
  - `compare run`：为每个模型实例化独立 `TradingAgentsGraph`（通过 `config["deep_think_llm"]`/`config["quick_think_llm"]`）并并发调用 `propagate`。
  - `replay capture/export/debate/serve`：基于 `final_state` 或已落盘报告重建 `Timeline`。
  - `report serve`：从 astock 报告目录生成 HTML。
  - `cron`：触发 `propagate -> digest -> notify` 管道。

### 3.2 配置与依赖

#### `pyproject.toml`

- **当前依赖**：`typer>=0.12`、`httpx>=0.27`、`pyyaml>=6.0`、`rich>=13.7`、`croniter>=2.0`、`markdown>=3.5`。
- **改写点**：
  - 增加 `tradingagents-astock` 依赖（建议 `pip install -e D:/aicodes/TradingAgents-astock` 或写为 `file:` 依赖）。
  - `httpx` 仍需保留（digest LLM + 飞书 webhook）。
  - `croniter`、`markdown`、`rich`、`typer`、`pyyaml` 均保留。
  - `pytest` dev 依赖保留。

#### `src/studio/core/config.py`

- **证据**：
  - `api` 默认值指向 HTTP：`config.py:18-24`
  - `data.ta_dir` 默认空串：`config.py:32`
  - `replay.exports_dir`、`store_path` 路径基于仓库根：`config.py:129-136`
- **改写点**：
  - 删除 `api` 段默认值；新增 `astock` 段（如 `results_dir`、`project_dir`、`config_path`）。
  - `data.ta_dir` 默认改为 `~/.tradingagents/logs` 或保持由用户指定为 astock `results_dir`。
  - 环境变量覆盖前缀可保留 `STUDIO__*`。

### 3.3 报告读取层

#### `src/studio/digest/fetcher.py`

- **证据**：
  - 报告优先级硬编码：`fetcher.py:10-16`
  - 文件卷根目录假设：`fetcher.py:76`（`ta_dir / "analysis_results"`）
  - 子目录结构假设：`fetcher.py:84`（`day / "reports"`）、`fetcher.py:87`（`reports.glob("*.md")`）
  - 最新目录查找假设：`fetcher.py:104`（`ta_dir / "analysis_results"`）
  - API 结果兜底字段：`fetcher.py:55-71`
- **改写点**：
  - 新增读取 `full_states_log_{date}.json` 并拼接报告文本（字段见第 1 节）。
  - 新增读取 CLI 报告目录 `reports/{ticker}_{timestamp}/complete_report.md`。
  - 如读取运行时中间产物 `results_dir/{ticker}/{date}/reports/*.md`，需将 `market_report.md` 等映射到展示名。
  - 删除 `REPORT_PRIORITY` 或改为按 astock 字段顺序拼接。

#### `src/studio/replay/capture.py`

- **证据**：
  - 报告文件名硬编码映射：`capture.py:18-29`
  - 文件卷根目录假设：`capture.py:71`、`capture.py:98`、`capture.py:114`（`ta_dir / "analysis_results"`）
  - `analysis_metadata.json` 假设：`capture.py:132`
  - `message_tool.log` 路径假设：`capture.py:154`、`capture.py:158`
  - API 状态/结果/SSE 兜底：`capture.py:36-84`
- **改写点**：
  - 从 `final_state` 直接构建 `TimelineEvent`（`market_report` → 市场分析师，`sentiment_report` → 情绪分析师等）。
  - 从 JSON 全状态文件或 CLI 报告子目录读取辩论历史，生成 `kind=report`/`message` 事件。
  - `message_tool.log` 路径改为 `{results_dir}/{ticker}/{date}/message_tool.log`，解析逻辑可保留。
  - 删除 `--live` SSE 抓取逻辑或改为基于 `graph.stream` 实时回调（astock `debug=True` 时 stream 可用）。

### 3.4 调度、推送与服务层

#### `src/studio/notify/scheduler.py`

- **证据**：
  - 导入 HTTP 客户端：`scheduler.py:13`
  - `run_pipeline` 提交分析并轮询：`scheduler.py:68-113`（`client.submit_analysis`、`client.wait_for_task`、`client.stock_name`）
  - `fetch_report` 与 condense 联用：`scheduler.py:91-103`
- **改写点**：
  - `run_pipeline` 改为调用 `TradingAgentsGraph.propagate(symbol, date)`，从返回的 `final_state` 生成报告文本，再 condense。
  - 移除轮询、task_id、登录等概念。
  - `cron.jobs` 配置仍保留，但 `pipeline` 中 `digest/notify` 的执行入口改变。

#### `src/studio/notify/report_server.py`

- **证据**：
  - 依赖 `fetch_report`：`report_server.py:18`
  - 依赖 `replay_capture`：`report_server.py:19`
  - 依赖 `client.stock_name`：`report_server.py:251-256`
- **改写点**：
  - `/report/{run_id}` 改为从 `final_state` 或 `reports/{ticker}_{ts}/complete_report.md` 渲染。
  - `/replay/{run_id}` 与 `/debate/{run_id}` 改为从 astock 落盘数据构建。
  - 索引页从 SQLite `runs` 表读取，但 `task_id` 需替换为合成 run key。

#### `src/studio/notify/channels/__init__.py`

- **证据**：`__init__.py:4-7` 导入并注册 `webhook`、`dingtalk`、`wecom`、`telegram`。
- **改写点**：仅保留 `feishu` 导入，`build_channels` 中遇到非 `feishu` 类型直接跳过或报错。

### 3.5 多模型对比层

#### `src/studio/compare/runner.py`

- **证据**：
  - `run_one` 使用 `TradingAgentsClient`：`runner.py:32`
  - 提交分析：`runner.py:34-36`
  - 轮询等待：`runner.py:40`
  - 获取结果：`runner.py:47`
- **改写点**：
  - `run_one(model, symbol, date, ...)` 内部构造 `TradingAgentsGraph`，将 `config["deep_think_llm"]` 与 `config["quick_think_llm"]` 均设为该 model，调用 `propagate(symbol, date)`。
  - 每个模型独立一个 graph 实例，避免配置交叉污染。
  - 记录 wall time、status（成功/失败）、final_state 关键字段。

#### `src/studio/compare/metrics.py`

- **证据**：
  - `collect_tokens` 调用原项目用量接口：`metrics.py:48-62`（`client.usage_records`）
  - 决策提取依赖 `run.result.get("decision")` 或文本正则：`metrics.py:82`
- **改写点**：
  - astock 无 `/api/usage-statistics/records`，token 字段需要从 `StatsCallbackHandler`（`cli/main.py` 使用）或 LLM 回调获取；如无法获取则留空。
  - 决策提取改为优先读取 `final_state["final_trade_decision"]`，再回退到文本正则。

### 3.6 SQLite 存储

#### `src/studio/core/store.py`

- **证据**：
  - `runs` 表以 `task_id` 为主键：`store.py:13-25`
  - `upsert_run` 签名字段包含 `quick_model`/`deep_model`：`store.py:84-92`
- **改写点**：
  - 保持 `runs` 表，但主键改为 `run_id`（如 `{ticker}_{date}_{ts}`）或保留 `task_id` 列但允许存储合成 key，并新增 `ticker`、`trade_date` 列便于查询。
  - `run_events`、`digests`、`benchmarks` 表结构可保留，只是 `task_id` 列存放 run key。

### 3.7 Docker 模板

#### `docker/Dockerfile`

- **证据**：
  - 仅 COPY studio 自身：`Dockerfile:12-14`
  - 默认 `PIP_INDEX_URL` 指向清华源：`Dockerfile:8`
- **改写点**：
  - 在同一镜像中安装 astock（`pip install -e /path/to/TradingAgents-astock`）及其依赖，注意 mootdx/httpx 等二进制依赖。
  - 保留 studio 产物卷 `/data/studio`，新增 astock `results_dir` 挂载点。

#### `docker/docker-compose.studio.yml`

- **证据**：
  - 叠加到 TradingAgents-CN compose 网络：`docker-compose.studio.yml:15-47`
  - 挂载原项目 `data` 卷为只读：`docker-compose.studio.yml:34`
- **改写点**：
  - 不再使用 `external` 网络；独立服务即可。
  - 挂载 astock `results_dir`（如 `~/.tradingagents/logs`）到容器内固定路径，供 fetcher/capture 读取。
  - 环境变量增加 `TRADINGAGENTS_RESULTS_DIR` 等 astock 配置。

#### `docker/entrypoint.sh`

- **证据**：`entrypoint.sh:8-9` 启动 `studio report serve` + `studio cron`。
- **改写点**：命令不变，但需确保容器内 astock 包可用；可考虑在启动前校验 `tradingagents` 包是否安装。

---

## 4. CLI 七个命令组映射

| 命令组 | 当前实现 | 移植后行为 |
|---|---|---|
| `doctor` | 检查 `/api/health`、登录、`data.ta_dir`、LLM、渠道 | 检查 astock `results_dir` 可读写、LLM 配置、飞书配置、astock 包可用性 |
| `digest` | 从 task_id / `--symbol` / `--file` 读取 CN 产物并 condense | 从 `--symbol` 读取 astock JSON 全状态或 `reports/{symbol}_{ts}` 并 condense；`--file` 保留 |
| `notify` | 推送指定 task_id 的简报 | 在 `digest`/`propagate` 完成后推送；`notify test` 仍向飞书发测试消息 |
| `compare` | 通过 HTTP 向 CN 提交 N 个模型并轮询 | 为每个模型构造独立 `TradingAgentsGraph` 并调用 `propagate(symbol, date)`，并发控制 |
| `replay` | 从 API + 文件卷抓取时间线 / 辩论 | 从 astock `final_state` / JSON 全状态 / CLI 报告目录重建时间线与辩论 |
| `report` | 基于 HTTP 客户端提供 `/report/{task_id}` 等服务 | 基于 astock 落盘数据提供 `/report/{run_id}`、`/replay/{run_id}`、`/debate/{run_id}` |
| `cron` | 定时触发 `分析 -> digest -> notify` | 定时触发 `TradingAgentsGraph.propagate -> digest -> notify` |

---

## 5. `studio.yaml` 配置体系映射

| 当前段 | 当前用途 | 移植后建议 |
|---|---|---|
| `api` | TradingAgents-CN 地址/账号/密码 | **删除**；astock 为本地库，无需 HTTP 登录 |
| `llm` | digest / 辩论话题配对用 LLM | **保留**，仍需 OpenAI 兼容接口 |
| `data.ta_dir` | 原项目 `data/` 目录 | 改为 astock `results_dir`（默认 `~/.tradingagents/logs`），或同时支持 CLI `reports/` 目录 |
| `notify.report_url_prefix` | 飞书卡片按钮前缀 | **保留** |
| `notify.channels` | 飞书/钉钉/企微/TG/webhook | **仅保留 `feishu`** |
| `compare.defaults` | 深度/并发/轮询间隔 | 深度/并发保留；轮询间隔不再使用（本地运行不需要） |
| `compare.prices` | 模型单价 | **保留**，用于成本估算 |
| `compare.aliases` | 模型显示别名 | **保留** |
| `replay.theme` / `exports_dir` | 回放主题与导出目录 | **保留** |
| `cron.timezone` / `cron.jobs` | 定时任务 | **保留**，但 job 中 `depth` 需映射为 astock 的 debate/风险讨论轮数 |

---

## 6. 依赖 astock 侧假设清单

1. `TradingAgentsGraph.propagate(company_name, trade_date)` 返回 `(final_state, signal)`，且 `final_state` 包含第 1.1 节列出的全部字段。
2. `final_state` 中 `trader_investment_plan` 与 `trader_investment_decision` 为同一内容；`investment_plan` 存在。
3. `results_dir` 在 `DEFAULT_CONFIG`（`tradingagents/default_config.py:7`）中可配置，默认 `~/.tradingagents/logs`。
4. CLI `run_analysis` 会把运行时报告 md 写入 `{results_dir}/{ticker}/{date}/reports/*.md`，日志写入同层 `message_tool.log`。
5. CLI `save_report_to_disk` 会按 `reports/{ticker}_{timestamp}/` 目录结构写出 5 组子目录与 `complete_report.md`。
6. `cli/main.py:64-71` 的 `REPORT_SECTIONS` 映射长期稳定（`market_report`→`market.md` 等）。
7. `TradingAgentsGraph` 可独立实例化，通过修改 `config["deep_think_llm"]`/`config["quick_think_llm"]` 实现多模型对比。
8. 股票代码会经过 `safe_ticker_component` 处理，落盘目录中的 ticker 与输入一致（无路径穿越）。
9. astock 无任务级用量统计接口，token 成本需通过回调或 LLM 客户端自行统计。

---

## 7. 结论

- **原样拿走**：16 个文件（配置/事件/文本/渲染/飞书渠道等无引擎耦合部分）。
- **改写**：21 个文件（CLI、引擎接入、配置、报告读取、replay、调度、对比、Docker、测试、README）。
- **删除**：4 个文件（`dingtalk.py`、`wecom.py`、`telegram.py`、`webhook.py`）。
- **最大改写风险点**：
  1. **`replay/capture.py` 与 `digest/fetcher.py` 的落盘文件名/目录映射**：astock 同时存在“运行时中间产物 (`results_dir/{ticker}/{date}/reports/*.md`)”和“CLI 归档报告 (`reports/{ticker}_{timestamp}/*/...`)”两套结构，且字段名→文件名映射与原 `REPORT_PRIORITY`/`REPORT_AGENTS` 完全不同，错误映射会导致报告缺失或辩论回放为空。
  2. **`task_id` 概念消失**：原项目大量模块以 `task_id` 为主键（store、report URL、replay URL、notify 按钮）。astock 以 `(ticker, date, timestamp)` 标识一次运行，需统一合成 run key 并贯穿 CLI/store/report server，否则索引与链接会断裂。
  3. **`compare` 多模型并发**：需要为每个模型独立构造 `TradingAgentsGraph` 并切换其 `deep_think_llm`/`quick_think_llm`，同时保证实例间无共享状态、错误隔离，否则会出现模型串扰或内存/依赖冲突。
