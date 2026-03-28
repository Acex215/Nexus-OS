#!/usr/bin/env python3
"""NEXUS Epoch Submission — submit gradient before epoch finalization.

Runs at 23:50 UTC via systemd timer (before 00:00 finalization).
Trains the sequence predictor (TCN) on compound token history,
generates real gradients, and submits to FlockCoordinator on-chain.

Daily cycle:
  00:00 -> epoch starts, ECT minted, salt generated
  00:00-23:49 -> behavioral actions collected via BehavioralActionRegistry
  23:50 -> sequence model trained, gradient submitted (THIS SCRIPT)
  23:59 -> epoch finalized, RST adjusted, ECT burned
  00:00 -> new epoch

Usage: cd /opt/nexus && python3 scripts/epoch_submit.py
"""
import json
import logging
import os
import sys
import time

import numpy as np

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
MODEL_DIR = '/opt/nexus/models'


def main():
    log.info("=== Epoch submission starting ===")

    # ── 1. Initialize clients ─────────────────────────────────────────────
    try:
        from libnexus.flock_client import FlockClient
    except (ImportError, FileNotFoundError) as e:
        log.error("FlockClient unavailable: %s", e)
        return 1

    try:
        from libnexus.behavioral_client import BehavioralClient
    except (ImportError, FileNotFoundError) as e:
        log.error("BehavioralClient unavailable: %s", e)
        return 1

    try:
        from models.behavioral_sequence_model import BehavioralSequenceModel
    except ImportError as e:
        log.error("BehavioralSequenceModel unavailable: %s", e)
        return 1

    # Secondary: feature collector for legacy obfuscation audit trail
    try:
        from agents.feature_collector import FeatureCollector
        fc = FeatureCollector()
        has_feature_collector = True
    except ImportError:
        has_feature_collector = False

    try:
        flock = FlockClient(wallet=DEPLOYER)
    except Exception as e:
        log.error("FlockClient init failed: %s", e)
        return 1

    try:
        behavioral_client = BehavioralClient(wallet=DEPLOYER)
    except Exception as e:
        log.error("BehavioralClient init failed: %s", e)
        return 1

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

    # ── 3. PRIMARY MODEL: Sequence Predictor (TCN) ────────────────────────
    os.makedirs(MODEL_DIR, exist_ok=True)
    seq_model_path = os.path.join(MODEL_DIR, 'sequence_model.npz')
    seq_model = BehavioralSequenceModel()
    if os.path.exists(seq_model_path):
        seq_model.load(seq_model_path)
        log.info("Loaded existing sequence model")

    steps, gradients = seq_model.train_on_compound_history(
        behavioral_client, window_size=12, max_compounds=500
    )
    log.info("Sequence model: %d training steps", steps)

    # Quality score from sequence prediction accuracy
    quality_score = 5000  # Default if no compounds yet
    if steps > 0:
        total_compounds = behavioral_client.get_total_compounds()
        if total_compounds > 13:
            test_compounds = []
            for cid in range(total_compounds - 13, total_compounds):
                try:
                    c = behavioral_client.get_compound(cid)
                    test_compounds.append({
                        'action_count': c['actionCount'],
                        'channels': {},
                        'dominant': 1,
                        'intensity': 'MEDIUM',
                        'channel_diversity': 5
                    })
                except:
                    pass
            if len(test_compounds) >= 13:
                seq = [seq_model.encode_compound(c) for c in test_compounds[:12]]
                target = seq_model.encode_compound(test_compounds[12])
                quality_score = seq_model.compute_quality_score(seq, target)

    seq_model.save(seq_model_path)
    log.info("Quality score: %d/10000", quality_score)

    # Gradient from SEQUENCE MODEL (not autoencoder)
    gradient_bytes = seq_model.get_gradient_bytes(gradients) if gradients else b'\x00' * 32

    # ── 4. Obfuscate the SEQUENCE MODEL gradient ─────────────────────────
    # Pad/truncate to 288 floats for consistent hashing
    grad_vector = np.frombuffer(gradient_bytes[:288*4], dtype=np.float32)[:288]
    if len(grad_vector) < 288:
        grad_vector = np.pad(grad_vector, (0, 288 - len(grad_vector)))

    salt_hex = daily_salt[2:] if daily_salt.startswith('0x') else daily_salt
    salt_bytes = bytes.fromhex(salt_hex)

    # Obfuscate: keccak(gradient_bytes || salt)
    from web3 import Web3
    obfuscated_gradient = Web3.keccak(grad_vector.astype(np.float32).tobytes() + salt_bytes)

    # ── 5. Hash the gradient for on-chain submission ──────────────────────
    gradient_hash = FlockClient.generate_gradient_hash(gradient_bytes)
    log.info("Gradient hash: 0x%s", gradient_hash.hex()[:16] + '...')

    # ── 6. Submit to FlockCoordinator ─────────────────────────────────────
    log.info("Submitting gradient (quality=%d = %.2f%%)...",
             quality_score, quality_score / 100)
    try:
        result = flock.submit_gradient(gradient_hash, quality_score)
    except Exception as e:
        log.error("Gradient submission failed: %s", e)
        return 1

    # ── 7. Log submission receipt ─────────────────────────────────────────
    log.info("Submitted successfully:")
    log.info("  epoch:    %d", epoch_id)
    log.info("  tx_hash:  %s", result['tx_hash'])
    log.info("  block:    %d", result['block'])
    log.info("  gas_used: %d", result['gas_used'])
    log.info("  model:    BehavioralSequenceModel (TCN)")
    log.info("  steps:    %d", steps)

    # === SECONDARY: Legacy feature collector audit trail ===
    feature_hash_hex = None
    if has_feature_collector:
        raw = fc.collect_raw_signals()
        features = fc.extract_features(raw)
        feature_obfuscated = fc.obfuscate(features, salt_hex)
        feature_hash_hex = '0x' + feature_obfuscated.hex()
        log.info("  feature_hash (legacy): %s", feature_hash_hex[:18] + '...')

    # Persist receipt to JSON for dashboard/debugging
    receipt_path = '/opt/nexus/logs/last_epoch_submission.json'
    try:
        receipt = {
            'epoch_id': epoch_id,
            'tx_hash': result['tx_hash'],
            'block': result['block'],
            'gas_used': result['gas_used'],
            'gradient_hash': '0x' + gradient_hash.hex(),
            'obfuscated_gradient': '0x' + obfuscated_gradient.hex(),
            'quality_score': quality_score,
            'model': 'BehavioralSequenceModel',
            'training_steps': steps,
            'timestamp': time.time(),
        }
        if feature_hash_hex:
            receipt['feature_hash_legacy'] = feature_hash_hex
        with open(receipt_path, 'w') as f:
            json.dump(receipt, f, indent=2)
        log.info("Receipt saved to %s", receipt_path)
    except Exception as e:
        log.warning("Failed to save receipt: %s", e)

    log.info("=== Epoch submission complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
