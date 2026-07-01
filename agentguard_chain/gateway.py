"""P0 安全网关：对单次工具调用做执行前检查。"""

from __future__ import annotations

from .event import GuardDecision, ToolCallEvent
from .guard.policy_engine import PolicyEngine
from .guard.risk_scorer import RiskScorer


class AgentGuardGateway:
    """安全网关总入口，负责编排规则检查和风险评分。"""

    def __init__(
        self,
        policy_engine: PolicyEngine | None = None,
        risk_scorer: RiskScorer | None = None,
    ):
        self.policy_engine = policy_engine or PolicyEngine()
        self.risk_scorer = risk_scorer or RiskScorer()

    def evaluate(self, event: ToolCallEvent) -> GuardDecision:
        # Gateway 只做编排：先收集规则命中，再交给评分器。
        # 这样后续接入行为链检测和 LLM 解释时，不会把核心规则搅在一起。
        policy_result = self.policy_engine.evaluate(event)
        return self.risk_scorer.score(event, policy_result)
