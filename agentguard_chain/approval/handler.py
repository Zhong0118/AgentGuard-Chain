"""ask 决策的审批处理。

P1 先提供可测试的自动模式：auto-deny / auto-allow。
后续 CLI interactive 可以复用这个接口，把人工输入转成 ApprovalRecord。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Callable

from agentguard_chain.decision import ALLOW, ASK, DENY
from agentguard_chain.event import GuardDecision, ToolCallEvent


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """一次审批结果，决定 ask 是否能继续执行工具。"""

    required: bool
    mode: str
    decision: str
    execute: bool
    operator: str = "system"
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ApprovalHandler:
    """把 GuardDecision 转换成最终执行许可。

    auto-* 模式用于批量评估；interactive 模式用于 ask 人工确认。
    interactive-all 模式用于演示“每个非硬阻断工具调用都由用户确认”。
    """

    VALID_MODES = {"auto-deny", "auto-allow", "interactive", "interactive-all"}

    def __init__(
        self,
        mode: str = "auto-deny",
        *,
        input_func: Callable[[str], str] | None = None,
        output_func: Callable[[str], None] | None = None,
    ):
        if mode not in self.VALID_MODES:
            raise ValueError(f"Unsupported approval mode: {mode}")
        self.mode = mode
        self.input_func = input_func or input
        self.output_func = output_func or print

    def resolve(self, event: ToolCallEvent, decision: GuardDecision) -> ApprovalRecord:
        if decision.decision == DENY:
            return ApprovalRecord(
                required=False,
                mode="none",
                decision="hard_denied",
                execute=False,
                reason="deny decisions are hard-blocked by AgentGuard",
            )

        if self.mode == "interactive-all":
            approved = self._ask_user(event, decision)
            return ApprovalRecord(
                required=True,
                mode=self.mode,
                decision="user_approved" if approved else "user_denied",
                execute=approved,
                operator="cli",
                reason=_approval_reason(event, decision, approved=approved),
            )

        if decision.decision != ASK:
            return ApprovalRecord(
                required=False,
                mode="none",
                decision="not_required",
                execute=decision.decision == ALLOW,
                reason="approval is only required for ask decisions",
            )

        if self.mode == "auto-allow":
            return ApprovalRecord(
                required=True,
                mode=self.mode,
                decision="user_approved",
                execute=True,
                reason=_approval_reason(event, decision, approved=True),
            )

        if self.mode == "interactive":
            approved = self._ask_user(event, decision)
            return ApprovalRecord(
                required=True,
                mode=self.mode,
                decision="user_approved" if approved else "user_denied",
                execute=approved,
                operator="cli",
                reason=_approval_reason(event, decision, approved=approved),
            )

        return ApprovalRecord(
            required=True,
            mode=self.mode,
            decision="user_denied",
            execute=False,
            reason=_approval_reason(event, decision, approved=False),
        )

    def _ask_user(self, event: ToolCallEvent, decision: GuardDecision) -> bool:
        """在命令行展示 ask 风险，并把 y/yes 视为批准。"""
        self.output_func("")
        self.output_func("AgentGuard approval requested")
        self.output_func(f"Tool: {event.tool_name}")
        self.output_func(f"Args: {json.dumps(event.tool_args, ensure_ascii=False)}")
        self.output_func(f"Risk level: {decision.risk_level} ({decision.risk_score:.2f})")
        self.output_func(f"Risk types: {', '.join(decision.risk_types) or 'unknown_risk'}")
        if decision.reason:
            self.output_func(f"Reason: {decision.reason}")
        answer = self.input_func("Approve this tool call? [y/N]: ").strip().lower()
        return answer in {"y", "yes"}


def _approval_reason(event: ToolCallEvent, decision: GuardDecision, *, approved: bool) -> str:
    action = "approved" if approved else "denied"
    risk_types = ", ".join(decision.risk_types) or "unknown_risk"
    return f"{action} {event.tool_name} after ask decision: {risk_types}"
