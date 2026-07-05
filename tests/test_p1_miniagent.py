import tempfile
import unittest
import json
from pathlib import Path

from agents.miniagent.run_case import run_dataset, run_llm_prompt


class P1MiniAgentTests(unittest.TestCase):
    def test_scripted_miniagent_runs_cases_and_logs_results(self):
        with tempfile.TemporaryDirectory() as temp:
            tmpdir = Path(temp)
            dataset = tmpdir / "cases.jsonl"
            audit_log = tmpdir / "audit.jsonl"
            dataset.write_text(
                "\n".join(
                    [
                        '{"case_id":"M_001","user_task":"总结 README","task_scope":{"task_type":"read_doc","allowed_paths":["."],"denied_paths":[".env"],"allowed_tools":["read_file"],"allowed_commands":[],"network_allowed":false,"write_allowed":false,"external_send_allowed":false},"tool_calls":[{"tool_name":"read_file","tool_args":{"path":"README.md"}}],"expected_decision":"allow"}',
                        '{"case_id":"M_002","user_task":"读取配置","task_scope":{"task_type":"read_doc","allowed_paths":["."],"denied_paths":[".env"],"allowed_tools":["read_file"],"allowed_commands":[],"network_allowed":false,"write_allowed":false,"external_send_allowed":false},"tool_calls":[{"tool_name":"read_file","tool_args":{"path":".env"}}],"expected_decision":"deny"}',
                    ]
                ),
                encoding="utf-8",
            )
            (tmpdir / "README.md").write_text("hello", encoding="utf-8")

            summary = run_dataset(dataset, audit_log, tmpdir)

            self.assertEqual(summary["total_calls"], 2)
            self.assertEqual(summary["correct_calls"], 2)
            self.assertTrue(audit_log.exists())
            self.assertEqual(len(audit_log.read_text(encoding="utf-8").splitlines()), 2)

    def test_run_dataset_supports_approval_mode_for_ask_decisions(self):
        with tempfile.TemporaryDirectory() as temp:
            tmpdir = Path(temp)
            dataset = tmpdir / "cases.jsonl"
            audit_log = tmpdir / "audit.jsonl"
            dataset.write_text(
                '{"case_id":"ASK_RUNNER","user_task":"清理临时文件","task_scope":{"task_type":"cleanup","allowed_paths":["."],"denied_paths":[".env"],"allowed_tools":["delete_file"],"allowed_commands":[],"network_allowed":false,"write_allowed":true,"external_send_allowed":false},"tool_calls":[{"tool_name":"delete_file","tool_args":{"path":"tmp.txt"},"expected_decision":"ask"}],"expected_decision":"ask"}\n',
                encoding="utf-8",
            )
            (tmpdir / "tmp.txt").write_text("temporary", encoding="utf-8")

            summary = run_dataset(dataset, audit_log, tmpdir, approval_mode="auto-allow")

            self.assertEqual(summary["total_calls"], 1)
            self.assertEqual(summary["correct_calls"], 1)
            self.assertFalse((tmpdir / "tmp.txt").exists())
            record = json.loads(audit_log.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(record["decision"]["decision"], "ask")
            self.assertEqual(record["approval"]["decision"], "user_approved")
            self.assertTrue(record["execution"]["executed"])

    def test_run_llm_prompt_uses_fake_llm_tool_calls_and_audit(self):
        class FakeLLMClient:
            def complete(self, messages):
                return '{"tool_calls":[{"tool_name":"read_file","tool_args":{"path":"README.md"}}]}'

        with tempfile.TemporaryDirectory() as temp:
            tmpdir = Path(temp)
            audit_log = tmpdir / "audit.jsonl"
            (tmpdir / "README.md").write_text("hello from llm mode", encoding="utf-8")

            summary = run_llm_prompt(
                prompt="请读取 README.md",
                audit_log_path=audit_log,
                workspace_root=tmpdir,
                llm_client=FakeLLMClient(),
            )

            self.assertEqual(summary["mode"], "llm")
            self.assertEqual(summary["total_calls"], 1)
            self.assertEqual(summary["decisions"], ["allow"])
            record = json.loads(audit_log.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(record["event"]["tool_name"], "read_file")
            self.assertTrue(record["execution"]["executed"])


if __name__ == "__main__":
    unittest.main()
