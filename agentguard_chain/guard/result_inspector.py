"""工具调用结果审查。

P1 这里先用可解释规则做最小闭环：发现工具返回值里的密钥、密码、
私钥等敏感片段，后续 P2 可以再接 LLM Judge 或更细的内容分类器。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Pattern


@dataclass(frozen=True, slots=True)
class OutputFinding:
    """一条工具输出风险发现。"""

    rule_id: str
    risk_type: str
    severity: str
    secret_type: str
    reason: str
    pattern_name: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OutputSecretRule:
    """输出检测规则：pattern 只判断是否出现，不负责脱敏替换。"""

    rule_id: str
    secret_type: str
    severity: str
    reason: str
    pattern: Pattern[str]


class ResultInspector:
    """审查工具返回内容，给审计日志补充 output_findings。"""

    def __init__(self, rules: list[OutputSecretRule] | None = None):
        self.rules = rules or DEFAULT_OUTPUT_SECRET_RULES

    def inspect(self, text: str | None) -> list[OutputFinding]:
        if not text:
            return []

        findings: list[OutputFinding] = []
        seen: set[str] = set()
        for rule in self.rules:
            if not rule.pattern.search(text):
                continue
            # 同一类秘密在一段输出里只记一次，避免日志被重复命中刷屏。
            if rule.secret_type in seen:
                continue
            seen.add(rule.secret_type)
            findings.append(
                OutputFinding(
                    rule_id=rule.rule_id,
                    risk_type="sensitive_output",
                    severity=rule.severity,
                    secret_type=rule.secret_type,
                    reason=rule.reason,
                    pattern_name=rule.pattern.pattern,
                )
            )
        return findings


DEFAULT_OUTPUT_SECRET_RULES = [
    OutputSecretRule(
        rule_id="OUT_PRIVATE_KEY",
        secret_type="private_key",
        severity="critical",
        reason="tool result contains a private key block",
        pattern=re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.IGNORECASE,
        ),
    ),
    OutputSecretRule(
        rule_id="OUT_API_KEY_ASSIGNMENT",
        secret_type="api_key",
        severity="high",
        reason="tool result contains an API key or token assignment",
        pattern=re.compile(
            r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|token)\s*[:=]\s*[^\s'\"`]+"
        ),
    ),
    OutputSecretRule(
        rule_id="OUT_KNOWN_TOKEN_PREFIX",
        secret_type="api_key",
        severity="high",
        reason="tool result contains a token with a known secret-like prefix",
        pattern=re.compile(r"\b(?:sk|ghp|xoxb|xoxp)-?[A-Za-z0-9_=-]{8,}\b", re.IGNORECASE),
    ),
    OutputSecretRule(
        rule_id="OUT_AWS_ACCESS_KEY",
        secret_type="api_key",
        severity="high",
        reason="tool result contains an AWS access key-like value",
        pattern=re.compile(r"\bAKIA[0-9A-Z]{8,}\b"),
    ),
    OutputSecretRule(
        rule_id="OUT_PASSWORD",
        secret_type="password",
        severity="high",
        reason="tool result contains a password assignment",
        pattern=re.compile(r"(?i)\b(?:password|passwd|pwd|db_password)\s*[:=]\s*[^\s'\"`]+"),
    ),
    OutputSecretRule(
        rule_id="OUT_DATABASE_URL",
        secret_type="database_url",
        severity="high",
        reason="tool result contains a database connection URL",
        pattern=re.compile(r"(?i)\b(?:database_url|db_url)\s*[:=]\s*[^\s'\"`]+"),
    ),
]
