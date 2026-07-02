"""基础 Streamlit Dashboard。

Dashboard 是审计证据展示层：读取 JSONL，不直接参与安全决策。
运行方式：streamlit run dashboard/app.py
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    import streamlit as st
except ImportError:  # pragma: no cover - 方便未安装 streamlit 时直接导入文件
    st = None


DEFAULT_SOURCES = (
    ("miniagent-scripted", Path("logs/p1_miniagent_audit.jsonl"), "mock-tools"),
    ("corecoder-guarded-demo", Path("logs/corecoder_guarded_audit.jsonl"), "scripted-llm"),
)


def load_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_records_from_sources(sources: list[tuple[str, Path, str]] | tuple[tuple[str, Path, str], ...]) -> list[dict]:
    """读取多份审计日志，并标记来源和当前 demo/mock 模式。"""
    records: list[dict] = []
    for source_name, path, execution_mode in sources:
        for record in load_records(path):
            enriched = dict(record)
            enriched["_source"] = source_name
            enriched["_execution_mode"] = execution_mode
            enriched["_log_path"] = str(path)
            records.append(enriched)
    return records


def decision_counts(records: list[dict]) -> dict[str, int]:
    """统计 allow/ask/deny 数量，供顶部指标和测试复用。"""
    counts: dict[str, int] = {}
    for record in records:
        decision = record["decision"]["decision"]
        counts[decision] = counts.get(decision, 0) + 1
    return counts


def agent_source_counts(records: list[dict]) -> dict[str, int]:
    """按 agent 与日志来源统计，避免把 mock/demo 当成真实生产流量。"""
    counts: dict[str, int] = {}
    for record in records:
        agent = record["event"].get("agent_name", "")
        source = record.get("_source", "unknown")
        key = f"{agent}|{source}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def timeline_rows(records: list[dict]) -> list[dict]:
    """把原始审计记录压平成工具调用时间线。"""
    rows: list[dict] = []
    for record in records:
        event = record["event"]
        decision = record["decision"]
        execution = record["execution"]
        findings = record.get("output_findings", [])
        redaction = record.get("redaction", {"applied": False, "redacted_types": []})
        approval = record.get(
            "approval",
            {
                "required": False,
                "mode": "none",
                "decision": "not_required",
                "execute": execution.get("executed", False),
            },
        )
        rows.append(
            {
                "source": record.get("_source", "unknown"),
                "execution_mode": record.get("_execution_mode", "unknown"),
                "timestamp": event.get("timestamp", ""),
                "event_id": event["event_id"],
                "agent": event.get("agent_name", ""),
                "tool": event["tool_name"],
                "decision": decision["decision"],
                "risk_level": decision["risk_level"],
                "risk_score": decision["risk_score"],
                "risk_types": ", ".join(decision.get("risk_types", [])),
                "rules": ", ".join(decision.get("matched_rules", [])),
                "executed": execution.get("executed", False),
                "output_findings": ", ".join(finding.get("secret_type", "") for finding in findings),
                "redaction_applied": bool(redaction.get("applied", False)),
                "redacted_types": ", ".join(redaction.get("redacted_types", [])),
                "approval_required": bool(approval.get("required", False)),
                "approval_mode": approval.get("mode", "none"),
                "approval_decision": approval.get("decision", "not_required"),
                "result_preview": execution.get("result_preview", ""),
            }
        )
    return rows


def output_finding_rows(records: list[dict]) -> list[dict]:
    """提取工具结果内容审查发现，单独展示哪些输出触发了脱敏。"""
    rows: list[dict] = []
    for record in records:
        event = record["event"]
        for finding in record.get("output_findings", []):
            rows.append(
                {
                    "source": record.get("_source", "unknown"),
                    "timestamp": event.get("timestamp", ""),
                    "event_id": event["event_id"],
                    "agent": event.get("agent_name", ""),
                    "tool": event["tool_name"],
                    "rule_id": finding.get("rule_id", ""),
                    "severity": finding.get("severity", ""),
                    "secret_type": finding.get("secret_type", ""),
                    "reason": finding.get("reason", ""),
                }
            )
    return rows


def input_finding_rows(records: list[dict]) -> list[dict]:
    """提取输入侧风险标注，展示危险意图是否来自用户输入或外部上下文。"""
    rows: list[dict] = []
    for record in records:
        event = record["event"]
        for finding in record.get("input_findings", []):
            rows.append(
                {
                    "source": record.get("_source", "unknown"),
                    "timestamp": event.get("timestamp", ""),
                    "event_id": event["event_id"],
                    "agent": event.get("agent_name", ""),
                    "rule_id": finding.get("rule_id", ""),
                    "risk_type": finding.get("risk_type", ""),
                    "severity": finding.get("severity", ""),
                    "input_source": finding.get("source", ""),
                    "reason": finding.get("reason", ""),
                }
            )
    return rows


def approval_rows(records: list[dict]) -> list[dict]:
    """提取 ask 审批记录，展示用户确认或自动审批如何影响执行。"""
    rows: list[dict] = []
    for record in records:
        approval = record.get("approval", {})
        if not approval.get("required", False):
            continue
        event = record["event"]
        rows.append(
            {
                "source": record.get("_source", "unknown"),
                "timestamp": event.get("timestamp", ""),
                "event_id": event["event_id"],
                "agent": event.get("agent_name", ""),
                "tool": event["tool_name"],
                "approval_mode": approval.get("mode", ""),
                "approval_decision": approval.get("decision", ""),
                "execute": bool(approval.get("execute", False)),
                "reason": approval.get("reason", ""),
            }
        )
    return rows


def chain_alert_rows(records: list[dict]) -> list[dict]:
    """提取行为链告警，突出 SensitiveReadToExternalSend 等跨步骤风险。"""
    rows: list[dict] = []
    for record in records:
        event = record["event"]
        for alert in record["decision"].get("chain_alerts", []):
            rows.append(
                {
                    "event_id": event["event_id"],
                    "tool": event["tool_name"],
                    "chain_type": alert.get("chain_type", ""),
                    "source_event_id": alert.get("source_event_id", ""),
                    "sink_event_id": alert.get("sink_event_id", ""),
                    "reason": alert.get("reason", ""),
                }
            )
    return rows


def chain_graph_rows(records: list[dict]) -> list[dict]:
    """把结构化风险链图谱压平成边列表，便于 Dashboard 表格展示。"""
    rows: list[dict] = []
    for record in records:
        event = record["event"]
        for graph in record["decision"].get("chain_graphs", []):
            for edge in graph.get("edges", []):
                rows.append(
                    {
                        "source": record.get("_source", "unknown"),
                        "event_id": event["event_id"],
                        "chain_id": graph.get("chain_id", ""),
                        "chain_type": graph.get("chain_type", ""),
                        "severity": graph.get("severity", ""),
                        "from": edge.get("from", ""),
                        "to": edge.get("to", ""),
                        "relation": edge.get("relation", ""),
                        "reason": graph.get("reason", ""),
                    }
                )
    return rows


def main() -> None:
    if st is None:
        raise RuntimeError("Streamlit is not installed. Install streamlit to run dashboard/app.py.")

    st.title("AgentGuard-Chain Audit Dashboard")
    st.caption("P1 展示层：读取 JSONL 审计日志。当前默认包含 MiniAgent mock-tools 与 CoreCoder scripted-LLM demo。")

    mini_log = Path(st.text_input("MiniAgent audit log", str(DEFAULT_SOURCES[0][1])))
    core_log = Path(st.text_input("CoreCoder guarded audit log", str(DEFAULT_SOURCES[1][1])))
    records = load_records_from_sources(
        [
            ("miniagent-scripted", mini_log, "mock-tools"),
            ("corecoder-guarded-demo", core_log, "scripted-llm"),
        ]
    )
    st.metric("Records", len(records))

    counts = decision_counts(records)
    col1, col2, col3 = st.columns(3)
    col1.metric("Allowed", counts.get("allow", 0))
    col2.metric("Asked", counts.get("ask", 0))
    col3.metric("Denied", counts.get("deny", 0))

    st.subheader("Agent / Source Counts")
    st.json(agent_source_counts(records))

    st.subheader("Tool Call Timeline")
    st.dataframe(timeline_rows(records), use_container_width=True)

    st.subheader("Input Findings")
    st.dataframe(input_finding_rows(records), use_container_width=True)

    st.subheader("Output Findings")
    st.dataframe(output_finding_rows(records), use_container_width=True)

    st.subheader("Approval Records")
    st.dataframe(approval_rows(records), use_container_width=True)

    st.subheader("Behavior Chain Alerts")
    st.dataframe(chain_alert_rows(records), use_container_width=True)

    st.subheader("Behavior Chain Graphs")
    st.dataframe(chain_graph_rows(records), use_container_width=True)


if __name__ == "__main__":
    main()
