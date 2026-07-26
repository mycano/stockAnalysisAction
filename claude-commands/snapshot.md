---
name: "stock-analysis-snapshot"
description: "获取标的的确定性报价、量价和已披露事实快照。"
managed_by: "stock-analysis"
schema_version: "2.0"
command_id: "stock-analysis.snapshot"
catalog_hash: "sha256:6d9ed4f19db8773424bf761842e60c3812ca476582f168c404473fc53b64de0a"
host_target: "claude-command"
x-stock-analysis-managed: true
x-stock-analysis-schema: "agent-entrypoint/v2"
x-stock-analysis-command: "snapshot"
x-stock-analysis-catalog-hash: "sha256:6d9ed4f19db8773424bf761842e60c3812ca476582f168c404473fc53b64de0a"
---

# /snapshot

获取标的的确定性报价、量价和已披露事实快照。

## 协议

你是 `HostRequest` 层。把用户意图整理为结构化对象，Python Router 负责验证、默认值、
重定向、安全门禁和确定性工作流选择。不得自行调用旧业务命令，也不得更改 Evidence、
Claim、Finding、缺失状态或阻断结果。

最小请求：

```json
{"schema_version":"2.0","command":"snapshot","arguments":{"asset":"<asset>"}}
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

宿主不得把事实快照解释为完整研究、估值或投资建议。

仅报告公开净值、画像和持仓事实，并显式保留未披露字段。

仅报告报价、量价和已披露财务事实；不得转化为估值或买卖判断。
