"""
NEXUS OS — ARIMA Temporal Forecaster

Predicts future temporal bin utilization using ARIMA time-series modeling.
Enables preemptive resource allocation by forecasting task load per bin.

Integration: forecast output feeds into the "historical_productivity" weight
in TemporalScorer's composite bin scoring function.
"""

import itertools
import json
import logging
import warnings
from datetime import datetime, timezone, timedelta

import numpy as np

log = logging.getLogger("nexus.temporal_forecaster")


class TemporalForecaster:
    """
    ARIMA-based forecaster for temporal bin utilization.

    Uses statsmodels ARIMA with automatic (p,d,q) selection via AIC.
    Falls back to simple moving average when data is insufficient (<168 points).
    """

    MIN_POINTS_ARIMA = 168  # 1 week of hourly data

    def __init__(self):
        self._model_fit = None
        self._historical = None
        self._bin_ids = None
        self._hourly_series = None  # np.array of hourly task counts
        self._order = None
        self._fallback = False

    # ── Fit ─────────────────────────────────────────────────────────────────

    def fit(self, historical_bin_data):
        """
        Train ARIMA model on past bin utilization.

        Args:
            historical_bin_data: list of dicts with keys:
                - bin_id: str
                - task_count: int
                - ect_spent: float (estimated compute time spent)
                - timestamp: ISO string or unix epoch
        """
        self._historical = historical_bin_data
        self._bin_ids = sorted(set(d["bin_id"] for d in historical_bin_data))

        # Build hourly time series of total task counts
        hourly = self._build_hourly_series(historical_bin_data)
        self._hourly_series = hourly

        if len(hourly) < self.MIN_POINTS_ARIMA:
            log.info(
                "Insufficient data (%d points < %d) — using moving average fallback",
                len(hourly), self.MIN_POINTS_ARIMA,
            )
            self._fallback = True
            self._model_fit = None
            return

        self._fallback = False
        self._fit_arima(hourly)

    def _build_hourly_series(self, data):
        """Aggregate data into hourly task count buckets."""
        timestamps = []
        for d in data:
            ts = d["timestamp"]
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            timestamps.append((dt, d["task_count"]))

        if not timestamps:
            return np.array([], dtype=np.float64)

        timestamps.sort(key=lambda x: x[0])
        start = timestamps[0][0].replace(minute=0, second=0, microsecond=0)
        end = timestamps[-1][0].replace(minute=0, second=0, microsecond=0)

        total_hours = int((end - start).total_seconds() / 3600) + 1
        series = np.zeros(total_hours, dtype=np.float64)

        for dt, count in timestamps:
            idx = int((dt - start).total_seconds() / 3600)
            idx = min(idx, total_hours - 1)
            series[idx] += count

        return series

    def _fit_arima(self, series):
        """Auto-select (p,d,q) by AIC and fit ARIMA model."""
        from statsmodels.tsa.arima.model import ARIMA

        best_aic = np.inf
        best_order = (1, 1, 1)
        best_fit = None

        candidates = list(itertools.product(range(4), range(2), range(4)))

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for order in candidates:
                try:
                    model = ARIMA(series, order=order)
                    fit = model.fit()
                    if fit.aic < best_aic:
                        best_aic = fit.aic
                        best_order = order
                        best_fit = fit
                except Exception:
                    continue

        if best_fit is None:
            log.warning("All ARIMA fits failed — falling back to moving average")
            self._fallback = True
            self._model_fit = None
            return

        self._order = best_order
        self._model_fit = best_fit
        log.info("ARIMA fitted: order=%s, AIC=%.2f", best_order, best_aic)

    # ── Predict ─────────────────────────────────────────────────────────────

    def predict(self, hours_ahead=24):
        """
        Forecast utilization for the next N hours of temporal bins.

        Args:
            hours_ahead: int, number of hours to forecast (default 24)

        Returns:
            list of dicts: [{bin_id, predicted_tasks, confidence}, ...]
        """
        if self._hourly_series is None or len(self._hourly_series) == 0:
            return []

        if self._fallback:
            forecasted = self._moving_average_forecast(hours_ahead)
        else:
            forecasted = self._arima_forecast(hours_ahead)

        results = []
        for i, val in enumerate(forecasted):
            bin_id = f"bin_{i % 24:02d}"
            results.append({
                "bin_id": bin_id,
                "predicted_tasks": round(max(val, 0), 2),
                "confidence": self._confidence_for_hour(i),
            })

        return results

    def _arima_forecast(self, hours_ahead):
        """Produce ARIMA forecast."""
        forecast = self._model_fit.forecast(steps=hours_ahead)
        return np.array(forecast, dtype=np.float64)

    def _moving_average_forecast(self, hours_ahead):
        """Simple moving average fallback (window=24 hours)."""
        window = min(24, len(self._hourly_series))
        avg = np.mean(self._hourly_series[-window:])
        # Use last full day's pattern if available, else flat average
        if len(self._hourly_series) >= 24:
            pattern = self._hourly_series[-24:]
            scale = avg / max(np.mean(pattern), 1e-9)
            return np.tile(pattern * scale, (hours_ahead // 24) + 1)[:hours_ahead]
        return np.full(hours_ahead, avg, dtype=np.float64)

    def _confidence_for_hour(self, hour_offset):
        """Confidence decays with forecast horizon."""
        if self._fallback:
            base = 0.5
        else:
            base = 0.9
        decay = 0.02 * hour_offset
        return round(max(base - decay, 0.1), 2)

    # ── Peak bins ───────────────────────────────────────────────────────────

    def identify_peak_bins(self, days=7):
        """
        Identify bins with consistently high utilization over past N days.

        Args:
            days: int, lookback period

        Returns:
            list of dicts: [{bin_id, avg_tasks, peak_count}, ...]
        """
        if not self._historical:
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        bin_counts = {}  # bin_id -> list of task_counts

        for d in self._historical:
            ts = d["timestamp"]
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))

            if dt < cutoff:
                continue

            bid = d["bin_id"]
            bin_counts.setdefault(bid, []).append(d["task_count"])

        if not bin_counts:
            return []

        # Overall mean across all bins
        all_counts = [c for counts in bin_counts.values() for c in counts]
        overall_mean = np.mean(all_counts)
        overall_std = np.std(all_counts) if len(all_counts) > 1 else 0

        threshold = overall_mean + 0.5 * overall_std

        peaks = []
        for bid, counts in sorted(bin_counts.items()):
            avg = np.mean(counts)
            if avg >= threshold:
                peaks.append({
                    "bin_id": bid,
                    "avg_tasks": round(float(avg), 2),
                    "peak_count": len([c for c in counts if c >= threshold]),
                })

        peaks.sort(key=lambda x: x["avg_tasks"], reverse=True)
        return peaks

    # ── Anomaly detection ───────────────────────────────────────────────────

    def detect_anomalies(self, current_utilization):
        """
        Detect bins where current utilization deviates >2 sigma from predicted.

        Args:
            current_utilization: list of dicts [{bin_id, task_count}, ...]

        Returns:
            list of dicts: [{bin_id, actual, predicted, deviation_sigma}, ...]
        """
        forecast = self.predict(hours_ahead=24)
        if not forecast:
            return []

        predicted_map = {f["bin_id"]: f["predicted_tasks"] for f in forecast}

        # Compute sigma from historical hourly series
        if self._hourly_series is not None and len(self._hourly_series) > 1:
            sigma = float(np.std(self._hourly_series))
        else:
            sigma = 1.0

        if sigma < 0.01:
            sigma = 1.0

        anomalies = []
        for entry in current_utilization:
            bid = entry["bin_id"]
            actual = entry["task_count"]
            predicted = predicted_map.get(bid)
            if predicted is None:
                continue

            deviation = abs(actual - predicted) / sigma
            if deviation > 2.0:
                anomalies.append({
                    "bin_id": bid,
                    "actual": actual,
                    "predicted": round(predicted, 2),
                    "deviation_sigma": round(deviation, 2),
                })

        anomalies.sort(key=lambda x: x["deviation_sigma"], reverse=True)
        return anomalies

    # ── Scheduling recommendation ───────────────────────────────────────────

    def get_scheduling_recommendation(self, tasks, forecast=None):
        """
        Recommend bin assignments based on forecast utilization.

        Args:
            tasks: list of task dicts (with 'name' and 'priority')
            forecast: optional pre-computed forecast (from predict());
                      if None, generates a 24-hour forecast

        Returns:
            dict: {
                schedule_in: [low utilization bins],
                avoid: [high utilization bins],
                assignments: [{task, recommended_bin, reason}]
            }
        """
        if forecast is None:
            forecast = self.predict(hours_ahead=24)

        if not forecast:
            return {
                "schedule_in": [],
                "avoid": [],
                "assignments": [],
            }

        predicted_values = [f["predicted_tasks"] for f in forecast]
        mean_load = np.mean(predicted_values)
        std_load = np.std(predicted_values) if len(predicted_values) > 1 else 0

        low_threshold = mean_load - 0.5 * std_load
        high_threshold = mean_load + 0.5 * std_load

        low_bins = [f["bin_id"] for f in forecast if f["predicted_tasks"] <= low_threshold]
        high_bins = [f["bin_id"] for f in forecast if f["predicted_tasks"] >= high_threshold]

        # Sort tasks by priority descending
        sorted_tasks = sorted(tasks, key=lambda t: t.get("priority", 3), reverse=True)

        # Assign high-priority tasks to low-utilization bins
        assignments = []
        available_low = list(low_bins)
        for task in sorted_tasks:
            if available_low:
                chosen = available_low.pop(0)
                reason = "low predicted utilization — good for heavy tasks"
            else:
                # Pick the bin with lowest predicted load overall
                remaining = sorted(forecast, key=lambda f: f["predicted_tasks"])
                chosen = remaining[0]["bin_id"]
                reason = "lowest available predicted load"

            assignments.append({
                "task": task.get("name", "unnamed"),
                "recommended_bin": chosen,
                "reason": reason,
            })

        return {
            "schedule_in": low_bins,
            "avoid": high_bins,
            "assignments": assignments,
        }


# ── Main demo ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import random

    print("=== NEXUS Temporal Forecaster Demo ===\n")

    # Generate 30 days of synthetic hourly bin data
    random.seed(42)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=30)

    synthetic_data = []
    for hour_offset in range(30 * 24):
        dt = start + timedelta(hours=hour_offset)
        hour = dt.hour

        # Simulate daily pattern: peak at 10-14, low at 0-6
        if 10 <= hour <= 14:
            base = random.randint(8, 15)
        elif 7 <= hour <= 9 or 15 <= hour <= 18:
            base = random.randint(4, 8)
        else:
            base = random.randint(0, 3)

        # Add weekly pattern: lower on weekends
        if dt.weekday() >= 5:
            base = max(0, base - 3)

        synthetic_data.append({
            "bin_id": f"bin_{hour:02d}",
            "task_count": base,
            "ect_spent": base * random.uniform(0.5, 2.0),
            "timestamp": dt.isoformat(),
        })

    print(f"Generated {len(synthetic_data)} synthetic data points (30 days)")

    # Fit model
    forecaster = TemporalForecaster()
    forecaster.fit(synthetic_data)
    print(f"Model type: {'ARIMA' if not forecaster._fallback else 'Moving Average'}")
    if forecaster._order:
        print(f"ARIMA order: {forecaster._order}")

    # Predict next 24 hours
    print("\n--- 24-Hour Forecast ---")
    forecast = forecaster.predict(hours_ahead=24)
    for f in forecast:
        bar = "#" * int(f["predicted_tasks"])
        print(f"  {f['bin_id']}  tasks={f['predicted_tasks']:6.2f}  "
              f"conf={f['confidence']:.2f}  {bar}")

    # Identify peak bins
    print("\n--- Peak Bins (past 7 days) ---")
    peaks = forecaster.identify_peak_bins(days=7)
    for p in peaks:
        print(f"  {p['bin_id']}  avg={p['avg_tasks']:.2f}  peak_count={p['peak_count']}")

    # Detect anomalies with synthetic current data
    print("\n--- Anomaly Detection ---")
    current = [
        {"bin_id": "bin_03", "task_count": 20},  # should be anomalous (nighttime)
        {"bin_id": "bin_12", "task_count": 12},   # normal (peak hour)
        {"bin_id": "bin_22", "task_count": 15},   # anomalous (late night)
    ]
    anomalies = forecaster.detect_anomalies(current)
    if anomalies:
        for a in anomalies:
            print(f"  {a['bin_id']}  actual={a['actual']}  "
                  f"predicted={a['predicted']}  deviation={a['deviation_sigma']}σ")
    else:
        print("  No anomalies detected")

    # Scheduling recommendation
    print("\n--- Scheduling Recommendation ---")
    sample_tasks = [
        {"name": "deploy-contract", "priority": 5},
        {"name": "agent-training", "priority": 4},
        {"name": "log-cleanup", "priority": 1},
        {"name": "security-audit", "priority": 5},
        {"name": "documentation", "priority": 2},
    ]
    rec = forecaster.get_scheduling_recommendation(sample_tasks, forecast)
    print(f"  Schedule heavy tasks in: {rec['schedule_in']}")
    print(f"  Avoid these bins:        {rec['avoid']}")
    print("\n  Assignments:")
    for a in rec["assignments"]:
        print(f"    {a['task']:<20s} → {a['recommended_bin']}  ({a['reason']})")

    print("\nDone.")
