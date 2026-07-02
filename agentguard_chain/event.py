"""AgentGuard-Chain 各模块共享的数据结构。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class TaskScope:
    """当前用户任务的权限边界，用来判断工具调用是否越界。"""

    task_type: str
    workspace_root: str
    allowed_paths: list[str] = field(default_factory=list)
    denied_paths: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    allowed_commands: list[str] = field(default_factory=list)
    network_allowed: bool = False
    write_allowed: bool = False
    external_send_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ToolCallEvent:
    """标准化工具调用事件。不同 Agent 的工具调用都要先转成这个结构。"""

    session_id: str
    agent_name: str
    user_task: str
    task_scope: TaskScope
    tool_name: str
    tool_args: dict[str, Any]
    cwd: str
    event_id: str = field(default_factory=lambda: f"evt-{uuid4().hex}")
    parent_agent_id: str | None = None
    timestamp: str = field(default_factory=_now_iso)
    call_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["task_scope"] = self.task_scope.to_dict()
        return data


@dataclass(slots=True)
class GuardDecision:
    """工具执行前的安全决策结果。"""

    event_id: str
    decision: str
    risk_score: float
    risk_level: str
    risk_types: list[str] = field(default_factory=list)
    matched_rules: list[str] = field(default_factory=list)
    chain_alerts: list[dict[str, Any]] = field(default_factory=list)
    chain_graphs: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    llm_explanation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AuditRecord:
    """一条可写入 JSONL 的审计记录，包含事件、决策和执行结果。"""

    event: ToolCallEvent
    decision: GuardDecision
    executed: bool
    result_preview: str = ""
    exit_code: int | None = None
    duration_ms: int | None = None
    input_findings: list[dict[str, Any]] = field(default_factory=list)
    output_findings: list[dict[str, Any]] = field(default_factory=list)
    redaction: dict[str, Any] = field(default_factory=dict)
    approval: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event.to_dict(),
            "decision": self.decision.to_dict(),
            "execution": {
                "executed": self.executed,
                "result_preview": self.result_preview,
                "exit_code": self.exit_code,
                "duration_ms": self.duration_ms,
            },
            "input_findings": self.input_findings,
            "approval": self.approval
            or {
                "required": False,
                "mode": "none",
                "decision": "not_required",
                "execute": self.executed,
                "operator": "system",
                "reason": "",
            },
            "output_findings": self.output_findings,
            "redaction": self.redaction or {"applied": False, "redacted_types": []},
        }
