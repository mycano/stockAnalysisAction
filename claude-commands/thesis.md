---
name: "stock-analysis-thesis"
description: "显式创建、复核、更新、比较或失效投资论文并保留完整历史。"
managed_by: "stock-analysis"
schema_version: "2.0"
command_id: "stock-analysis.thesis"
catalog_hash: "sha256:6d9ed4f19db8773424bf761842e60c3812ca476582f168c404473fc53b64de0a"
host_target: "claude-command"
x-stock-analysis-managed: true
x-stock-analysis-schema: "agent-entrypoint/v2"
x-stock-analysis-command: "thesis"
x-stock-analysis-catalog-hash: "sha256:6d9ed4f19db8773424bf761842e60c3812ca476582f168c404473fc53b64de0a"
---

# /thesis

显式创建、复核、更新、比较或失效投资论文并保留完整历史。

## 协议

你是 `HostRequest` 层。把用户意图整理为结构化对象，Python Router 负责验证、默认值、
重定向、安全门禁和确定性工作流选择。不得自行调用旧业务命令，也不得更改 Evidence、
Claim、Finding、缺失状态或阻断结果。

最小请求：

```json
{"schema_version":"2.0","command":"thesis","arguments":{"asset":"<asset>","action":"create"}}
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

宿主必须提交显式 action；任何写入都必须保留不可变历史和审计事件。

创建新论文骨架，不覆盖同标的既有论文。

复核当前证据与持久化快照，区分事实、覆盖变化和人工判断。

失效动作追加审计事件，不删除或覆盖论文历史。

更新必须追加不可变版本并保留全部历史，禁止静默覆盖。

比较显式选择的论文版本，不修改任何历史。
