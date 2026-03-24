#!/usr/bin/env python3
"""NEXUS Scheduled Mining Job — runs daily after epoch cycle.

Executes all 4 data mining operations, saves results to JSON,
and uploads a summary to ChromaDB for knowledge planner retrieval.

Runs at 01:00 UTC via systemd timer (after epoch start at 00:05).

Usage: cd /opt/nexus && python3 scripts/run_mining.py
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/opt/nexus')

os.makedirs('/opt/nexus/logs', exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [run-mining] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/opt/nexus/logs/run_mining.log', mode='a'),
    ]
)
log = logging.getLogger("run_mining")

RESULTS_PATH = Path('/opt/nexus/logs/mining_results.json')
CHROMA_COLLECTION = "mining_insights"


def _serialize_results(raw):
    """Make mining results JSON-serializable (numpy arrays -> lists)."""
    if isinstance(raw, dict):
        return {k: _serialize_results(v) for k, v in raw.items()}
    if isinstance(raw, list):
        return [_serialize_results(item) for item in raw]
    if hasattr(raw, 'tolist'):
        return raw.tolist()
    if isinstance(raw, (set, frozenset)):
        return list(raw)
    return raw


def _upload_to_chromadb(results, timestamp_iso):
    """Upload mining summary to ChromaDB for knowledge planner retrieval."""
    try:
        import chromadb
    except ImportError:
        log.warning("chromadb not installed — skipping knowledge upload")
        return False

    try:
        client = chromadb.HttpClient(host="localhost", port=8000)
        collection = client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        log.warning("ChromaDB connection failed: %s — skipping upload", e)
        return False

    doc_id = f"mining-{timestamp_iso[:10]}"

    # Build a text summary for semantic retrieval
    patterns = results.get('patterns', [])
    tiers = results.get('node_clusters', [])
    rep = results.get('reputation_scores', [])
    anomalies = results.get('anomalies', [])
    flagged = [a for a in anomalies if a.get('anomalous')]

    lines = [f"Data mining results for {timestamp_iso[:10]}"]

    if patterns:
        top_rules = patterns[:10]
        lines.append(f"Pattern mining: {len(patterns)} association rules found.")
        for r in top_rules:
            lines.append(
                f"  Rule: {r['antecedent']} => {r['consequent']} "
                f"(confidence={r['confidence']}, lift={r['lift']})"
            )

    if tiers:
        lines.append(f"Resource mining: {len(tiers)} nodes clustered.")
        for t in tiers:
            lines.append(f"  {t['wallet'][:12]}...: {t['tier_label']}")

    if rep:
        lines.append(f"Reputation mining: {len(rep)} wallets scored.")
        for r in rep:
            lines.append(
                f"  {r['wallet'][:12]}...: score={r['reputation_score']} "
                f"rec={r['rst_recommendation']}"
            )

    if flagged:
        lines.append(f"Anomaly detection: {len(flagged)} nodes flagged.")
        for a in flagged:
            lines.append(f"  {a['wallet'][:12]}...: {'; '.join(a['reasons'])}")
    else:
        lines.append(f"Anomaly detection: {len(anomalies)} nodes checked, none anomalous.")

    document = "\n".join(lines)

    metadata = {
        "type": "mining_results",
        "date": timestamp_iso[:10],
        "pattern_count": str(len(patterns)),
        "tier_count": str(len(tiers)),
        "reputation_count": str(len(rep)),
        "anomaly_count": str(len(flagged)),
        "timestamp": timestamp_iso,
    }

    try:
        collection.upsert(
            ids=[doc_id],
            documents=[document],
            metadatas=[metadata],
        )
        log.info("Uploaded mining summary to ChromaDB collection '%s' (id=%s)",
                 CHROMA_COLLECTION, doc_id)
        return True
    except Exception as e:
        log.warning("ChromaDB upsert failed: %s", e)
        return False


def main():
    log.info("=== Scheduled mining job starting ===")
    now = datetime.now(timezone.utc)
    timestamp_iso = now.isoformat()

    # ── Run all mining operations ─────────────────────────────────────────
    from modules.data_mining import NexusDataMiner

    miner = NexusDataMiner()
    raw = miner.run_all()

    # ── Build output structure ────────────────────────────────────────────
    results = {
        'timestamp': timestamp_iso,
        'patterns': _serialize_results(raw.get('patterns', [])),
        'node_clusters': _serialize_results(raw.get('resource_tiers', [])),
        'reputation_scores': _serialize_results(raw.get('reputation', [])),
        'anomalies': _serialize_results(raw.get('anomalies', [])),
    }

    # ── Save to JSON ──────────────────────────────────────────────────────
    try:
        RESULTS_PATH.write_text(json.dumps(results, indent=2))
        log.info("Results saved to %s", RESULTS_PATH)
    except Exception as e:
        log.error("Failed to save results: %s", e)

    # ── Check for anomalies ───────────────────────────────────────────────
    flagged = [a for a in results['anomalies'] if a.get('anomalous')]
    if flagged:
        log.warning("ANOMALIES DETECTED: %d node(s) flagged", len(flagged))
        for a in flagged:
            log.warning("  Node %s: %s", a['wallet'][:16] + '...', '; '.join(a['reasons']))

    # ── Upload to ChromaDB ────────────────────────────────────────────────
    _upload_to_chromadb(results, timestamp_iso)

    # ── Summary ───────────────────────────────────────────────────────────
    log.info("=== Mining job complete ===")
    log.info("  Patterns:    %d rules", len(results['patterns']))
    log.info("  Clusters:    %d nodes", len(results['node_clusters']))
    log.info("  Reputation:  %d wallets", len(results['reputation_scores']))
    log.info("  Anomalies:   %d/%d flagged",
             len(flagged), len(results['anomalies']))

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
