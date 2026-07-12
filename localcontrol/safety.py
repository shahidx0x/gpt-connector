from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings
from .models import RiskLevel


@dataclass(frozen=True)
class RiskAssessment:
    risk: RiskLevel
    approval_required: bool
    reason: str
    hits: list[str] = field(default_factory=list)


_HIGH_RISK_COMMAND_PATTERNS: dict[str, re.Pattern[str]] = {
    "file deletion": re.compile(r"(?i)\b(remove-item|del|erase|rd|rmdir|rm)\b"),
    "disk or boot change": re.compile(r"(?i)\b(format|diskpart|bcdedit|bootrec|cipher)\b"),
    "shutdown or reboot": re.compile(r"(?i)\b(shutdown|restart-computer|stop-computer)\b"),
    "registry change": re.compile(r"(?i)\breg(?:\.exe)?\s+(add|delete|import|restore)\b"),
    "service or task change": re.compile(r"(?i)\b(sc|schtasks)\b.+\b(create|delete|change|config)\b"),
    "user or firewall change": re.compile(r"(?i)\b(netsh|net\s+user|net\s+localgroup)\b"),
    "elevated launch": re.compile(r"(?i)\b(start-process)\b.+\b-verb\s+runas\b"),
    "encoded powershell": re.compile(r"(?i)\b(encodedcommand|-enc)\b"),
    "download and execute": re.compile(r"(?i)\b(iwr|irm|invoke-webrequest|curl|wget)\b.+\b(iex|invoke-expression)\b"),
}


def _safe_env_path(name: str) -> Path | None:
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve(strict=False)
    except OSError:
        return None


def sensitive_roots() -> list[Path]:
    roots = [
        _safe_env_path("SystemRoot"),
        _safe_env_path("windir"),
        _safe_env_path("ProgramFiles"),
        _safe_env_path("ProgramFiles(x86)"),
        _safe_env_path("ProgramData"),
    ]
    home = _safe_env_path("USERPROFILE") or Path.home()
    roots.extend(
        [
            home / ".ssh",
            home / ".aws",
            home / ".azure",
            home / ".gnupg",
            home / "AppData" / "Roaming" / "Microsoft" / "Credentials",
        ]
    )
    resolved: list[Path] = []
    for root in roots:
        if not root:
            continue
        try:
            resolved.append(root.resolve(strict=False))
        except OSError:
            continue
    return resolved


def is_sensitive_path(path: Path) -> bool:
    name = path.name.lower()
    if name in {".env", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials"}:
        return True
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path
    return any(resolved == root or resolved.is_relative_to(root) for root in sensitive_roots())


def assess_path_read(path: Path, include_secrets: bool) -> RiskAssessment:
    if include_secrets:
        return RiskAssessment(
            risk=RiskLevel.high,
            approval_required=True,
            reason="Returning unredacted secrets requires human approval.",
            hits=["include_secrets"],
        )
    return RiskAssessment(risk=RiskLevel.low, approval_required=False, reason="Read with redaction enabled.")


def assess_path_mutation(path: Path, operation: str) -> RiskAssessment:
    hits: list[str] = []
    if operation == "delete":
        hits.append("delete")
    if is_sensitive_path(path):
        hits.append("sensitive_path")
    if hits:
        return RiskAssessment(
            risk=RiskLevel.high,
            approval_required=True,
            reason=f"{operation} touches a destructive or sensitive target.",
            hits=hits,
        )
    return RiskAssessment(risk=RiskLevel.low, approval_required=False, reason=f"{operation} is low risk.")


def assess_shell_command(command: str, timeout_seconds: float, include_secrets: bool, settings: Settings) -> RiskAssessment:
    hits = [name for name, pattern in _HIGH_RISK_COMMAND_PATTERNS.items() if pattern.search(command)]
    if timeout_seconds > settings.max_unapproved_shell_timeout_seconds:
        hits.append("long_timeout")
    if include_secrets:
        hits.append("include_secrets")

    if hits:
        return RiskAssessment(
            risk=RiskLevel.high,
            approval_required=True,
            reason="Command is destructive, long-running, elevated, or may reveal secrets.",
            hits=hits,
        )
    return RiskAssessment(risk=RiskLevel.low, approval_required=False, reason="Command did not match high-risk rules.")

