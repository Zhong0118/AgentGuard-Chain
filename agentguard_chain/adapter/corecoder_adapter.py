"""CoreCoder 适配层：把真实 Coding Agent 接到 AgentGuard 网关前。

这里不改 CoreCoder 原始源码，而是在适配层覆盖/包装 `_exec_tool()`：
CoreCoder 仍负责让 LLM 产生工具调用，AgentGuard 负责在工具执行前审计。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentguard_chain.approval import ApprovalHandler
from agentguard_chain.audit.logger import AuditLogger
from agentguard_chain.event import TaskScope, ToolCallEvent
from agentguard_chain.gateway import AgentGuardGateway
from agentguard_chain.guard import InputInspector, OutputRedactor, ResultInspector


class CoreCoderAdapter:
    """把 CoreCoder 的工具调用格式转换成 AgentGuard 的统一事件。"""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()

    def to_event(
        self,
        *,
        session_id: str,
        user_task: str,
        tool_name: str,
        tool_args: dict[str, Any],
        task_scope: TaskScope,
        call_index: int,
    ) -> ToolCallEvent:
        return ToolCallEvent(
            session_id=session_id,
            agent_name="corecoder",
            user_task=user_task,
            task_scope=task_scope,
            tool_name=tool_name,
            tool_args=tool_args,
            cwd=str(self.workspace_root),
            call_index=call_index,
        )


class GuardedCoreCoderAgent:
    """CoreCoder 的安全包装器，在真正执行 tool.execute 前先过网关。

    设计重点：
    - 不修改 CoreCoder 的 agent loop 和工具实现，降低接入成本。
    - 如果传入 corecoder_agent，会直接替换它的 `_exec_tool`，让原 chat 流程自动受保护。
    - 如果只传入 tools，也可以在测试或演示中直接调用 `_exec_tool()` 验证阻断效果。
    """

    def __init__(
        self,
        *,
        workspace_root: Path,
        task_scope: TaskScope,
        user_task: str,
        session_id: str,
        corecoder_agent: Any | None = None,
        llm: Any | None = None,
        tools: list[Any] | None = None,
        gateway: AgentGuardGateway | None = None,
        audit_logger: AuditLogger | None = None,
        result_inspector: ResultInspector | None = None,
        output_redactor: OutputRedactor | None = None,
        approval_handler: ApprovalHandler | None = None,
        input_inspector: InputInspector | None = None,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.task_scope = task_scope
        self.user_task = user_task
        self.session_id = session_id
        self.adapter = CoreCoderAdapter(self.workspace_root)
        self.gateway = gateway or AgentGuardGateway()
        self.audit_logger = audit_logger
        self.result_inspector = result_inspector or ResultInspector()
        self.output_redactor = output_redactor or OutputRedactor()
        self.approval_handler = approval_handler or ApprovalHandler()
        self.input_inspector = input_inspector or InputInspector()
        self.input_findings = [
            finding.to_dict() for finding in self.input_inspector.inspect(user_task, source="user_task")
        ]
        self.call_index = 0

        if corecoder_agent is not None:
            self._corecoder_agent = corecoder_agent
            self.tools = list(getattr(corecoder_agent, "tools", tools or []))
            # 把原 Agent 的工具执行入口替换为受保护版本，chat 逻辑无需改动。
            corecoder_agent._exec_tool = self._exec_tool
        else:
            self._corecoder_agent = None
            self.tools = list(tools or [])
            if llm is not None and tools is None:
                # 只有真正需要构造 CoreCoder Agent 时才导入，避免测试环境被 LLM 依赖拖住。
                from agents.CoreCoder.corecoder.agent import Agent

                self._corecoder_agent = Agent(llm=llm)
                self.tools = list(self._corecoder_agent.tools)
                self._corecoder_agent._exec_tool = self._exec_tool

    def chat(self, user_input: str, on_token=None, on_tool=None) -> str:
        """把对话交给原 CoreCoder Agent，但工具执行会被本包装器拦截。"""
        if self._corecoder_agent is None:
            raise RuntimeError("chat() requires a wrapped CoreCoder Agent or llm.")
        return self._corecoder_agent.chat(user_input, on_token=on_token, on_tool=on_tool)

    def _exec_tool(self, tc: Any) -> str:
        """CoreCoder 工具执行前的强制安全边界。"""
        self.call_index += 1
        event = self.adapter.to_event(
            session_id=self.session_id,
            user_task=self.user_task,
            tool_name=tc.name,
            tool_args=dict(tc.arguments or {}),
            task_scope=self.task_scope,
            call_index=self.call_index,
        )
        decision = self.gateway.evaluate(event)
        approval = self.approval_handler.resolve(event, decision)

        if not approval.execute:
            result = (
                "AgentGuard blocked tool call "
                f"{tc.name}: {_blocked_reason(decision.reason, decision.risk_types, approval.decision)}"
            )
            self._log(
                event,
                decision,
                executed=False,
                result_preview=result,
                input_findings=self.input_findings,
                approval=approval.to_dict(),
            )
            return result

        tool = self._find_tool(tc.name)
        if tool is None:
            result = f"Error: unknown tool '{tc.name}'"
            self._log(
                event,
                decision,
                executed=False,
                result_preview=result,
                input_findings=self.input_findings,
                approval=_execution_failed_approval(approval.to_dict(), result),
            )
            return result

        try:
            result = tool.execute(**tc.arguments)
        except TypeError as exc:
            result = f"Error: bad arguments for {tc.name}: {exc}"
        except Exception as exc:
            result = f"Error executing {tc.name}: {exc}"

        # 真实 Agent 会继续消费工具结果，因此返回前也要脱敏，避免秘密进入后续上下文。
        raw_result = str(result)
        findings = self.result_inspector.inspect(raw_result)
        redacted = self.output_redactor.redact(raw_result)
        self._log(
            event,
            decision,
            executed=True,
            result_preview=redacted.text,
            input_findings=self.input_findings,
            output_findings=[finding.to_dict() for finding in findings],
            redaction=redacted.to_dict(),
            approval=approval.to_dict(),
        )
        return redacted.text

    def _find_tool(self, name: str) -> Any | None:
        for tool in self.tools:
            if getattr(tool, "name", None) == name:
                return tool
        return None

    def _log(
        self,
        event: ToolCallEvent,
        decision: Any,
        *,
        executed: bool,
        result_preview: str,
        input_findings: list[dict[str, Any]] | None = None,
        output_findings: list[dict[str, Any]] | None = None,
        redaction: dict[str, Any] | None = None,
        approval: dict[str, Any] | None = None,
    ) -> None:
        if self.audit_logger is None:
            return
        self.audit_logger.log(
            event,
            decision,
            executed=executed,
            result_preview=result_preview[:500],
            input_findings=input_findings,
            output_findings=output_findings,
            redaction=redaction,
            approval=approval,
        )


def _blocked_reason(reason: str, risk_types: list[str], approval_decision: str) -> str:
    if approval_decision != "not_required":
        return f"approval flow {approval_decision}"
    return reason or ", ".join(risk_types)


def _execution_failed_approval(approval: dict[str, Any], reason: str) -> dict[str, Any]:
    adjusted = dict(approval)
    adjusted["execute"] = False
    adjusted["decision"] = "execution_failed"
    adjusted["reason"] = reason
    return adjusted
