---
name: "stock-screen"
description: "已弃用的 /stock-screen 兼容入口；转发到 /screen。"
managed_by: "stock-analysis"
schema_version: "2.0"
command_id: "stock-analysis.screen"
catalog_hash: "sha256:6d9ed4f19db8773424bf761842e60c3812ca476582f168c404473fc53b64de0a"
host_target: "claude-command"
x-stock-analysis-managed: true
x-stock-analysis-schema: "agent-entrypoint/v2"
x-stock-analysis-command: "screen"
x-stock-analysis-catalog-hash: "sha256:6d9ed4f19db8773424bf761842e60c3812ca476582f168c404473fc53b64de0a"
deprecated: true
---

# /stock-screen（兼容）

此入口自 4.17.0 起弃用，仅兼容转发到 `/screen`；不得复制或执行第二套
业务协议。向用户显示弃用提示，保留原参数，并将其整理为：

```json
{"schema_version":"2.0","command":"screen","arguments":{"mode":"explore"}}
```

然后以独立 argv 元素调用：

```text
stock-analysis agent route --request <HostRequest JSON>
stock-analysis agent run --request <HostRequest JSON>
```

不得使用 `--input`，不得拼接 Shell 字符串，且必须保留 Router 的阻断、重定向和原因码。
