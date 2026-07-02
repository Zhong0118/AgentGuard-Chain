import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from agents.corecoder_guarded_runner import (
    RealLLMConfigError,
    format_summary_json,
    run_corecoder_real_llm_guarded,
    run_corecoder_scripted_demo,
)


@dataclass
class _FakeConfig:
    model: str = "fake-model"
    api_key: str = "fake-key"
    base_url: str | None = "http://fake.local/v1"
    temperature: float = 0.0
    max_tokens: int = 128
    max_context_tokens: int = 2048
    provider: str = "openai"


class _FakeLLM:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0


class _FakeCoreCoderAgent:
    def __init__(self, llm):
        self.llm = llm
        self.tools = []
        self._exec_tool = None
        self.max_context_tokens = None

    def chat(self, prompt, on_token=None, on_tool=None):
        return f"fake real llm response: {prompt}"


class CoreCoderGuardedRunnerTests(unittest.TestCase):
    def test_summary_json_is_safe_for_windows_console_encoding(self):
        text = format_summary_json({"response": "bad replacement char �"})

        text.encode("gbk")
        self.assertIn("\\ufffd", text)
        self.assertIn("response_preview", text)
        self.assertNotIn("\"response\"", text)

    def test_scripted_corecoder_demo_blocks_sensitive_file_and_logs_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            audit_log = workspace / "corecoder_audit.jsonl"

            summary = run_corecoder_scripted_demo(
                demo="sensitive-file",
                workspace_root=workspace,
                audit_log_path=audit_log,
            )

            self.assertEqual(summary["decision"], "deny")
            self.assertFalse(summary["executed"])
            self.assertIn("AgentGuard blocked", summary["response"])

            records = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["event"]["agent_name"], "corecoder")
            self.assertEqual(records[0]["event"]["tool_name"], "read_file")
            self.assertFalse(records[0]["execution"]["executed"])

    def test_scripted_corecoder_demo_allows_normal_read_through_corecoder_loop(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            (workspace / "workflow.md").write_text("CoreCoder normal read", encoding="utf-8")
            audit_log = workspace / "corecoder_audit.jsonl"

            summary = run_corecoder_scripted_demo(
                demo="normal-read",
                workspace_root=workspace,
                audit_log_path=audit_log,
                approval_mode="auto-deny",
            )

            self.assertEqual(summary["decision"], "allow")
            self.assertTrue(summary["executed"])
            self.assertIn("CoreCoder normal read", summary["response"])

    def test_real_llm_guarded_runner_uses_config_and_wraps_agent(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            audit_log = workspace / "corecoder_real_audit.jsonl"
            created = {}

            def llm_factory(**kwargs):
                created["llm_kwargs"] = kwargs
                return _FakeLLM(**kwargs)

            def agent_factory(llm, max_context_tokens):
                created["agent_llm"] = llm
                created["max_context_tokens"] = max_context_tokens
                return _FakeCoreCoderAgent(llm)

            summary = run_corecoder_real_llm_guarded(
                prompt="请总结 workflow.md",
                workspace_root=workspace,
                audit_log_path=audit_log,
                config=_FakeConfig(),
                llm_factory=llm_factory,
                agent_factory=agent_factory,
            )

        self.assertEqual(summary["mode"], "real-llm")
        self.assertEqual(summary["model"], "fake-model")
        self.assertEqual(summary["base_url"], "http://fake.local/v1")
        self.assertEqual(summary["response"], "fake real llm response: 请总结 workflow.md")
        self.assertEqual(created["llm_kwargs"]["model"], "fake-model")
        self.assertEqual(created["max_context_tokens"], 2048)

    def test_real_llm_guarded_runner_requires_api_key(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(RealLLMConfigError):
                run_corecoder_real_llm_guarded(
                    prompt="hello",
                    workspace_root=Path(temp),
                    audit_log_path=Path(temp) / "audit.jsonl",
                    config=_FakeConfig(api_key=""),
                    llm_factory=lambda **kwargs: _FakeLLM(**kwargs),
                    agent_factory=lambda llm, max_context_tokens: _FakeCoreCoderAgent(llm),
                )


if __name__ == "__main__":
    unittest.main()
