# 阶段 D：代码边界检查

本文档记录 scripted / LLM / real / mock 的边界检查结果。

## 1. 检查范围

| 项目 | 结论 |
| --- | --- |
| MiniAgent scripted | 用 JSONL 重放 tool_calls，用于可复现评估，不调用 LLM。 |
| MiniAgent llm | 调用 OpenAI-compatible API，让 LLM 输出 JSON `tool_calls`，用于真实 Agent 演示。 |
| CoreCoder scripted | 使用脚本化 LLM 生成固定工具调用，离线稳定演示 CoreCoder 工具执行前拦截。 |
| CoreCoder real | 使用 CoreCoder 真实 LLM 配置生成工具调用，需要 API key/base_url/model。 |
| Risk explainer template | 本地模板解释，不需要 API key，输出到 `logs/p2_explained_audit.jsonl`。 |
| Risk explainer llm | 使用 OpenAI-compatible API 生成解释，输出到 `logs/deepseek_explained_audit.jsonl`。 |
| Dashboard source label | 已区分 `template-explained`、`llm-explained`、`scripted-llm`、`real-llm`、`mock-tools`。 |
| generate_demo_data 默认行为 | 默认只生成离线可重建日志，不再覆盖真实 LLM 证据日志。 |

## 2. 本轮发现的问题

### 2.1 离线演示生成会覆盖真实 API 证据

原问题：

```text
experiments/generate_demo_data.py 默认 include_real_llm=false，
但 DEFAULT_LOGS 中包含 logs/deepseek_miniagent_llm_audit.jsonl、
logs/deepseek_corecoder_real_audit.jsonl、logs/deepseek_explained_audit.jsonl。
_reset_demo_outputs 会清空所有 logs，因此离线演示可能误删真实 API 验证证据。
```

处理：

```text
默认只重置 miniagent、corecoder_scripted、template_explained、eval、manifest 和 outbox。
只有显式传入 --include-real-llm 时，才重置并生成 miniagent_real、corecoder_real、llm_explained。
```

### 2.2 template explainer 和 LLM explainer 路径混用

原问题：

```text
template explainer 和 DeepSeek LLM explainer 都使用 logs/deepseek_explained_audit.jsonl，
容易让 Dashboard 和报告误以为 template 解释来自真实 LLM。
```

处理：

```text
template explainer: logs/p2_explained_audit.jsonl
LLM explainer:      logs/deepseek_explained_audit.jsonl
```

### 2.3 Dashboard 来源标签不够细

原问题：

```text
Dashboard 只有 risk-explainer-deepseek，没有 template explainer 默认源。
```

处理：

```text
risk-explainer-template -> logs/p2_explained_audit.jsonl -> template-explained
risk-explainer-deepseek -> logs/deepseek_explained_audit.jsonl -> llm-explained
```

## 3. 验证结果

新增测试：

```text
test_generate_demo_data_offline_mode_preserves_real_llm_logs
```

验证命令：

```powershell
C:\Users\zx\.conda\envs\dl\python.exe -m unittest discover -s tests
```

结果：

```text
Ran 65 tests
OK
```

## 4. 当前边界结论

当前边界已经清楚：

```text
scripted = 可复现实验，不依赖网络。
llm/real = 真实 LLM 生成工具调用或解释，需要 API key。
mock outbox = 模拟业务外发，只写 logs/outbox，不做真实 SMTP/webhook/API。
template explainer = 本地解释，不是 LLM。
DeepSeek explainer = 真实 LLM 解释。
```

后续如果接真实 webhook / SMTP / API，应继续使用同一条安全链路：

```text
ToolCallEvent -> AgentGuardGateway -> ApprovalHandler -> Tool executor -> ResultInspector -> AuditLogger
```
