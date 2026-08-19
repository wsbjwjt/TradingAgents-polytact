# 飞书长连接机器人：最小可用路径（R2）

> 研究日期：2026-08-19。来源：飞书开放平台官方文档 + lark-oapi SDK 源码仓库，逐条标注。

## 结论速览

长连接方案完全可行，且是官方推荐的自建应用接入方式。核心事实：**仅支持企业自建应用；每应用最多 50 条连接；多实例随机投递（我们必须只跑单实例）；任何权限/事件改动必须发布新版本后才生效（最常见踩坑点）**。

## 1. 最小可运行代码骨架

依赖：`pip install lark-oapi`（Python ≥ 3.8）。

```python
import lark_oapi as lark

def on_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    msg = data.event.message
    # msg.chat_id / msg.chat_type("p2p"|"group") / msg.message_type("text") / msg.content(JSON 字符串)
    print(lark.JSON.marshal(data, indent=4))

event_handler = lark.EventDispatcherHandler.builder("", "") \
    .register_p2_im_message_receive_v1(on_message) \
    .build()

def main():
    cli = lark.ws.Client(
        lark.APP_ID, lark.APP_SECRET,          # 建议改从环境变量读
        event_handler=event_handler,
        log_level=lark.LogLevel.DEBUG,
    )
    cli.start()  # 阻塞主线程；连接成功打印 "[ws] ws client ready"

if __name__ == "__main__":
    main()
```

来源：SDK 官方示例 [samples/ws/sample.py](https://github.com/larksuite/oapi-sdk-python/blob/main/samples/ws/sample.py)；官方文档[《使用长连接接收回调》](https://open.feishu.cn/document/event-subscription-guide/callback-subscription/step-1-choose-a-subscription-mode/configure-callback-request-address?lang=zh-CN)（2026-06-11 更新）。

补充：发送消息用普通 Client（非 ws）：

```python
client = lark.Client.builder().app_id(...).app_secret(...).build()
req = lark.api.im.v1.CreateMessageRequest.builder() \
    .receive_id_type("chat_id") \
    .request_body(lark.api.im.v1.CreateMessageRequestBody.builder()
        .receive_id(chat_id).msg_type("interactive").content(card_json_str).build()) \
    .build()
resp = client.im.v1.message.create(req)
```

来源：[SDK README](https://github.com/larksuite/oapi-sdk-python)。

## 2. 权限 scope 清单

| scope | 用途 | 必要性 |
|---|---|---|
| `im:message.p2p_msg`（或 `:readonly`） | 收单聊消息 | 私聊场景必需 |
| `im:message.group_at_msg`（或 `:readonly`） | 收群聊中 @机器人 的消息 | 群场景必需 |
| `im:message.group_msg` | 收群内**所有**消息 | 敏感权限，不需要（我们用 @ 触发） |
| `im:message:send_as_bot` | 机器人发消息/发卡片 | 必需 |

注意：`im:message.p2p_msg` / `im:message.group_at_msg` 的非 readonly 版本官方标注"已下线"（存量不受影响），**新申请一律用 `:readonly` 版本**。

来源：[《接收消息》事件文档](https://open.feishu.cn/document/server-docs/im-v1/message/events/receive?lang=zh-CN)（2026-08-05 更新）、[《机器人支持外部群》](https://open.feishu.cn/document/develop-robots/add-bot-to-external-group?lang=zh-CN)。

## 3. 群聊/单聊收消息机制

- 群聊：机器人默认**只能收到 @ 它的消息**（配 `group_at_msg:readonly`）；收全部群消息需 `group_msg`（敏感权限，审核严格，本项目不需要）。
- 单聊：配 `p2p_msg:readonly` 后可收所有私聊消息。
- 事件结构关键字段：`event.message.{message_id, chat_id, chat_type, message_type, content}`，`content` 是 JSON 字符串（text 类型为 `{"text":"..."}`，@机器人 的文本会带 `@_user_1` 占位符，需清洗）；`event.sender.sender_type` 区分 user/bot。
- **幂等**：官方明确"特殊情况下会重复推送，用 `message_id` 去重，不要依赖 event_id"。

来源：同《接收消息》事件文档；[《消息常见问题》](https://open.feishu.cn/document/server-docs/im-v1/faq?lang=zh-CN)。

## 4. 卡片消息（interactive）能力边界

Card JSON 2.0，要点：

- 单条卡片 JSON 总大小约 **30KB**；单个 markdown 元素约 **3000–4000 字符**（工程上按 2800 分段稳妥）；元素总数 ≤50。
- 富文本组件支持 CommonMark 标准 Markdown（除 HTMLBlock），换行规则与 CommonMark 有差异（单 Enter 软换行可能被忽略，用双换行）。
- 结构：`header`（title + template 颜色：blue/red/green/orange/purple/grey）+ `elements`（`markdown`/`div`/`hr`/`note`/`action`（按钮）/`collapse` 折叠）。
- 按钮跳转链接用 `url` 或 `multi_url`（分端 android/ios/pc）；按钮交互回调 `card.action.trigger` 同样走长连接，无需公网回调。
- 发送：`msg_type=interactive`，`content` 为卡片 JSON 字符串。

来源：[《卡片 JSON 2.0 版本更新说明》](https://open.feishu.cn/document/feishu-cards/card-json-v2-breaking-changes-release-notes?lang=zh-CN)、[Button 组件文档](https://open.larkoffice.com/document/feishu-cards/card-components/interactive-components/button)、工程实践参考 [feishu-claude-code/feishu_client.py](https://github.com/joewongjc/feishu-claude-code/blob/main/feishu_client.py)（markdown 元素按 2800 字符分段）。

晨报简报（目标几百字 + 一个"查看完整报告"按钮）远在所有限制之内，无需分段。

## 5. token 管理

SDK 内置 token management（自动获取/缓存/刷新 tenant_access_token），无需手动处理。来源：[SDK README](https://github.com/larksuite/oapi-sdk-python)（"This SDK wraps ... token management ..."）。

## 6. 长连接运行特性

- 每应用最多 **50 条**连接（每初始化一个 client 算一条）。
- **多实例随机投递**：同一事件可能被投递到任一在线连接——生产环境**只能跑一个实例**（我们的部署恰好是单实例）。
- 断线重连由 SDK 内部处理（`start()` 阻塞式运行）；仍建议进程级守护（docker restart policy）。
- 保存"长连接"订阅方式时，平台会校验连接已在线——**先在服务器把 client 跑起来，再去后台保存配置**。

来源：[《使用长连接接收回调》](https://open.feishu.cn/document/event-subscription-guide/callback-subscription/step-1-choose-a-subscription-mode/configure-callback-request-address?lang=zh-CN)、[《事件与回调常见问题》](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/event-subscription-guide/event-card-faq?lang=zh-CN)。

## 7. 发布与审核

- 企业自建应用：**权限/事件/订阅方式的任何改动都必须"创建版本并发布"后才生效**——这是"机器人没反应"的最高频原因。
- 发布需企业管理员审批；如果你自己就是企业管理员（个人/小企业场景），自己在飞书里审批即可，秒过。
- 可用范围建议设"全员可用"（或确保自己在白名单内）。

来源：[《事件与回调常见问题》](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/event-subscription-guide/event-card-faq?lang=zh-CN)、《消息常见问题》。

## 对本项目的设计约束（落进实现）

1. 飞书接入进程全局单实例（compose 里 `replicas: 1`，restart: unless-stopped）。
2. 群聊用 @机器人 触发；解析 `content` 时清洗 `@_user_1` 占位符再按逗号切代码。
3. 消息处理按 `message_id` 幂等去重（SQLite store 记一笔即可）。
4. 晨报卡片：header(template 按评级变色) + markdown 正文 + 一个 url 按钮（指向报告服务），体量远低于限制。
5. 卡片按钮回调（如未来加"重跑"按钮）走同一长连接，无需额外端口。
