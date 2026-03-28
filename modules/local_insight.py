#!/usr/bin/env python3
"""
NEXUS Local Insight Engine

Generates human-readable behavioral insights from the user's own
on-chain data. Always available — does not require debug mode.

This engine answers questions like:
- "How fast am I typing today vs my average?"
- "What's my most productive hour?"
- "How many context switches did I make this morning?"
- "Am I taking enough breaks?"
- "What pattern am I in right now?"
- "How does today compare to my weekly average?"
"""

import json
import time
import numpy as np
from collections import Counter, defaultdict
from datetime import datetime

import sys
sys.path.insert(0, '/opt/nexus')

from libnexus.behavioral_client import BehavioralClient


CHANNEL_NAMES = {
    1: 'Keystroke', 2: 'Mouse', 3: 'Window', 4: 'Web', 5: 'Message',
    6: 'File', 7: 'Clipboard', 8: 'System', 9: 'Session',
    10: 'App Lifecycle', 11: 'GPS', 12: 'Weather', 13: 'WiFi',
    14: 'Audio', 15: 'Display', 16: 'Power', 17: 'Peripheral',
    18: 'Notification'
}


class LocalInsightEngine:
    """
    Generates behavioral insights from the user's own on-chain data.
    Uses selfRead* contract functions — works after debug lockout.
    """

    def __init__(self, client: BehavioralClient = None):
        self.client = client or BehavioralClient()

    def _get_actions_in_range(self, start_time, end_time):
        """Read own actions in a time range using self-read (always available)."""
        try:
            action_ids = self.client.self_read_actions(int(start_time), int(end_time))
            actions = []
            for aid in action_ids:
                try:
                    a = self.client.self_read_action(aid)
                    try:
                        payload = json.loads(a['data'].decode('utf-8', errors='ignore'))
                    except:
                        payload = {}
                    actions.append({
                        'id': aid,
                        'channel': a['channelId'],
                        'type': a['actionType'],
                        'timestamp': a['timestamp'],
                        'payload': payload
                    })
                except:
                    pass
            return actions
        except Exception as e:
            print(f"[LocalInsight] Error reading actions: {e}")
            return []

    def now_vs_average(self):
        """
        Compare the last hour's activity to the weekly average for this hour.
        Returns human-readable comparison.
        """
        now = int(time.time())
        hour_start = now - 3600

        # Current hour's data
        current = self._get_actions_in_range(hour_start, now)
        current_total = len(current)
        current_channels = Counter(a['channel'] for a in current)

        # Same hour from previous 4 weeks
        week_sec = 7 * 24 * 3600
        historical_totals = []
        for w in range(1, 5):
            hist_start = hour_start - (w * week_sec)
            hist_end = now - (w * week_sec)
            hist = self._get_actions_in_range(hist_start, hist_end)
            historical_totals.append(len(hist))

        avg = np.mean(historical_totals) if historical_totals else 0

        if avg > 0:
            ratio = current_total / avg
            if ratio > 1.5:
                comparison = f"significantly above average ({ratio:.1f}x)"
            elif ratio > 1.1:
                comparison = f"slightly above average ({ratio:.1f}x)"
            elif ratio > 0.9:
                comparison = "about average"
            elif ratio > 0.5:
                comparison = f"below average ({ratio:.1f}x)"
            else:
                comparison = f"significantly below average ({ratio:.1f}x)"
        else:
            comparison = "no historical data for comparison"

        # Dominant channel
        if current_channels:
            dominant_ch = current_channels.most_common(1)[0]
            dominant_name = CHANNEL_NAMES.get(dominant_ch[0], f'Channel {dominant_ch[0]}')
        else:
            dominant_name = "none"

        return {
            'current_hour_actions': current_total,
            'weekly_average': round(avg, 1),
            'comparison': comparison,
            'dominant_activity': dominant_name,
            'active_channels': len(current_channels),
            'insight': f"This hour: {current_total} actions ({comparison}). "
                       f"Dominant: {dominant_name}."
        }

    def daily_summary(self):
        """Generate today's behavioral summary."""
        now = int(time.time())
        day_start = (now // 86400) * 86400
        actions = self._get_actions_in_range(day_start, now)

        if not actions:
            return {'insight': "No behavioral data collected today."}

        total = len(actions)
        channel_counts = Counter(a['channel'] for a in actions)
        hours_active = len(set(a['timestamp'] // 3600 for a in actions))

        # Per-channel breakdown
        breakdown = {}
        for ch_id, count in channel_counts.most_common():
            name = CHANNEL_NAMES.get(ch_id, f'Channel {ch_id}')
            breakdown[name] = count

        # Find peak hour
        hour_counts = Counter((a['timestamp'] % 86400) // 3600 for a in actions)
        peak_hour = hour_counts.most_common(1)[0][0] if hour_counts else 0

        # Session analysis (channel 9)
        session_actions = [a for a in actions if a['channel'] == 9]
        breaks = len([a for a in session_actions if a['type'] in (7, 8)])
        idles = len([a for a in session_actions if a['type'] in (5, 6)])

        # Build insights
        insights = []
        insights.append(f"Total actions today: {total:,} across {hours_active} active hours.")
        insights.append(f"Peak activity: {peak_hour:02d}:00-{peak_hour+1:02d}:00.")

        if channel_counts.get(1, 0) > channel_counts.get(4, 0) * 2:
            insights.append("Production-heavy day: writing/coding dominated over browsing.")
        elif channel_counts.get(4, 0) > channel_counts.get(1, 0) * 2:
            insights.append("Research-heavy day: browsing dominated over writing.")

        if breaks > 0:
            insights.append(f"You took {breaks} breaks today.")
        elif hours_active > 4:
            insights.append("No detected breaks in 4+ active hours — consider resting.")

        if channel_counts.get(18, 0) > 50:
            insights.append(f"High notification volume ({channel_counts[18]}). Consider a focus session.")

        return {
            'date': datetime.utcfromtimestamp(day_start).strftime('%Y-%m-%d'),
            'total_actions': total,
            'hours_active': hours_active,
            'peak_hour': f"{peak_hour:02d}:00",
            'breaks_taken': breaks,
            'idle_events': idles,
            'channel_breakdown': breakdown,
            'insights': insights
        }

    def typing_speed_trend(self):
        """
        Analyze typing speed over the last few hours.
        Uses keystroke batch intervals to estimate WPM trends.
        """
        now = int(time.time())
        hours_back = 4
        actions = self._get_actions_in_range(now - hours_back * 3600, now)

        keystroke_batches = [a for a in actions if a['channel'] == 1 and a['type'] == 1]

        if len(keystroke_batches) < 10:
            return {'insight': 'Not enough keystroke data for speed analysis.'}

        # Group by hour
        hourly_counts = defaultdict(int)
        for a in keystroke_batches:
            hr = (a['timestamp'] % 86400) // 3600
            hourly_counts[hr] += 1

        hours = sorted(hourly_counts.keys())
        counts = [hourly_counts[h] for h in hours]

        if len(counts) >= 2:
            trend = counts[-1] - counts[0]
            if trend > 10:
                trend_desc = "increasing (typing more over time)"
            elif trend < -10:
                trend_desc = "decreasing (possible fatigue)"
            else:
                trend_desc = "stable"
        else:
            trend_desc = "insufficient data"

        return {
            'hourly_keystroke_batches': {f"{h:02d}:00": c for h, c in zip(hours, counts)},
            'trend': trend_desc,
            'total_batches': len(keystroke_batches),
            'insight': f"Typing activity over {hours_back}h: {trend_desc}. "
                       f"Total keystroke batches: {len(keystroke_batches)}."
        }

    def current_pattern(self):
        """What behavioral pattern is the user in right now?"""
        now = int(time.time())
        actions = self._get_actions_in_range(now - 300, now)  # Last 5 min

        if not actions:
            return {'pattern': 'idle', 'insight': 'No activity in the last 5 minutes.'}

        channels = Counter(a['channel'] for a in actions)
        total = len(actions)

        # Pattern detection
        has_keys = channels.get(1, 0) > 5
        has_mouse = channels.get(2, 0) > 5
        has_web = channels.get(4, 0) > 0
        has_files = channels.get(6, 0) > 0
        has_msgs = channels.get(5, 0) > 0
        has_window = channels.get(3, 0) > 0
        window_switches = len([a for a in actions if a['channel'] == 3 and a['type'] == 1])

        if has_keys and has_files and window_switches < 3:
            pattern = 'deep_work'
            desc = "Focused writing/coding with minimal context switching."
        elif has_keys and has_web and channels.get(7, 0) > 0:
            pattern = 'research_and_write'
            desc = "Browsing and writing with copy-paste — active research."
        elif has_web and not has_keys:
            pattern = 'browsing'
            desc = "Web browsing without significant typing."
        elif has_msgs:
            pattern = 'communication'
            desc = "Active messaging or communication."
        elif has_keys and window_switches > 5:
            pattern = 'multitasking'
            desc = "Rapid context switching between multiple applications."
        elif total < 10:
            pattern = 'low_activity'
            desc = "Very light device usage."
        else:
            pattern = 'general'
            desc = "Mixed activity across multiple channels."

        return {
            'pattern': pattern,
            'description': desc,
            'actions_5min': total,
            'active_channels': {CHANNEL_NAMES.get(k, f'Ch{k}'): v for k, v in channels.most_common()},
            'window_switches': window_switches,
            'insight': f"Current pattern: {pattern}. {desc} ({total} actions in 5min)"
        }

    def get_all_insights(self):
        """Bundle all insights into a single response."""
        return {
            'current_pattern': self.current_pattern(),
            'now_vs_average': self.now_vs_average(),
            'daily_summary': self.daily_summary(),
            'typing_trend': self.typing_speed_trend(),
            'generated_at': datetime.utcnow().isoformat() + 'Z'
        }


if __name__ == '__main__':
    engine = LocalInsightEngine()
    insights = engine.get_all_insights()
    print(json.dumps(insights, indent=2))
