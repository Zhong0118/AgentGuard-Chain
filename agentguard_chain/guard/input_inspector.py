"""用户输入和外部上下文的轻量审查。

InputInspector 不是主安全边界；它负责给审计日志标注输入风险。
真正是否执行工具仍由 AgentGuardGateway 对 ToolCallEvent 做决策。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Pattern


@dataclass(frozen=True, slots=True)
class InputFinding:
    """一条输入侧风险发现。"""

    rule_id: str
    risk_type: str
    severity: str
    source: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class InputRule:
    """输入检测规则。"""

    rule_id: str
    risk_type: str
    severity: str
    reason: str
    pattern: Pattern[str]


class InputInspector:
    """对用户任务或不可信上下文做提示注入与越权意图标注。"""

    def __init__(self, rules: list[InputRule] | None = None):
        self.rules = rules or DEFAULT_INPUT_RULES

    def inspect(self, text: str | None, *, source: str = "user_task") -> list[InputFinding]:
        if not text:
            return []

        findings: list[InputFinding] = []
        for rule in self.rules:
            if rule.pattern.search(text):
                findings.append(
                    InputFinding(
                        rule_id=rule.rule_id,
                        risk_type=rule.risk_type,
                        severity=rule.severity,
                        source=source,
                        reason=rule.reason,
                    )
                )

        if source != "user_task" and _looks_like_instruction(text):
            findings.insert(
                0,
                InputFinding(
                    rule_id="UNTRUSTED_CONTEXT_COMMAND",
                    risk_type="untrusted_context_instruction",
                    severity="medium",
                    source=source,
                    reason="untrusted context contains instruction-like text",
                ),
            )

        return _dedupe_findings(findings)


DEFAULT_INPUT_RULES = [
    InputRule(
        rule_id="IGNORE_PREVIOUS_INSTRUCTIONS",
        risk_type="prompt_injection",
        severity="high",
        reason="input asks the agent to ignore prior instructions or rules",
        pattern=re.compile(
            r"(?i)(ignore|disregard|bypass).{0,30}(previous|prior|above|system|rules|instructions)|忽略.{0,12}(之前|以上|系统|规则|指令)"
        ),
    ),
    InputRule(
        rule_id="READ_SECRET_REQUEST",
        risk_type="sensitive_access_request",
        severity="high",
        reason="input requests access to sensitive files or credentials",
        pattern=re.compile(r"(?i)(\.env|id_rsa|id_ed25519|credentials|secret|api[_-]?key|token|读取\s*\.env)"),
    ),
    InputRule(
        rule_id="EXFILTRATION_REQUEST",
        risk_type="exfiltration_request",
        severity="high",
        reason="input requests sending data to an external destination",
        pattern=re.compile(r"(?i)(webhook|https?://|发送到|发到|上传到|外发|send\s+to|post\s+to)"),
    ),
    InputRule(
        rule_id="JAILBREAK_ROLEPLAY",
        risk_type="jailbreak",
        severity="medium",
        reason="input uses roleplay or authority framing to bypass safety boundaries",
        pattern=re.compile(r"(?i)(jailbreak|developer mode|安全审计模式|授权测试|不受.*限制)"),
    ),
]


def _looks_like_instruction(text: str) -> bool:
    return bool(re.search(r"(?i)(please|must|delete|read|send|execute|请|必须|删除|读取|发送|执行)", text))


def _dedupe_findings(findings: list[InputFinding]) -> list[InputFinding]:
    seen: set[str] = set()
    deduped: list[InputFinding] = []
    for finding in findings:
        if finding.rule_id in seen:
            continue
        seen.add(finding.rule_id)
        deduped.append(finding)
    return deduped
