---
name: "stock-analysis-analyze"
description: "股票、ETF 和基金的统一研究入口，默认使用 standard 深度。"
managed_by: "stock-analysis"
schema_version: "2.0"
command_id: "stock-analysis.analyze"
catalog_hash: "sha256:6d9ed4f19db8773424bf761842e60c3812ca476582f168c404473fc53b64de0a"
host_target: "codex-skill"
x-stock-analysis-managed: true
x-stock-analysis-schema: "agent-entrypoint/v2"
x-stock-analysis-command: "analyze"
x-stock-analysis-catalog-hash: "sha256:6d9ed4f19db8773424bf761842e60c3812ca476582f168c404473fc53b64de0a"
---

# /analyze

股票、ETF 和基金的统一研究入口，默认使用 standard 深度。

## 协议

你是 `HostRequest` 层。把用户意图整理为结构化对象，Python Router 负责验证、默认值、
重定向、安全门禁和确定性工作流选择。不得自行调用旧业务命令，也不得更改 Evidence、
Claim、Finding、缺失状态或阻断结果。

最小请求：

```json
{"schema_version":"2.0","command":"analyze","arguments":{"asset":"<asset>"}}
```

先以独立 argv 元素调用路由并向用户展示 `RouteDecision`：

```text
stock-analysis agent route --request <HostRequest JSON>
```

用户确认执行上下文后，以独立 argv 元素运行：

```text
stock-analysis agent run --request <HostRequest JSON>
```

不得拼接 Shell 命令字符串，不得把用户文本直接插入 Shell，也不得在正式链路使用
`--input`。保留 Router 返回的 `reason_codes`、`output_contract` 和全部缺失/部分状态。

## 命令边界

宿主可解释经验证的输出，但不得修改证据账本、结论状态或绕过阻断条件。

在同一冻结证据快照上完成深度研究；不得让宿主改写 Evidence、Claim 或 Finding。

提供边界明确的快速证据复核，显式列出未覆盖的深度能力。

生成可恢复、可审计的标准研究工作区并保留证据缺口。
