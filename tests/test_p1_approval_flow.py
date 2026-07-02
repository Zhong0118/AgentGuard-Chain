import json
import tempfile
import unittest
from pathlib import Path

from agentguard_chain.approval import ApprovalHandler
from agentguard_chain.audit import AuditLogger
from agentguard_chain.event import GuardDecision, TaskScope, ToolCallEvent
from agents.miniagent.agent import MiniAgent, ScriptedPlanner
from agents.miniagent.tools import MiniAgentTools
from agentguard_chain.gateway import AgentGuardGateway


class ApprovalFlowTests(unittest.TestCase):
    def make_event(self, tmpdir: Path) -> ToolCallEvent:
        return ToolCallEvent(
            event_id="evt-ask",
            session_id="sess-ask",
            agent_name="unit",
            user_task="删除临时文件",
            task_scope=TaskScope(
                task_type="cleanup",
                workspace_root=str(tmpdir),
                allowed_paths=[str(tmpdir)],
                denied_paths=[".env"],
                allowed_tools=["delete_file"],
                write_allowed=True,
            ),
            tool_name="delete_file",
            tool_args={"path": "tmp.txt"},
            cwd=str(tmpdir),
        )

    def test_auto_deny_approval_blocks_ask_decision(self):
        with tempfile.TemporaryDirectory() as temp:
            event = self.make_event(Path(temp))
            decision = GuardDecision(
                event_id=event.event_id,
                decision="ask",
                risk_score=0.45,
                risk_level="medium",
                risk_types=["delete_requires_confirmation"],
                matched_rules=["DELETE_REQUIRES_CONFIRMATION"],
            )

            result = ApprovalHandler(mode="auto-deny").resolve(event, decision)

            self.assertTrue(result.required)
            self.assertFalse(result.execute)
            self.assertEqual(result.decision, "user_denied")
            self.assertEqual(result.mode, "auto-deny")

    def test_auto_allow_approval_executes_ask_decision(self):
        with tempfile.TemporaryDirectory() as temp:
            event = self.make_event(Path(temp))
            decision = GuardDecision(
                event_id=event.event_id,
                decision="ask",
                risk_score=0.45,
                risk_level="medium",
                risk_types=["delete_requires_confirmation"],
                matched_rules=["DELETE_REQUIRES_CONFIRMATION"],
            )

            result = ApprovalHandler(mode="auto-allow").resolve(event, decision)

            self.assertTrue(result.required)
            self.assertTrue(result.execute)
            self.assertEqual(result.decision, "user_approved")
            self.assertEqual(result.mode, "auto-allow")

    def test_interactive_approval_accepts_yes(self):
        with tempfile.TemporaryDirectory() as temp:
            event = self.make_event(Path(temp))
            decision = GuardDecision(
                event_id=event.event_id,
                decision="ask",
                risk_score=0.45,
                risk_level="medium",
                risk_types=["delete_requires_confirmation"],
                matched_rules=["DELETE_REQUIRES_CONFIRMATION"],
                reason="删除文件需要确认",
            )
            prompts: list[str] = []

            result = ApprovalHandler(
                mode="interactive",
                input_func=lambda prompt: "y",
                output_func=prompts.append,
            ).resolve(event, decision)

            self.assertTrue(result.required)
            self.assertTrue(result.execute)
            self.assertEqual(result.decision, "user_approved")
            self.assertEqual(result.mode, "interactive")
            self.assertEqual(result.operator, "cli")
            self.assertTrue(any("delete_file" in line for line in prompts))

    def test_interactive_approval_denies_empty_answer(self):
        with tempfile.TemporaryDirectory() as temp:
            event = self.make_event(Path(temp))
            decision = GuardDecision(
                event_id=event.event_id,
                decision="ask",
                risk_score=0.45,
                risk_level="medium",
                risk_types=["delete_requires_confirmation"],
                matched_rules=["DELETE_REQUIRES_CONFIRMATION"],
            )

            result = ApprovalHandler(
                mode="interactive",
                input_func=lambda prompt: "",
                output_func=lambda text: None,
            ).resolve(event, decision)

            self.assertTrue(result.required)
            self.assertFalse(result.execute)
            self.assertEqual(result.decision, "user_denied")
            self.assertEqual(result.mode, "interactive")

    def test_miniagent_records_approval_and_respects_auto_deny(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            (workspace / "tmp.txt").write_text("temporary", encoding="utf-8")
            audit_log = workspace / "audit.jsonl"
            case = {
                "case_id": "ASK_001",
                "user_task": "清理临时文件",
                "task_scope": {
                    "task_type": "cleanup",
                    "allowed_paths": ["."],
                    "denied_paths": [".env"],
                    "allowed_tools": ["delete_file"],
                    "allowed_commands": [],
                    "network_allowed": False,
                    "write_allowed": True,
                    "external_send_allowed": False,
                },
                "tool_calls": [
                    {
                        "tool_name": "delete_file",
                        "tool_args": {"path": "tmp.txt"},
                        "expected_decision": "ask",
                    }
                ],
            }

            agent = MiniAgent(
                planner=ScriptedPlanner(case),
                gateway=AgentGuardGateway(),
                tools=MiniAgentTools(workspace),
                audit_logger=AuditLogger(audit_log),
                workspace_root=workspace,
                approval_handler=ApprovalHandler(mode="auto-deny"),
            )

            summary = agent.run()

            self.assertEqual(summary.steps[0].decision.decision, "ask")
            self.assertFalse(summary.steps[0].executed)
            self.assertTrue((workspace / "tmp.txt").exists())
            record = json.loads(audit_log.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(record["approval"]["decision"], "user_denied")
            self.assertFalse(record["approval"]["execute"])


if __name__ == "__main__":
    unittest.main()
