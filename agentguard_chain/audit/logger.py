"""JSONL 审计日志写入器。"""

from __future__ import annotations

import json
from pathlib import Path

from agentguard_chain.event import AuditRecord, GuardDecision, ToolCallEvent


class AuditLogger:
    """把每次工具调用的事件、决策和执行结果追加写入 JSONL。"""

    def __init__(self, path: str | Path = "logs/audit.jsonl"):
        self.path = Path(path)

    def log(
        self,
        event: ToolCallEvent,
        decision: GuardDecision,
        *,
        executed: bool,
        result_preview: str = "",
        exit_code: int | None = None,
        duration_ms: int | None = None,
    ) -> None:
        record = AuditRecord(
            event=event,
            decision=decision,
            executed=executed,
            result_preview=result_preview,
            exit_code=exit_code,
            duration_ms=duration_ms,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
