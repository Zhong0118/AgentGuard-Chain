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
    ("日志 1", Path("logs/p1_miniagent_audit.jsonl"), "audit"),
    ("日志 2", Path("logs/corecoder_guarded_audit.jsonl"), "audit"),
    ("日志 3", Path("logs/p2_explained_audit.jsonl"), "audit"),
    ("日志 4", Path("logs/deepseek_miniagent_llm_audit.jsonl"), "audit"),
    ("日志 5", Path("logs/deepseek_corecoder_real_audit.jsonl"), "audit"),
    ("日志 6", Path("logs/deepseek_explained_audit.jsonl"), "audit"),
)

DEFAULT_OUTBOX_SOURCES = (
    ("api", Path("logs/outbox/api_call_log.jsonl")),
    ("message", Path("logs/outbox/message_outbox.jsonl")),
    ("mail", Path("logs/outbox/mail_outbox.jsonl")),
)

MODE_LABELS = {
    "audit": "审计日志",
    "local-tools": "本地业务工具",
    "scripted-llm": "脚本化 LLM",
    "template-explained": "本地模板解释",
    "real-llm": "真实 LLM",
    "llm-explained": "LLM 解释",
    "unknown": "未知",
}

DECISION_LABELS = {
    "allow": "允许",
    "ask": "询问",
    "deny": "拒绝",
}

RISK_LEVEL_LABELS = {
    "low": "低",
    "medium": "中",
    "high": "高",
    "critical": "严重",
}

LEGACY_OUTBOX_FLAG = "m" + "ocked"


def load_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_records_from_sources(sources: list[tuple[str, Path, str]] | tuple[tuple[str, Path, str], ...]) -> list[dict]:
    """读取多份审计日志，并标记来源和执行模式。"""
    records: list[dict] = []
    for source_name, path, execution_mode in sources:
        for record in load_records(path):
            enriched = dict(record)
            enriched["_source"] = source_name
            enriched["_execution_mode"] = execution_mode
            enriched["_log_path"] = str(path)
            records.append(enriched)
    return records


def load_outbox_records(sources: list[tuple[str, Path]] | tuple[tuple[str, Path], ...]) -> list[dict]:
    """读取 API/message/mail 本地 outbox，并标记业务工具类型和文件来源。"""
    records: list[dict] = []
    for kind, path in sources:
        for record in load_records(path):
            enriched = dict(record)
            enriched["_outbox_kind"] = kind
            enriched["_outbox_path"] = str(path)
            records.append(enriched)
    return records


def decision_counts(records: list[dict]) -> dict[str, int]:
    """统计 allow/ask/deny 数量，供顶部指标和测试复用。"""
    counts: dict[str, int] = {}
    for record in records:
        decision = record["decision"]["decision"]
        counts[decision] = counts.get(decision, 0) + 1
    return counts


def available_values(records: list[dict], key: str) -> list[str]:
    """提取筛选框可选值，空字符串不展示。"""
    values = {str(record.get(key, "")) for record in records if record.get(key, "")}
    return sorted(values)


def filter_records(
    records: list[dict],
    *,
    sources: list[str] | None = None,
    decisions: list[str] | None = None,
    risk_levels: list[str] | None = None,
    tools: list[str] | None = None,
    only_executed: bool = False,
    only_with_explanations: bool = False,
    only_with_chain_alerts: bool = False,
) -> list[dict]:
    """按演示常用条件筛选审计记录。"""
    source_set = set(sources or [])
    decision_set = set(decisions or [])
    risk_set = set(risk_levels or [])
    tool_set = set(tools or [])
    filtered: list[dict] = []

    for record in records:
        event = record.get("event", {})
        decision = record.get("decision", {})
        execution = record.get("execution", {})
        explanation = decision.get("llm_explanation") or record.get("explanation", {}).get("text", "")

        if source_set and record.get("_source") not in source_set:
            continue
        if decision_set and decision.get("decision") not in decision_set:
            continue
        if risk_set and decision.get("risk_level") not in risk_set:
            continue
        if tool_set and event.get("tool_name") not in tool_set:
            continue
        if only_executed and not execution.get("executed", False):
            continue
        if only_with_explanations and not explanation:
            continue
        if only_with_chain_alerts and not decision.get("chain_alerts", []):
            continue
        filtered.append(record)
    return filtered


def dashboard_metrics(records: list[dict], outbox_records: list[dict] | None = None) -> dict[str, int]:
    """汇总顶部关键指标，面向演示而不是复杂分析。"""
    counts = decision_counts(records)
    return {
        "records": len(records),
        "allowed": counts.get("allow", 0),
        "asked": counts.get("ask", 0),
        "denied": counts.get("deny", 0),
        "real_llm_calls": sum(1 for record in records if record.get("_execution_mode") == "real-llm"),
        "explained": len(risk_explanation_rows(records)),
        "chain_alerts": len(chain_alert_rows(records)),
        "output_findings": len(output_finding_rows(records)),
        "approvals": len(approval_rows(records)),
        "outbox": len(outbox_records or []),
    }


def agent_source_counts(records: list[dict]) -> dict[str, int]:
    """按 agent 与日志来源统计，避免把本地演示日志当成生产流量。"""
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
                "llm_explanation": decision.get("llm_explanation") or record.get("explanation", {}).get("text", ""),
                "result_preview": execution.get("result_preview", ""),
            }
        )
    return rows


def risk_explanation_rows(records: list[dict]) -> list[dict]:
    """提取 LLM/template 风险解释，强调解释不参与硬决策。"""
    rows: list[dict] = []
    for record in records:
        decision = record.get("decision", {})
        text = decision.get("llm_explanation") or record.get("explanation", {}).get("text", "")
        if not text:
            continue
        event = record["event"]
        rows.append(
            {
                "source": record.get("_source", "unknown"),
                "timestamp": event.get("timestamp", ""),
                "event_id": event["event_id"],
                "agent": event.get("agent_name", ""),
                "tool": event["tool_name"],
                "decision": decision.get("decision", ""),
                "risk_level": decision.get("risk_level", ""),
                "explanation": text,
            }
        )
    return rows


def detail_record(record: dict) -> dict:
    """把单条审计记录整理成适合演示截图的详情结构。"""
    event = record.get("event", {})
    decision = record.get("decision", {})
    execution = record.get("execution", {})
    approval = record.get("approval", {})
    return {
        "source": record.get("_source", "unknown"),
        "execution_mode": record.get("_execution_mode", "unknown"),
        "event_id": event.get("event_id", ""),
        "agent": event.get("agent_name", ""),
        "tool": event.get("tool_name", ""),
        "tool_args": event.get("tool_args", {}),
        "user_task": event.get("user_task", ""),
        "decision": decision.get("decision", ""),
        "risk_level": decision.get("risk_level", ""),
        "risk_score": decision.get("risk_score", 0),
        "risk_types": decision.get("risk_types", []),
        "matched_rules": decision.get("matched_rules", []),
        "reason": decision.get("reason", ""),
        "executed": execution.get("executed", False),
        "result_preview": execution.get("result_preview", ""),
        "approval": approval,
        "input_findings": record.get("input_findings", []),
        "output_findings": record.get("output_findings", []),
        "chain_alerts": decision.get("chain_alerts", []),
        "chain_graphs": decision.get("chain_graphs", []),
        "llm_explanation": decision.get("llm_explanation") or record.get("explanation", {}).get("text", ""),
    }


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


def outbox_rows(records: list[dict]) -> list[dict]:
    """把本地业务 outbox 压平成统一表格，展示实际被允许的业务调用意图。"""
    rows: list[dict] = []
    for record in records:
        kind = record.get("_outbox_kind") or record.get("channel", "")
        row_id = record.get("api_call_id") or record.get("outbox_id", "")
        destination = record.get("endpoint") or record.get("target") or record.get("to", "")
        rows.append(
            {
                "kind": kind,
                "id": row_id,
                "destination": destination,
                "status": record.get("status", "queued"),
                "transport": record.get("transport") or ("legacy_local_outbox" if record.get(LEGACY_OUTBOX_FLAG, "") else ""),
                "delivered": record.get("delivered", ""),
                "source_path": record.get("_outbox_path", ""),
                "payload": json.dumps(_outbox_payload(record), ensure_ascii=False),
            }
        )
    return rows


def display_rows(rows: list[dict], columns: dict[str, str]) -> list[dict]:
    """把内部英文字段映射成中文列名，仅用于 Dashboard 展示。"""
    return [{label: row.get(key, "") for key, label in columns.items()} for row in rows]


def display_agent_source_counts(records: list[dict]) -> dict[str, int]:
    """按 Agent 和日志文件统计。"""
    counts: dict[str, int] = {}
    for record in records:
        agent = record["event"].get("agent_name", "")
        source_label = Path(record.get("_log_path", record.get("_source", "unknown"))).name
        key = f"{agent} | {source_label}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _outbox_payload(record: dict) -> dict:
    return {
        key: value
        for key, value in record.items()
        if not key.startswith("_") and key not in {"api_call_id", "outbox_id", "channel", "status", LEGACY_OUTBOX_FLAG, "transport", "delivered"}
    }


def main() -> None:
    if st is None:
        raise RuntimeError("Streamlit is not installed. Install streamlit to run dashboard/app.py.")

    st.set_page_config(page_title="AgentGuard-Chain 审计面板", layout="wide")
    st.title("AgentGuard-Chain 审计面板")
    st.caption("聚合 MiniAgent、CoreCoder、真实 LLM 和风险解释日志；本页面只读取审计 JSONL，不参与安全决策。")

    with st.sidebar:
        st.header("审计日志路径")
        st.caption("可以替换为任意同格式 JSONL；系统会读取存在的日志，缺失的会自动跳过。")
        source_paths: list[tuple[str, Path, str]] = []
        for index, (source_name, default_path, execution_mode) in enumerate(DEFAULT_SOURCES):
            path_text = st.text_input(f"日志文件 {index + 1}", str(default_path), key=f"source-{index}")
            source_paths.append((source_name, Path(path_text), execution_mode))
        st.header("本地业务 Outbox")
        api_outbox = Path(st.text_input("API 调用日志", str(DEFAULT_OUTBOX_SOURCES[0][1])))
        message_outbox = Path(st.text_input("消息发送日志", str(DEFAULT_OUTBOX_SOURCES[1][1])))
        mail_outbox = Path(st.text_input("邮件发送日志", str(DEFAULT_OUTBOX_SOURCES[2][1])))

    records = load_records_from_sources(source_paths)
    business_outbox = load_outbox_records(
        [
            ("api", api_outbox),
            ("message", message_outbox),
            ("mail", mail_outbox),
        ]
    )

    with st.sidebar:
        st.header("筛选")
        selected_sources = st.multiselect(
            "日志来源",
            available_values(records, "_source"),
        )
        selected_decisions = st.multiselect(
            "决策",
            sorted({record.get("decision", {}).get("decision", "") for record in records if record.get("decision", {}).get("decision", "")}),
            format_func=lambda value: DECISION_LABELS.get(value, value),
        )
        selected_risks = st.multiselect(
            "风险等级",
            sorted({record.get("decision", {}).get("risk_level", "") for record in records if record.get("decision", {}).get("risk_level", "")}),
            format_func=lambda value: RISK_LEVEL_LABELS.get(value, value),
        )
        selected_tools = st.multiselect(
            "工具",
            sorted({record.get("event", {}).get("tool_name", "") for record in records if record.get("event", {}).get("tool_name", "")}),
        )
        only_executed = st.checkbox("只看已执行", value=False)
        only_with_explanations = st.checkbox("只看带风险解释", value=False)
        only_with_chain_alerts = st.checkbox("只看行为链告警", value=False)

    filtered_records = filter_records(
        records,
        sources=selected_sources,
        decisions=selected_decisions,
        risk_levels=selected_risks,
        tools=selected_tools,
        only_executed=only_executed,
        only_with_explanations=only_with_explanations,
        only_with_chain_alerts=only_with_chain_alerts,
    )

    metrics = dashboard_metrics(filtered_records, business_outbox)
    metric_cols = st.columns(5)
    metric_cols[0].metric("审计记录", metrics["records"])
    metric_cols[1].metric("允许", metrics["allowed"])
    metric_cols[2].metric("询问", metrics["asked"])
    metric_cols[3].metric("拒绝", metrics["denied"])
    metric_cols[4].metric("行为链告警", metrics["chain_alerts"])

    metric_cols = st.columns(5)
    metric_cols[0].metric("风险解释", metrics["explained"])
    metric_cols[1].metric("真实 LLM 记录", metrics["real_llm_calls"])
    metric_cols[2].metric("输出发现", metrics["output_findings"])
    metric_cols[3].metric("审批记录", metrics["approvals"])
    metric_cols[4].metric("业务 Outbox", metrics["outbox"])

    st.subheader("Agent / 日志来源统计")
    st.json(display_agent_source_counts(filtered_records))

    timeline = timeline_rows(filtered_records)
    st.subheader("工具调用时间线")
    st.dataframe(
        display_rows(
            timeline,
            {
                "source": "日志来源",
                "timestamp": "时间",
                "agent": "Agent",
                "tool": "工具",
                "decision": "决策",
                "risk_level": "风险等级",
                "risk_score": "风险分数",
                "risk_types": "风险类型",
                "rules": "命中规则",
                "executed": "是否执行",
                "approval_required": "是否需确认",
                "llm_explanation": "风险解释",
                "result_preview": "结果摘要",
            },
        ),
        use_container_width=True,
    )

    st.subheader("审计详情")
    if filtered_records:
        label_to_record = {
            f"{record.get('event', {}).get('timestamp', '')} | {record.get('_source', 'unknown')} | {record.get('event', {}).get('tool_name', '')} | {record.get('decision', {}).get('decision', '')} | {record.get('event', {}).get('event_id', '')}": record
            for record in filtered_records
        }
        selected_label = st.selectbox("选择一条工具调用", list(label_to_record))
        st.json(detail_record(label_to_record[selected_label]))
    else:
        st.info("没有符合当前筛选条件的审计记录。")

    tab_names = [
        "输入风险",
        "输出风险",
        "审批记录",
        "风险解释",
        "行为链告警",
        "行为链图谱",
        "业务 Outbox",
    ]
    tabs = st.tabs(tab_names)
    tabs[0].dataframe(input_finding_rows(filtered_records), use_container_width=True)
    tabs[1].dataframe(output_finding_rows(filtered_records), use_container_width=True)
    tabs[2].dataframe(approval_rows(filtered_records), use_container_width=True)
    tabs[3].caption("解释文本只用于审计展示，不参与 allow / ask / deny 决策。")
    tabs[3].dataframe(risk_explanation_rows(filtered_records), use_container_width=True)
    tabs[4].dataframe(chain_alert_rows(filtered_records), use_container_width=True)
    tabs[5].dataframe(chain_graph_rows(filtered_records), use_container_width=True)
    tabs[6].dataframe(outbox_rows(business_outbox), use_container_width=True)


if __name__ == "__main__":
    main()
