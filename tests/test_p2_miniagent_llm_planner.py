import tempfile
import unittest
import json
from pathlib import Path

from agentguard_chain.event import TaskScope
from agents.miniagent.llm_planner import LLMPlanner, LLMPlannerError, OpenAICompatibleChatClient


class _FakeLLMClient:
    def __init__(self, response: str):
        self.response = response
        self.messages = []

    def complete(self, messages):
        self.messages = messages
        return self.response


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class _FakeOpener:
    def __init__(self):
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        return _FakeHTTPResponse(
            {"choices": [{"message": {"content": '{"tool_calls":[]}'}}]}
        )


class LLMPlannerTests(unittest.TestCase):
    def make_scope(self, workspace: Path) -> TaskScope:
        return TaskScope(
            task_type="llm_demo",
            workspace_root=str(workspace),
            allowed_paths=[str(workspace)],
            denied_paths=[".env"],
            allowed_tools=["read_file", "call_api"],
            allowed_commands=[],
            network_allowed=False,
            write_allowed=False,
            external_send_allowed=False,
        )

    def test_llm_planner_parses_json_tool_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            planner = LLMPlanner(
                user_task="请读取 README.md",
                task_scope=self.make_scope(workspace),
                llm_client=_FakeLLMClient(
                    '{"tool_calls":[{"tool_name":"read_file","tool_args":{"path":"README.md"}}]}'
                ),
            )

            calls = planner.plan()

            self.assertEqual(planner.case_id, "LLM_001")
            self.assertEqual(calls[0].tool_name, "read_file")
            self.assertEqual(calls[0].tool_args, {"path": "README.md"})
            self.assertIn("只输出 JSON", planner.llm_client.messages[0]["content"])

    def test_llm_planner_rejects_non_json_output(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            planner = LLMPlanner(
                user_task="请读取 README.md",
                task_scope=self.make_scope(workspace),
                llm_client=_FakeLLMClient("我会调用 read_file 工具"),
            )

            with self.assertRaises(LLMPlannerError):
                planner.plan()

    def test_llm_planner_rejects_tool_not_in_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            planner = LLMPlanner(
                user_task="请删除文件",
                task_scope=self.make_scope(workspace),
                llm_client=_FakeLLMClient(
                    '{"tool_calls":[{"tool_name":"delete_file","tool_args":{"path":"README.md"}}]}'
                ),
            )

            with self.assertRaises(LLMPlannerError):
                planner.plan()

    def test_openai_compatible_client_posts_chat_completion_request(self):
        opener = _FakeOpener()
        client = OpenAICompatibleChatClient(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="demo-model",
            opener=opener,
        )

        content = client.complete([{"role": "user", "content": "hello"}])

        request, timeout = opener.requests[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(content, '{"tool_calls":[]}')
        self.assertEqual(request.full_url, "https://api.example.com/v1/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer test-key")
        self.assertEqual(body["model"], "demo-model")
        self.assertEqual(body["messages"][0]["content"], "hello")
        self.assertEqual(timeout, 60)


if __name__ == "__main__":
    unittest.main()
