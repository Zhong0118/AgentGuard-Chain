"""P1 行为链检测。

单步工具调用可能看起来正常，但多步组合可能形成攻击链。
ChainDetector 按 session 记录历史状态，用来发现跨步骤风险。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from agentguard_chain.event import ToolCallEvent
from agentguard_chain.guard.parameter_checker import PolicyFinding


@dataclass(slots=True)
class SessionTrace:
    """一个会话内的关键行为摘要，不保存完整工具输出。"""

    sensitive_reads: list[dict[str, Any]] = field(default_factory=list)
    created_scripts: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ChainResult:
    """行为链检测结果，包含规则命中和展示用告警。"""

    findings: list[PolicyFinding] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    graphs: list[dict[str, Any]] = field(default_factory=list)


class ChainDetector:
    """检测敏感读取后外发、写脚本后执行等跨步骤攻击链。"""

    SCRIPT_SUFFIXES = (".sh", ".py", ".ps1", ".bat", ".cmd")

    def __init__(self):
        self._traces: dict[str, SessionTrace] = {}

    def inspect(self, event: ToolCallEvent) -> ChainResult:
        trace = self._traces.setdefault(event.session_id, SessionTrace())
        result = ChainResult()

        if _is_sensitive_read(event):
            trace.sensitive_reads.append(
                {
                    "event_id": event.event_id,
                    "tool_name": event.tool_name,
                    "path": _path_arg(event),
                    "call_index": event.call_index,
                }
            )

        if _is_script_write(event):
            trace.created_scripts.append(
                {
                    "event_id": event.event_id,
                    "tool_name": event.tool_name,
                    "path": _path_arg(event),
                    "call_index": event.call_index,
                }
            )

        if _is_external_send(event) and trace.sensitive_reads:
            alert = {
                "chain_type": "SensitiveReadToExternalSend",
                "source_event_id": trace.sensitive_reads[-1]["event_id"],
                "sink_event_id": event.event_id,
                "reason": "会话中先出现敏感文件读取，随后出现外部发送行为。",
            }
            result.alerts.append(alert)
            result.graphs.append(
                _build_chain_graph(
                    chain_type="SensitiveReadToExternalSend",
                    severity="critical",
                    source=trace.sensitive_reads[-1],
                    sink=_event_node(event),
                    relation="sensitive_data_flow",
                    reason=alert["reason"],
                )
            )
            result.findings.append(
                PolicyFinding(
                    rule_id="CHAIN_SENSITIVE_READ_TO_EXTERNAL_SEND",
                    risk_type="behavior_chain",
                    severity="critical",
                    reason=alert["reason"],
                )
            )

        executed_script = _executed_script_path(event)
        if executed_script:
            for script in trace.created_scripts:
                if _same_script(script["path"], executed_script):
                    alert = {
                        "chain_type": "WriteScriptToExecute",
                        "source_event_id": script["event_id"],
                        "sink_event_id": event.event_id,
                        "reason": "会话中先写入脚本文件，随后执行该脚本。",
                    }
                    result.alerts.append(alert)
                    result.graphs.append(
                        _build_chain_graph(
                            chain_type="WriteScriptToExecute",
                            severity="critical",
                            source=script,
                            sink=_event_node(event),
                            relation="script_execution_flow",
                            reason=alert["reason"],
                        )
                    )
                    result.findings.append(
                        PolicyFinding(
                            rule_id="CHAIN_WRITE_SCRIPT_TO_EXECUTE",
                            risk_type="behavior_chain",
                            severity="critical",
                            reason=alert["reason"],
                        )
                    )
                    break

        return result


def _is_sensitive_read(event: ToolCallEvent) -> bool:
    if event.tool_name != "read_file":
        return False
    path = _path_arg(event).replace("\\", "/").lower()
    return path.endswith(".env") or "/secrets/" in f"/{path}/" or "id_rsa" in path


def _is_script_write(event: ToolCallEvent) -> bool:
    if event.tool_name not in {"write_file", "edit_file"}:
        return False
    return _path_arg(event).lower().endswith(ChainDetector.SCRIPT_SUFFIXES)


def _is_external_send(event: ToolCallEvent) -> bool:
    if event.tool_name in {"send_message", "send_mail", "call_api"}:
        target = str(event.tool_args.get("target") or event.tool_args.get("to") or event.tool_args.get("endpoint") or "")
        return bool(re.search(r"https?://|webhook|@", target, flags=re.IGNORECASE))
    if event.tool_name in {"bash", "run_command"}:
        command = str(event.tool_args.get("command", ""))
        return bool(re.search(r"\bcurl\b|\bwget\b|https?://", command, flags=re.IGNORECASE))
    return False


def _executed_script_path(event: ToolCallEvent) -> str:
    if event.tool_name not in {"bash", "run_command"}:
        return ""
    command = str(event.tool_args.get("command", ""))
    match = re.search(r"\b(?:bash|sh|python|pwsh|powershell)\s+([^\s;&|]+)", command)
    return match.group(1).strip("\"'") if match else ""


def _path_arg(event: ToolCallEvent) -> str:
    return str(event.tool_args.get("path") or event.tool_args.get("file_path") or "")


def _same_script(recorded: str, executed: str) -> bool:
    return Path(recorded).as_posix().lower().endswith(Path(executed).as_posix().lower())


def _event_node(event: ToolCallEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "tool_name": event.tool_name,
        "path": _path_arg(event),
        "call_index": event.call_index,
    }


def _build_chain_graph(
    *,
    chain_type: str,
    severity: str,
    source: dict[str, Any],
    sink: dict[str, Any],
    relation: str,
    reason: str,
) -> dict[str, Any]:
    chain_id = f"chain-{source['event_id']}-{sink['event_id']}"
    return {
        "chain_id": chain_id,
        "chain_type": chain_type,
        "severity": severity,
        "nodes": [
            {
                "event_id": source["event_id"],
                "tool_name": source.get("tool_name", ""),
                "path": source.get("path", ""),
                "call_index": source.get("call_index", 0),
            },
            {
                "event_id": sink["event_id"],
                "tool_name": sink.get("tool_name", ""),
                "path": sink.get("path", ""),
                "call_index": sink.get("call_index", 0),
            },
        ],
        "edges": [
            {
                "from": source["event_id"],
                "to": sink["event_id"],
                "relation": relation,
            }
        ],
        "reason": reason,
    }
