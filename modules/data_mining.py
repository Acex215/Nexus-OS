#!/usr/bin/env python3
"""NEXUS Data Mining Module — extract patterns from blockchain and task history.

The blockchain is not just a ledger — it's a teacher.

Four mining operations:
  1. Pattern Mining   — Apriori association rules on task sequences
  2. Resource Mining  — k-Means clustering of node capability tiers
  3. Reputation Mining — composite scoring per wallet
  4. Anomaly Detection — flag outlier nodes via Naive Bayes / z-score

Usage: cd /opt/nexus && python3 modules/data_mining.py
"""

import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import numpy as np

sys.path.insert(0, '/opt/nexus')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [data-miner] %(levelname)s %(message)s',
)
log = logging.getLogger("data_miner")

TASK_LOG = Path('/opt/nexus/agents/logs/task_log.jsonl')
DEPLOYER = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'

# Optional heavy deps — graceful fallback
try:
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    log.warning("scikit-learn not available — resource mining will use basic quantiles")

try:
    from mlxtend.frequent_patterns import apriori, association_rules
    from mlxtend.preprocessing import TransactionEncoder
    HAS_MLXTEND = True
except ImportError:
    HAS_MLXTEND = False
    log.warning("mlxtend not available — using built-in frequent itemset mining")


# ── Helpers ───────────────────────────────────────────────────────────────

def _load_task_log():
    """Load all task log entries from JSONL."""
    entries = []
    if not TASK_LOG.exists():
        log.warning("Task log not found: %s", TASK_LOG)
        return entries
    with open(TASK_LOG, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _get_kernel():
    """Lazy-init NexusKernel for on-chain reads."""
    try:
        from libnexus.kernel import NexusKernel
        return NexusKernel(wallet=DEPLOYER)
    except Exception as e:
        log.warning("NexusKernel init failed: %s", e)
        return None


def _get_flock():
    """Lazy-init FlockClient for gradient quality data."""
    try:
        from libnexus.flock_client import FlockClient
        return FlockClient(wallet=DEPLOYER)
    except Exception as e:
        log.debug("FlockClient not available: %s", e)
        return None


# ══════════════════════════════════════════════════════════════════════════
# 1. PATTERN MINING — Apriori association rules on task sequences
# ══════════════════════════════════════════════════════════════════════════

class PatternMiner:
    """Find association rules in task history."""

    def __init__(self, entries):
        self.entries = entries

    def _build_transactions(self):
        """Convert each task into an itemset of categorical features."""
        transactions = []
        for e in self.entries:
            items = set()

            # outcome
            items.add(f"outcome={'success' if e.get('success') else 'fail'}")

            # priority
            prio = e.get('priority', 'P2')
            items.add(f"priority={prio}")

            # risk
            risk = e.get('risk', 'unknown')
            items.add(f"risk={risk}")

            # time of day bin (4-hour bins)
            ts = e.get('timestamp', '')
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    hour_bin = (dt.hour // 4) * 4
                    items.add(f"hour_bin={hour_bin:02d}-{hour_bin+4:02d}")
                    items.add(f"weekday={dt.strftime('%a')}")
                except (ValueError, TypeError):
                    pass

            # duration bin
            dur = e.get('duration_seconds', 0) or 0
            if dur < 60:
                items.add("duration=fast")
            elif dur < 300:
                items.add("duration=medium")
            else:
                items.add("duration=slow")

            # files changed bin
            fc = e.get('files_changed', 0) or 0
            if fc == 0:
                items.add("scope=no_files")
            elif fc <= 2:
                items.add("scope=small")
            else:
                items.add("scope=large")

            transactions.append(list(items))
        return transactions

    def mine(self, min_support=0.2, min_confidence=0.6):
        """Run pattern mining. Returns list of rule dicts."""
        transactions = self._build_transactions()
        if len(transactions) < 2:
            log.info("Pattern mining: not enough transactions (%d)", len(transactions))
            return []

        if HAS_MLXTEND:
            return self._mine_mlxtend(transactions, min_support, min_confidence)
        return self._mine_basic(transactions, min_support, min_confidence)

    def _mine_mlxtend(self, transactions, min_support, min_confidence):
        te = TransactionEncoder()
        te_ary = te.fit(transactions).transform(transactions)
        import pandas as pd
        df = pd.DataFrame(te_ary, columns=te.columns_)
        freq = apriori(df, min_support=min_support, use_colnames=True)
        if freq.empty:
            return []
        rules = association_rules(freq, metric="confidence", min_threshold=min_confidence)
        result = []
        for _, row in rules.iterrows():
            result.append({
                'antecedent': list(row['antecedents']),
                'consequent': list(row['consequents']),
                'support': round(float(row['support']), 4),
                'confidence': round(float(row['confidence']), 4),
                'lift': round(float(row['lift']), 4),
            })
        return sorted(result, key=lambda r: r['confidence'], reverse=True)

    def _mine_basic(self, transactions, min_support, min_confidence):
        """Basic frequent itemset mining (no mlxtend)."""
        n = len(transactions)
        item_counts = Counter()
        for txn in transactions:
            for item in txn:
                item_counts[item] += 1

        # Frequent 1-itemsets
        freq_items = {frozenset([item]) for item, count in item_counts.items()
                      if count / n >= min_support}

        # Frequent 2-itemsets
        pair_counts = Counter()
        for txn in transactions:
            txn_set = set(txn)
            for a, b in combinations(sorted(txn_set), 2):
                pair_counts[frozenset([a, b])] += 1

        freq_pairs = {pair for pair, count in pair_counts.items()
                      if count / n >= min_support}

        # Generate rules from frequent pairs
        rules = []
        for pair in freq_pairs:
            pair_support = pair_counts[pair] / n
            items = list(pair)
            for i in range(2):
                ant = frozenset([items[i]])
                cons = frozenset([items[1 - i]])
                ant_support = item_counts[items[i]] / n
                if ant_support == 0:
                    continue
                confidence = pair_support / ant_support
                if confidence >= min_confidence:
                    cons_support = item_counts[items[1 - i]] / n
                    lift = confidence / cons_support if cons_support > 0 else 0
                    rules.append({
                        'antecedent': list(ant),
                        'consequent': list(cons),
                        'support': round(pair_support, 4),
                        'confidence': round(confidence, 4),
                        'lift': round(lift, 4),
                    })

        return sorted(rules, key=lambda r: r['confidence'], reverse=True)


# ══════════════════════════════════════════════════════════════════════════
# 2. RESOURCE MINING — k-Means clustering of node capability tiers
# ══════════════════════════════════════════════════════════════════════════

class ResourceMiner:
    """Cluster nodes into capability tiers."""

    def __init__(self, kernel=None, task_entries=None):
        self.kernel = kernel
        self.task_entries = task_entries or []

    def _get_node_features(self):
        """Build feature matrix: [cpu_cores, memory_gb, storage_gb, ai_tops] per node."""
        if not self.kernel:
            return [], []

        try:
            nodes = self.kernel.get_all_nodes_detail()
        except Exception as e:
            log.warning("get_all_nodes_detail failed: %s", e)
            return [], []

        if not nodes:
            return [], []

        # Build task success stats per wallet (if we had node-task mapping)
        # For now, use hardware features only
        wallets = []
        features = []
        for n in nodes:
            wallets.append(n['wallet'])
            features.append([
                n.get('cpu_cores', 0),
                n.get('memory_gb', 0),
                n.get('storage_gb', 0),
                n.get('ai_tops', 0),
            ])

        return wallets, np.array(features, dtype=np.float64)

    def mine(self, n_clusters=3):
        """Cluster nodes into tiers. Returns list of {wallet, tier, features}."""
        wallets, X = self._get_node_features()
        if len(wallets) < 2:
            log.info("Resource mining: not enough nodes (%d) for clustering", len(wallets))
            if len(wallets) == 1:
                return [{'wallet': wallets[0], 'tier': 1, 'tier_label': 'Tier 1',
                          'features': X[0].tolist()}]
            return []

        k = min(n_clusters, len(wallets))

        if HAS_SKLEARN:
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            km = KMeans(n_clusters=k, random_state=42, n_init=10)
            labels = km.fit_predict(X_scaled)
        else:
            # Basic quantile-based tiering on total resource score
            scores = X.sum(axis=1)
            thresholds = np.quantile(scores, [1/3, 2/3])
            labels = np.zeros(len(scores), dtype=int)
            labels[scores > thresholds[1]] = 0
            labels[(scores > thresholds[0]) & (scores <= thresholds[1])] = 1
            labels[scores <= thresholds[0]] = 2

        # Rank clusters by mean resource magnitude so Tier 1 = best
        cluster_means = {}
        for c in range(k):
            mask = labels == c
            if mask.any():
                cluster_means[c] = X[mask].sum(axis=1).mean()
        ranked = sorted(cluster_means, key=cluster_means.get, reverse=True)
        tier_map = {c: i + 1 for i, c in enumerate(ranked)}

        results = []
        for i, wallet in enumerate(wallets):
            tier = tier_map.get(labels[i], k)
            results.append({
                'wallet': wallet,
                'tier': tier,
                'tier_label': f"Tier {tier}",
                'features': X[i].tolist(),
            })

        return sorted(results, key=lambda r: r['tier'])


# ══════════════════════════════════════════════════════════════════════════
# 3. REPUTATION MINING — composite scoring per wallet
# ══════════════════════════════════════════════════════════════════════════

class ReputationMiner:
    """Calculate composite reputation score per wallet."""

    WEIGHT_GRADIENT = 0.40
    WEIGHT_QUANTUM = 0.30
    WEIGHT_UPTIME = 0.20
    WEIGHT_NETWORK = 0.10

    def __init__(self, kernel=None, flock=None):
        self.kernel = kernel
        self.flock = flock

    def _gradient_quality_scores(self, wallets):
        """Get gradient quality from FlockCoordinator submissions."""
        scores = {}
        if not self.flock:
            # Placeholder: all wallets get 75% (synthetic baseline)
            for w in wallets:
                scores[w] = 0.75
            return scores

        try:
            epoch = self.flock.get_current_epoch()
            eid = epoch['epochId']
            if eid > 0:
                subs = self.flock.get_epoch_submissions(eid)
                for s in subs:
                    scores[s['contributor']] = s['qualityScore'] / 10000.0
        except Exception as e:
            log.debug("Gradient quality fetch failed: %s", e)

        # Fill missing with placeholder
        for w in wallets:
            if w not in scores:
                scores[w] = 0.75
        return scores

    def _quantum_benchmark_scores(self, wallets):
        """Placeholder until QB module exists."""
        return {w: 0.50 for w in wallets}

    def _uptime_scores(self, wallets):
        """Estimate uptime from node registration status."""
        scores = {}
        if not self.kernel:
            return {w: 0.80 for w in wallets}

        for w in wallets:
            try:
                node = self.kernel.get_node(w)
                # node = (hostname, cpuCores, memoryGB, storageGB, aiTops, active)
                active = node[5] if len(node) > 5 else False
                scores[w] = 0.95 if active else 0.30
            except Exception:
                scores[w] = 0.50
        return scores

    def _network_health_scores(self, wallets):
        """Check mesh peer registration status."""
        scores = {}
        if not self.kernel:
            return {w: 0.70 for w in wallets}

        try:
            peers = self.kernel.get_all_peers()
            peer_wallets = {p['wallet'] for p in peers if p.get('active')}
        except Exception:
            peer_wallets = set()

        for w in wallets:
            scores[w] = 0.90 if w in peer_wallets else 0.40
        return scores

    def mine(self):
        """Calculate reputation scores for all registered nodes."""
        if not self.kernel:
            log.info("Reputation mining: no kernel — returning empty")
            return []

        try:
            wallets = self.kernel.get_all_nodes()
        except Exception as e:
            log.warning("get_all_nodes failed: %s", e)
            return []

        if not wallets:
            return []

        grad = self._gradient_quality_scores(wallets)
        qb = self._quantum_benchmark_scores(wallets)
        uptime = self._uptime_scores(wallets)
        net = self._network_health_scores(wallets)

        results = []
        for w in wallets:
            score = (
                self.WEIGHT_GRADIENT * grad.get(w, 0) +
                self.WEIGHT_QUANTUM * qb.get(w, 0) +
                self.WEIGHT_UPTIME * uptime.get(w, 0) +
                self.WEIGHT_NETWORK * net.get(w, 0)
            )
            results.append({
                'wallet': w,
                'reputation_score': round(score, 4),
                'components': {
                    'gradient_quality': round(grad.get(w, 0), 4),
                    'quantum_benchmark': round(qb.get(w, 0), 4),
                    'uptime': round(uptime.get(w, 0), 4),
                    'network_health': round(net.get(w, 0), 4),
                },
                'rst_recommendation': _rst_recommendation(score),
            })
        return sorted(results, key=lambda r: r['reputation_score'], reverse=True)


def _rst_recommendation(score):
    """Map reputation score to RST adjustment recommendation."""
    if score >= 0.85:
        return "increase RST +5%"
    elif score >= 0.70:
        return "maintain RST"
    elif score >= 0.50:
        return "decrease RST -5%"
    else:
        return "decrease RST -15% (review needed)"


# ══════════════════════════════════════════════════════════════════════════
# 4. ANOMALY DETECTION — z-score flagging on node behavior
# ══════════════════════════════════════════════════════════════════════════

class AnomalyDetector:
    """Flag outlier nodes based on behavioral deviation."""

    def __init__(self, kernel=None, task_entries=None):
        self.kernel = kernel
        self.task_entries = task_entries or []

    def _build_behavior_matrix(self):
        """Build per-wallet behavior vectors from on-chain + task data."""
        if not self.kernel:
            return {}, []

        try:
            wallets = self.kernel.get_all_nodes()
        except Exception:
            return {}, []

        if not wallets:
            return {}, []

        # On-chain signals
        behaviors = {}
        for w in wallets:
            try:
                history = self.kernel.get_agent_history(w)
                entry_count = len(history) if history else 0
            except Exception:
                entry_count = 0

            try:
                node = self.kernel.get_node(w)
                active = node[5] if len(node) > 5 else False
            except Exception:
                active = False

            behaviors[w] = {
                'reasoning_entries': entry_count,
                'active': 1.0 if active else 0.0,
            }

        # Task-based signals (aggregate by wallet if task had blockchain_tx)
        wallet_tasks = defaultdict(lambda: {'count': 0, 'successes': 0, 'total_duration': 0.0})
        for e in self.task_entries:
            # We don't have per-wallet task attribution in the log, so
            # use aggregate stats as the baseline behavior profile
            pass

        feature_names = ['reasoning_entries', 'active']
        return behaviors, feature_names

    def detect(self, z_threshold=2.0):
        """Detect anomalous nodes. Returns list of {wallet, anomalous, reasons, z_scores}."""
        behaviors, feature_names = self._build_behavior_matrix()
        if len(behaviors) < 3:
            log.info("Anomaly detection: not enough nodes (%d) for meaningful analysis",
                     len(behaviors))
            results = []
            for w, b in behaviors.items():
                results.append({
                    'wallet': w,
                    'anomalous': False,
                    'reasons': ['insufficient data for comparison'],
                    'z_scores': {},
                })
            return results

        wallets = list(behaviors.keys())
        X = np.array([[behaviors[w][f] for f in feature_names] for w in wallets],
                      dtype=np.float64)

        means = X.mean(axis=0)
        stds = X.std(axis=0)
        # Avoid division by zero
        stds[stds == 0] = 1.0
        Z = (X - means) / stds

        results = []
        for i, w in enumerate(wallets):
            reasons = []
            z_dict = {}
            anomalous = False
            for j, fname in enumerate(feature_names):
                z_val = float(Z[i, j])
                z_dict[fname] = round(z_val, 3)
                if abs(z_val) > z_threshold:
                    anomalous = True
                    direction = "high" if z_val > 0 else "low"
                    reasons.append(f"{fname} unusually {direction} (z={z_val:+.2f})")

            results.append({
                'wallet': w,
                'anomalous': anomalous,
                'reasons': reasons if reasons else ['within normal range'],
                'z_scores': z_dict,
            })

        return results


# ══════════════════════════════════════════════════════════════════════════
# Facade
# ══════════════════════════════════════════════════════════════════════════

class NexusDataMiner:
    """Unified interface to all four mining operations."""

    def __init__(self):
        self.task_entries = _load_task_log()
        self.kernel = _get_kernel()
        self.flock = _get_flock()

    def mine_patterns(self, **kwargs):
        return PatternMiner(self.task_entries).mine(**kwargs)

    def mine_resources(self, **kwargs):
        return ResourceMiner(self.kernel, self.task_entries).mine(**kwargs)

    def mine_reputation(self):
        return ReputationMiner(self.kernel, self.flock).mine()

    def detect_anomalies(self, **kwargs):
        return AnomalyDetector(self.kernel, self.task_entries).detect(**kwargs)

    def run_all(self):
        """Run all mining operations and return combined results."""
        results = {}

        log.info("=== Pattern Mining ===")
        rules = self.mine_patterns()
        results['patterns'] = rules
        log.info("Found %d association rules", len(rules))
        for r in rules[:5]:
            log.info("  %s => %s  (conf=%.2f, lift=%.2f)",
                     r['antecedent'], r['consequent'], r['confidence'], r['lift'])

        log.info("=== Resource Mining ===")
        tiers = self.mine_resources()
        results['resource_tiers'] = tiers
        log.info("Classified %d nodes into tiers", len(tiers))
        for t in tiers:
            log.info("  %s: %s  features=%s",
                     t['wallet'][:12] + '...', t['tier_label'], t['features'])

        log.info("=== Reputation Mining ===")
        rep = self.mine_reputation()
        results['reputation'] = rep
        log.info("Scored %d wallets", len(rep))
        for r in rep:
            log.info("  %s: score=%.4f  rec=%s",
                     r['wallet'][:12] + '...', r['reputation_score'], r['rst_recommendation'])

        log.info("=== Anomaly Detection ===")
        anomalies = self.detect_anomalies()
        results['anomalies'] = anomalies
        flagged = [a for a in anomalies if a['anomalous']]
        log.info("Checked %d nodes, %d anomalous", len(anomalies), len(flagged))
        for a in anomalies:
            status = "ANOMALOUS" if a['anomalous'] else "normal"
            log.info("  %s: %s — %s",
                     a['wallet'][:12] + '...', status, '; '.join(a['reasons']))

        return results


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    miner = NexusDataMiner()
    results = miner.run_all()

    print()
    print("=" * 60)
    print("NEXUS Data Mining Summary")
    print("=" * 60)
    print(f"  Pattern rules:   {len(results['patterns'])}")
    print(f"  Resource tiers:  {len(results['resource_tiers'])}")
    print(f"  Reputation scores: {len(results['reputation'])}")
    anomalous = sum(1 for a in results['anomalies'] if a['anomalous'])
    print(f"  Anomalies:       {anomalous}/{len(results['anomalies'])} nodes flagged")
    print()
