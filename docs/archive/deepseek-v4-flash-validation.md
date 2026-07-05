# DeepSeek v4 flash API 验证记录

本文档记录使用 DeepSeek OpenAI-compatible API 对阶段一、阶段二、阶段三的真实 LLM 能力验证结果。

注意：

```text
本文档不保存真实 API key。
运行时请只通过环境变量注入 key。
```

## 1. 环境

Python 环境：

```text
C:\Users\zx\.conda\envs\dl\python.exe
```

依赖检查：

```text
openai: installed
dotenv: installed
streamlit: installed
```

DeepSeek 模型列表验证：

```text
deepseek-v4-flash
deepseek-v4-pro
```

本次使用模型：

```text
deepseek-v4-flash
```

## 2. 阶段一：MiniAgent LLM mode

命令模板：

```powershell
$env:MINIAGENT_API_KEY="<your api key>"
$env:MINIAGENT_BASE_URL="https://api.deepseek.com"
$env:MINIAGENT_MODEL="deepseek-v4-flash"
$env:PYTHONUTF8="1"
C:\Users\zx\.conda\envs\dl\python.exe -m agents.miniagent.run_case --mode llm --prompt "请读取 workflow.md 并总结项目目标" --audit-log logs/deepseek_miniagent_llm_audit.jsonl --workspace-root . --approval-mode auto-deny
```

实测结果：

```json
{
  "mode": "llm",
  "total_calls": 1,
  "executed_calls": 1,
  "blocked_calls": 0,
  "decisions": ["allow"],
  "tools": ["read_file"]
}
```

审计日志：

```text
logs/deepseek_miniagent_llm_audit.jsonl
```

结论：

```text
MiniAgent LLM mode 已使用 deepseek-v4-flash 真实生成 JSON tool_calls，并进入 AgentGuard 审查与执行。
```

## 3. 阶段二：CoreCoder real guarded mode

命令模板：

```powershell
$env:DEEPSEEK_API_KEY="<your api key>"
$env:OPENAI_BASE_URL="https://api.deepseek.com"
$env:CORECODER_MODEL="deepseek-v4-flash"
$env:PYTHONUTF8="1"
C:\Users\zx\.conda\envs\dl\python.exe -m agents.corecoder_guarded_runner --mode real --prompt "请读取 workflow.md 并总结项目目标" --audit-log logs/deepseek_corecoder_real_audit.jsonl --workspace-root . --approval-mode auto-deny
```

实测结果：

```json
{
  "mode": "real-llm",
  "model": "deepseek-v4-flash",
  "base_url": "https://api.deepseek.com",
  "provider": "openai",
  "decision": "allow",
  "executed": true,
  "records": 2
}
```

审计摘要：

```text
glob      -> allow / executed=true
read_file -> allow / executed=true
```

审计日志：

```text
logs/deepseek_corecoder_real_audit.jsonl
```

结论：

```text
CoreCoder real guarded mode 已使用 deepseek-v4-flash 真实运行。
CoreCoder 产生的工具调用已进入 GuardedCoreCoderAgent 和 AgentGuardGateway。
```

## 4. 阶段三：LLM risk explainer

命令模板：

```powershell
$env:AGENTGUARD_EXPLAINER_API_KEY="<your api key>"
$env:AGENTGUARD_EXPLAINER_BASE_URL="https://api.deepseek.com"
$env:AGENTGUARD_EXPLAINER_MODEL="deepseek-v4-flash"
$env:PYTHONUTF8="1"
C:\Users\zx\.conda\envs\dl\python.exe -m experiments.explain_audit_log --input logs/corecoder_guarded_audit.jsonl --output logs/deepseek_explained_audit.jsonl --mode llm
```

实测结果：

```json
{
  "mode": "llm",
  "records": 3,
  "explained_records": 3
}
```

审计解释覆盖：

```text
normal read_file allow 解释
sensitive .env read_file deny 解释
dangerous bash deny 解释
```

输出日志：

```text
logs/deepseek_explained_audit.jsonl
```

结论：

```text
LLM risk explainer 已使用 deepseek-v4-flash 真实生成中文风险解释。
解释文本仅写入 decision.llm_explanation，不改变 allow / ask / deny 决策。
```

## 5. 安全检查

已检查项目文件，未发现真实 API key 被写入仓库文件。

命令：

```powershell
rg "<api key pattern>" .
```

结果：

```text
no matches
```

## 6. 当前阶段状态

```text
阶段一 MiniAgent LLM mode：真实 API 验证通过。
阶段二 CoreCoder real guarded mode：真实 API 验证通过。
阶段三 LLM risk explainer：真实 API 验证通过，基础功能完成。
```

仍需注意：

```text
真实 API 演示依赖网络、DeepSeek 服务状态、账户余额和模型稳定性。
MiniAgent LLM mode 要求模型输出严格 JSON tool_calls。
CoreCoder real guarded mode 的工具调用由模型自主决定，真实 prompt 可能产生不同工具调用序列。
```

