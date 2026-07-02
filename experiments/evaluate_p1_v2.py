"""P1 v2 消融评估。

这个脚本不真实执行危险工具，而是重放 scripted 数据集中的 ToolCallEvent，
比较不同防线组合的检测率、误报率、漏报率和证据数量。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentguard_chain.approval import ApprovalHandler
from agentguard_chain.decision import ALLOW, DENY
from agentguard_chain.event import GuardDecision, TaskScope, ToolCallEvent
from agentguard_chain.gateway import AgentGuardGateway
from agentguard_chain.guard import InputInspector, ResultInspector
from agentguard_chain.guard.policy_engine import PolicyEngine
from agentguard_chain.guard.risk_scorer import RiskScorer


VARIANT_ORDER = [
    "baseline",
    "input_only",
    "tool_guard",
    "tool_chain",
    "tool_chain_result",
    "full_guard",
]


@dataclass(slots=True)
class MetricAccumulator:
    """累计单个消融版本的指标。"""

    total_calls: int = 0
    correct_calls: int = 0
    attack_cases: int = 0
    normal_cases: int = 0
    detected_attacks: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    input_findings: int = 0
    output_findings: int = 0
    chain_alerts: int = 0
    chain_graph_edges: int = 0
    approval_required: int = 0
    matched_rules: dict[str, int] = field(default_factory=dict)

    def add_decision(
        self,
        *,
        expected: str,
        predicted: str,
        decision: GuardDecision | None = None,
    ) -> None:
        self.total_calls += 1
        is_attack = expected != ALLOW
        self.attack_cases += 1 if is_attack else 0
        self.normal_cases += 0 if is_attack else 1

        if predicted == expected:
            self.correct_calls += 1
        if is_attack and predicted != ALLOW:
            self.detected_attacks += 1
        if is_attack and predicted == ALLOW:
            self.false_negatives += 1
        if not is_attack and predicted != ALLOW:
            self.false_positives += 1

        if decision is not None:
            self.chain_alerts += len(decision.chain_alerts)
            self.chain_graph_edges += sum(
                len(graph.get("edges", [])) for graph in decision.chain_graphs
            )
            for rule_id in decision.matched_rules:
                self.matched_rules[rule_id] = self.matched_rules.get(rule_id, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "correct_calls": self.correct_calls,
            "attack_cases": self.attack_cases,
            "normal_cases": self.normal_cases,
            "detected_attacks": self.detected_attacks,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "accuracy": _rate(self.correct_calls, self.total_calls),
            "attack_detection_rate": _rate(self.detected_attacks, self.attack_cases),
            "false_positive_rate": _rate(self.false_positives, self.normal_cases),
            "false_negative_rate": _rate(self.false_negatives, self.attack_cases),
            "input_findings": self.input_findings,
            "output_findings": self.output_findings,
            "chain_alerts": self.chain_alerts,
            "chain_graph_edges": self.chain_graph_edges,
            "approval_required": self.approval_required,
            "matched_rules": dict(sorted(self.matched_rules.items())),
        }


def evaluate_dataset(dataset_path: Path, workspace_root: Path) -> dict[str, Any]:
    cases = _load_jsonl(dataset_path)
    workspace_root = workspace_root.resolve()
    input_inspector = InputInspector()
    result_inspector = ResultInspector()
    approval_handler = ApprovalHandler(mode="auto-deny")

    policy_engine = PolicyEngine()
    risk_scorer = RiskScorer()
    chain_gateways = {
        "tool_chain": AgentGuardGateway(),
        "tool_chain_result": AgentGuardGateway(),
        "full_guard": AgentGuardGateway(),
    }
    metrics = {name: MetricAccumulator() for name in VARIANT_ORDER}

    for case in cases:
        case_input_findings = input_inspector.inspect(case.get("user_task", ""), source="user_task")

        for index, tool_call in enumerate(case["tool_calls"], start=1):
            expected = tool_call.get("expected_decision", case.get("expected_decision", ALLOW))
            event = _event_from_case(case, tool_call, index, workspace_root)

            _record_baseline(metrics["baseline"], expected)
            _record_input_only(metrics["input_only"], expected, case_input_findings)
            _record_tool_guard(metrics["tool_guard"], expected, event, policy_engine, risk_scorer)

            for variant in ["tool_chain", "tool_chain_result", "full_guard"]:
                decision = chain_gateways[variant].evaluate(event)
                metrics[variant].add_decision(
                    expected=expected,
                    predicted=decision.decision,
                    decision=decision,
                )
                if variant in {"tool_chain_result", "full_guard"} and decision.decision == ALLOW:
                    metrics[variant].output_findings += _count_output_findings(
                        event,
                        workspace_root,
                        result_inspector,
                    )
                if variant == "full_guard":
                    metrics[variant].input_findings += len(case_input_findings)
                    approval = approval_handler.resolve(event, decision)
                    metrics[variant].approval_required += 1 if approval.required else 0

    variants = {name: metrics[name].to_dict() for name in VARIANT_ORDER}
    return {
        "dataset": {
            "path": str(dataset_path),
            "total_cases": len(cases),
            "total_calls": variants["full_guard"]["total_calls"],
        },
        "variants": variants,
        "ranking_by_detection_rate": _ranking(variants),
    }


def _record_baseline(metric: MetricAccumulator, expected: str) -> None:
    metric.add_decision(expected=expected, predicted=ALLOW)


def _record_input_only(
    metric: MetricAccumulator,
    expected: str,
    input_findings: list[Any],
) -> None:
    metric.input_findings += len(input_findings)
    predicted = DENY if input_findings else ALLOW
    metric.add_decision(expected=expected, predicted=predicted)


def _record_tool_guard(
    metric: MetricAccumulator,
    expected: str,
    event: ToolCallEvent,
    policy_engine: PolicyEngine,
    risk_scorer: RiskScorer,
) -> None:
    policy_result = policy_engine.evaluate(event)
    decision = risk_scorer.score(event, policy_result)
    metric.add_decision(expected=expected, predicted=decision.decision, decision=decision)


def _count_output_findings(
    event: ToolCallEvent,
    workspace_root: Path,
    result_inspector: ResultInspector,
) -> int:
    if event.tool_name != "read_file":
        return 0

    path_text = str(event.tool_args.get("path") or event.tool_args.get("file_path") or "")
    target = Path(path_text)
    if not target.is_absolute():
        target = workspace_root / target
    try:
        resolved = target.resolve()
        resolved.relative_to(workspace_root)
    except (OSError, ValueError):
        return 0
    if not resolved.exists() or not resolved.is_file():
        return 0
    return len(result_inspector.inspect(resolved.read_text(encoding="utf-8", errors="replace")))


def _event_from_case(
    case: dict[str, Any],
    tool_call: dict[str, Any],
    call_index: int,
    workspace_root: Path,
) -> ToolCallEvent:
    return ToolCallEvent(
        event_id=f"evt-{case['case_id']}-{call_index}",
        session_id=f"sess-{case['case_id']}",
        agent_name="p1_eval",
        user_task=case["user_task"],
        task_scope=_scope_from_case(case["task_scope"], workspace_root),
        tool_name=tool_call["tool_name"],
        tool_args=tool_call["tool_args"],
        cwd=str(workspace_root),
        call_index=call_index,
    )


def _scope_from_case(raw_scope: dict[str, Any], workspace_root: Path) -> TaskScope:
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


def _ranking(variants: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    priority = {name: index for index, name in enumerate(VARIANT_ORDER)}
    ranked = sorted(
        variants.items(),
        key=lambda item: (
            item[1]["attack_detection_rate"],
            -item[1]["false_positive_rate"],
            priority[item[0]],
        ),
        reverse=True,
    )
    return [
        {
            "variant": name,
            "attack_detection_rate": values["attack_detection_rate"],
            "false_positive_rate": values["false_positive_rate"],
            "false_negative_rate": values["false_negative_rate"],
        }
        for name, values in ranked
    ]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _rate(count: int, total: int) -> float:
    return 0.0 if total == 0 else round(count / total, 4)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run P1 v2 ablation evaluation.")
    parser.add_argument("--dataset", default="datasets/p1_scripted_cases.jsonl")
    parser.add_argument("--workspace-root", default=".")
    parser.add_argument("--output", default="logs/p1_v2_eval.json")
    args = parser.parse_args()

    report = evaluate_dataset(Path(args.dataset), Path(args.workspace_root))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
