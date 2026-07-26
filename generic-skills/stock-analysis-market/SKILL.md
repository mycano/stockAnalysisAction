---
name: "stock-analysis-market"
description: "按市场、交易日历和时段生成确定性的市场复盘。"
managed_by: "stock-analysis"
schema_version: "2.0"
command_id: "stock-analysis.market"
catalog_hash: "sha256:d9cb45c6da32283c234898cc2e843baa08bb49c487b4c48fbcf62ed1e879a8ac"
host_target: "generic-skill"
x-stock-analysis-managed: true
x-stock-analysis-schema: "agent-entrypoint/v2"
x-stock-analysis-command: "market"
x-stock-analysis-catalog-hash: "sha256:d9cb45c6da32283c234898cc2e843baa08bb49c487b4c48fbcf62ed1e879a8ac"
---

# /market

按市场、交易日历和时段生成确定性的市场复盘。

## 协议

把用户意图整理为内部结构化请求，交由 Python Router 静默完成验证、默认值、重定向、
安全门禁和确定性工作流选择。不得自行调用旧业务命令，也不得更改证据、研究命题、
缺失状态或阻断结果。

内部最小请求：

```json
{"schema_version":"2.0","command":"market","arguments":{}}
```

以独立 argv 元素直接运行：

```text
stock-analysis agent run --request <内部请求 JSON>
```

不得拼接 Shell 命令字符串，不得把用户文本直接插入 Shell，也不得在正式链路使用
`--input`。

默认用户界面只能展示自然语言研究结果与简短的数据边界说明。路由对象、请求 JSON、
工作流名、原因码、证据对象、审计对象、文件路径、内部字段和诊断日志仅供内部执行，
不得展示或要求用户确认。只有标的真实歧义、互相冲突的要求、不可逆操作，或缺少决定
研究对象的核心参数时，才用自然语言询问会实质改变结果的问题。

## 命令边界

宿主只提交结构化市场、日期和时段；不得自行判断交易日或补写缺失行情。

先报告事实、数据质量与缺口，再给条件式观察清单。

明确各市场交易时段和数据截止时间，不混合不同交易日。
