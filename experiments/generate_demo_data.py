"""生成一套干净的 Dashboard / 报告演示日志。

默认只运行离线可复现链路；加 `--include-real-llm` 才会调用真实 API。
脚本不会保存 API key，只从环境变量读取真实 LLM 配置。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agents.corecoder_guarded_runner import RealLLMConfigError, run_corecoder_real_llm_guarded, run_corecoder_scripted_demo
from agents.miniagent.run_case import MiniAgentLLMConfigError, run_dataset, run_llm_prompt
from experiments.evaluate_p1_v2 import evaluate_dataset
from experiments.explain_audit_log import explain_audit_log


DEFAULT_LOGS = {
    "miniagent": Path("logs/p1_miniagent_audit.jsonl"),
    "corecoder_scripted": Path("logs/corecoder_guarded_audit.jsonl"),
    "template_explained": Path("logs/p2_explained_audit.jsonl"),
    "miniagent_real": Path("logs/deepseek_miniagent_llm_audit.jsonl"),
    "corecoder_real": Path("logs/deepseek_corecoder_real_audit.jsonl"),
    "llm_explained": Path("logs/deepseek_explained_audit.jsonl"),
    "eval": Path("logs/p1_v2_eval.json"),
    "manifest": Path("logs/demo_manifest.json"),
}

DEFAULT_OUTBOX = (
    Path("logs/outbox/api_call_log.jsonl"),
    Path("logs/outbox/message_outbox.jsonl"),
    Path("logs/outbox/mail_outbox.jsonl"),
)

REAL_LLM_LOG_KEYS = {"miniagent_real", "corecoder_real", "llm_explained"}


def generate_demo_data(
    *,
    workspace_root: Path,
    dataset_path: Path = Path("datasets/p1_scripted_cases.jsonl"),
    include_real_llm: bool = False,
    real_prompt: str = "请读取 workflow.md 并总结项目目标",
    logs: dict[str, Path] | None = None,
    outbox_logs: tuple[Path, ...] = DEFAULT_OUTBOX,
) -> dict[str, Any]:
    """生成演示日志并返回 manifest 字典。"""

    workspace_root = workspace_root.resolve()
    logs = logs or DEFAULT_LOGS
    _reset_demo_outputs(logs, outbox_logs, include_real_llm=include_real_llm)

    manifest: dict[str, Any] = {
        "workspace_root": str(workspace_root),
        "dataset": str(dataset_path),
        "include_real_llm": include_real_llm,
        "steps": [],
        "logs": {name: str(path) for name, path in logs.items()},
        "outbox": [str(path) for path in outbox_logs],
    }

    miniagent_summary = run_dataset(
        dataset_path,
        logs["miniagent"],
        workspace_root,
        approval_mode="auto-deny",
    )
    _add_step(manifest, "miniagent_scripted", "completed", miniagent_summary)

    scripted_summaries = []
    for demo in ["normal-read", "sensitive-file", "dangerous-command"]:
        scripted_summaries.append(
            run_corecoder_scripted_demo(
                demo=demo,
                workspace_root=workspace_root,
                audit_log_path=logs["corecoder_scripted"],
                approval_mode="auto-deny",
            )
        )
    _add_step(manifest, "corecoder_scripted", "completed", {"demos": scripted_summaries})

    eval_report = evaluate_dataset(dataset_path, workspace_root)
    logs["eval"].parent.mkdir(parents=True, exist_ok=True)
    logs["eval"].write_text(json.dumps(eval_report, ensure_ascii=False, indent=2), encoding="utf-8")
    _add_step(manifest, "p1_v2_eval", "completed", eval_report["dataset"])

    explanation_summary = explain_audit_log(
        logs["corecoder_scripted"],
        _log_path(logs, "template_explained", "explained"),
        mode="template",
    )
    _add_step(manifest, "risk_explainer_template", "completed", explanation_summary)

    if include_real_llm:
        _run_real_llm_steps(manifest, workspace_root, logs, real_prompt)
    else:
        _add_step(manifest, "real_llm", "skipped", {"reason": "run with --include-real-llm to call external API"})

    manifest["summary"] = _summarize_outputs(logs, outbox_logs, include_real_llm=include_real_llm)
    logs["manifest"].parent.mkdir(parents=True, exist_ok=True)
    logs["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _run_real_llm_steps(
    manifest: dict[str, Any],
    workspace_root: Path,
    logs: dict[str, Path],
    real_prompt: str,
) -> None:
    try:
        miniagent_real = run_llm_prompt(
            prompt=real_prompt,
            audit_log_path=logs["miniagent_real"],
            workspace_root=workspace_root,
            approval_mode="auto-deny",
        )
        _add_step(manifest, "miniagent_real_llm", "completed", miniagent_real)
    except MiniAgentLLMConfigError as exc:
        _add_step(manifest, "miniagent_real_llm", "skipped", {"reason": str(exc)})

    try:
        corecoder_real = run_corecoder_real_llm_guarded(
            prompt=real_prompt,
            workspace_root=workspace_root,
            audit_log_path=logs["corecoder_real"],
            approval_mode="auto-deny",
        )
        _add_step(
            manifest,
            "corecoder_real_llm",
            "completed",
            {
                "mode": corecoder_real.get("mode"),
                "model": corecoder_real.get("model"),
                "base_url": corecoder_real.get("base_url"),
                "decision": corecoder_real.get("decision"),
                "executed": corecoder_real.get("executed"),
                "records": corecoder_real.get("records"),
            },
        )
    except RealLLMConfigError as exc:
        _add_step(manifest, "corecoder_real_llm", "skipped", {"reason": str(exc)})

    try:
        explained = explain_audit_log(
            logs["corecoder_scripted"],
            _log_path(logs, "llm_explained", "explained"),
            mode="llm",
        )
        _add_step(manifest, "risk_explainer_llm", "completed", explained)
    except Exception as exc:
        _add_step(manifest, "risk_explainer_llm", "skipped", {"reason": str(exc)})


def _reset_demo_outputs(
    logs: dict[str, Path],
    outbox_logs: tuple[Path, ...],
    *,
    include_real_llm: bool,
) -> None:
    # 默认离线演示只重置可重建日志，避免误删真实 API 验证证据。
    reset_keys = ["miniagent", "corecoder_scripted", "template_explained", "eval", "manifest"]
    if "explained" in logs and "template_explained" not in logs:
        reset_keys.append("explained")
    if include_real_llm:
        reset_keys.extend(["miniagent_real", "corecoder_real", "llm_explained"])

    paths = [logs[key] for key in reset_keys if key in logs] + list(outbox_logs)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.write_text("", encoding="utf-8")
    tmp_dir = Path("tmp")
    if tmp_dir.exists():
        for pattern in ["generated_chain_*.sh", "generated_note_*.txt"]:
            for path in tmp_dir.glob(pattern):
                if path.is_file():
                    path.unlink()


def _summarize_outputs(
    logs: dict[str, Path],
    outbox_logs: tuple[Path, ...],
    *,
    include_real_llm: bool,
) -> dict[str, Any]:
    return {
        "audit_records": {
            name: _count_jsonl(path)
            for name, path in logs.items()
            if name not in {"eval", "manifest"} and (include_real_llm or name not in REAL_LLM_LOG_KEYS)
        },
        "outbox_records": {path.name: _count_jsonl(path) for path in outbox_logs},
    }


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _add_step(manifest: dict[str, Any], name: str, status: str, details: dict[str, Any]) -> None:
    manifest["steps"].append({"name": name, "status": status, "details": details})


def _log_path(logs: dict[str, Path], preferred_key: str, fallback_key: str) -> Path:
    return logs.get(preferred_key) or logs[fallback_key]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate clean AgentGuard demo logs.")
    parser.add_argument("--workspace-root", default=".")
    parser.add_argument("--dataset", default="datasets/p1_scripted_cases.jsonl")
    parser.add_argument(
        "--include-real-llm",
        action="store_true",
        help="Call external LLM APIs using environment variables.",
    )
    parser.add_argument("--real-prompt", default="请读取 workflow.md 并总结项目目标")
    args = parser.parse_args()

    manifest = generate_demo_data(
        workspace_root=Path(args.workspace_root),
        dataset_path=Path(args.dataset),
        include_real_llm=args.include_real_llm,
        real_prompt=args.real_prompt,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
