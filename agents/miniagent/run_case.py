"""Mini-Agent scripted case runner.

scripted mode 不让 LLM 生成工具调用，而是直接读取数据集中的 tool_calls。
这样实验可复现，适合计算检测率、误报率和漏报率。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agentguard_chain.approval import ApprovalHandler
from agentguard_chain.audit import AuditLogger
from agentguard_chain.gateway import AgentGuardGateway
from agents.miniagent.agent import MiniAgent, ScriptedPlanner
from agents.miniagent.tools import MiniAgentTools


def run_dataset(
    dataset_path: Path,
    audit_log_path: Path,
    workspace_root: Path,
    *,
    approval_mode: str = "auto-deny",
) -> dict[str, Any]:
    cases = _load_jsonl(dataset_path)
    gateway = AgentGuardGateway()
    logger = AuditLogger(audit_log_path)
    tools = MiniAgentTools(workspace_root)
    approval_handler = ApprovalHandler(mode=approval_mode)

    total = 0
    correct = 0
    false_positives = 0
    false_negatives = 0
    attack_total = 0
    normal_total = 0
    detected_attacks = 0

    for case in cases:
        agent = MiniAgent(
            planner=ScriptedPlanner(case),
            gateway=gateway,
            tools=tools,
            audit_logger=logger,
            workspace_root=workspace_root,
            approval_handler=approval_handler,
        )
        summary = agent.run()

        for step in summary.steps:
            total += 1
            expected_for_call = step.expected_decision
            call_is_attack = expected_for_call != "allow"
            attack_total += 1 if call_is_attack else 0
            normal_total += 0 if call_is_attack else 1

            if step.decision.decision == expected_for_call:
                correct += 1
            if call_is_attack and step.decision.decision != "allow":
                detected_attacks += 1
            if call_is_attack and step.decision.decision == "allow":
                false_negatives += 1
            if not call_is_attack and step.decision.decision != "allow":
                false_positives += 1

    return {
        "total_calls": total,
        "correct_calls": correct,
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

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _rate(count: int, total: int) -> float:
    return 0.0 if total == 0 else round(count / total, 4)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Mini-Agent scripted cases.")
    parser.add_argument("--dataset", default="datasets/p1_scripted_cases.jsonl")
    parser.add_argument("--audit-log", default="logs/p1_miniagent_audit.jsonl")
    parser.add_argument("--workspace-root", default=".")
    parser.add_argument(
        "--approval-mode",
        choices=["auto-deny", "auto-allow", "interactive"],
        default="auto-deny",
        help="How to handle ask decisions in scripted mode.",
    )
    args = parser.parse_args()
    summary = run_dataset(
        Path(args.dataset),
        Path(args.audit_log),
        Path(args.workspace_root).resolve(),
        approval_mode=args.approval_mode,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
