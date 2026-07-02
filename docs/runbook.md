# AgentGuard-Chain 运行文档

本文档说明当前项目能如何运行、如何查看结果，以及哪些部分仍然只是设计入口。

当前阶段的真实状态：

```text
P0：安全网关核心已可运行。
P1：MiniAgent scripted 原型已接入 AgentGuard，并能批量评估样本。
P1+：CoreCoder guarded scripted demo 已可运行，不需要 API key。
P1+：CoreCoder guarded real LLM runner 已可运行，需要 API key。
P1+：工具结果内容审查和输出脱敏已接入 MiniAgent / CoreCoder guarded wrapper。
P1+：ask 审批流已支持 auto-deny / auto-allow / interactive，并写入审计日志。
CoreCoder：原生 CLI 不会自动接入 AgentGuard；必须使用 guarded runner 或修改执行入口。
LLM：当前 MiniAgent 不调用 LLM；CoreCoder guarded 支持 scripted 与 real 两种模式。
Dashboard：已有基础 Streamlit 页面和数据整理函数，但还未做最终演示打磨。
行为链：已同时输出 chain_alerts 和结构化 chain_graphs。
输入审查：InputInspector 已接入 MiniAgent 和 CoreCoder guarded wrapper。
```

## 1. 当前系统结构

### 1.1 AgentGuard 主链路

```text
ToolCallEvent
    ↓
AgentGuardGateway
    ↓
PolicyEngine
    ↓
ParameterChecker
    ↓
ChainDetector
    ↓
RiskScorer
    ↓
GuardDecision: allow / ask / deny
    ↓
ResultInspector / OutputRedactor 审查工具结果并脱敏
    ↓
AuditLogger 写入 JSONL
```

核心代码：

```text
agentguard_chain/event.py
agentguard_chain/gateway.py
agentguard_chain/guard/policy_engine.py
agentguard_chain/guard/parameter_checker.py
agentguard_chain/guard/chain_detector.py
agentguard_chain/guard/risk_scorer.py
agentguard_chain/audit/logger.py
```

### 1.2 MiniAgent 当前链路

MiniAgent 已经接入 AgentGuard，当前是 scripted mode，不调用 LLM。

```text
datasets/p1_scripted_cases.jsonl
    ↓
ScriptedPlanner
    ↓
MiniAgent.run()
    ↓
构造 ToolCallEvent
    ↓
AgentGuardGateway.evaluate(event)
    ↓
allow: 调用 MiniAgentTools
deny: 不执行工具
    ↓
ResultInspector 检查工具结果
    ↓
OutputRedactor 对敏感结果脱敏
    ↓
AuditLogger 写入 logs/*.jsonl
    ↓
MiniAgentSummary 汇总每一步结果
```

相关代码：

```text
agents/miniagent/agent.py
agents/miniagent/run_case.py
agents/miniagent/tools.py
datasets/p1_scripted_cases.jsonl
```

### 1.3 Mock tools 的定位

`agents/miniagent/tools.py` 中的工具是模拟业务工具，不是真实外部系统：

```text
read_file
write_file
delete_file
bash / run_command
call_api
send_message
send_mail
```

其中：

```text
call_api      只返回固定 JSON 字符串
send_message 写入内存列表，同时落盘到 logs/outbox/message_outbox.jsonl
send_mail    写入内存列表，同时落盘到 logs/outbox/mail_outbox.jsonl
```

这不是最终业务系统，而是为了满足 P1 的两个目标：

```text
1. 可复现地制造 API 越权、消息外发、邮件外发等工具调用场景。
2. 验证 AgentGuard 是否能在工具执行前 allow / deny。
```

后续如果要更真实，可以把这些 mock tools 替换为：

```text
本地 FastAPI mock server
HTTP API proxy
SMTP sandbox
文件系统沙箱
```

## 2. 运行 P0 样本

P0 用于验证最小安全网关是否可用。

在项目根目录运行：

```powershell
python -m experiments.run_p0_cases --dataset datasets/p0_smoke_cases.jsonl --audit-log logs/p0_audit.jsonl --workspace-root .
```

预期输出类似：

```json
{
  "total_cases": 10,
  "correct_cases": 10,
  "attack_detection_rate": 1.0,
  "false_positive_rate": 0.0,
  "false_negative_rate": 0.0
}
```

查看审计日志：

```powershell
Get-Content logs/p0_audit.jsonl
```

每一行是一条 JSONL 审计记录，包含：

```text
event      工具调用事件
decision   allow / ask / deny、风险分数、命中规则
execution  是否真正执行、结果预览
```

## 3. 运行 P1 MiniAgent scripted 原型

P1 当前最稳定的运行入口是 MiniAgent scripted mode。

```powershell
python -m agents.miniagent.run_case --dataset datasets/p1_scripted_cases.jsonl --audit-log logs/p1_miniagent_audit.jsonl --workspace-root .
```

默认审批模式是 `auto-deny`。如果要观察 `ask` 被批准后执行，可以显式切换：

```powershell
python -m agents.miniagent.run_case --dataset datasets/p1_scripted_cases.jsonl --audit-log logs/p1_miniagent_audit.jsonl --workspace-root . --approval-mode auto-allow
```

如果要在命令行里人工确认 `ask` 操作，可以使用：

```powershell
python -m agents.miniagent.run_case --dataset datasets/p1_scripted_cases.jsonl --audit-log logs/p1_miniagent_audit.jsonl --workspace-root . --approval-mode interactive
```

当命中 `ask` 时，终端会展示工具名、参数、风险类型和原因，并询问：

```text
Approve this tool call? [y/N]:
```

输入 `y` 或 `yes` 会执行工具；直接回车或输入其他内容会拒绝执行。

也可以用实验入口：

```powershell
python -m experiments.run_miniagent_cases --dataset datasets/p1_scripted_cases.jsonl --audit-log logs/p1_miniagent_audit.jsonl --workspace-root .
```

预期输出类似：

```json
{
  "total_calls": 61,
  "correct_calls": 61,
  "attack_cases": 35,
  "normal_cases": 26,
  "detected_attacks": 35,
  "false_positives": 0,
  "false_negatives": 0,
  "accuracy": 1.0,
  "attack_detection_rate": 1.0,
  "false_positive_rate": 0.0,
  "false_negative_rate": 0.0
}
```

P1 数据集覆盖：

```text
正常文件读取
敏感文件读取
路径越界
危险命令
正常命令
API 越权
正常 API
外部消息/邮件发送
敏感读取 -> 外发
写脚本 -> 执行脚本
工具结果敏感输出 -> 审查与脱敏
delete_file 中风险操作 -> ask -> approval
输入提示注入 -> input_findings 审计标注
```

## 4. 查看 P1 审计结果

审计日志默认写入：

```text
logs/p1_miniagent_audit.jsonl
```

查看前几条：

```powershell
Get-Content logs/p1_miniagent_audit.jsonl -TotalCount 5
```

统计行数：

```powershell
(Get-Content logs/p1_miniagent_audit.jsonl | Measure-Object -Line).Lines
```

如果使用当前 P1 数据集，应该是：

```text
61
```

其中 `P1_051` 是输出审查样本：读取包含假密钥的调试文件，工具调用前允许执行，但工具结果会被发现并脱敏。审计日志中不应出现原始假密钥值。

`P1_052` 是审批样本：`delete_file` 属于中风险不可逆操作，决策为 `ask`。默认 `auto-deny` 下不会执行删除，并在 `approval` 字段中记录 `user_denied`。

重点字段：

```text
event.tool_name
event.tool_args
decision.decision
decision.risk_score
decision.risk_level
decision.risk_types
decision.matched_rules
decision.chain_alerts
execution.executed
approval
output_findings
redaction
```

判断是否执行：

```text
execution.executed = true   工具已执行
execution.executed = false  工具被阻断
```

## 4.1 查看消息/邮件 outbox

P1-16 已把 MiniAgent 的消息和邮件外发工具从纯内存 mock 改成文件化 outbox。

允许执行的内部消息会写入：

```text
logs/outbox/message_outbox.jsonl
```

允许执行的内部邮件会写入：

```text
logs/outbox/mail_outbox.jsonl
```

每条 outbox 记录都有 `outbox_id`。工具执行结果和审计日志的 `execution.result_preview` 也会返回同一个 `outbox_id`，用于复盘时把：

```text
Agent 工具调用
    ↓
AuditRecord
    ↓
message/mail outbox
```

串起来。

注意：这仍然不会真实外发消息或邮件，`delivered=false` 表示它只是本地可审计队列。

## 5. 运行测试

运行全部测试：

```powershell
python -m unittest discover -s tests
```

当前应通过：

```text
Ran 47 tests
OK
```

这些测试覆盖：

```text
P0 网关
策略引擎
参数检查
风险评分
行为链检测
MiniAgent loop
CoreCoder adapter 与 guarded runner
Dashboard 多日志数据整理函数
工具结果审查与输出脱敏
审批流与结构化风险链图谱
输入审查与 input_findings 审计
P1 v2 消融评估
P0/P1 runner
```

## 5.1 运行 P1 v2 消融评估

P1 v2 用于对比不同防线组合的效果：

```powershell
python -m experiments.evaluate_p1_v2 --dataset datasets/p1_scripted_cases.jsonl --workspace-root . --output logs/p1_v2_eval.json
```

当前默认数据集结果摘要：

```text
baseline              detection=0.0000  fpr=0.0000  fnr=1.0000
input_only            detection=0.4000  fpr=0.0385  fnr=0.6000
tool_guard            detection=0.8571  fpr=0.0000  fnr=0.1429
tool_chain            detection=1.0000  fpr=0.0000  fnr=0.0000
tool_chain_result     detection=1.0000  fpr=0.0000  fnr=0.0000
full_guard            detection=1.0000  fpr=0.0000  fnr=0.0000
```

`full_guard` 额外记录：

```text
input_findings: 19
output_findings: 2
chain_graph_edges: 8
approval_required: 1
```

这说明输入审查不是主防线；工具调用前审查和行为链检测才是检测率提升的核心。

## 6. 运行 Dashboard

Dashboard 入口：

```powershell
$env:PYTHONUTF8="1"
streamlit run dashboard/app.py
```

如果当前 shell 无法识别 `streamlit` 命令，也可以运行：

```powershell
$env:PYTHONUTF8="1"
python -m streamlit run dashboard/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

启动成功后访问：

```text
http://127.0.0.1:8501
```

如果没有安装 Streamlit，会报：

```text
Streamlit is not installed. Install streamlit to run dashboard/app.py.
```

当前 Dashboard 默认会读取两类日志：

```text
logs/p1_miniagent_audit.jsonl
logs/corecoder_guarded_audit.jsonl
```

如果这两份日志都存在，当前示例数据应展示：

```text
总记录数：64
MiniAgent：61 条，source=miniagent-scripted，execution_mode=mock-tools
CoreCoder：3 条，source=corecoder-guarded-demo，execution_mode=scripted-llm
输入审查发现：19 条
行为链告警：8 条
行为链图谱边：8 条
输出审查发现：2 条
审批记录：1 条
```

页面展示：

```text
allow / ask / deny 数量
Agent / source 统计
工具调用时间线
输入审查发现
输出审查发现
审批记录
行为链告警
行为链图谱
```

当前 Dashboard 会显式标记：

```text
miniagent-scripted       execution_mode = mock-tools
corecoder-guarded-demo   execution_mode = scripted-llm
```

注意：Dashboard 当前是基础展示版，还没有做最终比赛展示样式和演示视频。

## 6.1 当前 mock/demo 状态清单

这部分很重要，后续进入 P2 或真实演示时不要忘记替换。

| 模块 | 当前状态 | 是否真实外部系统 | 后续替换方向 |
|---|---|---:|---|
| MiniAgent planner | `ScriptedPlanner` 读取 JSONL | 否 | 增加 LLM planner mode |
| MiniAgent `call_api` | 返回固定 JSON 字符串 | 否 | 本地 FastAPI mock server / API proxy |
| MiniAgent `send_message` | 写入 `logs/outbox/message_outbox.jsonl` | 否 | 本地消息队列 / webhook sandbox |
| MiniAgent `send_mail` | 写入 `logs/outbox/mail_outbox.jsonl` | 否 | SMTP sandbox |
| CoreCoder guarded scripted demo | `ScriptedCoreCoderLLM` 生成 tool_call | 否 | 离线稳定演示 |
| CoreCoder guarded real LLM runner | CoreCoder LLM 真实生成 tool_call | 是 | 需要 API key / base_url |
| Dashboard | 读取 JSONL 静态日志 | 半真实 | 加刷新、筛选、演示截图 |

当前这些 mock/demo 不是“没用”，它们的作用是：

```text
可复现地产生危险工具调用
验证 AgentGuard 是否能执行前阻断
生成稳定审计日志和评估指标
```

但它们不能替代：

```text
真实 LLM 生成 tool_call
真实业务 API/消息/邮件系统
生产级旁路监听
```

## 7. CoreCoder guarded scripted demo

当前已经可以运行无需 API key 的 CoreCoder guarded demo。

它使用脚本化 LLM 驱动 CoreCoder 的真实 `Agent.chat()` loop 产生 tool call，然后通过 `GuardedCoreCoderAgent` 在 `_exec_tool()` 前拦截。

CoreCoder guarded runner 也支持审批模式参数：

```powershell
python -m agents.corecoder_guarded_runner --demo normal-read --approval-mode auto-deny --audit-log logs/corecoder_guarded_audit.jsonl --workspace-root .
```

当前内置三个 CoreCoder demo 不触发 `ask`，但 wrapper 已经具备 `ask -> approval -> execute/block` 的处理能力。`--approval-mode interactive` 同样可用于 CoreCoder guarded runner。

入口：

```text
agents/corecoder_guarded_runner.py
```

### 7.1 正常文件读取

```powershell
$env:PYTHONUTF8="1"
python -m agents.corecoder_guarded_runner --demo normal-read --audit-log logs/corecoder_guarded_audit.jsonl --workspace-root .
```

预期：

```text
decision = allow
executed = true
```

### 7.2 敏感文件读取阻断

```powershell
$env:PYTHONUTF8="1"
python -m agents.corecoder_guarded_runner --demo sensitive-file --audit-log logs/corecoder_guarded_audit.jsonl --workspace-root .
```

预期：

```text
decision = deny
executed = false
matched_rules 包含 SENSITIVE_PATH
```

### 7.3 危险命令阻断

```powershell
$env:PYTHONUTF8="1"
python -m agents.corecoder_guarded_runner --demo dangerous-command --audit-log logs/corecoder_guarded_audit.jsonl --workspace-root .
```

预期：

```text
decision = deny
executed = false
matched_rules 包含 CMD_PIPE_TO_SHELL / NETWORK_NOT_ALLOWED / COMMAND_NOT_ALLOWED
```

查看 CoreCoder guarded 审计日志：

```powershell
Get-Content logs/corecoder_guarded_audit.jsonl
```

## 7.4 CoreCoder guarded real LLM runner

真实 LLM 模式会使用 CoreCoder 自带配置：

```text
OPENAI_API_KEY / CORECODER_API_KEY / DEEPSEEK_API_KEY
OPENAI_BASE_URL / CORECODER_BASE_URL
CORECODER_MODEL
CORECODER_PROVIDER
```

示例：

```powershell
$env:OPENAI_API_KEY="你的 API key"
$env:OPENAI_BASE_URL="https://api.deepseek.com"
$env:CORECODER_MODEL="deepseek-chat"
python -m agents.corecoder_guarded_runner --mode real --prompt "请总结 workflow.md" --audit-log logs/corecoder_real_guarded_audit.jsonl --workspace-root . --approval-mode auto-deny
```

如果希望真实 CoreCoder 工具调用遇到 `ask` 时暂停等待人工确认，可以把审批模式改成：

```powershell
python -m agents.corecoder_guarded_runner --mode real --prompt "请总结 workflow.md" --audit-log logs/corecoder_real_guarded_audit.jsonl --workspace-root . --approval-mode interactive
```

如果没有 API key，会输出清晰错误：

```json
{
  "mode": "real",
  "error": "No API key found. Set OPENAI_API_KEY, CORECODER_API_KEY, or DEEPSEEK_API_KEY."
}
```

重要区别：

```text
python -m agents.corecoder_guarded_runner --mode real ...
```

会创建真实 CoreCoder Agent，并用 `GuardedCoreCoderAgent` 包装 `_exec_tool()`，所以真实 LLM 产生的 tool_call 会进入 AgentGuard 审查。

而：

```text
python -m corecoder ...
```

仍然是 CoreCoder 原生 CLI，不会自动接入 AgentGuard。

## 8. CoreCoder 原生 CLI 当前如何运行

CoreCoder 原生 CLI 位于：

```text
agents/CoreCoder/corecoder/cli.py
```

如果只想运行未受保护的 CoreCoder，需要把工作目录切到 `agents/CoreCoder`，并保证依赖和 API key 可用。

示例：

```powershell
cd agents/CoreCoder
$env:OPENAI_API_KEY="你的 API key"
$env:CORECODER_MODEL="gpt-4o"
python -m corecoder -p "请总结当前项目"
```

或者使用 OpenAI-compatible 服务：

```powershell
cd agents/CoreCoder
$env:OPENAI_API_KEY="你的 API key"
$env:OPENAI_BASE_URL="https://api.deepseek.com"
$env:CORECODER_MODEL="deepseek-chat"
python -m corecoder -p "请总结当前项目"
```

重要限制：

```text
当前这样运行的是 CoreCoder 原生版本，不会自动调用 AgentGuard。
```

也就是说：

```text
python -m corecoder ...
```

和：

```text
python -m agents.corecoder_guarded_runner ...
```

是两条不同入口。

只有后者当前会经过 AgentGuard。

## 9. CoreCoder Guarded 适配器现在有什么用

当前适配器提供的是一种半嵌入式接入方式：

```text
CoreCoder tool_call
    ↓
GuardedCoreCoderAgent._exec_tool()
    ↓
转换为 ToolCallEvent
    ↓
AgentGuardGateway.evaluate(event)
    ↓
allow 才执行 tool.execute()
deny 直接阻断
    ↓
允许执行后的工具结果进入 ResultInspector / OutputRedactor
    ↓
脱敏结果再返回给 CoreCoder 后续上下文
```

它已经被 `agents/corecoder_guarded_runner.py` 使用，所以 guarded scripted demo 会生效。

但是它不会在 CoreCoder 原生 CLI 中自动生效。

要让它真正生效，后续必须做其中一种：

```text
方案 A：写 guarded_corecoder_runner.py
        在 runner 中创建 CoreCoder Agent，然后用 GuardedCoreCoderAgent 包装。

方案 B：修改 CoreCoder 源码中的 Agent._exec_tool()
        在 tool.execute 前插入 AgentGuardGateway。

方案 C：把 CoreCoder 工具注册表中的工具替换为 GuardedTool wrapper。

方案 D：做旁路监听/日志模式
        只能事后审计，不能保证执行前阻断。
```

当前项目已经实现方案 A 的 scripted demo 和 real LLM runner 版本。

如果要接真实 LLM，应沿用方案 A：

```text
创建真实 CoreCoder Agent
    ↓
用 GuardedCoreCoderAgent 包装
    ↓
调用 guarded.chat(prompt)
    ↓
所有工具调用自动进入 AgentGuard
```

## 10. LLM 当前是否介入

当前状态：

```text
MiniAgent scripted mode：不介入 LLM。
CoreCoder 原生运行：会介入 LLM。
CoreCoder guarded scripted demo：使用脚本化 LLM，不需要 API key。
CoreCoder guarded real LLM runner：会介入真实 LLM，需要 API key。
```

为什么 MiniAgent 先不接 LLM：

```text
1. P1 需要稳定评估安全网关，scripted mode 更可复现。
2. 检测率、误报率、漏报率需要固定样本，不适合依赖随机 LLM 输出。
3. LLM 应该用来生成工具调用或解释风险，而不是作为高危操作的唯一放行依据。
```

后续 LLM 应该放到两处：

```text
1. MiniAgent llm mode
   LLM 根据用户输入生成 tool_calls，再交给 AgentGuard 审查。

2. CoreCoder guarded demo
   CoreCoder 使用真实 LLM 产生工具调用，AgentGuard 在执行前拦截。
```

## 11. 当前 P1 还缺什么

P1 核心工程闭环已经完成，但还不是最终展示级。

还需要补：

```text
1. Dashboard 启动验证
   确认 Streamlit 可运行，并准备截图或演示。

2. 更真实的 mock business tools
   可选：用本地 HTTP server 或文件队列模拟 API/message/mail。

3. 运行说明继续补充
   尤其是 CoreCoder guarded demo 和 Dashboard 演示流程。
```

## 12. 下一步应该继续 P1 还是开始 P2

建议：先继续补 P1，不要马上进入 P2。

理由：

```text
P2 是 MiniAgent LLM mode、解释器、报告/PPT 等加分项。
P1 里 CoreCoder guarded real LLM runner 已完成，Dashboard 展示仍需要比赛演示打磨。
如果现在直接做 P2，项目会变成“MiniAgent scripted 很完整，但真实 Agent 接入偏虚”。
```

推荐顺序：

```text
P1+ 第一步：实现 guarded_corecoder_runner.py（已完成 scripted demo）
P1+ 第二步：准备 CoreCoder 演示样例和日志（已完成 scripted demo）
P1+ 第三步：CoreCoder guarded real LLM runner（已完成，需要 API key 才能真实运行）
P1+ 第四步：验证 Dashboard 能展示 CoreCoder/MiniAgent 日志
P1+ 第五步：CLI interactive approval（已完成），把 ask 从自动模式扩展到人工确认
P2 第一步：MiniAgent llm mode 或 LLM risk explainer
P2 第二步：Web pending approval
P2 第三步：报告和 PPT
```

一句话：

```text
先把 P1 的展示和确认交互补实，再开始 P2。
```
