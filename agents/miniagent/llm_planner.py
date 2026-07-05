"""LLM planner for MiniAgent.

LLM mode is for demonstration: an LLM proposes JSON tool_calls, then the
existing MiniAgent loop sends every call through AgentGuard before execution.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol
from urllib import request

from agentguard_chain.event import TaskScope
from agents.miniagent.agent import PlannedToolCall


class LLMPlannerError(ValueError):
    """Raised when the LLM output is not valid MiniAgent tool-call JSON."""


class LLMClient(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str:
        """Return assistant text for the given chat messages."""


class OpenAICompatibleChatClient:
    """Minimal OpenAI-compatible chat completions client.

    The client is intentionally small: MiniAgent LLM mode needs only a single
    response string, while tests inject a fake opener to avoid network access.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.0,
        timeout: int = 60,
        opener: Any | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.opener = opener or request.urlopen

    def complete(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with self.opener(req, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMPlannerError("OpenAI-compatible response did not contain choices[0].message.content.") from exc
        if not isinstance(content, str):
            raise LLMPlannerError("OpenAI-compatible response content must be a string.")
        return content


class LLMPlanner:
    """Planner that asks an LLM to produce strict JSON tool calls."""

    def __init__(
        self,
        *,
        user_task: str,
        task_scope: TaskScope,
        llm_client: LLMClient,
        case_id: str = "LLM_001",
    ):
        self._user_task = user_task
        self._task_scope = task_scope
        self.llm_client = llm_client
        self._case_id = case_id

    @property
    def case_id(self) -> str:
        return self._case_id

    @property
    def user_task(self) -> str:
        return self._user_task

    def task_scope(self, workspace_root: Path) -> TaskScope:
        return self._task_scope

    def plan(self) -> list[PlannedToolCall]:
        raw_text = self.llm_client.complete(
            [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": self._user_task},
            ]
        )
        data = _parse_json_object(raw_text)
        raw_calls = data.get("tool_calls")
        if not isinstance(raw_calls, list):
            raise LLMPlannerError("LLM output must contain a tool_calls list.")

        planned: list[PlannedToolCall] = []
        for index, raw_call in enumerate(raw_calls, start=1):
            if not isinstance(raw_call, dict):
                raise LLMPlannerError(f"tool_calls[{index}] must be an object.")
            tool_name = raw_call.get("tool_name")
            tool_args = raw_call.get("tool_args")
            if not isinstance(tool_name, str) or not tool_name:
                raise LLMPlannerError(f"tool_calls[{index}].tool_name must be a non-empty string.")
            if tool_name not in self._task_scope.allowed_tools:
                raise LLMPlannerError(f"Tool {tool_name!r} is not allowed by the current TaskScope.")
            if not isinstance(tool_args, dict):
                raise LLMPlannerError(f"tool_calls[{index}].tool_args must be an object.")
            planned.append(PlannedToolCall(tool_name=tool_name, tool_args=tool_args, expected_decision="allow"))
        return planned

    def _system_prompt(self) -> str:
        tools = ", ".join(self._task_scope.allowed_tools)
        commands = ", ".join(self._task_scope.allowed_commands) or "(none)"
        return (
            "你是 MiniAgent 的工具调用规划器。只输出 JSON，不要输出 Markdown、解释或代码块。\n"
            "JSON schema: {\"tool_calls\":[{\"tool_name\":\"read_file\",\"tool_args\":{\"path\":\"README.md\"}}]}\n"
            f"allowed_tools: {tools}\n"
            f"allowed_commands: {commands}\n"
            f"write_allowed: {self._task_scope.write_allowed}\n"
            f"network_allowed: {self._task_scope.network_allowed}\n"
            f"external_send_allowed: {self._task_scope.external_send_allowed}\n"
            "如果不需要工具，输出 {\"tool_calls\":[]}。"
        )


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise LLMPlannerError("LLM output must be a single JSON object.") from exc
    if not isinstance(data, dict):
        raise LLMPlannerError("LLM output must be a JSON object.")
    return data
