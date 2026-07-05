# Artifacts

本目录保存较稳定的演示证据和评估结果。

目录约定：

```text
artifacts/demo/  固化的演示审计日志，可用于截图、报告和复盘
artifacts/eval/  固化的评估结果
```

说明：

```text
logs/ 是运行时目录，可通过 experiments.generate_demo_data 重建。
artifacts/ 是交付证据目录，避免演示日志被后续运行覆盖。
```

当前主要产物：

```text
artifacts/demo/corecoder_guarded_audit.jsonl
artifacts/demo/deepseek_corecoder_real_audit.jsonl
artifacts/demo/deepseek_explained_audit.jsonl
artifacts/demo/deepseek_miniagent_llm_audit.jsonl
artifacts/demo/p1_miniagent_audit.jsonl
artifacts/eval/p1_v2_eval.json
```

