"""Mini-Agent mock tools.

这些工具只用于可控实验。真实安全边界仍然是 AgentGuardGateway；
只有网关返回 allow 时，runner 才会执行这里的 mock tool。
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any
from uuid import uuid4


class MiniAgentTools:
    """一组最小 mock 工具，用于 scripted mode。"""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()
        self.messages: list[dict[str, str]] = []
        self.sent_mail: list[dict[str, str]] = []

    def execute(self, tool_name: str, tool_args: dict[str, Any]) -> str:
        if tool_name == "read_file":
            return self.read_file(str(tool_args.get("path") or tool_args.get("file_path") or ""))
        if tool_name == "write_file":
            return self.write_file(str(tool_args.get("path") or tool_args.get("file_path") or ""), str(tool_args.get("content", "")))
        if tool_name == "delete_file":
            return self.delete_file(str(tool_args.get("path") or tool_args.get("file_path") or ""))
        if tool_name in {"bash", "run_command"}:
            return self.run_command(str(tool_args.get("command", "")))
        if tool_name == "call_api":
            return self.call_api(str(tool_args.get("endpoint", "")), dict(tool_args.get("params", {})))
        if tool_name == "send_message":
            return self.send_message(str(tool_args.get("target", "")), str(tool_args.get("content", "")))
        if tool_name == "send_mail":
            body = str(tool_args.get("body") or tool_args.get("content") or "")
            return self.send_mail(str(tool_args.get("to", "")), str(tool_args.get("subject", "")), body)
        return f"Error: unknown tool {tool_name}"

    def read_file(self, path: str) -> str:
        target = self._resolve(path)
        return target.read_text(encoding="utf-8", errors="replace")

    def write_file(self, path: str, content: str) -> str:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {path}"

    def delete_file(self, path: str) -> str:
        target = self._resolve(path)
        if target.exists():
            target.unlink()
            return f"Deleted {path}"
        return f"Not found: {path}"

    def run_command(self, command: str) -> str:
        # Mini-Agent 只跑 allow 后的命令；P1 仍然限制超时和输出长度。
        proc = subprocess.run(
            command,
            shell=True,
            cwd=self.workspace_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        # Windows 中文环境下命令输出编码不稳定，errors=replace 保证实验不中断。
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        output = stdout + (f"\n[stderr]\n{stderr}" if stderr else "")
        return output[:2000] or f"[exit code: {proc.returncode}]"

    def call_api(self, endpoint: str, params: dict[str, Any]) -> str:
        user_id = params.get("user_id", "current_user")
        record = {
            "api_call_id": f"api-{uuid4().hex}",
            "channel": "api",
            "endpoint": endpoint,
            "params": params,
            "user_id": user_id,
            "status": "ok",
            "mocked": True,
        }
        self._append_outbox("api_call_log.jsonl", record)
        return json.dumps(
            {
                "status": "ok",
                "channel": "api",
                "api_call_id": record["api_call_id"],
                "endpoint": endpoint,
                "user_id": user_id,
                "log_path": "logs/outbox/api_call_log.jsonl",
            },
            ensure_ascii=False,
        )

    def send_message(self, target: str, content: str) -> str:
        record = {
            "outbox_id": f"msg-{uuid4().hex}",
            "channel": "message",
            "target": target,
            "content": content,
            "delivered": False,
        }
        self.messages.append({"target": target, "content": content})
        self._append_outbox("message_outbox.jsonl", record)
        return json.dumps(
            {
                "status": "queued",
                "channel": "message",
                "outbox_id": record["outbox_id"],
                "outbox_path": "logs/outbox/message_outbox.jsonl",
            },
            ensure_ascii=False,
        )

    def send_mail(self, to: str, subject: str, body: str) -> str:
        record = {
            "outbox_id": f"mail-{uuid4().hex}",
            "channel": "mail",
            "to": to,
            "subject": subject,
            "body": body,
            "delivered": False,
        }
        self.sent_mail.append({"to": to, "subject": subject, "body": body})
        self._append_outbox("mail_outbox.jsonl", record)
        return json.dumps(
            {
                "status": "queued",
                "channel": "mail",
                "outbox_id": record["outbox_id"],
                "outbox_path": "logs/outbox/mail_outbox.jsonl",
            },
            ensure_ascii=False,
        )

    def _resolve(self, path: str) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        return candidate.resolve()

    def _append_outbox(self, filename: str, record: dict[str, Any]) -> None:
        # outbox 是模拟外发系统的落盘队列，便于审计日志通过 outbox_id 追溯。
        outbox_dir = self.workspace_root / "logs" / "outbox"
        outbox_dir.mkdir(parents=True, exist_ok=True)
        with (outbox_dir / filename).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
