#!/usr/bin/env python3
"""NEXUS Epoch Submission — submit gradient before epoch finalization.

Runs at 23:50 UTC via systemd timer (before 00:00 finalization).
Collects the day's behavioral features, generates a gradient stub,
and submits to FlockCoordinator on-chain.

Daily cycle:
  00:00 -> epoch starts, ECT minted, salt generated
  00:00-23:49 -> features collected hourly
  23:50 -> gradient submitted (THIS SCRIPT)
  23:59 -> epoch finalized, RST adjusted, ECT burned
  00:00 -> new epoch

Usage: cd /opt/nexus && python3 scripts/epoch_submit.py
"""
import json
import logging
import os
import sys
import time

sys.path.insert(0, '/opt/nexus')

os.makedirs('/opt/nexus/logs', exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [epoch-submit] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/opt/nexus/logs/epoch_submit.log', mode='a'),
    ]
)
log = logging.getLogger("epoch_submit")

DEPLOYER = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'
DEFAULT_QUALITY_SCORE = 7500  # 75.00% — conservative default for synthetic data


def main():
    log.info("=== Epoch submission starting ===")

    # ── 1. Initialize clients ─────────────────────────────────────────────
    try:
        from libnexus.flock_client import FlockClient
    except (ImportError, FileNotFoundError) as e:
        log.error("FlockClient unavailable: %s", e)
        return 1

    try:
        from agents.feature_collector import FeatureCollector
    except ImportError as e:
        log.error("FeatureCollector unavailable: %s", e)
        return 1

    try:
        flock = FlockClient(wallet=DEPLOYER)
    except Exception as e:
        log.error("FlockClient init failed: %s", e)
        return 1

    fc = FeatureCollector()

    # ── 2. Get current epoch and daily salt ───────────────────────────────
    try:
        epoch = flock.get_current_epoch()
    except Exception as e:
        log.error("Failed to read current epoch: %s", e)
        return 1

    epoch_id = epoch['epochId']
    daily_salt = epoch['dailySalt']
    finalized = epoch['finalized']

    log.info("Epoch %d — salt: %s — submissions: %d — finalized: %s",
             epoch_id, daily_salt[:18] + '...', epoch['submissionCount'], finalized)

    if finalized:
        log.warning("Epoch %d already finalized, nothing to submit", epoch_id)
        return 0

    if epoch_id == 0:
        log.warning("No active epoch (epochId=0), nothing to submit")
        return 0

    # ── 3. Collect today's features ───────────────────────────────────────
    raw = fc.collect_raw_signals()
    log.info("Raw signals: wake=%dh, sessions=%d, network=%.0fMB, active=%dh",
             raw['wake_time'], raw['session_count'],
             raw['network_volume'], raw['active_hours'])

    # ── 4. Extract feature vector ─────────────────────────────────────────
    features = fc.extract_features(raw)
    log.info("Feature vector: shape=%s, norm=%.4f",
             features.shape, float((features ** 2).sum() ** 0.5))

    # ── 5. Generate gradient (stub: random bytes for now) ─────────────────
    # In production: fc.get_epoch_gradient(global_model_bytes)
    # For now, use the daily salt as a pseudo global model to seed the gradient
    salt_bytes = bytes.fromhex(daily_salt[2:]) if daily_salt.startswith('0x') else bytes.fromhex(daily_salt)
    gradient_bytes = fc.get_epoch_gradient(salt_bytes)
    log.info("Gradient generated: %d bytes", len(gradient_bytes))

    # ── 6. Hash the gradient ──────────────────────────────────────────────
    gradient_hash = FlockClient.generate_gradient_hash(gradient_bytes)
    log.info("Gradient hash: 0x%s", gradient_hash.hex()[:16] + '...')

    # ── 7. Submit to FlockCoordinator ─────────────────────────────────────
    log.info("Submitting gradient (quality=%d = %.2f%%)...",
             DEFAULT_QUALITY_SCORE, DEFAULT_QUALITY_SCORE / 100)
    try:
        result = flock.submit_gradient(gradient_hash, DEFAULT_QUALITY_SCORE)
    except Exception as e:
        log.error("Gradient submission failed: %s", e)
        return 1

    # ── 8. Log submission receipt ─────────────────────────────────────────
    log.info("Submitted successfully:")
    log.info("  epoch:    %d", epoch_id)
    log.info("  tx_hash:  %s", result['tx_hash'])
    log.info("  block:    %d", result['block'])
    log.info("  gas_used: %d", result['gas_used'])

    # Also log the obfuscated feature hash for audit trail
    obfuscated = fc.obfuscate(features, daily_salt[2:] if daily_salt.startswith('0x') else daily_salt)
    log.info("  feature_hash: 0x%s", obfuscated.hex()[:16] + '...')

    # Persist receipt to JSON for dashboard/debugging
    receipt_path = '/opt/nexus/logs/last_epoch_submission.json'
    try:
        receipt = {
            'epoch_id': epoch_id,
            'tx_hash': result['tx_hash'],
            'block': result['block'],
            'gas_used': result['gas_used'],
            'gradient_hash': '0x' + gradient_hash.hex(),
            'feature_hash': '0x' + obfuscated.hex(),
            'quality_score': DEFAULT_QUALITY_SCORE,
            'timestamp': time.time(),
        }
        with open(receipt_path, 'w') as f:
            json.dump(receipt, f, indent=2)
        log.info("Receipt saved to %s", receipt_path)
    except Exception as e:
        log.warning("Failed to save receipt: %s", e)

    log.info("=== Epoch submission complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
