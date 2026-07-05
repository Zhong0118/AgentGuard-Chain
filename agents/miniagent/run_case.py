"""Mini-Agent scripted case runner.

scripted mode 不让 LLM 生成工具调用，而是直接读取数据集中的 tool_calls。
这样实验可复现，适合计算检测率、误报率和漏报率。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from agentguard_chain.approval import ApprovalHandler
from agentguard_chain.audit import AuditLogger
from agentguard_chain.event import TaskScope
from agentguard_chain.gateway import AgentGuardGateway
from agents.miniagent.agent import MiniAgent, ScriptedPlanner
from agents.miniagent.llm_planner import LLMClient, LLMPlanner, OpenAICompatibleChatClient
from agents.miniagent.tools import MiniAgentTools


class MiniAgentLLMConfigError(RuntimeError):
    """MiniAgent LLM mode configuration error."""


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


def run_llm_prompt(
    *,
    prompt: str,
    audit_log_path: Path,
    workspace_root: Path,
    llm_client: LLMClient | None = None,
    approval_mode: str = "auto-deny",
    task_scope: TaskScope | None = None,
) -> dict[str, Any]:
    """Run MiniAgent with LLM-generated JSON tool calls.

    LLM mode is for real-agent demonstration. Scripted mode remains the stable
    path for dataset metrics.
    """
    workspace_root = workspace_root.resolve()
    task_scope = task_scope or _default_llm_scope(workspace_root)
    llm_client = llm_client or _client_from_env()
    agent = MiniAgent(
        planner=LLMPlanner(user_task=prompt, task_scope=task_scope, llm_client=llm_client),
        gateway=AgentGuardGateway(),
        tools=MiniAgentTools(workspace_root),
        audit_logger=AuditLogger(audit_log_path),
        workspace_root=workspace_root,
        approval_handler=ApprovalHandler(mode=approval_mode),
    )
    summary = agent.run()
    return {
        "mode": "llm",
        "prompt": prompt,
        "audit_log": str(audit_log_path),
        "total_calls": summary.total_calls,
        "executed_calls": summary.executed_calls,
        "blocked_calls": summary.blocked_calls,
        "decisions": [step.decision.decision for step in summary.steps],
        "tools": [step.event.tool_name for step in summary.steps],
    }

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _rate(count: int, total: int) -> float:
    return 0.0 if total == 0 else round(count / total, 4)


def _default_llm_scope(workspace_root: Path) -> TaskScope:
    return TaskScope(
        task_type="miniagent_llm_demo",
        workspace_root=str(workspace_root),
        allowed_paths=[str(workspace_root)],
        denied_paths=[".env", "secrets/", ".aws/credentials", "id_rsa"],
        allowed_tools=["read_file", "write_file", "bash", "call_api", "send_message", "send_mail"],
        allowed_commands=["echo", "python", "pytest", "dir"],
        network_allowed=False,
        write_allowed=True,
        external_send_allowed=False,
    )


def _client_from_env() -> OpenAICompatibleChatClient:
    api_key = (
        os.getenv("MINIAGENT_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
        or ""
    )
    if not api_key:
        raise MiniAgentLLMConfigError(
            "No API key found. Set MINIAGENT_API_KEY, OPENAI_API_KEY, or DEEPSEEK_API_KEY."
        )
    return OpenAICompatibleChatClient(
        api_key=api_key,
        base_url=os.getenv("MINIAGENT_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1",
        model=os.getenv("MINIAGENT_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Mini-Agent scripted cases.")
    parser.add_argument(
        "--mode",
        choices=["scripted", "llm"],
        default="scripted",
        help="scripted replays JSONL cases for metrics; llm asks an OpenAI-compatible model for JSON tool_calls.",
    )
    parser.add_argument("--dataset", default="datasets/p1_scripted_cases.jsonl")
    parser.add_argument("--audit-log", default="logs/p1_miniagent_audit.jsonl")
    parser.add_argument("--workspace-root", default=".")
    parser.add_argument("--prompt", default="请总结 README.md", help="Prompt for --mode llm.")
    parser.add_argument(
        "--approval-mode",
        choices=["auto-deny", "auto-allow", "interactive", "interactive-all"],
        default="auto-deny",
        help="How to handle guarded tool execution. interactive handles ask; interactive-all asks for every non-deny call.",
    )
    args = parser.parse_args()
    try:
        if args.mode == "llm":
            summary = run_llm_prompt(
                prompt=args.prompt,
                audit_log_path=Path(args.audit_log),
                workspace_root=Path(args.workspace_root).resolve(),
                approval_mode=args.approval_mode,
            )
        else:
            summary = run_dataset(
                Path(args.dataset),
                Path(args.audit_log),
                Path(args.workspace_root).resolve(),
                approval_mode=args.approval_mode,
            )
    except MiniAgentLLMConfigError as exc:
        print(json.dumps({"mode": args.mode, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from exc
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
