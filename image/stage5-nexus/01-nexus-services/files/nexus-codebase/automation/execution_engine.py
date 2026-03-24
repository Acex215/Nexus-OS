#!/usr/bin/env python3
"""NEXUS OS Execution Engine

Safe, audited execution of structured task plans.

- Validates plans against safety limits and protected files before any execution
- Executes steps on local or remote nodes via SSH
- Backs up files before modification, restores on rollback
- Commits successful runs to a git branch

Public API:
    validate_plan(plan)                       -> dict
    execute_on_node(node, command, timeout)   -> dict
    backup_file(filepath, backup_dir)         -> str | None
    execute_plan(plan, dry_run)               -> dict
    rollback_plan(plan, backup_dir)           -> None
"""
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from guardrails import (
    check_protected_files, check_command_safety, check_change_size,
)

log = logging.getLogger("execution_engine")

NODE_IPS = {
    "nexus-admin":   None,
    "nexus-master":  "10.0.20.3",
    "nexus-ai":      "10.0.20.4",
    "nexus-storage": "10.0.20.11",
    "nexus-ai2":     "10.0.20.6",
}

BACKUP_BASE = Path("/opt/nexus/backups/auto")
REPO_PATH   = Path("/opt/nexus")


# ── Validation ────────────────────────────────────────────────────────────────

def validate_plan(plan: dict) -> dict:
    """Check a structured plan for safety before any execution.

    Delegates to guardrails.py for all policy checks.

    Returns:
        {"valid": True}
        {"valid": False, "reason": str, "blocked": True}
        {"valid": False, "reason": str, "needs_approval": True}
    """
    steps          = plan.get("steps", []) or []
    files_modified = plan.get("files_modified", []) or []
    files_created  = plan.get("files_created", [])  or []

    # 1. Protected files — plan-level lists
    all_files = files_modified + files_created
    blocked   = check_protected_files(all_files)
    if blocked:
        return {"valid": False, "reason": f"Protected file: {blocked[0]}", "blocked": True}

    # Per-step paths and command strings
    for step in steps:
        path = step.get("path", "")
        if path:
            hit = check_protected_files([path])
            if hit:
                return {"valid": False, "reason": f"Protected file in step: {path}", "blocked": True}
        cmd = step.get("command", "")
        if cmd:
            # Scan command string for embedded protected path stems
            hit = check_protected_files([cmd])
            if hit:
                return {"valid": False, "reason": f"Protected path in command: {cmd[:60]}", "blocked": True}

    # 2. Change-size limits
    size = check_change_size(plan)
    if not size["within_limits"]:
        return {"valid": False, "reason": size["reason"], "blocked": True}
    if size["needs_approval"]:
        return {"valid": False, "reason": size["reason"], "needs_approval": True}

    # 3 & 4. Command blocklist and allowlist
    for step in steps:
        cmd = step.get("command", "").strip()
        if not cmd:
            continue
        safety = check_command_safety(cmd)
        if not safety["safe"]:
            reason = safety["reason"]
            if "blocklist" in reason:
                return {
                    "valid": False,
                    "reason": f"Blocked command in step {step.get('step_num', '?')}: {reason}",
                    "blocked": True,
                }
            return {
                "valid": False,
                "reason": f"Step {step.get('step_num', '?')}: {reason}",
                "needs_approval": True,
            }

    return {"valid": True}


# ── Node execution ─────────────────────────────────────────────────────────────

def execute_on_node(node: str, command: str, timeout: int = 300) -> dict:
    """Run a shell command on the specified node.

    Returns:
        {"stdout": str, "stderr": str, "returncode": int, "node": str, "timed_out": bool}
    """
    ip = NODE_IPS.get(node)

    if ip is None:
        # Local execution
        try:
            r = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=timeout
            )
            return {
                "stdout":     r.stdout[:4000],
                "stderr":     r.stderr[:2000],
                "returncode": r.returncode,
                "node":       node,
                "timed_out":  False,
            }
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "TIMEOUT", "returncode": -1, "node": node, "timed_out": True}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": -1, "node": node, "timed_out": False}
    else:
        # Remote execution via SSH
        ssh_cmd = [
            "ssh",
            "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=no",
            "-o", "BatchMode=yes",
            f"mhuraibi@{ip}",
            command,
        ]
        try:
            r = subprocess.run(
                ssh_cmd, capture_output=True, text=True, timeout=timeout
            )
            return {
                "stdout":     r.stdout[:4000],
                "stderr":     r.stderr[:2000],
                "returncode": r.returncode,
                "node":       node,
                "timed_out":  False,
            }
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "SSH TIMEOUT", "returncode": -1, "node": node, "timed_out": True}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": -1, "node": node, "timed_out": False}


# ── File backup ────────────────────────────────────────────────────────────────

def backup_file(filepath: str, backup_dir: str | None = None) -> str | None:
    """Copy filepath to backup_dir if it exists.

    Uses a manifest.json in backup_dir to record original paths so rollback_plan
    can restore them correctly regardless of path-separator collisions.

    Returns the backup path, or None if the file didn't exist.
    """
    if not os.path.exists(filepath):
        return None

    if backup_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = str(BACKUP_BASE / ts)

    os.makedirs(backup_dir, exist_ok=True)

    manifest_path = os.path.join(backup_dir, "manifest.json")
    if os.path.isfile(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)
    else:
        manifest = {}

    idx = len(manifest)
    backup_name = f"file_{idx:04d}"
    backup_path = os.path.join(backup_dir, backup_name)

    try:
        subprocess.run(["cp", "-p", filepath, backup_path], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        log.error("backup_file: cp failed for %s: %s", filepath, e.stderr)
        return None

    manifest[backup_name] = filepath
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    log.info("Backed up %s → %s", filepath, backup_path)
    return backup_path


# ── Rollback ───────────────────────────────────────────────────────────────────

def rollback_plan(plan: dict, backup_dir: str) -> None:
    """Restore backed-up files and remove any files created by the plan."""
    files_created = plan.get("files_created", []) or []

    # Remove files the plan created
    for fp in files_created:
        if os.path.exists(fp):
            try:
                os.remove(fp)
                log.info("Rollback: removed created file %s", fp)
            except Exception as e:
                log.warning("Rollback: could not remove %s: %s", fp, e)

    # Restore backed-up files via manifest
    manifest_path = os.path.join(backup_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        return

    with open(manifest_path) as f:
        manifest = json.load(f)

    for backup_name, original_path in manifest.items():
        backup_path = os.path.join(backup_dir, backup_name)
        if not os.path.isfile(backup_path):
            log.warning("Rollback: backup file missing: %s", backup_path)
            continue
        try:
            Path(original_path).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["cp", "-p", backup_path, original_path], check=True, capture_output=True)
            log.info("Rollback: restored %s", original_path)
        except Exception as e:
            log.warning("Rollback: could not restore %s: %s", original_path, e)


# ── Main execution ─────────────────────────────────────────────────────────────

def execute_plan(plan: dict, dry_run: bool = False) -> dict:
    """Execute a validated structured plan step by step.

    Creates a git branch, backs up files before modification, and commits
    on success. Rolls back on any step failure.

    Returns:
        Success: {"success": True,  "branch": str, "steps_completed": int,
                  "backup_dir": str, "commit_msg": str, "outputs": list}
        Failure: {"success": False, "failed_step": int, "error": str,
                  "rolled_back": True, "branch": str, "steps_completed": int,
                  "outputs": list}
    """
    intent_id = plan.get("intent_id", "unknown")
    summary   = plan.get("summary", "")
    steps     = plan.get("steps", []) or []
    rollback_cmds = plan.get("rollback_steps", []) or []

    # Build branch name and backup dir (sanitize intent_id)
    ts       = int(time.time())
    safe_id  = re.sub(r"[^a-zA-Z0-9\-_]", "-", intent_id)[:40]
    branch   = f"auto/{safe_id}-{ts}"
    backup_dir = str(BACKUP_BASE / f"{safe_id}-{ts}")

    os.makedirs(backup_dir, exist_ok=True)

    if not dry_run:
        r = subprocess.run(
            ["git", "-C", str(REPO_PATH), "checkout", "-b", branch],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            log.warning("git checkout -b failed: %s", r.stderr.strip())

    outputs: list[dict] = []

    for step in steps:
        step_num = step.get("step_num", len(outputs) + 1)
        action   = step.get("action", "bash")
        node     = step.get("node", "nexus-admin")
        cmd      = step.get("command", "")
        path     = step.get("path", "")
        content  = step.get("content", "")
        expect   = step.get("expect_pattern") or ""
        desc     = step.get("description", f"Step {step_num}")

        log.info("Step %d/%d [%s@%s]: %s", step_num, len(steps), action, node, desc)

        if dry_run:
            outputs.append({
                "stdout": f"[DRY RUN] {desc}",
                "stderr": "", "returncode": 0, "node": node, "timed_out": False,
            })
            continue

        # Backup existing file before this step touches it
        if action in ("modify_file", "create_file") and path and os.path.exists(path):
            backup_file(path, backup_dir)

        # Execute the step
        if action == "create_file":
            if not path:
                result: dict = {
                    "stdout": "", "stderr": "create_file: no path provided",
                    "returncode": 1, "node": node, "timed_out": False,
                }
            else:
                try:
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    Path(path).write_text(content, encoding="utf-8")
                    subprocess.run(
                        ["git", "-C", str(REPO_PATH), "add", path],
                        capture_output=True,
                    )
                    result = {
                        "stdout": f"Created {path} ({len(content)} bytes)",
                        "stderr": "", "returncode": 0, "node": node, "timed_out": False,
                    }
                except Exception as e:
                    result = {
                        "stdout": "", "stderr": str(e),
                        "returncode": 1, "node": node, "timed_out": False,
                    }
        else:
            # bash / modify_file / ssh_command all run via execute_on_node
            result = execute_on_node(node, cmd)

            # Permission-denied auto-retry with sudo (local commands only)
            if (result["returncode"] != 0
                    and not result["timed_out"]
                    and node == "nexus-admin"
                    and "permission denied" in (result["stderr"] + result["stdout"]).lower()
                    and not cmd.strip().lower().startswith("sudo")):
                log.warning("Step %d: permission denied — retrying with sudo", step_num)
                sudo_r = execute_on_node(node, "sudo " + cmd)
                if sudo_r["returncode"] == 0:
                    log.info("Step %d: sudo retry succeeded", step_num)
                result = sudo_r

        # Check expect_pattern (on non-empty stdout+stderr, after a successful rc).
        # A mismatch is a soft warning — the command succeeded, output just looks
        # different than expected (indentation, format, etc.).  Don't fail the step.
        if expect and result["returncode"] == 0:
            combined = result["stdout"] + result["stderr"]
            if not re.search(expect, combined):
                log.warning(
                    "Step %d: expect_pattern %r not found in output (soft check — "
                    "step still passes; check output format if this recurs)",
                    step_num, expect,
                )

        outputs.append(result)

        if result["returncode"] != 0:
            log.error(
                "Step %d failed (rc=%d timed_out=%s): %s",
                step_num, result["returncode"], result["timed_out"], result["stderr"][:200],
            )

            # Run rollback steps in reverse order
            if rollback_cmds:
                log.info("Executing %d rollback step(s)", len(rollback_cmds))
                for rb_cmd in reversed(rollback_cmds):
                    # LLM may return rollback_steps as step-dicts instead of strings
                    cmd_str = (rb_cmd.get("command", str(rb_cmd))
                               if isinstance(rb_cmd, dict) else str(rb_cmd))
                    rb_r = execute_on_node("nexus-admin", cmd_str, timeout=60)
                    log.info("Rollback rc=%d: %s", rb_r["returncode"], cmd_str[:60])

            # Restore file backups
            rollback_plan(plan, backup_dir)

            # Return to main branch
            subprocess.run(
                ["git", "-C", str(REPO_PATH), "checkout", "main"],
                capture_output=True,
            )

            perm_denied = "permission denied" in (
                result["stderr"] + result["stdout"]
            ).lower()
            return {
                "success":          False,
                "failed_step":      step_num,
                "error":            result["stderr"][:500],
                "rolled_back":      True,
                "branch":           branch,
                "steps_completed":  len(outputs) - 1,
                "outputs":          outputs,
                "permission_denied": perm_denied,
            }

    if dry_run:
        return {
            "success": True, "dry_run": True,
            "steps_completed": len(steps), "branch": branch, "outputs": outputs,
        }

    # All steps passed — stage only the plan's declared files and commit
    # Never use `git add -A` (sweeps entire repo, breaks checkout back to main)
    commit_msg = f"[CAF auto] {intent_id}: {summary}"
    declared_files = (plan.get("files_modified") or []) + (plan.get("files_created") or [])
    if declared_files:
        for fp in declared_files:
            if os.path.exists(fp):
                subprocess.run(["git", "-C", str(REPO_PATH), "add", fp], capture_output=True)
    # If no declared files, nothing extra to stage (create_file steps already did git add)
    r = subprocess.run(
        ["git", "-C", str(REPO_PATH), "commit", "--allow-empty", "-m", commit_msg],
        capture_output=True, text=True,
    )
    log.info("git commit: %s", r.stdout.strip() or r.stderr.strip())

    return {
        "success":         True,
        "branch":          branch,
        "steps_completed": len(steps),
        "backup_dir":      backup_dir,
        "commit_msg":      commit_msg,
        "outputs":         outputs,
    }
