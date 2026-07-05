"""Mini-Agent 的结构化执行循环。

MiniAgent 的核心循环不关心 planner 是 scripted 还是 LLM。
只要 planner 输出结构化 tool_calls，后续都会进入同一条安全链路：
planner -> guard -> approval -> tool executor -> result inspection -> audit -> summary。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentguard_chain.approval import ApprovalHandler
from agentguard_chain.audit import AuditLogger
from agentguard_chain.event import GuardDecision, TaskScope, ToolCallEvent
from agentguard_chain.gateway import AgentGuardGateway
from agentguard_chain.guard import InputInspector, OutputRedactor, ResultInspector
from agents.miniagent.tools import MiniAgentTools


@dataclass(slots=True)
class PlannedToolCall:
    """Planner 产出的一步工具调用。"""

    tool_name: str
    tool_args: dict[str, Any]
    expected_decision: str = "allow"


@dataclass(slots=True)
class MiniAgentStep:
    """Mini-Agent 执行一步后的结果，供评估器和 Dashboard 使用。"""

    event: ToolCallEvent
    decision: GuardDecision
    expected_decision: str
    executed: bool
    result_preview: str = ""


@dataclass(slots=True)
class MiniAgentSummary:
    """一次 case 的执行摘要。"""

    case_id: str
    steps: list[MiniAgentStep] = field(default_factory=list)

    @property
    def total_calls(self) -> int:
        return len(self.steps)

    @property
    def executed_calls(self) -> int:
        return sum(1 for step in self.steps if step.executed)

    @property
    def blocked_calls(self) -> int:
        return sum(1 for step in self.steps if not step.executed)

    @property
    def correct_calls(self) -> int:
        return sum(1 for step in self.steps if step.decision.decision == step.expected_decision)


class ScriptedPlanner:
    """从 JSONL case 中读取预设工具调用，保证实验可复现。"""

    def __init__(self, case: dict[str, Any]):
        self.case = case

    @property
    def case_id(self) -> str:
        return str(self.case["case_id"])

    @property
    def user_task(self) -> str:
        return str(self.case["user_task"])

    def task_scope(self, workspace_root: Path) -> TaskScope:
        raw_scope = self.case["task_scope"]

        def resolve_paths(values: list[str]) -> list[str]:
            return [str(workspace_root) if value == "." else value for value in values]

        return TaskScope(
            task_type=raw_scope["task_type"],
            workspace_root=str(workspace_root),
            allowed_paths=resolve_paths(raw_scope.get("allowed_paths", [])),
            denied_paths=raw_scope.get("denied_paths", []),
            allowed_tools=raw_scope.get("allowed_tools", []),
            allowed_commands=raw_scope.get("allowed_commands", []),
            network_allowed=raw_scope.get("network_allowed", False),
            write_allowed=raw_scope.get("write_allowed", False),
            external_send_allowed=raw_scope.get("external_send_allowed", False),
        )

    def plan(self) -> list[PlannedToolCall]:
        default_expected = self.case.get("expected_decision", "allow")
        return [
            PlannedToolCall(
                tool_name=raw_call["tool_name"],
                tool_args=raw_call["tool_args"],
                expected_decision=raw_call.get("expected_decision", default_expected),
            )
            for raw_call in self.case["tool_calls"]
        ]


class MiniAgent:
    """最小 Agent：按计划逐步调用工具，但每一步都先经过 AgentGuard。"""

    def __init__(
        self,
        *,
        planner: ScriptedPlanner,
        gateway: AgentGuardGateway,
        tools: MiniAgentTools,
        audit_logger: AuditLogger,
        workspace_root: Path,
        result_inspector: ResultInspector | None = None,
        output_redactor: OutputRedactor | None = None,
        approval_handler: ApprovalHandler | None = None,
        input_inspector: InputInspector | None = None,
    ):
        self.planner = planner
        self.gateway = gateway
        self.tools = tools
        self.audit_logger = audit_logger
        self.workspace_root = workspace_root.resolve()
        self.result_inspector = result_inspector or ResultInspector()
        self.output_redactor = output_redactor or OutputRedactor()
        self.approval_handler = approval_handler or ApprovalHandler()
        self.input_inspector = input_inspector or InputInspector()

    def run(self) -> MiniAgentSummary:
        scope = self.planner.task_scope(self.workspace_root)
        summary = MiniAgentSummary(case_id=self.planner.case_id)
        input_findings = [
            finding.to_dict()
            for finding in self.input_inspector.inspect(self.planner.user_task, source="user_task")
        ]

        for index, planned_call in enumerate(self.planner.plan(), start=1):
            event = ToolCallEvent(
                event_id=f"evt-{self.planner.case_id}-{index}",
                session_id=f"sess-{self.planner.case_id}",
                agent_name="miniagent",
                user_task=self.planner.user_task,
                task_scope=scope,
                tool_name=planned_call.tool_name,
                tool_args=planned_call.tool_args,
                cwd=str(self.workspace_root),
                call_index=index,
            )
            decision = self.gateway.evaluate(event)
            approval = self.approval_handler.resolve(event, decision)
            executed = approval.execute
            result = (
                self.tools.execute(event.tool_name, event.tool_args)
                if executed
                else _blocked_result(decision.decision, approval.decision)
            )
            output_findings = []
            redaction = {"applied": False, "redacted_types": []}
            visible_result = str(result)
            if executed:
                # 工具结果可能包含密钥、密码等敏感内容，落盘和摘要前先审查并脱敏。
                findings = self.result_inspector.inspect(visible_result)
                redacted = self.output_redactor.redact(visible_result)
                output_findings = [finding.to_dict() for finding in findings]
                redaction = redacted.to_dict()
                visible_result = redacted.text

            # 审计日志是安全系统的证据链，允许和阻断都要记录。
            self.audit_logger.log(
                event,
                decision,
                executed=executed,
                result_preview=visible_result[:300],
                input_findings=input_findings,
                output_findings=output_findings,
                redaction=redaction,
                approval=approval.to_dict(),
            )
            summary.steps.append(
                MiniAgentStep(
                    event=event,
                    decision=decision,
                    expected_decision=planned_call.expected_decision,
                    executed=executed,
                    result_preview=visible_result[:300],
                )
            )

        return summary


def _blocked_result(decision: str, approval_decision: str) -> str:
    if decision == "ask":
        return f"Blocked by AgentGuard-Chain approval flow: {approval_decision}"
    return "Blocked by AgentGuard-Chain"
