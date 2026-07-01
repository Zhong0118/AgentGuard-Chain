"""安全决策和风险等级常量。"""

ALLOW = "allow"
ASK = "ask"
DENY = "deny"

LOW = "low"
MEDIUM = "medium"
HIGH = "high"
CRITICAL = "critical"


def risk_level_for_score(score: float) -> str:
    if score >= 0.81:
        return CRITICAL
    if score >= 0.61:
        return HIGH
    if score >= 0.31:
        return MEDIUM
    return LOW
