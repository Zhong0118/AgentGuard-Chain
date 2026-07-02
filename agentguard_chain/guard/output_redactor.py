"""工具输出脱敏。

ResultInspector 负责“发现风险”，OutputRedactor 负责“落盘和返回前去掉原值”。
两者都先采用规则实现，保证 P1 可以离线、可复现地跑通。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Pattern


@dataclass(frozen=True, slots=True)
class RedactionRule:
    """一条脱敏规则。"""

    secret_type: str
    pattern: Pattern[str]
    replacement: str | Callable[[re.Match[str]], str]


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """脱敏结果，text 是可以写入审计日志或返回给 Agent 的内容。"""

    text: str
    applied: bool
    redacted_types: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "applied": self.applied,
            "redacted_types": self.redacted_types,
        }


class OutputRedactor:
    """对工具返回值做最小必要脱敏。"""

    def __init__(self, rules: list[RedactionRule] | None = None):
        self.rules = rules or DEFAULT_REDACTION_RULES

    def redact(self, text: str | None) -> RedactionResult:
        if text is None:
            return RedactionResult(text="", applied=False, redacted_types=[])

        redacted = str(text)
        redacted_types: list[str] = []
        for rule in self.rules:
            next_text, count = rule.pattern.subn(rule.replacement, redacted)
            if count:
                redacted = next_text
                if rule.secret_type not in redacted_types:
                    redacted_types.append(rule.secret_type)

        return RedactionResult(
            text=redacted,
            applied=bool(redacted_types),
            redacted_types=redacted_types,
        )


DEFAULT_REDACTION_RULES = [
    RedactionRule(
        secret_type="private_key",
        pattern=re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.IGNORECASE,
        ),
        replacement="<redacted:private_key>",
    ),
    RedactionRule(
        secret_type="api_key",
        pattern=re.compile(
            r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|token)\s*[:=]\s*[^\s'\"`]+"
        ),
        replacement=lambda match: f"{match.group(1)}=<redacted:api_key>",
    ),
    RedactionRule(
        secret_type="api_key",
        pattern=re.compile(r"\b(?:sk|ghp|xoxb|xoxp)-?[A-Za-z0-9_=-]{8,}\b", re.IGNORECASE),
        replacement="<redacted:api_key>",
    ),
    RedactionRule(
        secret_type="api_key",
        pattern=re.compile(r"\bAKIA[0-9A-Z]{8,}\b"),
        replacement="<redacted:api_key>",
    ),
    RedactionRule(
        secret_type="password",
        pattern=re.compile(r"(?i)\b(password|passwd|pwd|db_password)\s*[:=]\s*[^\s'\"`]+"),
        replacement=lambda match: f"{match.group(1)}=<redacted:password>",
    ),
    RedactionRule(
        secret_type="database_url",
        pattern=re.compile(r"(?i)\b(database_url|db_url)\s*[:=]\s*[^\s'\"`]+"),
        replacement=lambda match: f"{match.group(1)}=<redacted:database_url>",
    ),
]
