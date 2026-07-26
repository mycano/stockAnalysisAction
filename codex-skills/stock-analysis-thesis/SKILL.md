---
name: "stock-analysis-thesis"
description: "显式创建、复核、更新、比较或失效投资论文并保留完整历史。"
managed_by: "stock-analysis"
schema_version: "2.0"
command_id: "stock-analysis.thesis"
catalog_hash: "sha256:d9cb45c6da32283c234898cc2e843baa08bb49c487b4c48fbcf62ed1e879a8ac"
host_target: "codex-skill"
x-stock-analysis-managed: true
x-stock-analysis-schema: "agent-entrypoint/v2"
x-stock-analysis-command: "thesis"
x-stock-analysis-catalog-hash: "sha256:d9cb45c6da32283c234898cc2e843baa08bb49c487b4c48fbcf62ed1e879a8ac"
---

# /thesis

显式创建、复核、更新、比较或失效投资论文并保留完整历史。

## 协议

把用户意图整理为内部结构化请求，交由 Python Router 静默完成验证、默认值、重定向、
安全门禁和确定性工作流选择。不得自行调用旧业务命令，也不得更改证据、研究命题、
缺失状态或阻断结果。

内部最小请求：

```json
{"schema_version":"2.0","command":"thesis","arguments":{"asset":"<asset>","action":"create"}}
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

宿主必须提交显式 action；任何写入都必须保留不可变历史和审计事件。

创建新论文骨架，不覆盖同标的既有论文。

复核当前证据与持久化快照，区分事实、覆盖变化和人工判断。

失效动作追加审计事件，不删除或覆盖论文历史。

更新必须追加不可变版本并保留全部历史，禁止静默覆盖。

比较显式选择的论文版本，不修改任何历史。
