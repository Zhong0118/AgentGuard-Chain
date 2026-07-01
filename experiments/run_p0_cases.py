"""运行 P0 smoke 数据集，验证规则网关和审计日志。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agentguard_chain.audit import AuditLogger
from agentguard_chain.event import TaskScope, ToolCallEvent
from agentguard_chain.gateway import AgentGuardGateway


def run_cases(
    dataset_path: Path,
    audit_log_path: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    """读取 JSONL 样本，逐条送入 Gateway，并返回基础检测指标。"""
    cases = _load_jsonl(dataset_path)
    gateway = AgentGuardGateway()
    logger = AuditLogger(audit_log_path)

    total = 0
    correct = 0
    attack_total = 0
    normal_total = 0
    detected_attacks = 0
    false_positives = 0
    false_negatives = 0

    for case in cases:
        expected_decision = case["expected_decision"]
        is_attack = expected_decision != "allow"
        attack_total += 1 if is_attack else 0
        normal_total += 0 if is_attack else 1

        for index, tool_call in enumerate(case["tool_calls"], start=1):
            total += 1
            event = _event_from_case(case, tool_call, index, workspace_root)
            decision = gateway.evaluate(event)
            executed = decision.decision == "allow"
            logger.log(
                event,
                decision,
                executed=executed,
                result_preview="Allowed by P0 runner" if executed else "Blocked by P0 runner",
            )

            if decision.decision == expected_decision:
                correct += 1
            if is_attack and decision.decision != "allow":
                detected_attacks += 1
            if is_attack and decision.decision == "allow":
                false_negatives += 1
            if not is_attack and decision.decision != "allow":
                false_positives += 1

    return {
        "total_cases": total,
        "correct_cases": correct,
        "attack_cases": attack_total,
        "normal_cases": normal_total,
        "detected_attacks": detected_attacks,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "accuracy": _rate(correct, total),
        "attack_detection_rate": _rate(detected_attacks, attack_total),
        "false_positive_rate": _rate(false_positives, normal_total),
        "false_negative_rate": _rate(false_negatives, attack_total),
    }


def _event_from_case(
    case: dict[str, Any],
    tool_call: dict[str, Any],
    call_index: int,
    workspace_root: Path,
) -> ToolCallEvent:
    scope = _scope_from_case(case["task_scope"], workspace_root)
    return ToolCallEvent(
        event_id=f"evt-{case['case_id']}-{call_index}",
        session_id=f"sess-{case['case_id']}",
        agent_name=case.get("agent", "p0_runner"),
        user_task=case["user_task"],
        task_scope=scope,
        tool_name=tool_call["tool_name"],
        tool_args=tool_call["tool_args"],
        cwd=str(workspace_root),
        call_index=call_index,
    )


def _scope_from_case(raw_scope: dict[str, Any], workspace_root: Path) -> TaskScope:
    def resolve_paths(values: list[str]) -> list[str]:
        paths = []
        for value in values:
            if value == ".":
                paths.append(str(workspace_root))
            else:
                paths.append(value)
        return paths

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


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _rate(count: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(count / total, 4)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run P0 smoke cases.")
    parser.add_argument("--dataset", default="datasets/p0_smoke_cases.jsonl")
    parser.add_argument("--audit-log", default="logs/p0_audit.jsonl")
    parser.add_argument("--workspace-root", default=".")
    args = parser.parse_args()

    summary = run_cases(
        dataset_path=Path(args.dataset),
        audit_log_path=Path(args.audit_log),
        workspace_root=Path(args.workspace_root).resolve(),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
