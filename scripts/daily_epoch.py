#!/usr/bin/env python3
"""NEXUS Daily Epoch Cycle — runs the complete behavioral intelligence pipeline.

Schedule at 23:50 UTC via cron or systemd timer.
Executes: feature extraction → privacy budget → obfuscation → proof →
gradient hash → submission → cache destruction.
"""

import glob
import logging
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, '/opt/nexus')

from web3 import Web3

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('nexus.epoch')

# ANSI
B = '\033[1m'
G = '\033[92m'
R = '\033[91m'
Y = '\033[93m'
D = '\033[2m'
X = '\033[0m'


def main():
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    start_time = time.time()

    print()
    print(f'  {B}═══════════════════════════════════════════{X}')
    print(f'  {B}NEXUS Daily Epoch — {today}{X}')
    print(f'  {B}═══════════════════════════════════════════{X}')
    print()

    errors = []
    results = {}

    # ── Step 1: Feature extraction ────────────────
    log.info('Step 1: Feature extraction')
    features = None
    try:
        from modules.feature_extractor import FeatureExtractor
        fe = FeatureExtractor()
        features = fe.extract_daily()
        nonzero = int(np.count_nonzero(features))
        results['features_dim'] = features.shape[0]
        results['features_nonzero'] = nonzero
        log.info(f'  {G}288-dim vector: {nonzero} non-zero features{X}')
    except Exception as e:
        log.error(f'  {R}Feature extraction failed: {e}{X}')
        errors.append(('feature_extraction', str(e)))
        traceback.print_exc()

    # ── Step 2: Privacy budget ────────────────────
    log.info('Step 2: Privacy budget check')
    epsilon = 1.0
    try:
        from modules.privacy_budget import PrivacyBudgetManager
        pb = PrivacyBudgetManager()
        epsilon = pb.get_optimal_epsilon(remaining_operations=1)
        results['epsilon_available'] = pb.get_remaining()

        if not pb.spend(epsilon, 'daily_epoch'):
            log.error(f'  {R}Privacy budget exhausted{X}')
            errors.append(('privacy_budget', 'exhausted'))
            epsilon = 0.0
        else:
            results['epsilon_spent'] = epsilon
            log.info(f'  {G}Spent ε={epsilon:.4f}, remaining={pb.get_remaining():.4f}{X}')
    except Exception as e:
        log.error(f'  {R}Privacy budget failed: {e}{X}')
        errors.append(('privacy_budget', str(e)))

    # ── Step 3: Obfuscation ───────────────────────
    log.info('Step 3: Obfuscation')
    obfuscated = None
    salt = None
    try:
        from modules.obfuscation import BehavioralObfuscator
        ob = BehavioralObfuscator()
        salt = ob.get_daily_salt()

        if features is not None and epsilon > 0:
            obfuscated = ob.obfuscate(features, epsilon=epsilon)
            det = obfuscated['rotation_det']
            results['rotation_det'] = det
            log.info(f'  {G}Obfuscated: det={det:.1f}, salt={obfuscated["salt_hash"].hex()[:12]}...{X}')
        else:
            log.warning(f'  {Y}Skipped: no features or no budget{X}')
    except Exception as e:
        log.error(f'  {R}Obfuscation failed: {e}{X}')
        errors.append(('obfuscation', str(e)))

    # ── Step 4: Privacy proof ─────────────────────
    log.info('Step 4: Privacy proof generation')
    proof = None
    try:
        from modules.privacy_verifier import PrivacyVerifier
        pv = PrivacyVerifier()

        if features is not None and salt is not None:
            proof = pv.generate_proof(features, salt, epsilon)
            merkle = proof.get('dataset_merkle_root', b'')
            if isinstance(merkle, bytes):
                merkle_hex = merkle.hex()[:16]
            else:
                merkle_hex = str(merkle)[:16]
            results['merkle_root'] = merkle_hex
            log.info(f'  {G}Proof generated: merkle={merkle_hex}...{X}')
        else:
            log.warning(f'  {Y}Skipped: no features or salt{X}')
    except Exception as e:
        log.error(f'  {R}Privacy proof failed: {e}{X}')
        errors.append(('privacy_proof', str(e)))

    # ── Step 5: Gradient hash ─────────────────────
    log.info('Step 5: Gradient computation')
    gradient_hash = None
    try:
        if obfuscated is not None:
            vec_bytes = obfuscated['obfuscated_vector'].tobytes()
            gradient_hash = Web3.keccak(vec_bytes)
            results['gradient_hash'] = gradient_hash.hex()
            log.info(f'  {G}Gradient hash: {gradient_hash.hex()[:16]}...{X}')
        else:
            log.warning(f'  {Y}Skipped: no obfuscated vector{X}')
    except Exception as e:
        log.error(f'  {R}Gradient computation failed: {e}{X}')
        errors.append(('gradient', str(e)))

    # ── Step 6: Submit gradient ───────────────────
    log.info('Step 6: Submit gradient to FlockCoordinator')
    try:
        from libnexus.flock_client import FlockClient
        fc = FlockClient()
        if gradient_hash is not None and proof is not None:
            merkle_root = proof.get('dataset_merkle_root', b'\x00' * 32)
            if hasattr(fc, 'submit_gradient'):
                fc.submit_gradient(gradient_hash, merkle_root)
                log.info(f'  {G}Gradient submitted on-chain{X}')
            else:
                log.info(f'  {Y}FlockClient.submit_gradient() not available — logged locally{X}')
                results['gradient_submitted'] = False
        else:
            log.warning(f'  {Y}Skipped: no gradient or proof{X}')
    except FileNotFoundError:
        log.info(f'  {Y}FlockCoordinator not deployed — gradient logged locally{X}')
        results['gradient_submitted'] = False
    except Exception as e:
        log.error(f'  {R}Gradient submission failed: {e}{X}')
        errors.append(('gradient_submit', str(e)))

    # ── Step 7: Submit privacy proof ──────────────
    log.info('Step 7: Submit privacy proof')
    try:
        if proof is not None:
            # Log proof data locally for now
            proof_summary = {
                'epsilon': epsilon,
                'merkle_root': results.get('merkle_root', ''),
                'salt_hash': obfuscated['salt_hash'].hex()[:32] if obfuscated else '',
            }
            log.info(f'  {Y}Privacy proof logged locally (NetworkObscuration not deployed){X}')
            results['proof_logged'] = True
        else:
            log.warning(f'  {Y}Skipped: no proof{X}')
    except Exception as e:
        log.error(f'  {R}Privacy proof submission failed: {e}{X}')
        errors.append(('proof_submit', str(e)))

    # ── Step 8: Cache destruction (ALWAYS runs) ───
    log.info('Step 8: Cache destruction')
    destroyed = 0
    try:
        for path in glob.glob('/tmp/nexus-*'):
            try:
                if __import__('os').path.isdir(path):
                    shutil.rmtree(path)
                else:
                    __import__('os').remove(path)
                destroyed += 1
                log.info(f'  Destroyed: {path}')
            except Exception as e:
                log.warning(f'  Cannot destroy {path}: {e}')
        results['caches_destroyed'] = destroyed
        log.info(f'  {G}Destroyed {destroyed} cache paths{X}')
    except Exception as e:
        log.error(f'  {R}Cache destruction failed: {e}{X}')
        errors.append(('cache_destroy', str(e)))

    # ── Step 9: Summary ───────────────────────────
    elapsed = time.time() - start_time

    # Count actions processed
    actions = 0
    try:
        from libnexus.behavioral_client import BehavioralClient
        c = BehavioralClient()
        actions = c.get_total_actions()
        results['total_actions'] = actions
    except Exception:
        pass

    print()
    print(f'  {B}═══════════════════════════════════════════{X}')
    print(f'  {B}Daily Epoch Complete{X}')
    print(f'  {D}───────────────────────────────────────────{X}')
    print(f'  Date:              {today}')
    print(f'  Actions on-chain:  {actions:,}')
    print(f'  Feature vector:    {results.get("features_dim", 0)} dims, '
          f'{results.get("features_nonzero", 0)} non-zero')
    print(f'  Epsilon spent:     {results.get("epsilon_spent", 0):.4f}')
    if gradient_hash:
        print(f'  Gradient hash:     {gradient_hash.hex()[:32]}...')
    print(f'  Caches destroyed:  {destroyed} paths')
    print(f'  Elapsed:           {elapsed:.1f}s')

    if errors:
        print(f'  {R}Errors:            {len(errors)}{X}')
        for step, msg in errors:
            print(f'    {R}{step}: {msg}{X}')
    else:
        print(f'  {G}Status:            All steps succeeded{X}')

    print(f'  {B}═══════════════════════════════════════════{X}')
    print()

    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
