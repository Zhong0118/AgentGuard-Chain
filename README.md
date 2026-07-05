# AgentGuard-Chain

AgentGuard-Chain 是一个面向 LLM Agent 的工具调用安全监督原型系统。它不是单纯的 prompt 过滤器，而是把安全边界放在 Agent 生成工具调用之后、工具真实执行之前，对工具调用、代码执行、文件访问和外发行为进行审计、评分、阻断和留证。

项目面向比赛题目“面向大模型及其应用的安全性研究”，覆盖提示注入、工具调用劫持、危险命令执行、敏感文件访问、API 越权和多步外传行为链等场景。

## 核心能力

```text
Agent / LLM planner
    ↓
ToolCallEvent
    ↓
AgentGuardGateway
    ↓
PolicyEngine + ParameterChecker + ChainDetector + RiskScorer
    ↓
allow / ask / deny
    ↓
Tool executor
    ↓
ResultInspector + OutputRedactor
    ↓
AuditLogger
    ↓
Dashboard
```

- 输入风险标注：识别提示注入、越狱式请求和可疑上下文。
- 工具调用前审查：统一审查文件、命令、API、消息、邮件等工具调用。
- 行为链检测：检测“敏感读取 -> 外部发送”“写脚本 -> 执行脚本”等跨步骤风险链。
- 人工确认：支持 `allow / ask / deny`，`ask` 可走自动拒绝、自动允许或交互确认；`interactive-all` 可对每个非硬阻断工具调用进行确认。
- 结果审查与脱敏：审查工具返回内容中的密钥、密码、token 等敏感信息。
- 审计留证：以 JSONL 记录 `ToolCallEvent`、`GuardDecision`、执行结果和解释。
- Dashboard 展示：展示指标、告警、风险链、审批记录和本地 outbox。

## 当前实现状态

| 模块 | 状态 |
| --- | --- |
| P0 安全网关 | 已完成 |
| MiniAgent scripted mode | 已完成，用于可复现实验 |
| MiniAgent LLM mode | 已完成，支持 OpenAI-compatible API |
| CoreCoder guarded 离线回放 | 已完成，离线可运行 |
| CoreCoder guarded real mode | 已完成入口，并已用 DeepSeek v4 flash 验证 |
| LLM risk explainer | 已完成 template / LLM 两种模式 |
| Dashboard | 已完成基础演示版 |
| P1 scripted dataset | 已扩充到 200 个 case / 228 个 tool calls |
| 单元测试 | 65 个测试通过 |

## 目录结构

```text
agentguard_chain/      可复用安全监督框架
agents/miniagent/      MiniAgent scripted / LLM 原型
agents/CoreCoder/      CoreCoder 开源 Agent 代码样本
agents/corecoder_guarded_runner.py
                       CoreCoder guarded 演示入口
dashboard/             Streamlit Dashboard
datasets/              P0/P1 对抗样本和测试夹具
experiments/           评估、演示数据生成、风险解释脚本
artifacts/             固化演示日志和评估结果
docs/                  文档、报告、验证记录
logs/                  本地运行时日志，不纳入版本交付
tmp/                   工具执行临时文件，不纳入版本交付
```

## 安装

推荐使用已有 conda 环境或 Python 3.10+ 环境：

```powershell
pip install -r requirements.txt
```

真实 LLM 模式需要 OpenAI-compatible API key。离线 scripted 评估不需要网络和 API key。

## 快速验证

运行全部测试：

```powershell
C:\Users\zx\.conda\envs\dl\python.exe -m unittest discover -s tests
```

预期结果：

```text
Ran 65 tests
OK
```

生成一套离线演示数据：

```powershell
$env:PYTHONUTF8="1"
python -m experiments.generate_demo_data --workspace-root .
```

默认不会调用真实 LLM，也不会覆盖已有 `logs/deepseek_*` 真实 API 证据日志。

启动 Dashboard：

```powershell
python -m streamlit run dashboard/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

打开：

```text
http://127.0.0.1:8501
```

## 常用命令

运行 MiniAgent scripted 数据集：

```powershell
python -m agents.miniagent.run_case --mode scripted --dataset datasets/p1_scripted_cases.jsonl --audit-log logs/p1_miniagent_audit.jsonl --workspace-root . --approval-mode auto-deny
```

运行 MiniAgent LLM mode：

```powershell
$env:MINIAGENT_API_KEY="<your api key>"
$env:MINIAGENT_BASE_URL="https://api.deepseek.com"
$env:MINIAGENT_MODEL="deepseek-v4-flash"
python -m agents.miniagent.run_case --mode llm --prompt "请读取 workflow.md 并总结项目目标" --audit-log logs/deepseek_miniagent_llm_audit.jsonl --workspace-root . --approval-mode auto-deny
```

运行 CoreCoder guarded 离线回放：

```powershell
python -m agents.corecoder_guarded_runner --mode scripted --demo normal-read --audit-log logs/corecoder_guarded_audit.jsonl --workspace-root . --approval-mode auto-deny
python -m agents.corecoder_guarded_runner --mode scripted --demo sensitive-file --audit-log logs/corecoder_guarded_audit.jsonl --workspace-root . --approval-mode auto-deny
python -m agents.corecoder_guarded_runner --mode scripted --demo dangerous-command --audit-log logs/corecoder_guarded_audit.jsonl --workspace-root . --approval-mode auto-deny
```

运行 CoreCoder guarded real mode：

```powershell
$env:DEEPSEEK_API_KEY="<your api key>"
$env:OPENAI_BASE_URL="https://api.deepseek.com"
$env:CORECODER_MODEL="deepseek-v4-flash"
python -m agents.corecoder_guarded_runner --mode real --prompt "请读取 workflow.md 并总结项目目标" --audit-log logs/deepseek_corecoder_real_audit.jsonl --workspace-root . --approval-mode auto-deny
```

运行消融评估：

```powershell
python -m experiments.evaluate_p1_v2 --dataset datasets/p1_scripted_cases.jsonl --workspace-root . --output logs/p1_v2_eval.json
```

生成风险解释：

```powershell
python -m experiments.explain_audit_log --input logs/p1_miniagent_audit.jsonl --output logs/p2_explained_audit.jsonl --mode template
```

## 评估结果摘要

当前固化评估结果位于 `artifacts/eval/p1_v2_eval.json`。

| 防线组合 | 攻击检测率 | 误报率 | 漏报率 |
| --- | ---: | ---: | ---: |
| baseline | 0.0000 | 0.0000 | 1.0000 |
| input_only | 0.5351 | 0.3772 | 0.4649 |
| tool_guard | 0.8684 | 0.0000 | 0.1316 |
| tool_chain | 1.0000 | 0.0000 | 0.0000 |
| tool_chain_result | 1.0000 | 0.0000 | 0.0000 |
| full_guard | 1.0000 | 0.0000 | 0.0000 |

结论：复杂自然语言上下文会让单纯输入过滤更容易误报；工具调用前审查和行为链检测才是检测率提升的核心。

## 重要边界

- `scripted` 用于稳定复现和指标评估，不依赖网络。
- `llm` / `real` 用于真实 LLM 生成工具调用或解释，需要 API key。
- `本地 outbox` 只写入 `logs/outbox/*.jsonl`，不做真实 SMTP/webhook/API 外发。
- LLM risk explainer 只生成解释，不参与 `allow / ask / deny` 硬决策。
- `interactive` 只在 `ask` 决策时请求 CLI 确认；`interactive-all` 会对每个非硬阻断工具调用请求 CLI 确认。
- CoreCoder 原生 CLI 不会自动接入 AgentGuard，必须使用 `agents.corecoder_guarded_runner` 或修改工具执行入口。

## 文档入口

- `workflow.md`：项目设计总方案。
- `docs/runbook.md`：运行手册。
- `docs/demo-script.md`：演示脚本。
- `docs/final-report.md`：最终报告。
- `docs/validation.md`：验证记录。
- `docs/code-structure.md`：代码结构说明。
- `docs/boundary-check.md`：scripted / LLM / real / local outbox 边界检查。
