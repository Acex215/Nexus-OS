"""288-dimensional feature extractor for behavioral data.

Converts a time window of on-chain actions into a single 288-dim vector.
This is the LOSSY PROJECTION step: millions of raw events → 288 numbers.
The vector cannot reconstruct individual actions — by design.

Layout: 18 channels × 16 statistical features = 288 dimensions.
"""

import math
import sys
import time
from collections import defaultdict

import numpy as np

sys.path.insert(0, '/opt/nexus')
from libnexus.behavioral_client import BehavioralClient

NUM_CHANNELS = 18
NUM_FEATURES = 16
VECTOR_DIM = NUM_CHANNELS * NUM_FEATURES

CHANNEL_NAMES = [
    'keystroke', 'mouse', 'window', 'web', 'message', 'file',
    'clipboard', 'system', 'session', 'app_lifecycle', 'gps',
    'weather', 'wifi', 'audio', 'display', 'power', 'peripheral',
    'notification',
]

FEATURE_NAMES = [
    'total_count', 'rate_per_hour', 'burst_count', 'burst_avg_duration',
    'pause_count', 'pause_avg_duration', 'entropy', 'dominant_type_ratio',
    'mean_interval', 'std_interval', 'min_interval', 'max_interval',
    'hourly_concentration', 'first_action_hour', 'last_action_hour',
    'active_hours',
]


class FeatureExtractor:
    """Extract 288-dimensional feature vectors from on-chain behavioral data."""

    def __init__(self, client=None):
        self.client = client or BehavioralClient()

    def extract(self, start_time: int, end_time: int) -> np.ndarray:
        """Extract feature vector for a time window.

        Args:
            start_time: Unix timestamp (seconds) for window start.
            end_time: Unix timestamp (seconds) for window end.

        Returns:
            numpy array of shape (288,), dtype float64, values in [0, 1].
        """
        # Read all actions in range
        actions = self._read_actions(start_time, end_time)

        # Group by channel
        by_channel = defaultdict(list)
        for action in actions:
            by_channel[action['channelId']].append(action)

        # Extract 16 features per channel
        window_hours = max((end_time - start_time) / 3600, 0.001)
        vec = np.zeros(VECTOR_DIM, dtype=np.float64)

        for ch_idx in range(NUM_CHANNELS):
            ch_id = ch_idx + 1  # channels are 1-indexed
            ch_actions = by_channel.get(ch_id, [])
            features = self._extract_channel_features(ch_actions, window_hours)
            offset = ch_idx * NUM_FEATURES
            vec[offset:offset + NUM_FEATURES] = features

        assert vec.shape == (VECTOR_DIM,)
        assert np.all(np.isfinite(vec))
        return vec

    def extract_daily(self) -> np.ndarray:
        """Extract features for today (midnight UTC to now)."""
        now = int(time.time())
        midnight = now - (now % 86400)
        return self.extract(midnight, now)

    def get_feature_names(self) -> list:
        """Return 288 human-readable feature names."""
        names = []
        for ch_name in CHANNEL_NAMES:
            for feat_name in FEATURE_NAMES:
                names.append(f'{ch_name}_{feat_name}')
        return names

    def _read_actions(self, start_time, end_time):
        """Read actions from chain in the time range."""
        total = self.client.get_total_actions()
        if total == 0:
            return []

        actions = []

        # Scan backwards from latest to find actions in range
        # This is more efficient than scanning forward for recent windows
        batch_size = 100
        for start_idx in range(max(0, total - 1), -1, -batch_size):
            end_idx = max(start_idx - batch_size + 1, 0)
            found_before_range = False

            for i in range(start_idx, end_idx - 1, -1):
                try:
                    a = self.client.get_action(i)
                    ts = a['timestamp']
                    if ts < start_time:
                        found_before_range = True
                        break
                    if ts <= end_time:
                        actions.append(a)
                except Exception:
                    continue

            if found_before_range:
                break

        return actions

    def _extract_channel_features(self, actions, window_hours):
        """Compute 16 normalized features for one channel's actions."""
        features = np.zeros(NUM_FEATURES, dtype=np.float64)

        if not actions:
            return features

        count = len(actions)
        timestamps = sorted(a['timestamp'] for a in actions)
        action_types = [a['actionType'] for a in actions]

        # 1. total_count — log-normalized
        features[0] = _norm_log(count, 10000)

        # 2. rate_per_hour
        rate = count / window_hours
        features[1] = min(rate / 100.0, 1.0)

        # Intervals between consecutive actions
        intervals = []
        for i in range(1, len(timestamps)):
            dt = timestamps[i] - timestamps[i - 1]
            if dt >= 0:
                intervals.append(dt)

        # 3-4. burst detection (>2σ above mean rate)
        burst_count, burst_avg_dur = _detect_bursts(timestamps)
        features[2] = _norm_log(burst_count, 100)
        features[3] = min(burst_avg_dur / 3600.0, 1.0)

        # 5-6. pause detection (gaps >60 seconds)
        pauses = [dt for dt in intervals if dt > 60]
        features[4] = _norm_log(len(pauses), 100)
        features[5] = min((sum(pauses) / len(pauses) / 3600.0) if pauses else 0, 1.0)

        # 7. entropy of action type distribution
        features[6] = _action_entropy(action_types)

        # 8. dominant type ratio
        if action_types:
            type_counts = defaultdict(int)
            for t in action_types:
                type_counts[t] += 1
            max_count = max(type_counts.values())
            features[7] = max_count / count

        # 9-12. interval statistics
        if intervals:
            features[8] = min(np.mean(intervals) / 3600.0, 1.0)
            features[9] = min(np.std(intervals) / 3600.0, 1.0)
            features[10] = min(min(intervals) / 3600.0, 1.0)
            features[11] = min(max(intervals) / 3600.0, 1.0)

        # 13. hourly concentration (Herfindahl index)
        features[12] = _hourly_herfindahl(timestamps)

        # 14. first action hour (normalized 0-1)
        if timestamps:
            from datetime import datetime, timezone
            first_dt = datetime.fromtimestamp(timestamps[0], tz=timezone.utc)
            features[13] = first_dt.hour / 23.0

        # 15. last action hour (normalized 0-1)
        if timestamps:
            from datetime import datetime, timezone
            last_dt = datetime.fromtimestamp(timestamps[-1], tz=timezone.utc)
            features[14] = last_dt.hour / 23.0

        # 16. active hours (normalized 0-1)
        if timestamps:
            from datetime import datetime, timezone
            hours_set = set()
            for ts in timestamps:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                hours_set.add(dt.hour)
            features[15] = len(hours_set) / 24.0

        return features


def _norm_log(x, cap):
    """Log-normalize: log1p(x) / log1p(cap), clamped to [0, 1]."""
    return min(math.log1p(x) / math.log1p(cap), 1.0)


def _action_entropy(action_types):
    """Shannon entropy of action type distribution, normalized to [0, 1]."""
    if not action_types:
        return 0.0

    counts = defaultdict(int)
    for t in action_types:
        counts[t] += 1

    total = len(action_types)
    n_types = len(counts)
    if n_types <= 1:
        return 0.0

    entropy = 0.0
    for c in counts.values():
        p = c / total
        if p > 0:
            entropy -= p * math.log2(p)

    max_entropy = math.log2(n_types)
    return entropy / max_entropy if max_entropy > 0 else 0.0


def _detect_bursts(timestamps, window_sec=60):
    """Detect bursts: periods where action rate is >2σ above mean.

    Returns (burst_count, avg_burst_duration_seconds).
    """
    if len(timestamps) < 10:
        return 0, 0.0

    # Compute per-minute action rates
    if timestamps[-1] == timestamps[0]:
        return 0, 0.0

    min_ts = timestamps[0]
    max_ts = timestamps[-1]
    num_windows = max(1, (max_ts - min_ts) // window_sec + 1)

    window_counts = [0] * num_windows
    for ts in timestamps:
        idx = min((ts - min_ts) // window_sec, num_windows - 1)
        window_counts[idx] += 1

    mean_rate = np.mean(window_counts)
    std_rate = np.std(window_counts)
    threshold = mean_rate + 2 * std_rate

    if threshold <= 0 or std_rate == 0:
        return 0, 0.0

    burst_count = 0
    burst_durations = []
    in_burst = False
    burst_start = 0

    for i, c in enumerate(window_counts):
        if c > threshold and not in_burst:
            in_burst = True
            burst_start = i
        elif c <= threshold and in_burst:
            in_burst = False
            burst_durations.append((i - burst_start) * window_sec)
            burst_count += 1

    if in_burst:
        burst_durations.append((len(window_counts) - burst_start) * window_sec)
        burst_count += 1

    avg_dur = sum(burst_durations) / len(burst_durations) if burst_durations else 0.0
    return burst_count, avg_dur


def _hourly_herfindahl(timestamps):
    """Herfindahl index of actions across 24 hours.

    High (→1) = concentrated in few hours, Low (→0) = spread evenly.
    Normalized so uniform distribution = 0, single hour = 1.
    """
    if not timestamps:
        return 0.0

    from datetime import datetime, timezone
    hour_counts = [0] * 24
    for ts in timestamps:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        hour_counts[dt.hour] += 1

    total = sum(hour_counts)
    if total == 0:
        return 0.0

    hhi = sum((c / total) ** 2 for c in hour_counts)
    # Normalize: HHI ranges from 1/24 (uniform) to 1 (single hour)
    # Map to [0, 1]: (hhi - 1/24) / (1 - 1/24)
    min_hhi = 1.0 / 24.0
    return min(max((hhi - min_hhi) / (1.0 - min_hhi), 0.0), 1.0)
