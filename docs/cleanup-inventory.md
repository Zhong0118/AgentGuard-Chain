# 阶段 A/B 清单

本文档补齐阶段 A 和阶段 B：

- 阶段 A：状态盘点，只确认文件角色和处理建议。
- 阶段 B：清理明显运行时产物，保留真实 API 验证证据。

## 1. 阶段 A：状态盘点

### 1.1 保留

这些是当前项目主线，继续保留。

| 路径 | 角色 | 说明 |
| --- | --- | --- |
| `agentguard_chain/` | 核心防护框架 | 网关、规则、风险评分、行为链、输入/结果审查、脱敏、审批、审计、解释器。 |
| `agents/miniagent/` | MiniAgent 原型 | 支持 scripted 和 LLM mode，用于证明真实 Agent loop。 |
| `agents/corecoder_guarded_runner.py` | CoreCoder guarded 入口 | 用于证明 AgentGuard 可接入真实开源 Agent 的工具执行链路。 |
| `agentguard_chain/adapter/corecoder_adapter.py` | CoreCoder 适配器 | 将 CoreCoder 工具调用转成 AgentGuard 可审查事件。 |
| `dashboard/app.py` | Dashboard | 展示审计日志、风险链、审批、outbox 和指标。 |
| `experiments/evaluate_p1_v2.py` | 消融评估 | 输出 baseline / input_only / tool_guard / full_guard 等对比指标。 |
| `experiments/generate_demo_data.py` | 演示数据生成 | 默认离线生成演示日志，可选真实 LLM。 |
| `experiments/explain_audit_log.py` | 风险解释生成 | template / LLM 两种解释模式。 |
| `datasets/p0_smoke_cases.jsonl` | P0 数据集 | 最小网关 smoke cases。 |
| `datasets/p1_scripted_cases.jsonl` | P1 数据集 | 约 200 条 scripted 对抗样本和正常样本。 |
| `datasets/fixtures/` | 测试夹具 | 用于结果审查、脱敏等测试。 |
| `tests/` | 测试 | 当前 62 个测试覆盖 P0/P1/P2 关键模块。 |
| `artifacts/demo/` | 固化演示证据 | 从 logs 中复制出的稳定审计日志。 |
| `artifacts/eval/` | 固化评估证据 | 固化评估结果。 |

### 1.2 整理

这些已经整理过或需要后续继续轻量整理。

| 路径 | 当前处理 |
| --- | --- |
| `docs/README.md` | 已作为文档入口。 |
| `docs/code-structure.md` | 已说明代码边界。 |
| `docs/validation.md` | 已合并 CoreCoder 和 DeepSeek 验证记录。 |
| `docs/runbook.md` | 已作为运行入口，后续可继续压缩过长内容。 |
| `docs/demo-script.md` | 保留为演示脚本。 |
| `docs/usage-and-demo-guide.md` | 保留为面向答辩/演示的使用手册。 |
| `docs/report-outline.md` | 保留为报告提纲，后续可发展成 final report。 |

### 1.3 可删除

这些是运行时或缓存产物，不应长期保留。

| 路径 | 原因 |
| --- | --- |
| `tmp/*` | 工具执行临时文件，已加入 `.gitignore`。 |
| `logs/p0_audit.jsonl` | P0 运行日志，可通过 `experiments/run_p0_cases.py` 重建。 |
| `logs/p1_miniagent_audit.jsonl` | P1 批量运行日志，已固化到 `artifacts/demo/`，也可重建。 |
| `logs/corecoder_guarded_audit.jsonl` | CoreCoder scripted 日志，已固化到 `artifacts/demo/`，也可重建。 |
| `logs/p1_v2_eval.json` | 评估结果，已固化到 `artifacts/eval/`，也可重建。 |
| `logs/p2_explained_audit.jsonl` | template 解释日志，可重建。 |
| `logs/p1_interactive_demo_audit.jsonl` | 交互演示运行日志，可重建。 |
| `logs/outbox/*.jsonl` | 本地 API/message/mail outbox，可重建。 |
| `__pycache__/` | Python 缓存，已被 `.gitignore` 忽略。 |

### 1.4 需要合并

这些不是马上改代码，而是后续文档收束时处理。

| 路径 | 建议 |
| --- | --- |
| `workflow.md` | 保留为项目设计总方案。 |
| `plan.md` | 后续可压缩为历史计划，或转入 `docs/archive/`。 |
| `docs/archive/p1-followup.md` | 已归档，不作为当前入口。 |
| `docs/archive/p1-p2.md` | 已归档，不作为当前入口。 |
| `docs/archive/corecoder-real-validation.md` | 已合并进 `docs/validation.md`，保留为原始记录。 |
| `docs/archive/deepseek-v4-flash-validation.md` | 已合并进 `docs/validation.md`，保留为原始记录。 |

### 1.5 暂不动

这些虽然可以继续优化，但当前不应在 A/B 阶段大动。

| 路径 | 原因 |
| --- | --- |
| `agents/CoreCoder/` | 第三方/开源 Agent 代码样本，后续只通过 adapter/runner 接入。 |
| `experiments/run_miniagent_cases.py` | 兼容包装入口，虽然薄，但文档和实验入口仍有用。 |
| `requirements.txt` | P2 新增依赖记录，后续 README 阶段统一整理。 |
| `logs/deepseek_miniagent_llm_audit.jsonl` | 真实 API 验证证据，本轮保留。 |
| `logs/deepseek_corecoder_real_audit.jsonl` | 真实 API 验证证据，本轮保留。 |
| `logs/deepseek_explained_audit.jsonl` | 真实 API 解释证据，本轮保留。 |

## 2. 阶段 B：清理结果

本轮清理策略：

```text
保留真实 API 证据日志。
删除可重建的运行时日志。
删除 tmp 中被误跟踪的临时脚本/文本。
不删除 artifacts 中的固化证据。
不删除源码、数据集、测试和文档。
```

已清理的运行时产物：

```text
logs/p0_audit.jsonl
logs/p1_miniagent_audit.jsonl
logs/corecoder_guarded_audit.jsonl
logs/p1_v2_eval.json
logs/p2_explained_audit.jsonl
logs/p1_interactive_demo_audit.jsonl
logs/outbox/api_call_log.jsonl
logs/outbox/mail_outbox.jsonl
logs/outbox/message_outbox.jsonl
tmp/p1_chain_047.sh
tmp/p1_chain_048.py
tmp/p1_chain_049.ps1
tmp/p1_chain_050.sh
tmp/p1_note.txt
```

保留的运行时证据日志：

```text
logs/deepseek_miniagent_llm_audit.jsonl
logs/deepseek_corecoder_real_audit.jsonl
logs/deepseek_explained_audit.jsonl
```

注意：稳定提交和报告引用优先使用 `artifacts/`，`logs/` 仍然是本地运行目录。
