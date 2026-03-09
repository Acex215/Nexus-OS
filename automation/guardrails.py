#!/usr/bin/env python3
"""NEXUS OS CAF — Guardrails

Single source of truth for ALL safety policies.
Imported by execution_engine, audit_logger, and the orchestrator.

Public API:
    check_protected_files(file_list)   -> list[str]
    check_command_safety(command)      -> dict
    check_change_size(plan)            -> dict
    check_secrets_in_output(text)      -> bool
    sanitize_for_log(text)             -> str
    EXECUTION_POLICIES                 (dict)
"""

import fnmatch
import json
import re
from pathlib import Path

CONSTITUTION_PATH = Path("/opt/nexus/automation/constitution.json")

# ── Execution policies (informational reference) ───────────────────────────────

EXECUTION_POLICIES: dict[str, str] = {
    "git_workflow":
        "All changes on auto/* branches. Never commit to main.",
    "backup_before_modify":
        "Every file backed up to /opt/nexus/backups/auto/ before modification.",
    "test_after_modify":
        "Run test_command from world model if exists for the module.",
    "rollback_on_failure":
        "If any step fails, revert all changes and restore backups.",
    "no_secrets_in_logs":
        "Never log wallet passwords, API tokens, private keys, .env contents.",
    "no_deployment_without_approval":
        "systemd service changes require Discord approval.",
    "no_contract_deployment":
        "All Solidity deployments require Md approval via Discord.",
    "no_internet_from_cluster":
        "Never attempt to route VLAN 20 traffic to internet.",
}

# ── Command lists ──────────────────────────────────────────────────────────────

COMMAND_ALLOWLIST: list[str] = [
    "ssh", "git", "python3", "pip3", "pip", "curl", "cat", "ls", "grep",
    "find", "mkdir", "cp", "mv", "head", "tail", "wc", "diff", "chmod",
    "chown", "systemctl", "echo", "touch", "tee", "sed", "awk", "sort",
    "uniq", "tar", "gzip", "gunzip", "sha256sum", "md5sum", "base64",
    "jq", "sqlite3", "psql", "df", "du", "free", "ps", "top", "htop",
    "journalctl", "date", "hostname", "uname", "which", "env", "export",
    "test", "true", "false", "xargs", "cut", "tr", "printf", "read",
    "ipfs", "geth", "kubectl", "helm", "docker", "npm", "node",
]

# Substring blocklist — any match in the command string → hard block
COMMAND_BLOCKLIST: list[str] = [
    "rm -rf", "rm -r /", "rm -fr",
    "dd ", "dd\t",
    "fdisk", "mkfs",
    "reboot", "shutdown", "poweroff", "halt", "init 0", "init 6",
    "iptables -F", "iptables -X", "nft flush", "ufw reset",
    # Piped shell execution (both space-around-pipe and no-space variants)
    "curl|sh", "curl|bash", "wget|sh", "wget|bash",
    "| bash", "| sh", "| python", "| perl",
    "|bash", "|sh",
    # Direct destructive sudo
    "sudo rm", "sudo dd", "sudo mkfs", "sudo reboot", "sudo shutdown",
    "sudo poweroff", "sudo halt",
    # Device writes
    "> /dev/sd", "> /dev/mmcblk", "> /dev/nvme",
]

# ── Size limits (mirrors execution_engine constants) ──────────────────────────

MAX_LINES_ADDED          = 200
MAX_LINES_DELETED        = 50
MAX_FILES_MODIFIED       = 5
SOFT_LINES_ADDED         = 100
SOFT_LINES_DELETED       = 30
SOFT_FILES_MODIFIED      = 3

# ── Secret detection patterns ─────────────────────────────────────────────────
# Each entry: (detect_re, redact_re, replacement)
# detect_re  — used by check_secrets_in_output (just needs to find a match)
# redact_re  — used by sanitize_for_log (substituted out)

_SECRET_SPECS: list[tuple[re.Pattern, re.Pattern, str]] = []

def _spec(pattern: str, redact_pattern: str, replacement: str,
          flags: int = 0) -> None:
    _SECRET_SPECS.append((
        re.compile(pattern, flags),
        re.compile(redact_pattern, flags),
        replacement,
    ))

# Discord / CAF bot tokens
_spec(
    r'(?:CAF_DISCORD_TOKEN|DISCORD_TOKEN)\s*=\s*\S+',
    r'((?:CAF_DISCORD_TOKEN|DISCORD_TOKEN)\s*=\s*)\S+',
    r'\1[REDACTED]',
)
# OpenAI-style API keys (sk-...)
_spec(
    r'sk-[A-Za-z0-9\-_]{8,}',
    r'sk-[A-Za-z0-9\-_]{8,}',
    '[REDACTED]',
)
# GitHub personal access tokens
_spec(
    r'gh[pso]_[A-Za-z0-9]{10,}',
    r'gh[pso]_[A-Za-z0-9]{10,}',
    '[REDACTED]',
)
# Ethereum private keys (0x + 64 hex chars)
_spec(
    r'0x[0-9a-fA-F]{64}',
    r'0x[0-9a-fA-F]{64}',
    '0x[REDACTED]',
)
# Generic KEY=VALUE or TOKEN=VALUE patterns
_spec(
    r'(?:TOKEN|SECRET|PASSWORD|PRIVATE_KEY|PASSWD|API_KEY)\s*=\s*\S+',
    r'((?:TOKEN|SECRET|PASSWORD|PRIVATE_KEY|PASSWD|API_KEY)\s*=\s*)\S+',
    r'\1[REDACTED]',
    re.IGNORECASE,
)
# Context-keyword pattern: "token is XYZ", "key is XYZ", etc.
_spec(
    r'(?:token|secret|password|key|passwd)\s+(?:is\s+)?[A-Za-z0-9+/=_\-]{8,}',
    r'((?:token|secret|password|key|passwd)\s+(?:is\s+)?)([A-Za-z0-9+/=_\-]{8,})',
    r'\1[REDACTED]',
    re.IGNORECASE,
)


# ── Protected file loader ──────────────────────────────────────────────────────

def _load_protected_patterns() -> list[str]:
    try:
        data = json.loads(CONSTITUTION_PATH.read_text())
        return data.get("protected_files", [])
    except Exception:
        # Hard-coded fallback — constitution.json should never be absent
        return [
            "/opt/nexus/agents/hierarchy_manager.py",
            "/opt/nexus/agents/agent_registry.py",
            "/opt/nexus/agents/agent_workflow.py",
            "/opt/nexus/agents/blockchain_logger.py",
            "/opt/nexus/agents/llm_client.py",
            "/opt/nexus/agents/.env",
            "/opt/nexus/contracts/source/*.sol",
            "/opt/nexus/blockchain/genesis*.json",
            "/opt/nexus/automation/constitution.json",
            "/opt/nexus/automation/intent_registry.yaml",
        ]


# ── Public API ─────────────────────────────────────────────────────────────────

def check_protected_files(file_list: list[str]) -> list[str]:
    """Return the subset of file_list that matches a protected file pattern.

    An empty return value means all files are safe to modify.
    Supports fnmatch glob patterns from constitution.json.
    """
    patterns = _load_protected_patterns()
    matched: list[str] = []
    for path in file_list:
        for pattern in patterns:
            if fnmatch.fnmatch(path, pattern):
                matched.append(path)
                break
            # Non-glob exact or prefix match
            if "*" not in pattern and (path == pattern or path.startswith(pattern)):
                matched.append(path)
                break
    return matched


def check_command_safety(command: str) -> dict:
    """Assess whether a shell command is safe to execute autonomously.

    Returns:
        {"safe": True,  "reason": "allowlisted"}
        {"safe": False, "reason": "<blocklist|needs_approval> — <detail>"}

    Logic:
        1. Blocklist substring scan (hard block).
        2. First token against allowlist (unknown → needs human approval).
        Special: intent_registry.yaml — permits status-field-only sed patterns.
    """
    cmd = command.strip()
    if not cmd:
        return {"safe": True, "reason": "empty command"}

    # 1. Blocklist — any substring is a hard block
    for blocked in COMMAND_BLOCKLIST:
        if blocked in cmd:
            return {
                "safe":   False,
                "reason": f"blocklist — matched: {blocked!r}",
            }

    # 2. Special case: intent_registry.yaml status-only edits are permitted
    if "intent_registry.yaml" in cmd:
        # Allow if it's a targeted status field update (sed -i 's/status: .../status: .../g')
        if re.search(r"sed.*status:.*intent_registry\.yaml", cmd):
            return {"safe": True, "reason": "intent_registry status update (allowed)"}
        return {
            "safe":   False,
            "reason": "needs_approval — intent_registry.yaml modifications require review",
        }

    # 3. Allowlist — unknown first token → needs approval
    parts = cmd.split()
    first = parts[0] if parts else ""
    if first and first not in COMMAND_ALLOWLIST:
        return {
            "safe":   False,
            "reason": f"needs_approval — {first!r} not in command allowlist",
        }

    return {"safe": True, "reason": "allowlisted"}


def check_change_size(plan: dict) -> dict:
    """Check whether a plan's change volume is within safety limits.

    Returns:
        {"within_limits": True,  "needs_approval": False, "reason": ""}
        {"within_limits": True,  "needs_approval": True,  "reason": "<soft limit detail>"}
        {"within_limits": False, "needs_approval": False, "reason": "<hard limit detail>"}
    """
    steps          = plan.get("steps", []) or []
    files_modified = plan.get("files_modified", []) or []
    files_created  = plan.get("files_created", []) or []

    total_added   = sum(s.get("lines_added_estimate", 0)   for s in steps)
    total_deleted = sum(s.get("lines_deleted_estimate", 0) for s in steps)
    num_modified  = len(files_modified)
    num_total     = num_modified + len(files_created)

    # Hard limits (within_limits=False)
    if total_added > MAX_LINES_ADDED:
        return {
            "within_limits":  False,
            "needs_approval": False,
            "reason": f"hard limit: {total_added} lines added (max {MAX_LINES_ADDED})",
        }
    if total_deleted > MAX_LINES_DELETED:
        return {
            "within_limits":  False,
            "needs_approval": False,
            "reason": f"hard limit: {total_deleted} lines deleted (max {MAX_LINES_DELETED})",
        }
    if num_modified > MAX_FILES_MODIFIED:
        return {
            "within_limits":  False,
            "needs_approval": False,
            "reason": f"hard limit: {num_modified} files modified (max {MAX_FILES_MODIFIED})",
        }

    # Soft limits (needs_approval=True)
    if total_added > SOFT_LINES_ADDED:
        return {
            "within_limits":  True,
            "needs_approval": True,
            "reason": f"soft limit: {total_added} lines added (threshold {SOFT_LINES_ADDED})",
        }
    if total_deleted > SOFT_LINES_DELETED:
        return {
            "within_limits":  True,
            "needs_approval": True,
            "reason": f"soft limit: {total_deleted} lines deleted (threshold {SOFT_LINES_DELETED})",
        }
    if num_modified > SOFT_FILES_MODIFIED:
        return {
            "within_limits":  True,
            "needs_approval": True,
            "reason": f"soft limit: {num_modified} files modified (threshold {SOFT_FILES_MODIFIED})",
        }

    return {"within_limits": True, "needs_approval": False, "reason": ""}


def check_secrets_in_output(text: str) -> bool:
    """Return True if text appears to contain secrets (keys, tokens, passwords)."""
    for detect_re, _, _ in _SECRET_SPECS:
        if detect_re.search(text):
            return True
    return False


def sanitize_for_log(text: str) -> str:
    """Replace any detected secrets in text with '[REDACTED]' before logging."""
    if not text:
        return text
    for _, redact_re, replacement in _SECRET_SPECS:
        text = redact_re.sub(replacement, text)
    return text
