---
name: "stock-analysis-portfolio"
description: "复核、导入、压力测试或比较明确授权的结构化持仓。"
managed_by: "stock-analysis"
schema_version: "2.0"
command_id: "stock-analysis.portfolio"
catalog_hash: "sha256:6d9ed4f19db8773424bf761842e60c3812ca476582f168c404473fc53b64de0a"
host_target: "codex-skill"
x-stock-analysis-managed: true
x-stock-analysis-schema: "agent-entrypoint/v2"
x-stock-analysis-command: "portfolio"
x-stock-analysis-catalog-hash: "sha256:6d9ed4f19db8773424bf761842e60c3812ca476582f168c404473fc53b64de0a"
---

# /portfolio

复核、导入、压力测试或比较明确授权的结构化持仓。

## 协议

你是 `HostRequest` 层。把用户意图整理为结构化对象，Python Router 负责验证、默认值、
重定向、安全门禁和确定性工作流选择。不得自行调用旧业务命令，也不得更改 Evidence、
Claim、Finding、缺失状态或阻断结果。

最小请求：

```json
{"schema_version":"2.0","command":"portfolio","arguments":{"action":"review"}}
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

宿主必须声明持仓状态；partial、stale 或 missing 不得升级为 complete。

只有 complete 持仓可形成完整压力测试结论，否则返回阻断和缺口。

只有 complete 持仓可形成完整比较结论，并保留基准与期间。

导入前验证结构和完整性；不得静默合并或覆盖未知持仓。

持仓非 complete 时只能报告有限事实和缺口，不得给出完整组合结论。
