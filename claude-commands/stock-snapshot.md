---
name: "stock-snapshot"
description: "已弃用的 /stock-snapshot 兼容入口；转发到 /snapshot。"
managed_by: "stock-analysis"
schema_version: "2.0"
command_id: "stock-analysis.snapshot"
catalog_hash: "sha256:d9cb45c6da32283c234898cc2e843baa08bb49c487b4c48fbcf62ed1e879a8ac"
host_target: "claude-command"
x-stock-analysis-managed: true
x-stock-analysis-schema: "agent-entrypoint/v2"
x-stock-analysis-command: "snapshot"
x-stock-analysis-catalog-hash: "sha256:d9cb45c6da32283c234898cc2e843baa08bb49c487b4c48fbcf62ed1e879a8ac"
deprecated: true
---

# /stock-snapshot（兼容）

此入口自 4.17.0 起弃用，仅兼容转发到 `/snapshot`；不得复制或执行第二套
业务协议。向用户显示弃用提示，保留原参数，并将其整理为：

```json
{"schema_version":"2.0","command":"snapshot","arguments":{"asset_type":"company","asset":"<asset>"}}
```

然后以独立 argv 元素调用：

```text
stock-analysis agent run --request <HostRequest JSON>
```

不得使用 `--input`，不得拼接 Shell 字符串。路由、阻断、重定向、原因码和内部路径均
保持内部可审计，不得展示给用户；用户只看到自然语言结果与必要的数据边界说明。
