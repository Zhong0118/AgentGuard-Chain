# 代码结构说明

本文档用于回答“哪些代码是正式框架、哪些是 MiniAgent / CoreCoder 演示、哪些是实验脚本”。当前项目不建议为了命名整齐做大规模重命名；更重要的是保持边界清晰。

## 1. 核心原则

AgentGuard-Chain 的代码分成四层：

```text
可复用防护框架
    ↓
Agent 适配与演示
    ↓
实验评估脚本
    ↓
Dashboard / 文档 / 产物
```

其中安全边界不在输入 prompt 处，而在 Agent 生成工具调用之后、工具真实执行之前。

```text
Agent planner / LLM
    ↓
ToolCallEvent
    ↓
AgentGuardGateway
    ↓
allow / ask / deny
    ↓
Tool executor
    ↓
ResultInspector / OutputRedactor
    ↓
AuditLogger
```

## 2. 可复用防护框架

目录：`agentguard_chain/`

| 文件 | 作用 |
| --- | --- |
| `event.py` | 定义 `TaskScope`、`ToolCallEvent`、`GuardDecision`、`AuditRecord`，是跨 Agent 的统一数据结构。 |
| `gateway.py` | 防护入口，编排规则检测、行为链检测和风险评分。 |
| `guard/policy_engine.py` | 单步工具调用策略检查。 |
| `guard/parameter_checker.py` | 路径、命令、网络、外发等参数级检测。 |
| `guard/chain_detector.py` | 跨步骤行为链检测，例如写脚本后执行、敏感读取后外发。 |
| `guard/risk_scorer.py` | 把规则命中转换成 `allow / ask / deny`。 |
| `guard/input_inspector.py` | 用户输入和外部文本的风险标注，属于辅助防线。 |
| `guard/result_inspector.py` | 工具结果内容审查。 |
| `guard/output_redactor.py` | 输出脱敏。 |
| `approval/handler.py` | `ask` 决策的人机确认处理，支持自动拒绝、自动允许、交互确认。 |
| `audit/logger.py` | 写入 JSONL 审计日志。 |
| `explainer.py` | 风险解释器，支持模板解释和 OpenAI-compatible LLM 解释；不参与硬决策。 |

这部分是后续做 Python 库化时最应该保留下来的公共 API。

## 3. Agent 适配与演示

目录：`agents/`

| 文件 | 作用 |
| --- | --- |
| `agents/miniagent/agent.py` | MiniAgent 核心循环：planner -> guard -> approval -> tool executor -> result inspection -> audit -> summary。 |
| `agents/miniagent/llm_planner.py` | OpenAI-compatible LLM planner，只允许模型返回 JSON `tool_calls`。 |
| `agents/miniagent/tools.py` | MiniAgent 的本地工具集合，包括文件读写、命令执行、本地 API/message/mail outbox。 |
| `agents/miniagent/run_case.py` | MiniAgent CLI 主入口，支持 `scripted` 和 `llm` 两种模式。 |
| `agents/corecoder_guarded_runner.py` | CoreCoder guarded 入口，证明真实开源 Agent 可以在工具执行前接入 AgentGuard。 |
| `agentguard_chain/adapter/corecoder_adapter.py` | CoreCoder 工具调用适配器，把 CoreCoder 的工具调用转成 AgentGuard 可审查的事件。 |

注意：

```text
CoreCoder 原生 CLI 不会自动接入 AgentGuard。
必须使用 agents.corecoder_guarded_runner，或者在 CoreCoder 工具执行入口加入 GuardedCoreCoderAgent。
```

MiniAgent 工具边界：

```text
read_file / write_file / delete_file / bash 属于本地真实工具。
send_message / send_mail / call_api 目前是本地 outbox，只写入 logs/outbox/*.jsonl。
本地 outbox 的目的不是伪装成真实业务系统，而是安全展示“外发动作会被审计、阻断或记录”。
后续如果要接真实 webhook / SMTP / API，应优先保留同样的 ToolCallEvent 和 AgentGuardGateway 链路。
```

## 4. 实验与评估脚本

目录：`experiments/`

| 文件 | 作用 |
| --- | --- |
| `run_p0_cases.py` | P0 smoke cases 评估入口，只验证最小规则网关。 |
| `run_miniagent_cases.py` | MiniAgent 批量运行兼容入口，内部调用 `agents/miniagent/run_case.py`。 |
| `evaluate_p1_v2.py` | 消融评估入口，对比 baseline、input_only、tool_guard、tool_chain、full_guard。 |
| `expand_p1_dataset.py` | 扩充 P1 scripted 数据集。 |
| `explain_audit_log.py` | 读取审计日志并生成风险解释。 |
| `generate_demo_data.py` | 生成干净的演示日志和 manifest。默认离线运行，只有 `--include-real-llm` 才调用真实 API。 |

这些脚本用于实验、评估和演示，不应承载核心安全逻辑。

## 5. 展示层与产物

| 路径 | 作用 |
| --- | --- |
| `dashboard/app.py` | Streamlit Dashboard，读取审计日志并展示指标、风险链、审批记录和 outbox。 |
| `datasets/` | 对抗样本和测试样本。 |
| `artifacts/demo/` | 固化演示审计日志。 |
| `artifacts/eval/` | 固化评估结果。 |
| `logs/` | 本地运行时日志，已被 `.gitignore` 忽略。 |
| `tmp/` | 工具执行临时文件，已被 `.gitignore` 忽略。 |

## 6. 当前不建议做的重命名

暂时不建议重命名这些文件：

```text
agents/miniagent/run_case.py
experiments/run_miniagent_cases.py
agents/corecoder_guarded_runner.py
```

原因：

```text
它们已被测试和文档引用。
当前名称虽然不是最漂亮，但职责已能表达。
强行重命名会带来低收益的 import 和文档 churn。
```

后续如果要库化发布，可以再新增更稳定的命令入口，例如：

```text
agentguard-miniagent
agentguard-corecoder-demo
agentguard-eval
agentguard-dashboard
```
