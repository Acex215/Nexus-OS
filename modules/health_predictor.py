"""
NEXUS OS — On-Device Health Risk Predictor

Runs LOCAL inference to match a user's behavioral feature vector against
known risk clusters from the global meta-model. The meta-model (downloaded
from IPFS) knows which clusters correlate with health risks. The matching
— which user falls into which cluster — happens ONLY on the user's device.

PRIVACY INVARIANT:
    The network knows  "cluster 7A correlates with elevated risk."
    The network does NOT know  "user X matched cluster 7A."
    That inference happens ONLY on this device.
"""

import hashlib
import json
import logging
import os
import random
import time
from datetime import datetime, timezone

import numpy as np

log = logging.getLogger("nexus.health_predictor")

CONSENT_MANAGER_ADDRESS = "0x0000000000000000000000000000000000000000"
CONSENT_MANAGER_ABI_PATH = "/opt/nexus/contracts/source/ConsentManager_sol_ConsentManager.abi"
PRIVATE_ALERTS_PATH = "/opt/nexus/logs/private_health_alerts.json"

# Known risk clusters (stub — real clusters come from the trained meta-model).
# Each cluster is a centroid vector + metadata.
STUB_RISK_CLUSTERS = {
    "7A": {
        "centroid": None,  # populated on model load
        "risk_level": "high",
        "risk_category": "sleep_disruption",
        "recommendation": "Irregular sleep patterns detected. Consider establishing a consistent sleep schedule.",
    },
    "3B": {
        "centroid": None,
        "risk_level": "medium",
        "risk_category": "stress",
        "recommendation": "Elevated stress indicators. Short breaks and breathing exercises may help.",
    },
    "5C": {
        "centroid": None,
        "risk_level": "medium",
        "risk_category": "sedentary",
        "recommendation": "Low activity levels detected. Even brief walks can improve circulation.",
    },
    "2D": {
        "centroid": None,
        "risk_level": "low",
        "risk_category": "hydration",
        "recommendation": "Mild dehydration pattern. Increase water intake during afternoon hours.",
    },
    "9E": {
        "centroid": None,
        "risk_level": "high",
        "risk_category": "cardiac_irregularity",
        "recommendation": "Unusual heart-rate variability pattern. Consult a healthcare provider.",
    },
}

SIMILARITY_THRESHOLDS = {
    "high": 0.80,
    "medium": 0.70,
    "low": 0.60,
}


class HealthPredictor:
    """
    On-device health risk predictor.

    Loads a global meta-model (cluster centroids) from IPFS and runs
    cosine-similarity matching locally. Results never leave the device.
    """

    def __init__(self, rpc_url="http://localhost:8545",
                 consent_address=CONSENT_MANAGER_ADDRESS):
        self._model_loaded = False
        self._clusters = {}
        self._feature_dim = None
        self._rpc_url = rpc_url
        self._consent_address = consent_address
        self._consent_contract = None
        self._w3 = None

    # ── Model loading ───────────────────────────────────────────────────────

    def load_model(self, model_path):
        """
        Load the global meta-model (risk cluster centroids) from a local
        file previously downloaded from IPFS.

        Expected format: JSON with {"clusters": {"id": {"centroid": [...], ...}}}
        Falls back to stub clusters with random centroids if file not found.
        """
        if os.path.exists(model_path):
            try:
                with open(model_path, "r") as f:
                    data = json.load(f)
                clusters = data.get("clusters", {})
                for cid, info in clusters.items():
                    self._clusters[cid] = {
                        "centroid": np.array(info["centroid"], dtype=np.float64),
                        "risk_level": info.get("risk_level", "medium"),
                        "risk_category": info.get("risk_category", "unknown"),
                        "recommendation": info.get("recommendation", "No specific recommendation."),
                    }
                if self._clusters:
                    self._feature_dim = len(next(iter(self._clusters.values()))["centroid"])
                self._model_loaded = True
                log.info("Loaded %d risk clusters from %s (dim=%d)",
                         len(self._clusters), model_path, self._feature_dim)
                return
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                log.warning("Failed to load model from %s: %s — using stubs", model_path, e)

        # Stub: generate random centroids for demo purposes
        self._feature_dim = 32
        rng = np.random.RandomState(42)
        for cid, info in STUB_RISK_CLUSTERS.items():
            centroid = rng.randn(self._feature_dim)
            centroid = centroid / np.linalg.norm(centroid)
            self._clusters[cid] = {
                "centroid": centroid,
                "risk_level": info["risk_level"],
                "risk_category": info["risk_category"],
                "recommendation": info["recommendation"],
            }
        self._model_loaded = True
        log.info("Loaded %d stub risk clusters (dim=%d)", len(self._clusters), self._feature_dim)

    # ── Risk prediction ─────────────────────────────────────────────────────

    def predict_risk(self, local_feature_vector):
        """
        Compare feature vector against known risk clusters using cosine
        similarity. All computation is local — results never leave the device.

        Args:
            local_feature_vector: list or np.array of floats (same dim as model)

        Returns:
            dict: {cluster_id, risk_level, risk_category, confidence, recommendation}
                  or {cluster_id: None, risk_level: "low", ...} if no match
        """
        if not self._model_loaded:
            raise RuntimeError("Model not loaded — call load_model() first")

        vec = np.array(local_feature_vector, dtype=np.float64)
        if vec.shape[0] != self._feature_dim:
            raise ValueError(
                f"Feature vector dimension {vec.shape[0]} != model dimension {self._feature_dim}"
            )

        vec_norm = np.linalg.norm(vec)
        if vec_norm < 1e-12:
            return {
                "cluster_id": None,
                "risk_level": "low",
                "risk_category": "none",
                "confidence": 0.0,
                "recommendation": "Insufficient data for risk assessment.",
            }

        vec_unit = vec / vec_norm

        best_sim = -1.0
        best_cluster = None

        for cid, info in self._clusters.items():
            centroid = info["centroid"]
            c_norm = np.linalg.norm(centroid)
            if c_norm < 1e-12:
                continue
            sim = float(np.dot(vec_unit, centroid / c_norm))
            if sim > best_sim:
                best_sim = sim
                best_cluster = cid

        if best_cluster is None:
            return {
                "cluster_id": None,
                "risk_level": "low",
                "risk_category": "none",
                "confidence": 0.0,
                "recommendation": "No matching risk cluster.",
            }

        info = self._clusters[best_cluster]
        threshold = SIMILARITY_THRESHOLDS.get(info["risk_level"], 0.70)

        if best_sim >= threshold:
            return {
                "cluster_id": best_cluster,
                "risk_level": info["risk_level"],
                "risk_category": info["risk_category"],
                "confidence": round(best_sim, 4),
                "recommendation": info["recommendation"],
            }

        return {
            "cluster_id": None,
            "risk_level": "low",
            "risk_category": "none",
            "confidence": round(best_sim, 4),
            "recommendation": "Feature vector does not strongly match any known risk cluster.",
        }

    # ── Consent verification ────────────────────────────────────────────────

    def check_consent(self, data_category="health_metrics"):
        """
        Query the on-chain ConsentManager to verify the patient has active
        consent before generating any health-related output.

        Returns True if:
          - ConsentManager is deployed and patient has active consent, OR
          - ConsentManager is not deployed (consent check skipped with warning)
        Returns False if consent is explicitly not granted.
        """
        try:
            from web3 import Web3
            from web3.middleware import ExtraDataToPOAMiddleware
        except ImportError:
            log.warning("web3 not available — skipping on-chain consent check")
            return True

        try:
            if self._w3 is None:
                self._w3 = Web3(Web3.HTTPProvider(self._rpc_url))
                self._w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

            if not self._w3.is_connected():
                log.warning("Cannot connect to RPC at %s — skipping consent check", self._rpc_url)
                return True

            if self._consent_address == "0x0000000000000000000000000000000000000000":
                log.warning("ConsentManager not deployed — skipping consent check")
                return True

            if self._consent_contract is None:
                if os.path.exists(CONSENT_MANAGER_ABI_PATH):
                    with open(CONSENT_MANAGER_ABI_PATH, "r") as f:
                        abi = json.load(f)
                else:
                    log.warning("ConsentManager ABI not found — skipping consent check")
                    return True

                addr = Web3.to_checksum_address(self._consent_address)
                self._consent_contract = self._w3.eth.contract(address=addr, abi=abi)

            # Check consent for the default account (the local user's wallet)
            accounts = self._w3.eth.accounts
            if not accounts:
                log.warning("No local accounts — skipping consent check")
                return True

            patient = accounts[0]
            has_consent = self._consent_contract.functions.hasActiveConsent(
                patient, data_category
            ).call()

            if not has_consent:
                log.info("No active consent for %s category '%s'", patient, data_category)
            return has_consent

        except Exception as e:
            log.warning("Consent check failed: %s — defaulting to denied", e)
            return False

    # ── Private alert generation ────────────────────────────────────────────

    def generate_private_alert(self, risk_assessment):
        """
        Create a LOCAL notification for a health risk assessment.
        This is NEVER transmitted to the network.

        Writes to /opt/nexus/logs/private_health_alerts.json (local only).
        """
        alert = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cluster_id": risk_assessment.get("cluster_id"),
            "risk_level": risk_assessment.get("risk_level"),
            "risk_category": risk_assessment.get("risk_category"),
            "confidence": risk_assessment.get("confidence"),
            "recommendation": risk_assessment.get("recommendation"),
            "checksum": hashlib.sha256(
                json.dumps(risk_assessment, sort_keys=True).encode()
            ).hexdigest(),
        }

        # Append to local-only alert log
        alerts = []
        if os.path.exists(PRIVATE_ALERTS_PATH):
            try:
                with open(PRIVATE_ALERTS_PATH, "r") as f:
                    alerts = json.load(f)
            except (json.JSONDecodeError, OSError):
                alerts = []

        alerts.append(alert)

        os.makedirs(os.path.dirname(PRIVATE_ALERTS_PATH), exist_ok=True)
        with open(PRIVATE_ALERTS_PATH, "w") as f:
            json.dump(alerts, f, indent=2)

        print(f"\u26a0\ufe0f  Health insight (private, on-device only): {alert['recommendation']}")
        log.info("Private alert generated: %s [%s] confidence=%.4f",
                 alert["risk_category"], alert["risk_level"], alert["confidence"])

        return alert


# ── Main demo ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s  %(message)s")

    print("=== NEXUS On-Device Health Risk Predictor Demo ===")
    print("PRIVACY: all inference runs locally. Results never leave this device.\n")

    predictor = HealthPredictor()

    # Load model (will use stubs since no real model exists yet)
    predictor.load_model("/opt/nexus/models/health_meta_model.json")

    # Check consent (will warn that ConsentManager is not deployed)
    consent = predictor.check_consent("health_metrics")
    print(f"Consent check: {'granted' if consent else 'DENIED'}\n")

    # Generate a fake feature vector that closely matches cluster 7A
    # (sleep_disruption). We retrieve 7A's centroid and add small noise.
    cluster_7a = predictor._clusters["7A"]["centroid"]
    rng = np.random.RandomState(99)
    fake_vector = cluster_7a + rng.randn(32) * 0.1
    fake_vector = fake_vector / np.linalg.norm(fake_vector)

    print("--- Prediction: vector near cluster 7A (sleep_disruption) ---")
    result = predictor.predict_risk(fake_vector)
    print(f"  Cluster:    {result['cluster_id']}")
    print(f"  Risk level: {result['risk_level']}")
    print(f"  Category:   {result['risk_category']}")
    print(f"  Confidence: {result['confidence']}")
    print()

    # Generate private alert
    predictor.generate_private_alert(result)

    # Test with a random vector (likely no strong match)
    print("\n--- Prediction: random vector (no strong cluster match) ---")
    random_vec = rng.randn(32)
    random_vec = random_vec / np.linalg.norm(random_vec)
    result2 = predictor.predict_risk(random_vec)
    print(f"  Cluster:    {result2['cluster_id']}")
    print(f"  Risk level: {result2['risk_level']}")
    print(f"  Confidence: {result2['confidence']}")

    # Test with zero vector
    print("\n--- Prediction: zero vector (insufficient data) ---")
    result3 = predictor.predict_risk(np.zeros(32))
    print(f"  Risk level: {result3['risk_level']}")
    print(f"  Message:    {result3['recommendation']}")

    print("\nDone. Alert log: " + PRIVATE_ALERTS_PATH)
