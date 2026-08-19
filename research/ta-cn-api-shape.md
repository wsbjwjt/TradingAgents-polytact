# hsliuping/TradingAgents-CN Web API 形状盘点

> 数据来源：`https://github.com/hsliuping/TradingAgents-CN`（clone 到 `%TEMP%\ta-cn-ref`），以其 `app/` 目录的 FastAPI 路由/模型/服务源码为一手来源。盘点日期：2026-08-19。
>
> 目标：核对 CN-studio 的 `src/studio/core/client.py` 对端点的假设是否与本仓库真实实现一致。

## 1. 路由前缀与端点清单

从 `app/main.py` 的 `app.include_router(...)` 注册代码得到完整前缀：

| 模块 | 注册前缀 | 实际完整根路径 |
|------|----------|----------------|
| `auth_db` | `/api/auth` | `/api/auth/*` |
| `analysis` | `/api/analysis` | `/api/analysis/*` |
| `sse` | `/api/stream` | `/api/stream/*` |
| `usage_statistics` | 无额外前缀，但 router 自带 `prefix="/api/usage"` | `/api/usage/*` |

涉及的端点：

- `POST /api/auth/login`
- `POST /api/analysis/single`
- `GET /api/analysis/tasks/{task_id}/status`
- `GET /api/analysis/tasks/{task_id}/result`
- `GET /api/stream/tasks/{task_id}`
- `GET /api/usage/records`

## 2. 各端点请求/响应 Schema

### 2.1 登录 `POST /api/auth/login`

**请求模型**（`app/routers/auth_db.py:37-39`）：

```python
class LoginRequest(BaseModel):
    username: str
    password: str
```

**响应结构**（`app/routers/auth_db.py:185-199`）：

```json
{
  "success": true,
  "data": {
    "access_token": "<jwt>",
    "refresh_token": "<jwt>",
    "expires_in": 3600,
    "user": {
      "id": "<str>",
      "username": "...",
      "email": "...",
      "name": "...",
      "is_admin": false
    }
  },
  "message": "登录成功"
}
```

### 2.2 提交单股分析 `POST /api/analysis/single`

**请求模型**：`app/models/analysis.py:154-162`

```python
class SingleAnalysisRequest(BaseModel):
    symbol: Optional[str] = Field(None, description="6位股票代码")
    stock_code: Optional[str] = Field(None, description="股票代码(已废弃,使用symbol)")
    parameters: Optional[AnalysisParameters] = None
```

其中 `AnalysisParameters`（`app/models/analysis.py:33-54`）：

```python
class AnalysisParameters(BaseModel):
    market_type: str = "A股"
    analysis_date: Optional[datetime] = None
    research_depth: str = "标准"          # 枚举见下
    selected_analysts: List[str] = ["market", "fundamentals", "news", "social"]
    custom_prompt: Optional[str] = None
    include_sentiment: bool = True
    include_risk: bool = True
    language: str = "zh-CN"
    quick_analysis_model: Optional[str] = "qwen-turbo"
    deep_analysis_model: Optional[str] = "qwen-max"
```

**枚举取值**：

- `research_depth`： `"快速"`, `"基础"`, `"标准"`, `"深度"`, `"全面"`（`app/models/analysis.py` 注释与 `app/services/simple_analysis_service.py:464-470`）。也支持数字 `1-5` 或字符串数字 `"1"-"5"`。
- `selected_analysts`：可选 `"market"`, `"social"`, `"news"`, `"fundamentals"`（`tradingagents/graph/setup.py:65-76`）。
- `quick_analysis_model` / `deep_analysis_model`：系统不强制枚举，常见支持见 `app/constants/model_capabilities.py:94-210`（如 `qwen-turbo`, `qwen-plus`, `qwen-max`, `gpt-4o-mini`, `deepseek-chat` 等）。

**响应结构**（`app/routers/analysis.py:88-92`）：

```json
{
  "success": true,
  "data": {
    "task_id": "<uuid>",
    "status": "pending",
    "message": "任务已创建，等待执行"
  },
  "message": "分析任务已在后台启动"
}
```

### 2.3 任务状态 `GET /api/analysis/tasks/{task_id}/status`

路由实现：`app/routers/analysis.py:105-219`。

返回统一包装：

```json
{
  "success": true,
  "data": { ...status对象... },
  "message": "任务状态获取成功"
}
```

`data` 的字段来自两处：

1. 若任务在内存中，由 `SimpleAnalysisService.get_task_status`（`app/services/simple_analysis_service.py:1889-1974`）返回：
   - `task_id`, `status`, `progress`, `message`, `current_step`, `stock_code`/`stock_symbol`, `start_time`, `end_time`
   - 若 Redis 有进度，额外返回：`current_step_name`, `current_step_description`, `elapsed_time`, `remaining_time`, `estimated_total_time`, `steps`, `last_update`
2. 若内存未命中，从 MongoDB `analysis_tasks` 集合构造（`app/routers/analysis.py:135-209`）：
   - 进行中的任务返回 `status`（来自 MongoDB，通常为 `"processing"` 或 `"pending"`）、`progress`、`current_step`、`start_time`、`end_time` 等
   - 已完成的任务从 `analysis_reports` 构造，返回 `status: "completed"`、`progress: 100` 等

### 2.4 任务结果 `GET /api/analysis/tasks/{task_id}/result`

路由实现：`app/routers/analysis.py:221-704`。

返回统一包装：

```json
{
  "success": true,
  "data": { ...result对象... },
  "message": "分析结果获取成功"
}
```

`data` 最终由 `app/routers/analysis.py:645-663` 构建，包含字段：

```python
{
  "analysis_id": str,
  "stock_symbol": str,
  "stock_code": str,
  "analysis_date": str,          # 形如 "2025-08-20"
  "summary": str,
  "recommendation": str,
  "confidence_score": float,
  "risk_level": str,             # 如 "中等"
  "key_points": List[str],
  "execution_time": float,
  "tokens_used": int,
  "analysts": List[str],
  "research_depth": str,
  "detailed_analysis": dict,
  "state": dict,
  "decision": dict,              # {action, confidence, risk_score, target_price, reasoning}
  "reports": dict                # 键值对：报告名 -> markdown 字符串
}
```

### 2.5 SSE 进度流 `GET /api/stream/tasks/{task_id}`

路由实现：`app/routers/sse.py:224-240`。

- `media_type="text/event-stream"`
- 通过 Redis PubSub 频道 `task_progress:{task_id}` 订阅进度

事件类型与 payload（`app/routers/sse.py:46, 70, 78, 87`）：

| 事件名 | 触发时机 | payload 示例 |
|--------|----------|--------------|
| `connected` | 订阅成功后立即发送 | `{"task_id": "...", "message": "已连接进度流"}` |
| `progress` | 收到 Redis 消息 | 由 `RedisProgressTracker` 发布的对象，典型字段：`progress_percentage`, `last_message`, `elapsed_time`, `remaining_time`, `estimated_total_time`, `current_step`, `steps` |
| `heartbeat` | 每 `sse_heartbeat_interval_seconds`（默认 10s）无消息时 | `{"timestamp": ...}` |
| `error` | 异常或订阅失败 | `{"error": "..."}` |

**结束标志**：单任务 SSE 没有专门的 `finished` 事件；连接在 `sse_task_max_idle_seconds`（默认 300s）无消息后自动关闭。批次 SSE 才有 `event: finished`（`app/routers/sse.py:207`）。

### 2.6 使用记录 `GET /api/usage/records`

路由实现：`app/routers/usage_statistics.py:16-53`。

注意：该 router 注册前缀为 `/api/usage`，因此真实端点是 ** `/api/usage/records` **，而非 `/api/usage-statistics/records`。

Query 参数：

- `provider`: 可选 str
- `model_name`: 可选 str
- `start_date`: ISO 格式日期字符串
- `end_date`: ISO 格式日期字符串
- `limit`: int，默认 100，范围 `1-1000`

响应结构：

```json
{
  "success": true,
  "message": "获取使用记录成功",
  "data": {
    "records": [ ...UsageRecord... ],
    "total": 0
  }
}
```

## 3. 分析任务状态机

### 3.1 内存状态（`MemoryStateManager`）

定义于 `app/services/memory_state_manager.py:16-22`：

```python
class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

### 3.2 MongoDB 持久化状态

定义于 `app/models/analysis.py:14-20`：

```python
class AnalysisStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

### 3.3 状态流转

- `create_analysis_task` 创建任务：内存 `pending`，MongoDB `pending`（`app/services/simple_analysis_service.py:760-837`）。
- 开始执行后：内存 `running`，MongoDB `processing`（`app/services/simple_analysis_service.py:960-970`）。
- 成功完成：内存 `completed` + `progress=100`，MongoDB `completed`（`app/services/simple_analysis_service.py:1013-1023`）。
- 失败：内存 `failed`，MongoDB `failed`（`app/services/simple_analysis_service.py:1073-1084`）。
- 取消：通过 `POST /api/analysis/tasks/{task_id}/cancel` 调用 `QueueService.cancel_task`（`app/routers/analysis.py:948-967`）。
- 僵尸任务清理：超过 `max_running_hours`（默认 2h）仍处于 `processing/running/pending` 的任务会被标记为 `failed`（`app/services/simple_analysis_service.py:2262-2322`）。

### 3.4 状态查询的兼容性

`/api/analysis/tasks/{task_id}/status` 会优先查内存；内存未命中再查 MongoDB。因此同一个任务可能先返回 `running`（内存），后返回 `processing` 或 `completed`（MongoDB）。前端/客户端若只认固定字符串，需要同时兼容 `running` 与 `processing`。

## 4. 鉴权机制

### 4.1 登录端点

见 2.1。用户名密码在 MongoDB `users` 集合中比对 bcrypt 哈希（`app/services/user_service.py:123-177`）。

### 4.2 Token 类型

- `access_token`：JWT，默认有效期 60 分钟（`app/core/config.py:125`）。
- `refresh_token`：JWT，登录时生成 7 天有效期（`app/routers/auth_db.py:170`）；配置项 `REFRESH_TOKEN_EXPIRE_DAYS` 默认 30 天（`app/core/config.py:126`），实际代码中未使用该配置，直接写死 7 天。

JWT payload（`app/services/auth_service.py:22`）：

```python
{"sub": username, "exp": expire}
```

算法 `HS256`，密钥 `JWT_SECRET`（默认 `change-me-in-production`）。

### 4.3 后续请求携带方式

依赖函数 `get_current_user`（`app/routers/auth_db.py:69-114`）要求：

```
Authorization: Bearer <access_token>
```

所有分析端点、SSE 端点、使用统计端点都依赖 `get_current_user`。

### 4.4 默认账号

- 没有代码在应用启动时自动创建默认用户。默认管理员需通过脚本创建：
  - `scripts/create_default_admin.py` 默认创建 `admin / admin123`（`scripts/create_default_admin.py:29-31, 219`）。
  - `app/services/user_service.py:303-350` 提供 `create_admin_user(username="admin", password="admin123", email="admin@tradingagents.cn")`。
- 特殊处理：`admin` 字符串用户 ID 在多处被映射为固定 ObjectId `507f1f77bcf86cd799439011`（`app/services/simple_analysis_service.py:721-724`, `2115-2122`）。

## 5. 分析结果的数据结构与落盘目录

### 5.1 结果字段名

`GET /api/analysis/tasks/{task_id}/result` 返回的 `data` 字段：

- 顶层字段：`analysis_id`, `stock_symbol`, `stock_code`, `analysis_date`, `summary`, `recommendation`, `confidence_score`, `risk_level`, `key_points`, `execution_time`, `tokens_used`, `analysts`, `research_depth`, `detailed_analysis`, `state`, `decision`, `reports`
- `decision` 子字段：`action`（中文：买入/卖出/持有）, `confidence`, `risk_score`, `target_price`, `reasoning`

### 5.2 reports 字段的键名

从 `state` 中提取的报告键名（`app/services/simple_analysis_service.py:1567-1687` 与 `app/routers/analysis.py:406-464`）：

- `market_report`
- `sentiment_report`
- `news_report`
- `fundamentals_report`
- `investment_plan`
- `trader_investment_plan`
- `final_trade_decision`
- `bull_researcher`（来自 `investment_debate_state.bull_history`）
- `bear_researcher`（来自 `investment_debate_state.bear_history`）
- `research_team_decision`（来自 `investment_debate_state.judge_decision`）
- `risky_analyst`（来自 `risk_debate_state.risky_history`）
- `safe_analyst`（来自 `risk_debate_state.safe_history`）
- `neutral_analyst`（来自 `risk_debate_state.neutral_history`）
- `risk_management_decision`（来自 `risk_debate_state.judge_decision`）

### 5.3 本地落盘目录结构

保存函数：`SimpleAnalysisService._save_modular_reports_to_data_dir`（`app/services/simple_analysis_service.py:2755-2932`）。

默认根目录：

```
<project_root>/data/analysis_results/
```

若环境变量 `TRADINGAGENTS_RESULTS_DIR` 存在则优先使用（相对路径会拼接到项目根目录）。

单只股票的分析结果目录：

```
data/analysis_results/
└── {stock_symbol}/
    └── {analysis_date}/
        ├── message_tool.log
        ├── analysis_metadata.json
        └── reports/
            ├── market_report.md
            ├── sentiment_report.md
            ├── news_report.md
            ├── fundamentals_report.md
            ├── investment_plan.md
            ├── trader_investment_plan.md
            ├── final_trade_decision.md
            ├── research_team_decision.md
            └── risk_management_decision.md
```

`analysis_metadata.json` 包含 `stock_symbol`, `analysis_date`, `research_depth`, `analysts`, `status`, `reports_count`, `report_types`。

CN-studio fetcher 若读取 `data/analysis_results/{symbol}/{date}/reports/*.md`，与本仓库的默认落盘结构一致；唯一例外是当设置 `TRADINGAGENTS_RESULTS_DIR` 时路径会改变。

## 6. 与 CN-studio `client.py` 假设的对比

| 项目 | `client.py` 假设 | 本仓库真实实现 | 结论 |
|------|------------------|----------------|------|
| 登录 | `POST /api/auth/login`，请求 `{username, password}`，从 `data.access_token` 取 token | 完全一致 | 吻合 |
| 提交分析 | `POST /api/analysis/single`，body `{symbol, stock_code, parameters}`，parameters 含 `quick_analysis_model`, `deep_analysis_model`, `selected_analysts`, `research_depth`, `analysis_date` | 完全一致；字段名是 `quick_analysis_model`/`deep_analysis_model`，不是 `quick_model`/`deep_model` | 吻合（注意字段名） |
| 状态轮询 | `GET /api/analysis/tasks/{id}/status` | 完全一致 | 吻合 |
| 取结果 | `GET /api/analysis/tasks/{id}/result` | 完全一致 | 吻合 |
| SSE | `GET /api/stream/tasks/{id}` | 完全一致 | 吻合 |
| 使用记录 | `GET /api/usage-statistics/records` | 真实端点是 **`/api/usage/records`** | **不匹配，client 会 404** |
| 终态判断 | `TERMINAL = {"completed", "failed", "cancelled", "cancelled_failed"}` | 真实状态可能是 `completed`/`failed`/`cancelled`（内存），也可能出现 `processing`/`running`/`pending` | 基本够用，但 `cancelled_failed` 不是真实状态；`processing`/`running` 不应被误判为终态 |
| 默认账号 | 默认 `admin / <空密码>` | 真实默认管理员通常是 `admin / admin123`（需脚本创建） | 不匹配；且生产环境不应依赖默认账号 |

### 最大出入点

1. **使用统计端点路径错误**：`client.py` 调用 `/api/usage-statistics/records`，而本仓库真实路径是 `/api/usage/records`。这是唯一会导致请求直接 404 的硬性不匹配。
2. **默认密码差异**：`client.py` 默认密码为空字符串，本仓库默认管理员脚本使用 `admin123`。
3. **状态值兼容性**：状态查询在内存中用 `running`，MongoDB 中用 `processing`，`client.py` 的 `TERMINAL` 集合没有包含这两个非终态，所以轮询逻辑不会误判；但如果仅做字符串匹配，需要注意 `cancelled_failed` 并非真实状态。
4. **字段名注意**：任务描述中提到 `quick_model`/`deep_model`，但真实请求字段是 `quick_analysis_model`/`deep_analysis_model`；所幸 `client.py` 实际发送的就是带 `_analysis_model` 后缀的版本，与源码一致。
