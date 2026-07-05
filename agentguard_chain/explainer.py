"""风险解释器：把审计决策转换成面向人的中文说明。

LLM explainer 只负责解释已经产生的 GuardDecision，不参与 allow/ask/deny。
没有 API key 或测试环境中，可以使用模板解释保持可复现。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import request


class RiskExplainerError(RuntimeError):
    """风险解释器配置或调用失败。"""


class ExplainerClient(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str:
        """返回中文解释文本。"""


@dataclass(frozen=True, slots=True)
class RiskExplanation:
    """单条审计记录的解释结果。"""

    event_id: str
    mode: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return {"event_id": self.event_id, "mode": self.mode, "text": self.text}


class OpenAICompatibleExplainerClient:
    """最小 OpenAI-compatible chat client，用于风险解释。"""

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
            raise RiskExplainerError("OpenAI-compatible response did not contain choices[0].message.content.") from exc
        if not isinstance(content, str) or not content.strip():
            raise RiskExplainerError("OpenAI-compatible response content must be a non-empty string.")
        return content.strip()


class RiskExplainer:
    """把审计记录解释成人能读懂的风险说明。"""

    def __init__(self, *, llm_client: ExplainerClient | None = None):
        self.llm_client = llm_client

    def explain_record(self, record: dict[str, Any]) -> RiskExplanation:
        event_id = str(record.get("event", {}).get("event_id", "unknown"))
        if self.llm_client is None:
            return RiskExplanation(event_id=event_id, mode="template", text=_template_explanation(record))

        messages = [
            {
                "role": "system",
                "content": (
                    "你是 AgentGuard-Chain 的风险解释器。"
                    "只解释已有审计记录，不改变 allow/ask/deny 决策。"
                    "请用 3-5 句中文说明：风险来源、命中证据、执行状态、建议处理。"
                ),
            },
            {"role": "user", "content": json.dumps(_compact_record(record), ensure_ascii=False)},
        ]
        return RiskExplanation(event_id=event_id, mode="llm", text=self.llm_client.complete(messages))


def explain_records(records: list[dict[str, Any]], *, explainer: RiskExplainer) -> list[dict[str, Any]]:
    """返回带 `decision.llm_explanation` 的新记录列表，不修改原始 records。"""

    enriched: list[dict[str, Any]] = []
    for record in records:
        copied = json.loads(json.dumps(record, ensure_ascii=False))
        explanation = explainer.explain_record(copied)
        copied.setdefault("decision", {})["llm_explanation"] = explanation.text
        copied.setdefault("explanation", explanation.to_dict())
        enriched.append(copied)
    return enriched


def client_from_env() -> OpenAICompatibleExplainerClient:
    """从环境变量创建真实 LLM 解释器客户端。"""

    api_key = (
        os.getenv("AGENTGUARD_EXPLAINER_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
    )
    if not api_key:
        raise RiskExplainerError(
            "No API key found. Set AGENTGUARD_EXPLAINER_API_KEY, OPENAI_API_KEY, or DEEPSEEK_API_KEY."
        )
    base_url = (
        os.getenv("AGENTGUARD_EXPLAINER_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    )
    model = os.getenv("AGENTGUARD_EXPLAINER_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    return OpenAICompatibleExplainerClient(api_key=api_key, base_url=base_url, model=model)


def _template_explanation(record: dict[str, Any]) -> str:
    event = record.get("event", {})
    decision = record.get("decision", {})
    execution = record.get("execution", {})
    approval = record.get("approval", {})
    rules = decision.get("matched_rules", [])
    chains = decision.get("chain_graphs", [])
    output_findings = record.get("output_findings", [])

    parts = [
        f"工具 {event.get('tool_name', 'unknown')} 的决策为 {decision.get('decision', 'unknown')}，风险等级为 {decision.get('risk_level', 'unknown')}。",
    ]
    if rules:
        parts.append(f"命中规则包括：{', '.join(str(rule) for rule in rules)}。")
    if decision.get("reason"):
        parts.append(f"主要原因：{decision['reason']}")
    if chains:
        chain_types = ", ".join(str(chain.get("chain_type", "")) for chain in chains)
        parts.append(f"该调用还关联行为链风险：{chain_types}。")
    if output_findings:
        secret_types = ", ".join(str(item.get("secret_type", "")) for item in output_findings)
        parts.append(f"工具结果中发现敏感输出类型：{secret_types}。")
    if approval.get("required"):
        parts.append(f"该操作需要确认，审批结果为 {approval.get('decision', 'unknown')}。")
    executed = "已执行" if execution.get("executed", False) else "未执行"
    parts.append(f"最终工具状态：{executed}。")
    parts.append(_recommendation(decision.get("decision", "unknown")))
    return "".join(parts)


def _recommendation(decision: str) -> str:
    if decision == "allow":
        return "建议继续保留审计记录，并在工具结果含敏感信息时执行脱敏。"
    if decision == "ask":
        return "建议由用户确认任务授权、目标路径和外发对象后再决定是否执行。"
    if decision == "deny":
        return "建议保持阻断，并要求用户缩小任务范围或提供明确授权。"
    return "建议人工复核该工具调用的上下文和权限边界。"


def _compact_record(record: dict[str, Any]) -> dict[str, Any]:
    event = record.get("event", {})
    decision = record.get("decision", {})
    execution = record.get("execution", {})
    return {
        "event": {
            "event_id": event.get("event_id"),
            "agent_name": event.get("agent_name"),
            "user_task": _truncate(event.get("user_task", "")),
            "tool_name": event.get("tool_name"),
            "tool_args": event.get("tool_args", {}),
        },
        "decision": {
            "decision": decision.get("decision"),
            "risk_score": decision.get("risk_score"),
            "risk_level": decision.get("risk_level"),
            "risk_types": decision.get("risk_types", []),
            "matched_rules": decision.get("matched_rules", []),
            "reason": _truncate(decision.get("reason", "")),
            "chain_graphs": decision.get("chain_graphs", []),
        },
        "execution": {
            "executed": execution.get("executed", False),
            "result_preview": _truncate(execution.get("result_preview", "")),
        },
        "input_findings": record.get("input_findings", []),
        "output_findings": record.get("output_findings", []),
        "approval": record.get("approval", {}),
    }


def _truncate(value: Any, limit: int = 1200) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + f"... truncated ({len(text)} chars total)"

