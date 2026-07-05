"""为审计 JSONL 增加风险解释。

默认 template 模式不需要 API key；llm 模式使用 OpenAI-compatible API。
解释结果写入 decision.llm_explanation，不改变原始安全决策。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agentguard_chain.explainer import RiskExplainer, RiskExplainerError, client_from_env, explain_records


def explain_audit_log(input_path: Path, output_path: Path, *, mode: str = "template") -> dict[str, Any]:
    records = _load_jsonl(input_path)
    client = client_from_env() if mode == "llm" else None
    explained = explain_records(records, explainer=RiskExplainer(llm_client=client))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in explained) + ("\n" if explained else ""),
        encoding="utf-8",
    )
    return {
        "input": str(input_path),
        "output": str(output_path),
        "mode": mode,
        "records": len(explained),
        "explained_records": sum(1 for record in explained if record.get("decision", {}).get("llm_explanation")),
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Explain AgentGuard audit JSONL records.")
    parser.add_argument("--input", default="logs/p1_miniagent_audit.jsonl")
    parser.add_argument("--output", default="logs/p2_explained_audit.jsonl")
    parser.add_argument("--mode", choices=["template", "llm"], default="template")
    args = parser.parse_args()

    try:
        summary = explain_audit_log(Path(args.input), Path(args.output), mode=args.mode)
    except RiskExplainerError as exc:
        print(json.dumps({"mode": args.mode, "error": str(exc)}, ensure_ascii=True, indent=2))
        raise SystemExit(2) from exc
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

