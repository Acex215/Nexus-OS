#!/usr/bin/env python3
"""NEXUS OS Development Orchestrator v4.0

Unified async event loop with health monitoring, git tracking,
and autonomous intent execution.

Runs on nexus-admin. Uses:
- Tier 1: ThinkPad Qwen3.5-35B (when online, VLAN 30)
- Tier 2: nexus-ai2 Qwen2.5-7B (24/7 fallback, VLAN 20)
- ChromaDB for persistent memory
- Git branch isolation for safety
"""
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, '/opt/nexus/automation')

from chroma_memory import remember, recall
from planning_engine import (
    select_next_intent, update_intent_status, get_active_intents, decompose_intent,
    load_intent_registry,
)
from context_builder import build_context_packet
from llm_router import route_llm_call, check_tier_health, TIER_ENDPOINTS
from task_planner import generate_execution_plan, verify_plan_result
from web_research import research_topic, should_research
from audit_logger import log_action, get_recent_audits
from feedback_loop import (
    analyze_task_result, store_lesson,
    write_change_ledger_entry, get_relevant_lessons,
)
from health_monitor import (
    run_health_checks, store_health_results, detect_transitions,
    get_health_summary, update_project_state,
)
from git_monitor import (
    check_for_new_commits, get_changed_files, trigger_incremental_reindex,
)
import discord_comms
from discord_comms import (
    send_notification, start_discord_listener, handle_discord_message,
    should_notify, is_idle_mode, update_stats,
)
from discord_reporter import send_oneshot
from persona import format_for_human
from failure_analyzer import analyze_failure, clear_failure_history, _failure_history

# ── Constants ──────────────────────────────────────────────────────────────────

TIER1_URL  = 'http://10.0.30.2:1234/v1/chat/completions'
TIER1_MODEL = 'qwen/qwen3.5-35b-a3b'
TIER2_URL  = 'http://10.0.20.6:11434/v1/chat/completions'
TIER2_MODEL = 'qwen2.5-coder:7b'

LIVING_GUIDE  = '/opt/nexus/automation/NEXUS_Living_Guide.md'
PROJECT_STATE = '/opt/nexus/automation/project_state.json'
REPO_PATH     = '/opt/nexus'
AUDIT_LOG     = '/opt/nexus/automation/audit.jsonl'
LOG_FILE      = '/opt/nexus/automation/orchestrator.log'
BACKUP_DIR    = '/opt/nexus/backups/auto'

CYCLE_SLEEP     = 30    # main loop tick (seconds)
FAIL_PAUSE      = 1800  # pause after 3 consecutive failures (seconds)
RETRY_BACKOFFS  = [60, 120, 300]  # seconds between LLM-timeout planning retries

TASK_TIMEOUT_MINUTES = int(os.environ.get('TASK_TIMEOUT_MINUTES', '30'))
TASK_TIMINGS_PATH    = '/opt/nexus/automation/.task_timings.json'
MAX_TIMEOUT_FAILURES = 3

CATEGORY_ORDER_SCORE = {"next_step": 0, "next_phase": 1, "roadmap": 2, "idea": 3}

PROTECTED = [
    '/opt/nexus/agents/hierarchy_manager.py',
    '/opt/nexus/agents/agent_registry.py',
    '/opt/nexus/agents/agent_workflow.py',
    '/opt/nexus/agents/blockchain_logger.py',
    '/opt/nexus/agents/llm_client.py',
    '/opt/nexus/agents/.env',
]

NODE_IPS = {
    'nexus-master':  '10.0.20.3',
    'nexus-ai':      '10.0.20.4',
    'nexus-storage': '10.0.20.11',
    'nexus-ai2':     '10.0.20.6',
    'nexus-admin':   None,
}

# ── Logging ────────────────────────────────────────────────────────────────────

def log(msg: str, level: str = 'INFO') -> None:
    ts   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}][{level}] {msg}'
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')


def audit(entry: dict) -> None:
    """Write a structured audit entry via audit_logger (standardized schema)."""
    log_action(entry)


# ── Low-level helpers ──────────────────────────────────────────────────────────

def run_cmd(cmd: str, timeout: int = 60) -> dict:
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return {
            'stdout':     result.stdout[:2000],
            'stderr':     result.stderr[:2000],
            'returncode': result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {'stdout': '', 'stderr': 'TIMEOUT', 'returncode': -1}
    except Exception as e:
        return {'stdout': '', 'stderr': str(e), 'returncode': -1}


def run_plan_step(step: dict) -> dict:
    """Execute a single plan step based on its action type."""
    action  = step.get('action', 'bash')
    node    = step.get('node', 'nexus-admin')
    cmd     = step.get('command', '')
    path    = step.get('path', '')
    content = step.get('content', '')

    if action == 'create_file':
        if not path:
            return {'stdout': '', 'stderr': 'create_file: no path provided', 'returncode': 1}
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(content, encoding='utf-8')
            return {'stdout': f'Created {path} ({len(content)} bytes)', 'stderr': '', 'returncode': 0}
        except Exception as e:
            return {'stdout': '', 'stderr': str(e), 'returncode': 1}

    if action == 'modify_file':
        if not cmd:
            return {'stdout': '', 'stderr': 'modify_file: no command provided', 'returncode': 1}
        return run_cmd(cmd)

    if action == 'ssh_command':
        ip = NODE_IPS.get(node)
        if not ip:
            return run_cmd(cmd)
        import shlex
        ssh_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 mhuraibi@{ip} {shlex.quote(cmd)}"
        return run_cmd(ssh_cmd, timeout=120)

    # Default: bash
    return run_cmd(cmd)


def ask_llm(system: str, user: str, prefer_tier1: bool = True,
            max_tokens: int = 2048, timeout: int = 180) -> str | None:
    role   = "plan" if prefer_tier1 else "summarize"
    result = route_llm_call(role, system, user)
    if result.get("error"):
        log(f'ask_llm: {result["error"]}', 'ERROR')
        return None
    tier = result.get("tier_used", "?")
    log(f'ask_llm: Tier {tier} responded (role={role})')
    return result.get("response")


def is_protected(filepath: str) -> bool:
    import fnmatch
    for p in PROTECTED:
        if '*' in p:
            if fnmatch.fnmatch(filepath, p):
                return True
        elif filepath == p or filepath.startswith(p):
            return True
    return False


def backup_file(filepath: str) -> None:
    if os.path.exists(filepath):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts   = datetime.now().strftime('%Y%m%d_%H%M%S')
        name = os.path.basename(filepath)
        dst  = os.path.join(BACKUP_DIR, f'{name}.{ts}.bak')
        subprocess.run(['cp', filepath, dst])
        log(f'Backed up {filepath} -> {dst}')


# ── Watchdog timing helpers ────────────────────────────────────────────────────

def _load_timings() -> dict:
    try:
        with open(TASK_TIMINGS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_timings(timings: dict) -> None:
    try:
        tmp = TASK_TIMINGS_PATH + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(timings, f, indent=2)
        os.replace(tmp, TASK_TIMINGS_PATH)
    except Exception as e:
        log(f'_save_timings: {e}', 'WARN')


def _record_task_start(intent_id: str) -> None:
    """Record the current UTC time as started_at for watchdog timeout tracking."""
    timings = _load_timings()
    entry   = timings.get(intent_id, {})
    entry['started_at'] = datetime.now(timezone.utc).isoformat()
    entry.setdefault('timeout_failures', 0)
    timings[intent_id]  = entry
    _save_timings(timings)


def _clear_task_timing(intent_id: str) -> None:
    """Remove timing data for an intent when it completes or fails normally."""
    timings = _load_timings()
    timings.pop(intent_id, None)
    _save_timings(timings)


def read_living_guide() -> str:
    with open(LIVING_GUIDE) as f:
        return f.read()


def read_project_state() -> dict:
    with open(PROJECT_STATE) as f:
        return json.load(f)


# ── Planning helpers ───────────────────────────────────────────────────────────

def plan_task(intent: dict, context_packet: str) -> list[str] | None:
    """Generate execution plan via task_planner; stash full plan in intent['_plan']."""
    plan = generate_execution_plan(intent, context_packet)
    if plan is None:
        return None
    intent['_plan'] = plan
    return [s.get('command', s.get('description', f'Step {i+1}'))
            for i, s in enumerate(plan.get('steps', []))]


def select_next_task(thinkpad_alive: bool) -> tuple[dict | None, list[dict], dict | None]:
    """Deterministic task selection: planning_engine picks WHAT, LLM generates HOW.

    Returns (task_dict | None, intents_needing_notification, retry_state | None).
    - task_dict is None when there is no autonomous work to do.
    - retry_state is set (not None) when planning failed due to LLM unavailability;
      it contains {'intent': ..., 'context': ...} so the caller can schedule a retry.
      The intent is left in_progress to prevent re-selection.
    """
    selected_intent, to_notify = select_next_intent(thinkpad_online=thinkpad_alive)

    if selected_intent is None:
        log('No actionable intents found in registry', 'IDLE')
        return (None, to_notify, None)

    intent    = selected_intent
    intent_id = intent['id']
    log(f'Selected intent: {intent_id} — {intent["title"]}')

    if not update_intent_status(intent_id, 'in_progress'):
        log(f'Could not transition {intent_id} to in_progress', 'WARN')
    else:
        _record_task_start(intent_id)

    # Build context packet (include live health summary)
    try:
        context_packet = build_context_packet(
            intent.get('description', intent['title']),
            affected_files=intent.get('affected_files', []),
        )
        log(f'Context packet: {len(context_packet)} chars')
    except Exception as e:
        log(f'context_builder failed: {e}', 'WARN')
        context_packet = f"Task: {intent['title']}\n{intent.get('description', '')}"

    # Append health summary to context
    try:
        health_str = get_health_summary()
        context_packet += f"\n\n--- Live Cluster Health ---\n{health_str}"
    except Exception:
        pass

    steps = plan_task(intent, context_packet)
    if not steps and not intent.get('_plan', {}).get('should_decompose'):
        import task_planner as _tp
        if _tp._last_failure_was_llm:
            # LLM timed out — intent stays in_progress; caller will schedule retry
            log(f'LLM unavailable for planning {intent_id} — signalling retry', 'RETRY')
            return (None, to_notify, {'intent': intent, 'context': context_packet})

        # Structural failure (bad JSON, unsafe steps, etc.) — mark failed immediately
        log(f'Planning failed for {intent_id} — marking failed', 'ERROR')
        if should_research(intent.get('title', ''), 'planning failed'):
            query = f"{intent.get('title', '')} implementation guide python"
            log(f'Researching to aid future planning: {query[:60]}', 'RESEARCH')
            research_topic(query, max_pages=2)
        update_intent_status(intent_id, 'failed')
        try:
            all_intents  = load_intent_registry()
            blocked_by   = [i['id'] for i in all_intents
                            if intent_id in (i.get('depends_on') or [])]
            blocks_str   = ', '.join(f'`{b}`' for b in blocked_by) if blocked_by else 'none'
            send_oneshot(format_for_human("failure", {
                "intent_id":   intent_id,
                "title":       intent.get("title", ""),
                "failed_step": "planning",
                "error":       "Structural error (bad plan JSON, unsafe steps, or parse failure)",
                "rolled_back": False,
                "blocks":      blocks_str,
            }))
        except Exception as _e:
            log(f'Failure notification error: {_e}', 'WARN')
        return (None, to_notify, None)

    plan = intent.get('_plan', {})

    # ── Decomposition path ─────────────────────────────────────────────────────
    if plan.get('should_decompose') and plan.get('decomposition'):
        sub_tasks = plan['decomposition']
        log(f'Plan requests decomposition of {intent_id} into {len(sub_tasks)} sub-task(s)', 'PLAN')
        try:
            sub_intents = decompose_intent(intent, sub_tasks)
        except Exception as e:
            log(f'decompose_intent failed: {e} — marking {intent_id} failed', 'ERROR')
            update_intent_status(intent_id, 'failed')
            return (None, to_notify, None)
        if not sub_intents:
            log(f'Decomposition of {intent_id} produced 0 sub-tasks — marking failed', 'ERROR')
            update_intent_status(intent_id, 'failed')
            send_oneshot(
                f'⚠️ **Decomposition failed** for `{intent_id}`:\n'
                f'Plan requested decomposition but produced 0 sub-tasks '
                f'(depth limit reached or empty list). Marked failed — will retry.'
            )
            return (None, to_notify, None)
        ids_preview = ', '.join(f"`{s['id']}`" for s in sub_intents[:5])
        log(f'Decomposed {intent_id} → {len(sub_intents)} sub-intent(s): {ids_preview}', 'PLAN')
        send_oneshot(format_for_human("decomposed", {
            "intent_id": intent_id,
            "title":     intent["title"],
            "sub_count": len(sub_intents),
            "sub_ids":   [s["id"] for s in sub_intents[:5]],
        }))
        return (None, to_notify, None)

    # ── Human-review path ──────────────────────────────────────────────────────
    if plan.get('notify_human', False):
        conf = float(plan.get('confidence', 0))
        risk = plan.get('risk_assessment', '?')
        log(
            f'Plan for {intent_id} requires human review '
            f'(confidence={conf:.2f}, risk={risk}) — marking failed.',
            'APPROVAL',
        )
        update_intent_status(intent_id, 'failed')
        return (None, to_notify, None)

    log(f'Plan generated: {len(steps)} steps, confidence={float(plan.get("confidence", 0)):.2f}')
    return ({
        'task':             intent['title'],
        'intent_id':        intent_id,
        'score':            CATEGORY_ORDER_SCORE.get(intent.get('category', 'idea'), 3),
        'steps':            steps,
        '_plan':            plan,
        '_intent':          intent,
        '_context_packet':  context_packet,
    }, to_notify, None)


def _run_self_repair(
    task: dict, plan: dict, result: dict, intent_id: str, task_name: str,
) -> dict | None:
    """Diagnose a failed execution step and re-run with a revised plan.

    Returns a new execute_plan result dict if repair was attempted (may still
    be a failure), or None if repair was skipped (caller should suppress the
    standard failure notification since we already sent one).
    """
    from execution_engine import execute_plan as _execute_plan

    history = _failure_history.get(intent_id, [])

    if len(history) >= 3:
        last_diag = history[-1].get('diagnosis', 'unknown')
        log(f'Self-repair exhausted ({len(history)} attempts) for {intent_id}', 'ERROR')
        send_oneshot(
            f'❌ Failed: `{intent_id}` — exhausted {len(history)} self-repair attempts.\n'
            f'Last diagnosis: {last_diag}'
        )
        return None

    plan_steps      = plan.get('steps', [])
    failed_step_num = result.get('failed_step', 1)
    step_index      = failed_step_num - 1           # convert 1-indexed → 0-indexed

    failed_step = next(
        (s for s in plan_steps if s.get('step_num') == failed_step_num),
        plan_steps[step_index] if step_index < len(plan_steps) else {},
    )
    step_result = (result.get('outputs') or [{}])[-1]
    intent_obj  = task.get('_intent', {'id': intent_id, 'title': task_name})

    log(f'Running failure analysis for {intent_id} (attempt {len(history)+1}/3)', 'REPAIR')
    analysis = analyze_failure(
        intent         = intent_obj,
        failed_step    = failed_step,
        step_result    = step_result,
        step_index     = step_index,
        execution_plan = plan_steps,
        failure_history= history,
    )

    history.append(analysis)
    _failure_history[intent_id] = history

    diag = analysis.get('diagnosis', 'unknown')
    conf = analysis.get('confidence', 0.0)

    if not analysis.get('should_retry') or conf < 0.6:
        log(f'Self-repair declined for {intent_id}: should_retry={analysis["should_retry"]} conf={conf:.0%}', 'REPAIR')
        send_oneshot(
            f'❌ Failed: `{intent_id}` — {diag}\n'
            f'(self-repair confidence: {conf:.0%}, retryable: {analysis["should_retry"]})'
        )
        return None

    # Run pre-fix commands without approval gate
    for fix_cmd in analysis.get('pre_fix_commands', []):
        log(f'Self-repair pre-fix: {fix_cmd}', 'REPAIR')
        try:
            fr = subprocess.run(fix_cmd, shell=True, timeout=60, capture_output=True, text=True)
            if fr.returncode != 0:
                log(f'Pre-fix rc={fr.returncode}: {fr.stderr[:80]}', 'WARN')
        except Exception as _e:
            log(f'Pre-fix error (continuing): {_e}', 'WARN')

    revised_steps = analysis.get('revised_plan', [])
    if not revised_steps:
        log(f'Self-repair gave no revised steps for {intent_id} — giving up', 'WARN')
        send_oneshot(f'❌ Failed: `{intent_id}` — {diag}\n(self-repair produced no revised steps)')
        return None

    # Normalise revised steps to look like plan step dicts
    for i, rs in enumerate(revised_steps, step_index + 1):
        rs.setdefault('step_num', i)
        rs.setdefault('action', 'bash')
        rs.setdefault('node', 'nexus-admin')
        rs.setdefault('description', rs.get('command', '')[:80])

    new_plan = dict(plan)
    new_plan['steps'] = plan_steps[:step_index] + revised_steps

    log(f'Self-repair for {intent_id}: {diag} (conf={conf:.0%}) — re-executing', 'REPAIR')
    send_oneshot(
        f'🔧 Self-repair `{intent_id}`: {diag}\n'
        f'Retrying with revised plan (confidence: {conf:.0%})'
    )

    new_result = _execute_plan(new_plan)
    if new_result.get('success'):
        clear_failure_history(intent_id)
    return new_result


def execute_task(task: dict) -> bool:
    """Validate then execute a structured plan via execution_engine."""
    from execution_engine import validate_plan, execute_plan

    task_name = task.get('task', 'unknown')
    if task_name == 'IDLE' or not task.get('steps'):
        log('No actionable tasks. Sleeping.', 'IDLE')
        return True

    plan: dict = task.get('_plan', {})
    intent_id  = task.get('intent_id')

    if not plan or not plan.get('steps'):
        log(f'No structured plan for "{task_name}" — marking failed', 'ERROR')
        if intent_id:
            update_intent_status(intent_id, 'failed')
        return False

    # ── Pre-execution safety validation ───────────────────────────────────────
    validation = validate_plan(plan)
    if not validation['valid']:
        reason = validation.get('reason', 'unknown reason')
        if validation.get('blocked'):
            log(f'Plan BLOCKED for "{task_name}": {reason}', 'SAFETY')
            audit({'action': 'plan_blocked', 'task': task_name, 'reason': reason})
            send_notification('alert', f'Plan blocked for `{task_name}`:\n{reason}')
            if intent_id:
                update_intent_status(intent_id, 'failed')
            return False
        if validation.get('needs_approval'):
            log(f'Plan needs approval for "{task_name}": {reason}', 'APPROVAL')
            audit({'action': 'plan_needs_approval', 'task': task_name, 'reason': reason})
            from discord_comms import request_approval
            approved = request_approval(intent_id or task_name, f'{task_name} — {reason}')
            if not approved:
                log(f'Approval denied/timed out for "{task_name}" — marking blocked', 'APPROVAL')
                if intent_id:
                    update_intent_status(intent_id, 'blocked')
                return False
            log(f'Approval granted for "{task_name}" — proceeding', 'APPROVAL')

    # ── Execute ────────────────────────────────────────────────────────────────
    log(f'Executing plan for: {task_name}')
    result  = execute_plan(plan)
    success = result['success']
    outputs = result.get('outputs', [])

    # Permission denied (even after sudo retry): mark blocked, ask Md for help
    if not success and result.get('permission_denied'):
        err = result.get('error', '')
        log(f'Task BLOCKED — permission denied: {task_name} '
            f'(step {result.get("failed_step", "?")})', 'WARN')
        if intent_id:
            update_intent_status(intent_id, 'blocked')
            send_oneshot(format_for_human("blocked", {
                "intent_id": intent_id,
                "title":     task_name,
                "reason":    (
                    f"Permission denied at step {result.get('failed_step', '?')} "
                    f"(sudo also failed). Fix permissions then reply "
                    f"`approve {intent_id}` to retry.\n"
                    f"Error: {err[:150]}"
                ),
            }))
        return False

    # ── Self-repair: diagnose failure and retry with revised plan ──────────────
    _self_repair_ran = False
    if not success and intent_id and not result.get('permission_denied'):
        repaired = _run_self_repair(task, plan, result, intent_id, task_name)
        if repaired is None:
            _self_repair_ran = True   # _run_self_repair already sent the Discord message
        else:
            result  = repaired
            success = result['success']
            outputs = result.get('outputs', outputs)

    # ── LLM verification (advisory) ───────────────────────────────────────────
    if success and plan:
        intent_stub = {
            'title': task_name,
            'acceptance_criteria': plan.get('acceptance_criteria', []),
        }
        verdict = verify_plan_result(intent_stub, plan, outputs)
        log(f'Plan verification: success={verdict["success"]}, {verdict["reason"]}')
        if not verdict['success'] and verdict.get('suggestions'):
            log(f'  Suggestion: {verdict["suggestions"]}', 'HINT')

    # ── Update state ───────────────────────────────────────────────────────────
    branch     = result.get('branch', 'N/A')
    complexity = plan.get('risk_assessment', 'low').split()[0].lower()

    if success:
        remember(
            f'COMPLETED: {task_name}. steps={result.get("steps_completed", 0)}, branch={branch}',
            {'task': task_name, 'type': 'success', 'branch': branch},
        )
        log(f'Task DONE: {task_name}', 'SUCCESS')
        update_stats(in_progress='idle',
                     completed_today=discord_comms._stats['completed_today'] + 1)
        if should_notify('task_completed', complexity):
            send_oneshot(format_for_human("task_complete", {
                "intent_id": intent_id or task_name,
                "title":     task_name,
                "steps":     result.get("steps_completed", 0),
                "branch":    branch,
            }))
        if intent_id:
            update_intent_status(intent_id, 'completed')
    else:
        err = result.get('error', '')
        remember(
            f'FAILED: {task_name}. step={result.get("failed_step")}, '
            f'rolled_back={result.get("rolled_back")}, error={err[:120]}',
            {'task': task_name, 'type': 'failure'},
            'failures',
        )
        log(
            f'Task FAILED: {task_name} '
            f'(step {result.get("failed_step")}, rolled_back={result.get("rolled_back")})',
            'ERROR',
        )
        if should_research(task_name, err):
            query = f"{task_name} {err[:100]}".strip()
            log(f'Researching failure context: {query[:80]}', 'RESEARCH')
            research_topic(query, max_pages=2)
        update_stats(in_progress='idle', last_error=f'{task_name}: {err[:80]}')
        if intent_id:
            update_intent_status(intent_id, 'failed')
            # Notify Md immediately — don't let execution failures go silent
            # (skip if _run_self_repair already sent a specific failure message)
            if not _self_repair_ran:
                try:
                    all_intents = load_intent_registry()
                    blocked_by  = [i['id'] for i in all_intents
                                   if intent_id in (i.get('depends_on') or [])]
                    blocks_str  = ', '.join(f'`{b}`' for b in blocked_by) if blocked_by else 'none'
                    send_oneshot(format_for_human("failure", {
                        "intent_id":   intent_id,
                        "title":       task_name,
                        "failed_step": result.get("failed_step"),
                        "error":       err[:200],
                        "rolled_back": result.get("rolled_back"),
                        "blocks":      blocks_str,
                    }))
                except Exception as _e:
                    log(f'Failure notification error: {_e}', 'WARN')
        elif should_notify('task_failed'):
            send_oneshot(format_for_human("failure", {
                "intent_id":   task_name,
                "title":       task_name,
                "failed_step": result.get("failed_step"),
                "error":       err[:200],
                "rolled_back": result.get("rolled_back"),
                "blocks":      "none",
            }))

    audit({
        'action':          'task_complete' if success else 'task_failed',
        'intent_id':       intent_id,
        'branch':          branch,
        'steps_planned':   len(plan.get('steps', [])),
        'steps_completed': result.get('steps_completed', 0),
        'files_modified':  plan.get('files_modified', []),
        'files_created':   plan.get('files_created', []),
        'success':         success,
        'error':           result.get('error', ''),
    })

    # ── Feedback loop ──────────────────────────────────────────────────────────
    intent_obj      = task.get('_intent', {'id': intent_id or task_name, 'title': task_name})
    context_packet  = task.get('_context_packet', '')
    try:
        analysis = analyze_task_result(intent_obj, plan, result, context_packet)
        store_lesson(analysis, intent_obj)
        write_change_ledger_entry(intent_obj, plan, result)
        log(f'Feedback: outcome={analysis["outcome"]}, '
            f'retrieval={analysis["retrieval_quality"]}, '
            f'plan={analysis["plan_quality"]}', 'FEEDBACK')
        # Signal retry to the caller via the result dict
        if analysis.get('should_retry') and not success:
            result['_should_retry'] = True
    except Exception as e:
        log(f'Feedback loop error: {e}', 'WARN')

    # ── Follow-up intent generation (successful tasks only) ────────────────────
    if success:
        try:
            from planning_engine import generate_follow_up_intents
            follow_ups = generate_follow_up_intents(intent_obj, result)
            if follow_ups:
                ids_str = ', '.join(f"`{f['id']}`" for f in follow_ups)
                log(f'Follow-up intents generated: {ids_str}', 'FEEDBACK')
                send_oneshot(
                    f"🔁 **Follow-ups queued** after `{intent_id}`:\n"
                    + "\n".join(f"- {f['id']}: {f['title']}" for f in follow_ups)
                )
        except Exception as e:
            log(f'Follow-up generation error: {e}', 'WARN')

    if intent_id:
        _clear_task_timing(intent_id)
    return success


def update_guide_after_task(task_name: str, success: bool) -> None:
    ts     = datetime.now().strftime('%Y-%m-%d %H:%M')
    status = 'DONE' if success else 'FAILED'
    with open(LIVING_GUIDE, 'a') as f:
        f.write(f'\n- [{ts}] [{status}] {task_name}\n')
    state = read_project_state()
    state['last_updated']    = datetime.now().isoformat()
    state['last_updated_by'] = 'orchestrator'
    with open(PROJECT_STATE, 'w') as f:
        json.dump(state, f, indent=2)


# ── Unified async orchestrator ─────────────────────────────────────────────────

class NexusOrchestrator:
    """Async event-driven orchestrator with health, git, and intent handling."""

    # Event scheduling intervals (seconds)
    HEALTH_INTERVAL   = 300    #  5 minutes
    GIT_INTERVAL      = 900    # 15 minutes
    STATUS_INTERVAL   = 21600  #  6 hours
    WATCHDOG_INTERVAL = 300    #  5 minutes (stale-task detection)

    def __init__(self) -> None:
        self.last_health_check      = datetime.min
        self.last_git_check         = datetime.min
        self.last_status_report     = datetime.min
        self.last_watchdog_check    = datetime.min
        self.consecutive_failures   = 0
        self._thinkpad_alive        = False
        self._last_heartbeat        = 0.0
        self._next_intent_check     = 0.0   # epoch; 0 = run immediately
        self._last_deadlock_notify  = 0.0   # dedup deadlock alerts (24h)
        self._ran_task_this_cycle   = False  # True → skip sleep to chain tasks back-to-back
        # intent_id → {retry_time, attempt, intent, context}
        self._retry_queue: dict[str, dict] = {}

    # ── Tier-1 heartbeat ──────────────────────────────────────────────────────

    def _check_thinkpad(self) -> bool:
        now = time.time()
        if now - self._last_heartbeat < 300:
            return self._thinkpad_alive
        self._thinkpad_alive  = check_tier_health(1)
        self._last_heartbeat  = now
        log(f'ThinkPad {"ONLINE" if self._thinkpad_alive else "OFFLINE"}', 'HEARTBEAT')
        return self._thinkpad_alive

    def _check_llm_available(self) -> bool:
        """Return True if at least one LLM tier is healthy (uses cached health state)."""
        return any(check_tier_health(t) for t in [1, 2, 3])

    # ── Event handlers ────────────────────────────────────────────────────────

    async def _handle_health_check(self) -> None:
        log('Running cluster health checks…', 'HEALTH')
        loop    = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, run_health_checks)
        store_health_results(results)

        transitions = detect_transitions(results)
        for t in transitions:
            log(
                f'Service transition: {t["service"]} on {t["node"]}: '
                f'{t["was"]} → {t["now"]}',
                'HEALTH',
            )
            if t["now"] in ("failed", "unreachable"):
                send_notification(
                    "alert",
                    f'`{t["service"]}` on `{t["node"]}`: {t["was"]} → {t["now"]}',
                )

        update_project_state()
        log(f'Health check done: {len(results)} services, '
            f'{len(transitions)} transition(s)', 'HEALTH')

    async def _handle_git_check(self) -> None:
        loop       = asyncio.get_event_loop()
        new_commits = await loop.run_in_executor(None, check_for_new_commits)
        if not new_commits:
            return
        log(f'Git monitor: {len(new_commits)} new commit(s)', 'GIT')
        for commit in new_commits:
            changed = get_changed_files(REPO_PATH, commit)
            if changed:
                log(f'  commit {commit[:12]}: {len(changed)} file(s) changed', 'GIT')
                trigger_incremental_reindex(changed)

    async def _handle_status_report(self) -> None:
        try:
            from discord_comms import send_status_summary
            send_status_summary()
        except Exception as e:
            log(f'Status report failed: {e}', 'WARN')

    async def _handle_check_intents(self) -> None:
        """Select and execute the next pending intent."""
        self._check_thinkpad()
        self._next_intent_check = 0.0   # reset; may be set to future time below

        # Update pending queue count for status reports; reconcile in_progress state
        try:
            from planning_engine import load_intent_registry
            registry = load_intent_registry()
            pending      = sum(1 for i in registry if i.get('status') == 'pending')
            in_prog_ids  = [i['id'] for i in registry if i.get('status') == 'in_progress']
            update_stats(queue_pending=pending, tier1_online=self._thinkpad_alive)

            # Reconciliation: warn if YAML shows in_progress but engine has no active work
            engine_active = bool(
                self._retry_queue
                or getattr(self, '_ran_task_this_cycle', False)
            )
            if in_prog_ids and not engine_active:
                log(
                    f'RECONCILE: {len(in_prog_ids)} intent(s) marked in_progress in registry '
                    f'but execution engine has no active work: {in_prog_ids}. '
                    'Watchdog will recover these if they exceed timeout.',
                    'WARN',
                )
        except Exception:
            pass

        loop = asyncio.get_event_loop()

        # ── Retry queue: process due entries before picking new work ──────────
        if self._retry_queue:
            now_t = time.time()
            due = {k: v for k, v in self._retry_queue.items()
                   if now_t >= v['retry_time']}
            if due:
                # Process the earliest-due retry only (one at a time)
                intent_id, entry = min(due.items(), key=lambda x: x[1]['retry_time'])
                attempt = entry['attempt']
                intent  = entry['intent']
                context = entry['context']

                log(f'Planning retry {attempt}/{len(RETRY_BACKOFFS)} for {intent_id}', 'RETRY')
                steps = await loop.run_in_executor(None, plan_task, intent, context)

                import task_planner as _tp
                plan  = intent.get('_plan', {})

                if steps or plan.get('should_decompose'):
                    del self._retry_queue[intent_id]
                    log(f'Retry {attempt} succeeded for {intent_id}', 'RETRY')
                    send_oneshot(
                        f"✅ **Retry succeeded** for `{intent_id}` (attempt {attempt}/{len(RETRY_BACKOFFS)})"
                    )
                    if plan.get('should_decompose') and plan.get('decomposition'):
                        sub_tasks = plan['decomposition']
                        try:
                            sub_intents = decompose_intent(intent, sub_tasks)
                        except Exception as e:
                            log(f'decompose_intent failed: {e}', 'ERROR')
                            update_intent_status(intent_id, 'failed')
                            self._next_intent_check = time.time() + 30
                            return
                        if not sub_intents:
                            log(f'Decomposition of {intent_id} produced 0 sub-tasks — marking failed', 'ERROR')
                            update_intent_status(intent_id, 'failed')
                            send_oneshot(
                                f'⚠️ **Decomposition failed** for `{intent_id}`:\n'
                                f'Produced 0 sub-tasks (depth limit or empty list). Marked failed.'
                            )
                        else:
                            ids_preview = ', '.join(f"`{s['id']}`" for s in sub_intents[:5])
                            log(f'Decomposed {intent_id} → {len(sub_intents)} sub-intent(s)', 'PLAN')
                            send_oneshot(format_for_human("decomposed", {
                                "intent_id": intent_id,
                                "title":     intent.get("title", ""),
                                "sub_count": len(sub_intents),
                                "sub_ids":   [s["id"] for s in sub_intents[:5]],
                            }))
                        self._next_intent_check = time.time() + 30
                        return

                    task = {
                        'task':            intent['title'],
                        'intent_id':       intent_id,
                        'score':           CATEGORY_ORDER_SCORE.get(intent.get('category', 'idea'), 3),
                        'steps':           steps,
                        '_plan':           plan,
                        '_intent':         intent,
                        '_context_packet': context,
                    }
                    update_stats(in_progress=task['task'])
                    success = await loop.run_in_executor(None, execute_task, task)
                    update_guide_after_task(task['task'], success)
                    if success:
                        self.consecutive_failures = 0
                    else:
                        self.consecutive_failures += 1
                    self._next_intent_check = time.time() + 30
                    return

                elif _tp._last_failure_was_llm and attempt < len(RETRY_BACKOFFS):
                    del self._retry_queue[intent_id]
                    backoff = RETRY_BACKOFFS[attempt]
                    log(f'LLM still unavailable for {intent_id} — '
                        f'retry in {backoff}s (attempt {attempt + 1}/{len(RETRY_BACKOFFS)})',
                        'RETRY')
                    self._retry_queue[intent_id] = {
                        'retry_time': time.time() + backoff,
                        'attempt':    attempt + 1,
                        'intent':     intent,
                        'context':    context,
                    }
                    # Fall through to proactive work while waiting

                else:
                    del self._retry_queue[intent_id]
                    log(f'All planning retries failed for {intent_id} — marking failed', 'ERROR')
                    update_intent_status(intent_id, 'failed')
                    try:
                        all_intents = load_intent_registry()
                        blocked_by  = [i['id'] for i in all_intents
                                       if intent_id in (i.get('depends_on') or [])]
                        blocks_str  = ', '.join(f'`{b}`' for b in blocked_by) if blocked_by else 'none'
                        send_oneshot(format_for_human("failure", {
                            "intent_id":   intent_id,
                            "title":       intent.get("title", ""),
                            "failed_step": "planning",
                            "error":       f"LLM unavailable after {len(RETRY_BACKOFFS)} retry attempts",
                            "rolled_back": True,
                            "blocks":      blocks_str,
                        }))
                    except Exception as _e:
                        log(f'Failure notification error: {_e}', 'WARN')
                    # Fall through to proactive work

                # After scheduling a retry or exhausting retries, do proactive work
                from proactive_tasks import get_next_proactive_task
                p_name, p_func = get_next_proactive_task()
                if p_func:
                    try:
                        p_result = await loop.run_in_executor(None, p_func)
                        log(f'Proactive {p_name}: {p_result}', 'PROACTIVE')
                    except Exception as e:
                        log(f'Proactive {p_name} error: {e}', 'PROACTIVE')
                self._next_intent_check = time.time() + 30
                return

        # ── LLM pre-check: don't attempt planning if all tiers are down ───────
        if not self._check_llm_available():
            log('All LLM tiers down — deferring intent execution, doing proactive work', 'RETRY')
            self._next_intent_check = time.time() + 120   # check again in 2 min
            from proactive_tasks import get_next_proactive_task
            p_name, p_func = get_next_proactive_task()
            if p_func:
                try:
                    p_result = await loop.run_in_executor(None, p_func)
                    log(f'Proactive {p_name}: {p_result}', 'PROACTIVE')
                except Exception as e:
                    log(f'Proactive {p_name} error: {e}', 'PROACTIVE')
            else:
                log('All proactive tasks recent. Sleeping 2 min.', 'IDLE')
            return

        task, to_notify, retry_state = await loop.run_in_executor(
            None, select_next_task, self._thinkpad_alive
        )

        # Send one batched Discord message for all intents awaiting human approval
        if to_notify:
            log(f'Notifying human about {len(to_notify)} approval-pending intent(s)', 'DISCORD')
            if len(to_notify) == 1:
                msg = format_for_human("need_approval", {
                    "intent_id":  to_notify[0]["id"],
                    "title":      to_notify[0].get("title", "?"),
                    "risk":       to_notify[0].get("risk", "low"),
                    "complexity": to_notify[0].get("complexity", "medium"),
                })
            else:
                _risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}
                parts = ["🔒 **Approvals needed:**\n"]
                for intent in to_notify:
                    em = _risk_emoji.get(str(intent.get("risk", "low")).lower(), "⚪")
                    parts.append(
                        f"• **`{intent['id']}`** — {intent.get('title', '?')} {em}\n"
                        f"  {intent.get('risk','?')} risk · {intent.get('complexity','?')} complexity"
                    )
                parts.append(f"\nReply `approve {to_notify[0]['id']}` or `approve all`")
                msg = "\n".join(parts)
            try:
                ok = send_oneshot(msg[:1900])
                if ok:
                    log(f'  Discord approval batch sent ({len(to_notify)} intents)', 'DISCORD')
                else:
                    log('  Discord send_oneshot returned False for approval batch', 'WARN')
            except Exception as e:
                log(f'Discord approval notification failed: {e}', 'WARN')

        # ── Handle LLM-timeout retry scheduling ───────────────────────────────
        if retry_state:
            intent_id = retry_state['intent']['id']
            backoff   = RETRY_BACKOFFS[0]   # first retry after 60s
            log(f'LLM timeout for {intent_id} — scheduling retry in {backoff}s', 'RETRY')
            self._retry_queue[intent_id] = {
                'retry_time': time.time() + backoff,
                'attempt':    1,
                'intent':     retry_state['intent'],
                'context':    retry_state['context'],
            }

        if not task or task.get('task') == 'IDLE':
            if to_notify:
                log(
                    f'No autonomous work; notified human about '
                    f'{len(to_notify)} approval-pending intent(s).',
                    'IDLE',
                )

            # Deadlock detection: no work + no approvable intents + failed intents exist
            # (Suppress if intents are just waiting for LLM retry)
            if not to_notify and not self._retry_queue:
                try:
                    all_intents  = load_intent_registry()
                    failed_ids   = [i['id'] for i in all_intents if i.get('status') == 'failed']
                    if failed_ids and time.time() - self._last_deadlock_notify > 86400:
                        self._last_deadlock_notify = time.time()
                        failed_str = ', '.join(f'`{f}`' for f in failed_ids)
                        log(f'Deadlock detected — failed intents blocking queue: {failed_str}', 'WARN')
                        send_oneshot(format_for_human("deadlock", {
                            "failed": failed_str,
                        }))
                except Exception as _e:
                    log(f'Deadlock detection error: {_e}', 'WARN')

            # Instead of sleeping, run proactive background work
            from proactive_tasks import get_next_proactive_task
            p_name, p_func = get_next_proactive_task()
            if p_func:
                try:
                    p_result = await loop.run_in_executor(None, p_func)
                    log(f'Proactive {p_name}: {p_result}', 'PROACTIVE')
                except Exception as e:
                    log(f'Proactive {p_name} error: {e}', 'PROACTIVE')
                # Short delay then re-check — don't block for 5 minutes
                self._next_intent_check = time.time() + 30
            else:
                # All proactive tasks ran recently — genuine idle
                log('All proactive tasks recent. Sleeping 2 min.', 'IDLE')
                self._next_intent_check = time.time() + 120
            return

        update_stats(in_progress=task.get('task', 'unknown'))
        success = await loop.run_in_executor(None, execute_task, task)
        self._ran_task_this_cycle = True   # skip CYCLE_SLEEP to chain immediately
        update_guide_after_task(task.get('task', 'unknown'), success)

        # should_retry flag is written into the plan result by execute_task
        # via the feedback loop analysis; check and act on it once
        plan_result = task.get('_plan', {})
        if not success and plan_result.get('_should_retry'):
            log(f'Feedback loop suggests retry for "{task.get("task")}" — '
                'waiting 5 min then re-attempting once', 'FEEDBACK')
            await asyncio.sleep(300)
            success = await loop.run_in_executor(None, execute_task, task)
            update_guide_after_task(task.get('task', 'unknown'), success)
            log(f'Retry outcome: {"success" if success else "failed"}', 'FEEDBACK')

        if success:
            self.consecutive_failures = 0
        else:
            self.consecutive_failures += 1
            if self.consecutive_failures >= 3:
                log('3 consecutive failures — pausing 30 min.', 'WARN')
                send_notification('alert',
                                  '3 consecutive task failures. Pausing 30 minutes.')
                await asyncio.sleep(FAIL_PAUSE)
                self.consecutive_failures = 0

    # ── Main loop ─────────────────────────────────────────────────────────────

    # ── Watchdog ──────────────────────────────────────────────────────────────

    async def _check_stale_tasks(self) -> None:
        """Detect in_progress intents that exceeded TASK_TIMEOUT_MINUTES and recover them."""
        now      = datetime.now(timezone.utc)
        timings  = _load_timings()
        intents  = load_intent_registry()
        in_prog  = [i for i in intents if i.get('status') == 'in_progress']

        if not in_prog:
            return

        cutoff = timedelta(minutes=TASK_TIMEOUT_MINUTES)
        for intent in in_prog:
            iid    = intent['id']
            entry  = timings.get(iid, {})
            ts_str = entry.get('started_at')

            if not ts_str:
                # No start time recorded — seed it now; fire next cycle if still stuck
                _record_task_start(iid)
                log(f'Watchdog: {iid} in_progress with no started_at — seeding timestamp', 'WATCHDOG')
                continue

            try:
                started = datetime.fromisoformat(ts_str)
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            age_min = (now - started).total_seconds() / 60
            if age_min < TASK_TIMEOUT_MINUTES:
                continue

            # Intent has been in_progress longer than the timeout
            failures = entry.get('timeout_failures', 0) + 1
            timings[iid] = {**entry, 'timeout_failures': failures, 'started_at': None}
            _save_timings(timings)

            title = intent.get('title', '')

            if failures >= MAX_TIMEOUT_FAILURES:
                log(
                    f'Watchdog: {iid} timed out {failures}× — '
                    f'marking blocked (exceeded max retries)',
                    'WARN',
                )
                update_intent_status(iid, 'blocked')
                _clear_task_timing(iid)
                send_oneshot(
                    f'🔒 **Task blocked** — exceeded {MAX_TIMEOUT_FAILURES} timeout retries\n'
                    f'`{iid}` — {title}\n'
                    f'Reply `approve {iid}` to unblock.'
                )
            else:
                log(
                    f'Watchdog: {iid} stale after {age_min:.0f} min '
                    f'(timeout #{failures}/{MAX_TIMEOUT_FAILURES}) — marking failed',
                    'WARN',
                )
                update_intent_status(iid, 'failed')
                send_oneshot(
                    f'⏱️ **Timeout** (#{failures}/{MAX_TIMEOUT_FAILURES}):\n'
                    f'`{iid}` — {title}\n'
                    f'No progress for {age_min:.0f} min. Marked failed — will retry.'
                )

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def main_loop(self) -> None:
        log('=' * 60)
        log('NEXUS OS Development Orchestrator v4.0 starting')
        log(f'Tier 1: {TIER1_URL}')
        log(f'Tier 2: {TIER2_URL}')
        log(f'Cycle: {CYCLE_SLEEP}s  |  Health: {self.HEALTH_INTERVAL}s  '
            f'|  Git: {self.GIT_INTERVAL}s')
        log('=' * 60)

        os.makedirs(BACKUP_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)

        start_discord_listener(handle_discord_message)

        while True:
            try:
                self._ran_task_this_cycle = False
                now    = datetime.now()
                events = []

                # Schedule events based on elapsed time
                if (now - self.last_health_check).total_seconds() >= self.HEALTH_INTERVAL:
                    events.append("health_check")
                    self.last_health_check = now

                if (now - self.last_git_check).total_seconds() >= self.GIT_INTERVAL:
                    events.append("git_check")
                    self.last_git_check = now

                if (now - self.last_status_report).total_seconds() >= self.STATUS_INTERVAL:
                    events.append("status_report")
                    self.last_status_report = now

                if (now - self.last_watchdog_check).total_seconds() >= self.WATCHDOG_INTERVAL:
                    events.append("watchdog")
                    self.last_watchdog_check = now

                if (not is_idle_mode()
                        and self.consecutive_failures < 3
                        and time.time() >= self._next_intent_check):
                    events.append("check_intents")
                elif is_idle_mode():
                    log('Idle mode active — skipping intent check', 'IDLE')

                # Process events in listed priority order
                for event_type in events:
                    try:
                        if event_type == "health_check":
                            await self._handle_health_check()
                        elif event_type == "git_check":
                            await self._handle_git_check()
                        elif event_type == "status_report":
                            await self._handle_status_report()
                        elif event_type == "watchdog":
                            await self._check_stale_tasks()
                        elif event_type == "check_intents":
                            await self._handle_check_intents()
                    except Exception as e:
                        log(f'Event {event_type} error: {e}', 'ERROR')
                        send_notification('alert',
                                          f'Event `{event_type}` error: {str(e)[:200]}')

            except KeyboardInterrupt:
                log('Stopped by user')
                send_notification('status', '⏹️ Orchestrator stopped by operator.')
                break
            except Exception as e:
                log(f'Unexpected main loop error: {e}', 'ERROR')
                send_notification('alert',
                                  f'Unexpected orchestrator error: {str(e)[:200]}')

            # Skip sleep when a task just ran — chain back-to-back without delay
            await asyncio.sleep(0 if self._ran_task_this_cycle else CYCLE_SLEEP)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
    )
    try:
        asyncio.run(NexusOrchestrator().main_loop())
    except KeyboardInterrupt:
        pass
