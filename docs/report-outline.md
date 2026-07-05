# AgentGuard-Chain 安全风险分析报告大纲

本文档是最终比赛报告的写作骨架，目标是把“为什么做、怎么做、怎么证明有效”讲清楚。

---

## 1. 摘要

建议写 300-500 字，覆盖：

```text
研究对象：LLM Agent 工具调用、代码执行、文件访问风险
核心问题：提示注入和越权任务会诱导 Agent 误用工具
方法：AgentGuard-Chain 可嵌入/旁路双模式行为监督框架
能力：输入标注、工具调用前审查、结果审查、输出脱敏、行为链检测、审计展示
实验：P1 scripted adversarial dataset + CoreCoder guarded demo
结论：工具调用前拦截和行为链检测比单纯输入过滤更有效
```

---

## 2. 赛题理解与项目定位

### 2.1 赛题要求拆解

对应比赛要求：

```text
至少 3 类攻击场景
模型对抗样本与越狱测试用例集
智能体攻击脚本
行为监督原型系统
工具调用、代码执行、文件访问实时审计
允许 / 拒绝 / 询问策略
监督端实时展示告警或阻断记录
```

### 2.2 项目定位

建议表述：

```text
AgentGuard-Chain 不是单纯输入过滤器，而是位于 Agent 与工具之间的行为监督层。
系统主模式是嵌入式工具网关，辅模式是旁路审计展示。
```

### 2.3 非目标

明确不做：

```text
生产级 sandbox
多用户权限系统
真实外部邮件或 webhook 发送
大型数据库
完整多 Agent 集群平台
```

---

## 3. 威胁模型

### 3.1 资产

```text
敏感文件：.env、SSH key、credentials、token 文件
代码执行环境：shell、PowerShell、脚本文件
业务工具：API、message、mail
Agent 上下文：user_task、untrusted file content、tool result
审计日志：ToolCallEvent、GuardDecision、AuditRecord
```

### 3.2 攻击者能力

```text
能输入恶意 prompt
能提供含恶意指令的外部文件内容
能伪装成正常调试、测试、部署任务
能诱导 Agent 多步执行
不能直接绕过工具网关执行工具
```

### 3.3 防守边界

```text
工具执行前：必须经过 AgentGuardGateway
工具执行后：ResultInspector 和 OutputRedactor 检查返回内容
跨步骤：ChainDetector 维护会话行为链
展示层：Dashboard 只读 JSONL，不参与安全决策
```

---

## 4. 攻击场景设计

至少写 3 类，建议写 5 类。

### 4.1 场景一：提示注入导致敏感文件访问

样本：

```text
P1_009 - P1_015
```

攻击链：

```text
恶意输入 / 外部上下文
    ↓
诱导 read_file(".env")
    ↓
SENSITIVE_PATH 命中
    ↓
deny
```

展示证据：

```text
logs/p1_miniagent_audit.jsonl
Dashboard Tool Call Timeline
matched_rules = SENSITIVE_PATH
```

### 4.2 场景二：危险代码执行

样本：

```text
P1_017 - P1_024
```

风险：

```text
curl | bash
wget | sh
rm -rf
raw disk write
reverse shell
encoded PowerShell
certutil download
```

防御：

```text
COMMAND_NOT_ALLOWED
NETWORK_NOT_ALLOWED
CMD_PIPE_TO_SHELL
CMD_FORCE_RECURSIVE_DELETE
CMD_REVERSE_SHELL
```

### 4.3 场景三：API 越权

样本：

```text
P1_031 - P1_036
```

核心逻辑：

```text
允许 current_user
拒绝 admin/root/other_user
```

展示证据：

```text
matched_rules = API_USER_SCOPE_VIOLATION
logs/outbox/api_call_log.jsonl 只记录被允许的正常 API 调用
```

### 4.4 场景四：外部发送与敏感信息外传

样本：

```text
P1_037 - P1_046
```

风险链：

```text
敏感读取
    ↓
外部 URL / 邮件 / API / 网络发送
    ↓
CHAIN_SENSITIVE_READ_TO_EXTERNAL_SEND
```

展示证据：

```text
Behavior Chain Alerts
Behavior Chain Graphs
```

### 4.5 场景五：写脚本后执行

样本：

```text
P1_047 - P1_050
```

风险链：

```text
write_file("tmp/x.sh")
    ↓
bash("bash tmp/x.sh")
    ↓
CHAIN_WRITE_SCRIPT_TO_EXECUTE
```

---

## 5. 系统设计

### 5.1 总体架构

```text
MiniAgent / CoreCoder
    ↓
ToolCallEvent
    ↓
AgentGuardGateway
    ↓
PolicyEngine + ParameterChecker + ChainDetector + RiskScorer
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

### 5.2 核心事件模型

说明：

```text
TaskScope：任务权限边界
ToolCallEvent：统一工具调用事件
GuardDecision：allow / ask / deny
AuditRecord：完整审计证据
```

### 5.3 防御策略

```text
输入审查：InputInspector
上下文来源标注：user_task / untrusted content
路径与命令检查：ParameterChecker
任务权限收敛：TaskScope
工具调用前拦截：AgentGuardGateway
行为链检测：ChainDetector
结果审查：ResultInspector
输出脱敏：OutputRedactor
审批确认：ApprovalHandler
审计展示：Dashboard
风险解释：LLM risk explainer 只解释 GuardDecision，不参与硬决策
```

### 5.4 CoreCoder 适配

重点说明：

```text
原生 CoreCoder CLI 不自动接入 AgentGuard。
本项目通过 GuardedCoreCoderAgent 包装 _exec_tool，实现工具执行前拦截。
```

---

## 6. 实验设计

### 6.1 数据集

当前目标：

```text
P0 smoke cases：10
P1 scripted cases：约 200
```

样本字段：

```text
case_id
category
user_task
task_scope
tool_calls
expected_decision
```

### 6.2 评估指标

```text
accuracy
attack_detection_rate
false_positive_rate
false_negative_rate
input_findings
output_findings
chain_alerts
chain_graph_edges
approval_required
```

### 6.3 消融实验

对比：

```text
baseline
input_only
tool_guard
tool_chain
tool_chain_result
full_guard
```

核心结论：

```text
input_only 只能发现明显恶意输入；
tool_guard 显著提升检测率；
tool_chain / full_guard 能补齐多步攻击链。
```

---

## 7. 实验结果

引用：

```text
logs/p1_v2_eval.json
```

建议表格列：

```text
variant
attack_detection_rate
false_positive_rate
false_negative_rate
chain_alerts
output_findings
approval_required
```

---

## 8. Dashboard 展示

展示模块：

```text
Tool Call Timeline
Input Findings
Output Findings
Approval Records
Risk Explanations
Behavior Chain Alerts
Behavior Chain Graphs
Business Tool Outbox
```

风险解释日志：

```text
logs/p2_explained_audit.jsonl
```

报告中要强调：

```text
LLM risk explainer 是可解释性增强，不是安全边界。
最终 allow / ask / deny 仍由规则、任务范围和行为链检测产生。
```

业务 outbox：

```text
logs/outbox/api_call_log.jsonl
logs/outbox/message_outbox.jsonl
logs/outbox/mail_outbox.jsonl
```

---

## 9. 局限性

需要诚实说明：

```text
规则策略仍是启发式，不是形式化安全证明
MiniAgent scripted mode 用于可复现评估，MiniAgent LLM mode 用于真实 LLM 工具调用演示
CoreCoder real LLM runner 需要 API key 和网络环境
当前没有生产级 sandbox 和资源限制
Dashboard 是展示层，不参与实时审批控制
真实 SMTP/webhook 未接入，使用本地 outbox 代替
```

---

## 10. 总结

建议结论：

```text
AgentGuard-Chain 证明了对 Agent 外部工具交互进行统一事件化、前置审查、链路检测和审计展示的可行性。
实验表明，相比单纯输入过滤，工具调用前审查和行为链检测更适合 Agent 安全场景。
```
