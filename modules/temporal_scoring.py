"""
NEXUS OS — Temporal Bin Scoring Engine

Composite scoring system for temporal bins, integrating decision matrices
(priority, stakeholder, risk) with historical productivity data.
Used by the scheduler to assign tasks to optimal time bins.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

import numpy as np

log = logging.getLogger("nexus.temporal_scoring")

TASK_LOG_PATH = "/opt/nexus/logs/task_log.jsonl"


class TemporalScorer:
    """
    Scores temporal bins using a composite of decision matrices and
    historical productivity.

    Composite formula:
        score = 0.3 * priority + 0.3 * stakeholder + 0.2 * risk + 0.2 * historical
    """

    # Default 5×5 decision matrices (row=task level 0-4, col=bin slot 0-4)
    # Values are normalized weights in [0, 1]

    DEFAULT_PRIORITY_MATRIX = np.array([
        [0.2, 0.4, 0.6, 0.8, 1.0],
        [0.3, 0.5, 0.7, 0.9, 1.0],
        [0.4, 0.6, 0.8, 1.0, 1.0],
        [0.5, 0.7, 0.9, 1.0, 1.0],
        [0.6, 0.8, 1.0, 1.0, 1.0],
    ], dtype=np.float64)

    DEFAULT_STAKEHOLDER_MATRIX = np.array([
        [0.1, 0.2, 0.3, 0.4, 0.5],
        [0.2, 0.3, 0.5, 0.6, 0.7],
        [0.3, 0.5, 0.7, 0.8, 0.9],
        [0.5, 0.6, 0.8, 0.9, 1.0],
        [0.6, 0.7, 0.9, 1.0, 1.0],
    ], dtype=np.float64)

    DEFAULT_RISK_MATRIX = np.array([
        [0.1, 0.1, 0.2, 0.3, 0.4],
        [0.2, 0.3, 0.4, 0.5, 0.6],
        [0.3, 0.4, 0.6, 0.7, 0.8],
        [0.4, 0.6, 0.7, 0.9, 1.0],
        [0.5, 0.7, 0.9, 1.0, 1.0],
    ], dtype=np.float64)

    WEIGHTS = {
        "priority": 0.3,
        "stakeholder": 0.3,
        "risk": 0.2,
        "historical": 0.2,
    }

    def __init__(self, priority_matrix=None, stakeholder_matrix=None,
                 risk_matrix=None, task_log_path=None):
        self.priority_matrix = priority_matrix if priority_matrix is not None \
            else self.DEFAULT_PRIORITY_MATRIX.copy()
        self.stakeholder_matrix = stakeholder_matrix if stakeholder_matrix is not None \
            else self.DEFAULT_STAKEHOLDER_MATRIX.copy()
        self.risk_matrix = risk_matrix if risk_matrix is not None \
            else self.DEFAULT_RISK_MATRIX.copy()
        self.task_log_path = task_log_path or TASK_LOG_PATH
        self._productivity_cache = {}

    # ── Core scoring ──────────────────────────────────────────────────────

    def score_bin(self, bin_id, tasks):
        """
        Compute composite score for a temporal bin given its tasks.

        Args:
            bin_id: Bin identifier (hex string or bytes32)
            tasks: List of task dicts, each with keys:
                   - priority: int 1-5
                   - stakeholder_impact: int 1-5
                   - risk_level: int 1-5

        Returns:
            float: Composite score in [0, 1]
        """
        if not tasks:
            return 0.0

        priority_scores = []
        stakeholder_scores = []
        risk_scores = []

        for task in tasks:
            p = min(max(int(task.get("priority", 3)) - 1, 0), 4)
            s = min(max(int(task.get("stakeholder_impact", 3)) - 1, 0), 4)
            r = min(max(int(task.get("risk_level", 3)) - 1, 0), 4)

            # Column index: spread across matrix columns by task position
            col = min(len(priority_scores), 4)

            priority_scores.append(self.priority_matrix[p, col])
            stakeholder_scores.append(self.stakeholder_matrix[s, col])
            risk_scores.append(self.risk_matrix[r, col])

        avg_priority = float(np.mean(priority_scores))
        avg_stakeholder = float(np.mean(stakeholder_scores))
        avg_risk = float(np.mean(risk_scores))
        historical = self.get_bin_productivity(bin_id)

        composite = (
            self.WEIGHTS["priority"] * avg_priority +
            self.WEIGHTS["stakeholder"] * avg_stakeholder +
            self.WEIGHTS["risk"] * avg_risk +
            self.WEIGHTS["historical"] * historical
        )

        return round(min(max(composite, 0.0), 1.0), 4)

    # ── Historical productivity ───────────────────────────────────────────

    def get_bin_productivity(self, bin_id):
        """
        Historical success rate for tasks in this bin, derived from task_log.jsonl.

        Returns:
            float: Success rate in [0, 1], defaults to 0.5 if no history
        """
        bin_key = str(bin_id)
        if bin_key in self._productivity_cache:
            return self._productivity_cache[bin_key]

        if not os.path.exists(self.task_log_path):
            return 0.5

        total = 0
        successes = 0
        try:
            with open(self.task_log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(entry.get("bin_id", "")) == bin_key:
                        total += 1
                        if entry.get("success", False):
                            successes += 1
        except OSError:
            return 0.5

        if total == 0:
            productivity = 0.5
        else:
            productivity = successes / total

        self._productivity_cache[bin_key] = productivity
        return productivity

    # ── Wake-shift rescheduling ───────────────────────────────────────────

    def wake_shift_reschedule(self, actual_wake_hour, planned_wake_hour,
                              tasks=None, available_bins=None):
        """
        If actual wake differs from planned by >1 hour, cascade-recalculate
        all remaining bins for the day.

        Args:
            actual_wake_hour: int (0-23), actual wake hour
            planned_wake_hour: int (0-23), planned wake hour
            tasks: list of task dicts to reschedule (optional)
            available_bins: list of bin dicts with 'bin_id' and 'hour' (optional)

        Returns:
            dict: {rescheduled_tasks: [...], reason: str} or
                  {rescheduled_tasks: [], reason: "no shift detected"}
        """
        drift = abs(actual_wake_hour - planned_wake_hour)
        if drift <= 1:
            return {
                "rescheduled_tasks": [],
                "reason": "no shift detected"
            }

        reason = (f"wake shift detected: planned={planned_wake_hour:02d}:00, "
                  f"actual={actual_wake_hour:02d}:00, drift={drift}h")
        log.info(reason)

        if not tasks or not available_bins:
            return {
                "rescheduled_tasks": [],
                "reason": reason + " (no tasks/bins provided for rescheduling)"
            }

        # Filter bins to only those after actual wake hour
        shifted_bins = [b for b in available_bins if b.get("hour", 0) >= actual_wake_hour]

        if not shifted_bins:
            return {
                "rescheduled_tasks": [],
                "reason": reason + " (no bins available after wake)"
            }

        # Re-score and re-assign using optimize_day
        assignments = self.optimize_day(tasks, shifted_bins)

        return {
            "rescheduled_tasks": assignments,
            "reason": reason
        }

    # ── Day optimization ──────────────────────────────────────────────────

    def optimize_day(self, tasks, available_bins):
        """
        Assign tasks to bins using composite scores (greedy).
        Highest-scored task gets highest-scored bin first.

        Args:
            tasks: list of task dicts with priority, stakeholder_impact, risk_level, name
            available_bins: list of bin dicts with bin_id, hour

        Returns:
            list of assignment dicts: [{task, bin_id, hour, score}, ...]
        """
        if not tasks or not available_bins:
            return []

        qaoa_flag = len(tasks) > 20

        # Score each task individually
        task_scores = []
        for i, task in enumerate(tasks):
            p = min(max(int(task.get("priority", 3)) - 1, 0), 4)
            s = min(max(int(task.get("stakeholder_impact", 3)) - 1, 0), 4)
            r = min(max(int(task.get("risk_level", 3)) - 1, 0), 4)
            # Use center column (2) for standalone task scoring
            score = (
                self.WEIGHTS["priority"] * self.priority_matrix[p, 2] +
                self.WEIGHTS["stakeholder"] * self.stakeholder_matrix[s, 2] +
                self.WEIGHTS["risk"] * self.risk_matrix[r, 2]
            )
            task_scores.append((score, i, task))

        # Score each bin by historical productivity
        bin_scores = []
        for b in available_bins:
            prod = self.get_bin_productivity(b.get("bin_id", ""))
            bin_scores.append((prod, b))

        # Sort descending
        task_scores.sort(key=lambda x: x[0], reverse=True)
        bin_scores.sort(key=lambda x: x[0], reverse=True)

        assignments = []
        used_bins = set()

        for task_score, _, task in task_scores:
            best_bin = None
            for bin_prod, b in bin_scores:
                bid = str(b.get("bin_id", ""))
                if bid not in used_bins:
                    best_bin = b
                    used_bins.add(bid)
                    break

            if best_bin is None:
                # More tasks than bins — assign to least-loaded bin
                if bin_scores:
                    best_bin = bin_scores[-1][1]
                else:
                    continue

            combined = task_score + self.WEIGHTS["historical"] * self.get_bin_productivity(
                best_bin.get("bin_id", ""))

            entry = {
                "task": task.get("name", f"task_{_}"),
                "bin_id": best_bin.get("bin_id", ""),
                "hour": best_bin.get("hour", 0),
                "score": round(combined, 4),
            }
            if qaoa_flag:
                entry["qaoa_recommended"] = True
            assignments.append(entry)

        if qaoa_flag:
            log.warning(f"{len(tasks)} tasks exceed greedy threshold — "
                        "flagged for QAOA optimization (quantum_benchmark module)")

        return assignments

    # ── Heatmap generation ────────────────────────────────────────────────

    def generate_heatmap_data(self, days=30):
        """
        Build a 24×7 matrix (hours × day-of-week) of average bin utilization
        and success rates over the past N days.

        Returns:
            dict: {
                utilization: 24×7 numpy array (task counts, normalized),
                success_rate: 24×7 numpy array (success fractions),
                period_days: int,
                total_entries: int
            }
        """
        utilization = np.zeros((24, 7), dtype=np.float64)
        success_count = np.zeros((24, 7), dtype=np.float64)
        total_count = np.zeros((24, 7), dtype=np.float64)

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        entries_read = 0

        if os.path.exists(self.task_log_path):
            try:
                with open(self.task_log_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        ts = entry.get("timestamp")
                        if not ts:
                            continue
                        try:
                            if isinstance(ts, (int, float)):
                                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                            else:
                                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                        except (ValueError, OSError):
                            continue

                        if dt < cutoff:
                            continue

                        hour = dt.hour
                        dow = dt.weekday()  # Monday=0, Sunday=6
                        entries_read += 1

                        utilization[hour, dow] += 1
                        total_count[hour, dow] += 1
                        if entry.get("success", False):
                            success_count[hour, dow] += 1
            except OSError as e:
                log.warning(f"Could not read task log: {e}")

        # Normalize utilization to [0, 1]
        max_util = utilization.max()
        if max_util > 0:
            utilization_norm = utilization / max_util
        else:
            utilization_norm = utilization

        # Success rate
        with np.errstate(divide="ignore", invalid="ignore"):
            success_rate = np.where(
                total_count > 0,
                success_count / total_count,
                0.5  # default for no-data cells
            )

        return {
            "utilization": utilization_norm,
            "success_rate": success_rate,
            "period_days": days,
            "total_entries": entries_read,
        }


if __name__ == "__main__":
    print("=== NEXUS Temporal Scorer Demo ===\n")

    scorer = TemporalScorer()

    # Sample tasks for a day
    sample_tasks = [
        {"name": "deploy-contract",     "priority": 5, "stakeholder_impact": 5, "risk_level": 4},
        {"name": "code-review",         "priority": 3, "stakeholder_impact": 3, "risk_level": 2},
        {"name": "agent-training",      "priority": 4, "stakeholder_impact": 4, "risk_level": 3},
        {"name": "documentation",       "priority": 2, "stakeholder_impact": 2, "risk_level": 1},
        {"name": "security-audit",      "priority": 5, "stakeholder_impact": 5, "risk_level": 5},
        {"name": "dashboard-update",    "priority": 3, "stakeholder_impact": 3, "risk_level": 2},
        {"name": "backup-verification", "priority": 4, "stakeholder_impact": 4, "risk_level": 4},
        {"name": "log-cleanup",         "priority": 1, "stakeholder_impact": 1, "risk_level": 1},
    ]

    # Available bins (8am-5pm work hours)
    sample_bins = [
        {"bin_id": f"bin_{h:02d}", "hour": h}
        for h in range(8, 18)
    ]

    # Score a single bin
    bin_score = scorer.score_bin("bin_09", sample_tasks[:3])
    print(f"Bin 09:00 score (3 tasks): {bin_score}")

    # Optimize full day
    print("\n--- Day Optimization (greedy) ---")
    assignments = scorer.optimize_day(sample_tasks, sample_bins)
    for a in assignments:
        print(f"  {a['hour']:02d}:00  {a['task']:<25s}  score={a['score']:.4f}")

    # Wake shift test
    print("\n--- Wake Shift Reschedule ---")
    result = scorer.wake_shift_reschedule(
        actual_wake_hour=10,
        planned_wake_hour=7,
        tasks=sample_tasks,
        available_bins=sample_bins
    )
    print(f"  Reason: {result['reason']}")
    print(f"  Rescheduled: {len(result['rescheduled_tasks'])} tasks")
    for a in result["rescheduled_tasks"][:3]:
        print(f"    {a['hour']:02d}:00  {a['task']:<25s}  score={a['score']:.4f}")

    # Heatmap
    print("\n--- Heatmap Data ---")
    hm = scorer.generate_heatmap_data(days=30)
    print(f"  Period: {hm['period_days']} days, entries: {hm['total_entries']}")
    print(f"  Utilization shape: {hm['utilization'].shape}")
    print(f"  Success rate shape: {hm['success_rate'].shape}")

    print("\nDone.")
