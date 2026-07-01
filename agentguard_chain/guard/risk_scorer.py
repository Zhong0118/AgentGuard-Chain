"""把规则命中结果转换成可执行的安全决策。"""

from __future__ import annotations

from agentguard_chain.decision import ALLOW, ASK, CRITICAL, DENY, HIGH, LOW, MEDIUM
from agentguard_chain.event import GuardDecision, ToolCallEvent
from agentguard_chain.guard.policy_engine import PolicyResult


SEVERITY_SCORES = {
    "critical": 0.95,
    "high": 0.75,
    "medium": 0.45,
    "low": 0.1,
}


class RiskScorer:
    """P0 评分器，采用确定性规则优先级。

    critical 命中直接 deny。high 在 P0 也先 deny，因为当前还没有交互式
    用户确认通道；后续阶段可以把部分 high 风险改成 ask。
    """

    def score(self, event: ToolCallEvent, policy_result: PolicyResult) -> GuardDecision:
        if not policy_result.findings:
            return GuardDecision(
                event_id=event.event_id,
                decision=ALLOW,
                risk_score=0.1,
                risk_level=LOW,
                risk_types=[],
                matched_rules=[],
                reason="工具调用位于当前 P0 任务范围内，未命中高危规则。",
            )

        highest = max(SEVERITY_SCORES[finding.severity] for finding in policy_result.findings)
        risk_level = _risk_level_for_score(highest)
        decision = DENY if risk_level in {CRITICAL, HIGH} else ASK

        return GuardDecision(
            event_id=event.event_id,
            decision=decision,
            risk_score=highest,
            risk_level=risk_level,
            risk_types=policy_result.risk_types,
            matched_rules=policy_result.rule_ids,
            reason=" ".join(policy_result.reasons),
        )


def _risk_level_for_score(score: float) -> str:
    if score >= 0.81:
        return CRITICAL
    if score >= 0.61:
        return HIGH
    if score >= 0.31:
        return MEDIUM
    return LOW
