"""单步策略引擎。

PolicyEngine 只负责找出命中了哪些规则，不直接决定 allow/ask/deny。
最终决策由 RiskScorer 统一生成，便于后续替换评分策略。
"""

from __future__ import annotations

from dataclasses import dataclass

from agentguard_chain.event import ToolCallEvent
from agentguard_chain.guard.parameter_checker import ParameterChecker, PolicyFinding


@dataclass(frozen=True, slots=True)
class PolicyResult:
    findings: list[PolicyFinding]

    @property
    def rule_ids(self) -> list[str]:
        return _dedupe([finding.rule_id for finding in self.findings])

    @property
    def risk_types(self) -> list[str]:
        return _dedupe([finding.risk_type for finding in self.findings])

    @property
    def reasons(self) -> list[str]:
        return [finding.reason for finding in self.findings]


class PolicyEngine:
    """对单个 ToolCallEvent 执行工具权限和参数规则检查。"""

    def __init__(self, parameter_checker: ParameterChecker | None = None):
        self.parameter_checker = parameter_checker or ParameterChecker()

    def evaluate(self, event: ToolCallEvent) -> PolicyResult:
        findings: list[PolicyFinding] = []

        # 工具白名单是第一层粗粒度任务边界。
        allowed_tools = event.task_scope.allowed_tools
        if allowed_tools and event.tool_name not in allowed_tools:
            findings.append(
                PolicyFinding(
                    rule_id="TOOL_NOT_ALLOWED",
                    risk_type="tool_not_allowed",
                    severity="critical",
                    reason=f"工具 {event.tool_name} 不在当前任务允许列表中。",
                )
            )

        # 写入/编辑/删除是单独权限。即使工具在白名单里，也必须显式允许写操作。
        if event.tool_name in {"write_file", "edit_file", "delete_file"} and not event.task_scope.write_allowed:
            findings.append(
                PolicyFinding(
                    rule_id="WRITE_NOT_ALLOWED",
                    risk_type="write_not_allowed",
                    severity="critical",
                    reason=f"当前任务范围是只读任务，不允许执行 {event.tool_name}。",
                )
            )

        # 删除是不可逆动作。即使任务允许写操作，P1 也先要求用户确认。
        if event.tool_name == "delete_file" and event.task_scope.write_allowed:
            findings.append(
                PolicyFinding(
                    rule_id="DELETE_REQUIRES_CONFIRMATION",
                    risk_type="delete_requires_confirmation",
                    severity="medium",
                    reason="删除文件属于中风险不可逆操作，需要用户确认。",
                )
            )

        if event.tool_name in {"bash", "run_command"}:
            findings.extend(self._evaluate_command_allowlist(event))

        findings.extend(self.parameter_checker.check(event))
        return PolicyResult(findings=findings)

    def _evaluate_command_allowlist(self, event: ToolCallEvent) -> list[PolicyFinding]:
        allowed_commands = event.task_scope.allowed_commands
        if not allowed_commands:
            return []

        command = str(event.tool_args.get("command", "")).strip()
        if any(command == allowed or command.startswith(f"{allowed} ") for allowed in allowed_commands):
            return []

        return [
            PolicyFinding(
                rule_id="COMMAND_NOT_ALLOWED",
                risk_type="command_not_allowed",
                severity="high",
                reason=f"命令 {command!r} 不在当前任务允许命令列表中。",
            )
        ]


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
