# AgentGuard-Chain 演示脚本

本文档用于比赛答辩、录屏和自测。按顺序执行即可复现当前项目的核心能力。

---

## 0. 演示目标

演示时只讲一条主线：

```text
Agent 产生工具调用
    ↓
AgentGuard 执行前审查
    ↓
allow / ask / deny
    ↓
工具执行或阻断
    ↓
工具结果审查与脱敏
    ↓
行为链与业务 outbox 留证
    ↓
Dashboard 展示
```

不要把项目讲成“提示词过滤器”。重点是工具调用、代码执行和文件访问审计。

---

## 1. 演示前准备

在项目根目录执行：

```powershell
$env:PYTHONUTF8="1"
python -m unittest discover -s tests
```

预期：

```text
Ran 55 tests
OK
```

如果只想快速生成一套干净演示数据，可以直接运行：

```powershell
$env:PYTHONUTF8="1"
python -m experiments.generate_demo_data --workspace-root .
```

这会重建：

```text
logs/p1_miniagent_audit.jsonl
logs/corecoder_guarded_audit.jsonl
logs/p1_v2_eval.json
logs/p2_explained_audit.jsonl
logs/demo_manifest.json
logs/outbox/*.jsonl
```

当前已经固化过一份演示证据：

```text
artifacts/demo/
artifacts/eval/
```

录屏或报告截图可以优先参考 `artifacts/README.md` 中列出的产物。

如果要同时调用真实 DeepSeek/OpenAI-compatible API，再显式加：

```powershell
python -m experiments.generate_demo_data --workspace-root . --include-real-llm
```

注意：`--include-real-llm` 只从环境变量读取 API key，不会把 key 写入文件。

真实 LLM 证据日志单独写入：

```text
logs/deepseek_miniagent_llm_audit.jsonl
logs/deepseek_corecoder_real_audit.jsonl
logs/deepseek_explained_audit.jsonl
```

---

## 2. 生成 MiniAgent 审计日志

清空旧日志，避免演示数据混在一起：

```powershell
Clear-Content -Path logs\p1_miniagent_audit.jsonl
if (Test-Path logs\outbox\api_call_log.jsonl) { Clear-Content -Path logs\outbox\api_call_log.jsonl }
if (Test-Path logs\outbox\message_outbox.jsonl) { Clear-Content -Path logs\outbox\message_outbox.jsonl }
if (Test-Path logs\outbox\mail_outbox.jsonl) { Clear-Content -Path logs\outbox\mail_outbox.jsonl }
```

运行数据集：

```powershell
$env:PYTHONUTF8="1"
python -m agents.miniagent.run_case --dataset datasets/p1_scripted_cases.jsonl --audit-log logs/p1_miniagent_audit.jsonl --workspace-root . --approval-mode auto-deny
```

讲解要点：

```text
MiniAgent scripted mode 不调用 LLM，是为了可复现实验。
真实安全边界不在 prompt，而在每一次工具调用前。
```

预期输出：

```text
attack_detection_rate = 1.0
false_positive_rate = 0.0
false_negative_rate = 0.0
```

---

## 3. 生成 CoreCoder guarded 离线回放日志

```powershell
Clear-Content -Path logs\corecoder_guarded_audit.jsonl
$env:PYTHONUTF8="1"
python -m agents.corecoder_guarded_runner --mode scripted --demo normal-read --audit-log logs/corecoder_guarded_audit.jsonl --workspace-root . --approval-mode auto-deny
python -m agents.corecoder_guarded_runner --mode scripted --demo sensitive-file --audit-log logs/corecoder_guarded_audit.jsonl --workspace-root . --approval-mode auto-deny
python -m agents.corecoder_guarded_runner --mode scripted --demo dangerous-command --audit-log logs/corecoder_guarded_audit.jsonl --workspace-root . --approval-mode auto-deny
```

讲解要点：

```text
CoreCoder 原生 CLI 不自动接入 AgentGuard。
guarded runner 通过 GuardedCoreCoderAgent 包装工具执行入口。
scripted 离线回放不需要 API key，适合稳定演示。
```

预期：

```text
normal-read       allow
sensitive-file    deny
dangerous-command deny
```

---

## 4. 可选演示 MiniAgent LLM mode

MiniAgent LLM mode 用于证明系统不只是回放 JSONL，也可以由真实 LLM 生成工具调用。

配置：

```powershell
$env:MINIAGENT_API_KEY="你的 API key"
$env:MINIAGENT_BASE_URL="https://api.openai.com/v1"
$env:MINIAGENT_MODEL="gpt-4o-mini"
```

运行：

```powershell
$env:PYTHONUTF8="1"
python -m agents.miniagent.run_case --mode llm --prompt "请读取 workflow.md 并总结" --audit-log logs/p2_miniagent_llm_audit.jsonl --workspace-root . --approval-mode auto-deny
```

讲解：

```text
LLMPlanner 要求模型只输出 JSON tool_calls。
MiniAgent 不直接信任 LLM 输出，每个 tool_call 仍进入 AgentGuard 审查。
LLM mode 用于真实 Agent 演示，不用于检测率评估。
```

如果没有 API key，可以展示：

```powershell
python -m agents.miniagent.run_case --mode llm --prompt "hello" --audit-log logs/p2_miniagent_llm_audit.jsonl --workspace-root .
```

预期：

```json
{
  "mode": "llm",
  "error": "No API key found. Set MINIAGENT_API_KEY, OPENAI_API_KEY, or DEEPSEEK_API_KEY."
}
```

---

## 5. 运行消融评估

```powershell
$env:PYTHONUTF8="1"
python -m experiments.evaluate_p1_v2 --dataset datasets/p1_scripted_cases.jsonl --workspace-root . --output logs/p1_v2_eval.json
```

讲解重点：

```text
baseline：默认全部放行
input_only：只做输入检查
tool_guard：工具调用前审查
tool_chain：加入行为链检测
full_guard：输入、工具、行为链、结果、审批完整闭环
```

答辩时强调：

```text
输入过滤不是主防线。
Agent 安全的关键是工具执行前拦截和跨步骤行为链检测。
```

---

## 6. 启动 Dashboard

```powershell
$env:PYTHONUTF8="1"
python -m streamlit run dashboard/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

打开：

```text
http://127.0.0.1:8501
```

如果 Streamlit 未安装，先按项目环境安装依赖后再运行。

如果要展示风险解释，可以先生成解释后的日志：

```powershell
python -m experiments.explain_audit_log --input logs/p1_miniagent_audit.jsonl --output logs/p2_explained_audit.jsonl --mode template
```

然后在 Dashboard 的 MiniAgent audit log 输入框中填入：

```text
logs/p2_explained_audit.jsonl
```

---

## 7. Dashboard 展示顺序

### 7.1 顶部统计

展示：

```text
Records
Allowed
Asked
Denied
Real LLM Calls
Risk Explanations
Chain Alerts
Output Findings
Approvals
Business Outbox
```

讲解：

```text
这里是所有 Agent 工具调用审计记录的聚合。
Real LLM Calls 用于证明 MiniAgent / CoreCoder 已经接过真实模型。
Risk Explanations 只用于展示解释，不参与安全决策。
```

### 7.2 左侧筛选

建议依次筛选：

```text
source = corecoder-deepseek-real
source = risk-explainer-deepseek
decision = deny
risk_level = critical
With explanations
With chain alerts
```

讲解：

```text
Dashboard 不是控制台，只是审计展示层。
筛选用于快速定位真实 LLM 调用、阻断记录、解释记录和行为链。
```

### 7.3 Tool Call Timeline

挑 3-4 条讲：

```text
正常 read_file -> allow
读取 .env -> deny
危险 bash -> deny
CoreCoder real LLM -> glob/read_file -> allow
```

需要指出字段：

```text
tool
decision
risk_level
matched_rules
executed
result_preview
```

### 7.4 Audit Detail

讲：

```text
单条详情把 event、decision、execution、approval、chain_graphs 和 llm_explanation 合在一起。
答辩时可以用这一屏讲清“Agent 想做什么、系统为什么拦或放、是否执行、留下了什么证据”。
```

### 7.5 Input Findings

讲：

```text
输入审查只是辅助标注，不是最终安全边界。
```

### 7.6 Output Findings

展示：

```text
工具结果里包含假 API key
ResultInspector 发现敏感输出
OutputRedactor 脱敏
```

### 7.7 Approval Records

讲：

```text
delete_file 属于中风险操作，进入 ask。
auto-deny 模式下不执行。
interactive 模式下可由用户确认。
```

### 7.8 Behavior Chain Alerts / Graphs

讲两类链：

```text
SensitiveReadToExternalSend
WriteScriptToExecute
```

强调：

```text
单步看似普通的操作，组合起来可能构成高风险链。
```

### 7.9 Risk Explanations

讲：

```text
这里展示的是 LLM/template risk explainer 生成的中文解释。
解释只用于审计和答辩说明，不参与 allow / ask / deny 决策。
```

### 7.10 Business Tool Outbox

展示：

```text
api_call_log.jsonl
message_outbox.jsonl
mail_outbox.jsonl
```

讲解：

```text
允许执行的本地业务工具不会真实外发，而是进入本地 outbox。
这让业务侧效果也能审计。
```

---

## 8. 单独演示 ask 人工确认

运行：

```powershell
$env:PYTHONUTF8="1"
python -m agents.miniagent.run_case --dataset datasets/p1_scripted_cases.jsonl --audit-log logs/p1_interactive_demo_audit.jsonl --workspace-root . --approval-mode interactive
```

当出现：

```text
Approve this tool call? [y/N]:
```

输入：

```text
n
```

讲解：

```text
ask 是中风险操作的人机确认机制。
拒绝后 execution.executed=false。
```

---

## 9. 可选：CoreCoder real LLM

如果有 API key：

```powershell
$env:OPENAI_API_KEY="你的 API key"
$env:OPENAI_BASE_URL="https://api.deepseek.com"
$env:CORECODER_MODEL="deepseek-v4-flash"
python -m agents.corecoder_guarded_runner --mode real --prompt "请总结 workflow.md" --audit-log logs/deepseek_corecoder_real_audit.jsonl --workspace-root . --approval-mode auto-deny
```

如果没有 API key，展示 scripted 离线回放即可。不要现场强行连真实网络。

阶段二验证记录见：

```text
docs/validation.md
```

讲解口径：

```text
scripted 离线回放用于稳定复现 CoreCoder 工具执行前拦截；
real mode 用于真实 LLM 生成 tool_call 的演示；
当前环境没有 API key 时，只展示无 key 清晰失败，不伪造真实联网结果。
```

---

## 10. 推荐截图清单

```text
1. MiniAgent 运行结果
2. CoreCoder guarded 三个 demo 输出
3. P1 v2 消融评估结果
4. Dashboard 顶部统计
5. Dashboard source/decision/risk 筛选
6. Tool Call Timeline
7. Audit Detail 单条详情
8. Risk Explanations
9. Output Findings
10. Approval Records
11. Behavior Chain Graphs
12. Business Tool Outbox
```

---

## 11. 答辩口径

一句话版本：

```text
AgentGuard-Chain 是一个位于 Agent 与外部工具之间的行为监督层，通过统一 ToolCallEvent、TaskScope 权限收敛、工具调用前审查、行为链检测和审计展示，实现对文件访问、代码执行和业务工具调用的实时异常判定。
```

如果被问为什么不用纯输入过滤：

```text
因为 Agent 的真实风险发生在工具调用和多步行为链上。
输入过滤只能发现明显恶意文本，不能证明工具没有越权执行。
```

如果被问为什么使用 scripted MiniAgent：

```text
scripted dataset 用于可复现实验和指标评估，CoreCoder guarded 离线回放用于展示真实 Agent loop 的适配能力。
```

如果被问为什么不真实外发邮件：

```text
比赛原型需要本地业务工具和安全审计，不需要真实外发。当前 outbox 设计能保留业务侧证据，同时避免演示环境产生真实外部影响。
```
