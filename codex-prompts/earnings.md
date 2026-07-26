---
name: "stock-analysis-earnings"
description: "复核已披露财报事实、可比期间和对论文的影响。"
managed_by: "stock-analysis"
schema_version: "2.0"
command_id: "stock-analysis.earnings"
catalog_hash: "sha256:d9cb45c6da32283c234898cc2e843baa08bb49c487b4c48fbcf62ed1e879a8ac"
host_target: "codex-prompt"
x-stock-analysis-managed: true
x-stock-analysis-schema: "agent-entrypoint/v2"
x-stock-analysis-command: "earnings"
x-stock-analysis-catalog-hash: "sha256:d9cb45c6da32283c234898cc2e843baa08bb49c487b4c48fbcf62ed1e879a8ac"
---

# /earnings

复核已披露财报事实、可比期间和对论文的影响。

## 协议

把用户意图整理为内部结构化请求，交由 Python Router 静默完成验证、默认值、重定向、
安全门禁和确定性工作流选择。不得自行调用旧业务命令，也不得更改证据、研究命题、
缺失状态或阻断结果。

内部最小请求：

```json
{"schema_version":"2.0","command":"earnings","arguments":{"asset":"<asset>"}}
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

宿主必须保留披露期和比较期，不得把相关变化写成管理层已证实的因果。

仅指出对现有论文的潜在影响，论文变更必须交由显式 thesis 动作。

区分财报事实、变化、解释和未知项，不在缺少原始财报时推断。

只报告已披露事实并明确披露期、可比期间与缺失原文。
