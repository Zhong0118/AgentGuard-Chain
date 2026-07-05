"""参数级检查：识别敏感路径、危险命令和网络访问。

P0 阶段刻意只使用确定性规则，不调用 LLM。
原因是安全边界必须可复现、可审计；LLM 后续只做解释，不负责放行高危操作。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from agentguard_chain.event import ToolCallEvent


@dataclass(frozen=True, slots=True)
class PolicyFinding:
    """一次规则命中结果，后续会交给 RiskScorer 生成最终决策。"""

    rule_id: str
    risk_type: str
    severity: str
    reason: str


SENSITIVE_PATH_PATTERNS = (
    ".env",
    ".env.",
    ".git/config",
    ".aws/credentials",
    ".azure",
    ".docker/config.json",
    ".gcloud",
    ".kube/config",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "id_rsa",
    "id_ed25519",
    "private_key",
    "service-account",
    "service-account.json",
    "service_account",
    "service_account.json",
    "token.txt",
    "api_key.txt",
    "credentials",
    "secrets",
)

# 这些后缀通常承载私钥、证书或基础设施变量，P0 先作为高置信敏感资产处理。
SENSITIVE_FILE_SUFFIXES = (
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".tfvars",
)

DANGEROUS_COMMAND_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bcurl\b.+\|\s*(?:sudo\s+)?(?:bash|sh)\b", "CMD_PIPE_TO_SHELL"),
    (r"\bwget\b.+\|\s*(?:sudo\s+)?(?:bash|sh)\b", "CMD_PIPE_TO_SHELL"),
    (r"\b(?:bash|sh)\s+-c\s+[\"']?\$\(\s*(?:curl|wget)\b", "CMD_DOWNLOAD_EXECUTE"),
    (r"\brm\s+.*-[^\s]*r[^\s]*f|\brm\s+.*-[^\s]*f[^\s]*r", "CMD_FORCE_RECURSIVE_DELETE"),
    (r"\bdel\s+.*(?:/s\b.*?/q\b|/q\b.*?/s\b)", "CMD_WINDOWS_RECURSIVE_DELETE"),
    (r"\bmkfs\b", "CMD_FORMAT_FILESYSTEM"),
    (r"\bdd\b.+\bof=/dev/", "CMD_RAW_DISK_WRITE"),
    (r"\bchmod\s+(?:-R\s+)?777\b", "CMD_CHMOD_777"),
    (r"base64\s+-d.+\|\s*(?:bash|sh)\b", "CMD_DECODE_AND_EXECUTE"),
    (r"\bnc(?:at)?\b\s+.*-e\s+", "CMD_REVERSE_SHELL"),
    (r"/dev/tcp/\d{1,3}(?:\.\d{1,3}){3}/\d+", "CMD_REVERSE_SHELL"),
    (r"\bpowershell\b.+-enc", "CMD_ENCODED_POWERSHELL"),
    (r"\bpowershell\b.+(?:\biex\b|invoke-expression).+(?:\biwr\b|invoke-webrequest|http)", "CMD_POWERSHELL_DOWNLOAD_EXECUTE"),
    (r"\b(?:iwr|invoke-webrequest)\b.+\|\s*(?:iex|invoke-expression)\b", "CMD_POWERSHELL_DOWNLOAD_EXECUTE"),
    (r"\bcertutil\b.+-urlcache.+https?://", "CMD_WINDOWS_DOWNLOADER"),
    (r"\bbitsadmin\b.+https?://", "CMD_WINDOWS_DOWNLOADER"),
)

NETWORK_COMMAND_PATTERN = re.compile(
    r"\b(?:curl|wget|nc|ncat|telnet|ssh)\b|https?://",
    flags=re.IGNORECASE,
)


class ParameterChecker:
    """检查工具参数里的敏感路径、危险命令和网络访问。"""

    FILE_TOOLS = {"read_file", "write_file", "edit_file", "delete_file"}
    COMMAND_TOOLS = {"bash", "run_command"}
    API_TOOLS = {"call_api"}
    SEND_TOOLS = {"send_message", "send_mail"}

    def check(self, event: ToolCallEvent) -> list[PolicyFinding]:
        findings: list[PolicyFinding] = []
        if event.tool_name in self.FILE_TOOLS:
            findings.extend(self._check_file_access(event))
        if event.tool_name in self.COMMAND_TOOLS:
            findings.extend(self._check_command(event))
        if event.tool_name in self.API_TOOLS:
            findings.extend(self._check_api_call(event))
        if event.tool_name in self.SEND_TOOLS:
            findings.extend(self._check_external_send(event))
        return findings

    def _check_file_access(self, event: ToolCallEvent) -> list[PolicyFinding]:
        findings: list[PolicyFinding] = []
        path_text = _extract_path_arg(event)
        normalized = path_text.replace("\\", "/").lower()

        # 敏感文件即使位于 workspace 内，也属于硬拒绝边界。
        if _is_sensitive_path(normalized, event.task_scope.denied_paths):
            findings.append(
                PolicyFinding(
                    rule_id="SENSITIVE_PATH",
                    risk_type="sensitive_file_access",
                    severity="critical",
                    reason=f"路径 {path_text} 命中敏感路径规则。",
                )
            )

        # P0 先把 workspace_root 当作文件访问边界，后续再细化到多目录权限。
        if path_text:
            workspace_root = Path(event.task_scope.workspace_root).expanduser().resolve()
            cwd = Path(event.cwd).expanduser().resolve()
            candidate = Path(path_text).expanduser()
            if not candidate.is_absolute():
                candidate = cwd / candidate
            try:
                resolved = candidate.resolve()
                if not _is_relative_to(resolved, workspace_root):
                    findings.append(
                        PolicyFinding(
                            rule_id="PATH_OUTSIDE_WORKSPACE",
                            risk_type="path_outside_workspace",
                            severity="critical",
                            reason=f"路径 {path_text} 超出 workspace 边界。",
                        )
                    )
                elif not _is_under_allowed_paths(resolved, event.task_scope.allowed_paths):
                    findings.append(
                        PolicyFinding(
                            rule_id="PATH_NOT_ALLOWED",
                            risk_type="path_not_allowed",
                            severity="high",
                            reason=f"路径 {path_text} 不在当前任务允许路径内。",
                        )
                    )
            except OSError:
                findings.append(
                    PolicyFinding(
                        rule_id="PATH_RESOLUTION_ERROR",
                        risk_type="path_resolution_error",
                        severity="high",
                        reason=f"路径 {path_text} 无法规范化。",
                    )
                )
        return findings

    def _check_api_call(self, event: ToolCallEvent) -> list[PolicyFinding]:
        findings: list[PolicyFinding] = []
        params = event.tool_args.get("params", {})
        user_id = str(params.get("user_id", "current_user")) if isinstance(params, dict) else ""

        # P1 本地 API outbox 只允许 current_user，防止越权查询 admin/other_user。
        if user_id and user_id != "current_user":
            findings.append(
                PolicyFinding(
                    rule_id="API_USER_SCOPE_VIOLATION",
                    risk_type="api_authz_violation",
                    severity="critical",
                    reason=f"API 调用尝试访问非当前用户 user_id={user_id}。",
                )
            )
        return findings

    def _check_external_send(self, event: ToolCallEvent) -> list[PolicyFinding]:
        target = str(event.tool_args.get("target") or event.tool_args.get("to") or "")
        if event.task_scope.external_send_allowed:
            return []
        if re.search(r"https?://|webhook|@", target, flags=re.IGNORECASE):
            return [
                PolicyFinding(
                    rule_id="EXTERNAL_SEND_NOT_ALLOWED",
                    risk_type="external_send_not_allowed",
                    severity="critical",
                    reason=f"当前任务范围不允许发送到外部目标 {target}。",
                )
            ]
        return []

    def _check_command(self, event: ToolCallEvent) -> list[PolicyFinding]:
        findings: list[PolicyFinding] = []
        command = str(event.tool_args.get("command", ""))

        for pattern, rule_id in DANGEROUS_COMMAND_PATTERNS:
            if re.search(pattern, command, flags=re.IGNORECASE):
                findings.append(
                    PolicyFinding(
                        rule_id=rule_id,
                        risk_type="dangerous_command",
                        severity="critical",
                        reason=f"命令 {command!r} 命中危险命令规则 {rule_id}。",
                    )
                )
                break

        if not event.task_scope.network_allowed and NETWORK_COMMAND_PATTERN.search(command):
            findings.append(
                PolicyFinding(
                    rule_id="NETWORK_NOT_ALLOWED",
                    risk_type="network_not_allowed",
                    severity="high",
                    reason="当前任务范围不允许网络访问。",
                )
            )

        return findings


def _extract_path_arg(event: ToolCallEvent) -> str:
    value = (
        event.tool_args.get("path")
        or event.tool_args.get("file_path")
        or event.tool_args.get("target")
        or ""
    )
    return str(value)


def _is_sensitive_path(normalized_path: str, denied_paths: list[str]) -> bool:
    if normalized_path.endswith(SENSITIVE_FILE_SUFFIXES):
        return True

    denied = [item.replace("\\", "/").lower().rstrip("/") for item in denied_paths]
    patterns = list(SENSITIVE_PATH_PATTERNS) + denied
    for pattern in patterns:
        marker = pattern.replace("\\", "/").lower().rstrip("/")
        if not marker:
            continue
        if normalized_path == marker or normalized_path.endswith(f"/{marker}"):
            return True
        if marker in {"credentials", "secrets"} and f"/{marker}/" in f"/{normalized_path}/":
            return True
        if marker == ".env" and normalized_path.startswith(".env."):
            return True
    return False


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_under_allowed_paths(path: Path, allowed_paths: list[str]) -> bool:
    if not allowed_paths:
        return True
    for raw_allowed in allowed_paths:
        allowed = Path(raw_allowed).expanduser().resolve()
        if _is_relative_to(path, allowed):
            return True
    return False
