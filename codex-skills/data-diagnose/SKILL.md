---
name: "data-diagnose"
description: "检查命令协议、生成入口和运行环境。"
managed_by: "stock-analysis"
schema_version: "2.0"
command_id: "stock-analysis.data-diagnose"
catalog_hash: "sha256:6d9ed4f19db8773424bf761842e60c3812ca476582f168c404473fc53b64de0a"
host_target: "codex-skill"
x-stock-analysis-managed: true
x-stock-analysis-schema: "agent-entrypoint/v2"
x-stock-analysis-command: "data-diagnose"
x-stock-analysis-catalog-hash: "sha256:6d9ed4f19db8773424bf761842e60c3812ca476582f168c404473fc53b64de0a"
operational: true
---

# /data-diagnose

检查命令协议、生成入口和运行环境。

这是运维入口，不属于八个研究命令，也不接受或模拟 `HostRequest`。以独立 argv 元素运行：

```text
stock-analysis-agent doctor all
```

只报告诊断事实、缺失配置和安全修复建议；不得借此执行研究工作流。
