# AgentGuard-Chain 文档入口

本目录只保留当前阶段需要阅读和展示的文档。历史计划、早期讨论和原始验证记录放在 `docs/archive/`，避免和当前运行入口混在一起。

## 当前主文档

| 文件 | 用途 |
| --- | --- |
| `runbook.md` | 项目运行手册，说明 MiniAgent、CoreCoder guarded demo、评估脚本和 Dashboard 的启动方式。 |
| `usage-and-demo-guide.md` | 面向演示和答辩的完整使用流程，解释输入审查、工具调用审查、输出审查、风险链和人工确认。 |
| `validation.md` | 当前可复现验证记录，汇总离线测试、DeepSeek API 实测、CoreCoder guarded real demo 和 Dashboard 状态。 |
| `demo-script.md` | 演示脚本，按场景说明如何展示攻击、拦截、日志和指标。 |
| `final-report.md` | 最终报告正文，面向比赛提交材料。 |
| `report-outline.md` | 报告提纲，用于后续整理比赛提交材料。 |
| `code-structure.md` | 代码结构说明，区分可复用框架、Agent 适配、实验脚本和展示层。 |
| `cleanup-inventory.md` | 阶段 A/B 清单，记录文件盘点、保留/清理策略和本轮清理结果。 |
| `boundary-check.md` | 阶段 D 检查记录，说明 scripted/LLM/real/mock 边界和本轮修复。 |

## 产物目录

| 路径 | 用途 |
| --- | --- |
| `artifacts/demo/` | 稳定演示日志样例，可直接给 Dashboard 或报告截图使用。 |
| `artifacts/eval/` | 固化评估结果样例。 |
| `logs/` | 本地运行时日志，已被 `.gitignore` 忽略，不作为交付源码。 |
| `tmp/` | 数据集和工具执行的临时文件，已被 `.gitignore` 忽略。 |

## 命名约定

- `docs/*.md`：当前有效文档。
- `docs/archive/*.md`：历史记录，只用于追溯设计演进。
- `artifacts/demo/*.jsonl`：可复现演示审计日志。
- `artifacts/eval/*.json`：可复现评估结果。
- `logs/*.jsonl`：本地新跑出来的审计日志。
- `tmp/*`：运行时临时文件，不应手动维护。
