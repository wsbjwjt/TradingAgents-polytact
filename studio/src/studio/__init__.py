"""TradingAgents-polytact Studio：对接 polytact engine（astock 引擎的兼容 API）的增强套件。

四个模块：
  digest  —— 长报告提炼成 200 字开盘简报
  notify  —— 飞书推送 + cron 定时管道
  compare —— 多模型同题对比，硬指标表格
  replay  —— 智能体辩论过程渲染成单文件 HTML 回放
  bot     —— 飞书入站机器人，接收代码列表后触发分析管道

与 engine 零耦合：只通过 HTTP API / 只读数据卷集成。
"""
__version__ = "0.1.0"
