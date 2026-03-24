"""
NEXUS OS — Leave-One-Out Contribution Scorer

Scores contributors not on raw accuracy but on UNIQUE contribution to
the meta-model. Numerai-parallel: the question is not "was your model
good?" but "did your model add information the ensemble didn't already
have?"

Algorithm: federated averaging with leave-one-out evaluation. Remove
each contributor's gradient, re-aggregate, re-evaluate. The difference
is that contributor's unique marginal value.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

import numpy as np

log = logging.getLogger("nexus.contribution_scorer")

HISTORY_PATH = "/opt/nexus/logs/contribution_history.jsonl"
RST_BENCHMARK = 5000  # basis points — median expected contribution


class ContributionScorer:
    """
    Leave-one-out contribution scoring for federated learning epochs.

    Measures each contributor's unique marginal value to the meta-model
    by computing the performance delta when their gradient is removed.
    """

    def __init__(self, history_path=None):
        self._history_path = history_path or HISTORY_PATH

    # ── Core scoring ────────────────────────────────────────────────────────

    def score_epoch(self, epoch_gradients, validation_set):
        """
        Run leave-one-out scoring for a single epoch.

        Args:
            epoch_gradients: dict of {wallet: gradient_array}
                Each gradient is a numpy array (or list) representing the
                contributor's federated gradient update.
            validation_set: dict with:
                - features: np.array of shape (n_samples, n_features)
                - labels: np.array of shape (n_samples,)

        Returns:
            list of dicts sorted by score descending:
                [{wallet, unique_score, raw_delta, classification}, ...]
                unique_score is in basis points (0–10000)
        """
        if not epoch_gradients:
            return []

        wallets = list(epoch_gradients.keys())
        gradients = {w: np.array(g, dtype=np.float64) for w, g in epoch_gradients.items()}

        # Step 1: aggregate ALL gradients → full model weights
        full_model = self._federated_average(gradients)

        # Step 2: evaluate full model on validation set
        full_score = self._evaluate(full_model, validation_set)

        # Step 3: leave-one-out for each contributor
        raw_deltas = {}
        for wallet in wallets:
            remaining = {w: g for w, g in gradients.items() if w != wallet}

            if not remaining:
                # Solo contributor — their delta IS the full score
                raw_deltas[wallet] = full_score
                continue

            reduced_model = self._federated_average(remaining)
            reduced_score = self._evaluate(reduced_model, validation_set)
            raw_deltas[wallet] = full_score - reduced_score

        # Step 4: normalize to 0–10000 basis points
        scores = self._normalize_to_basis_points(raw_deltas)

        # Build result list
        results = []
        for wallet in wallets:
            score = scores[wallet]
            delta = raw_deltas[wallet]

            if delta > 0:
                classification = "positive"
            elif delta < -0.01:
                classification = "harmful"
            else:
                classification = "neutral"

            results.append({
                "wallet": wallet,
                "unique_score": score,
                "raw_delta": round(float(delta), 6),
                "classification": classification,
            })

        results.sort(key=lambda x: x["unique_score"], reverse=True)

        # Persist to history
        self._append_history(results)

        return results

    def _federated_average(self, gradients):
        """
        Aggregate gradients using simple federated averaging.
        Each contributor weighted equally.
        """
        arrays = list(gradients.values())
        return np.mean(arrays, axis=0)

    def _evaluate(self, model_weights, validation_set):
        """
        Evaluate model weights against validation set.

        Stub implementation: uses cosine similarity between model weights
        and a "target direction" derived from validation labels.
        Real implementation requires forward pass through the actual model
        architecture with proper loss computation.
        """
        features = np.array(validation_set["features"], dtype=np.float64)
        labels = np.array(validation_set["labels"], dtype=np.float64)

        # Stub: project features with model weights, measure correlation with labels
        if model_weights.shape[0] != features.shape[1]:
            # Dimension mismatch — truncate or pad
            dim = min(model_weights.shape[0], features.shape[1])
            predictions = features[:, :dim] @ model_weights[:dim]
        else:
            predictions = features @ model_weights

        # Normalize
        p_std = np.std(predictions)
        l_std = np.std(labels)
        if p_std < 1e-12 or l_std < 1e-12:
            return 0.0

        predictions_norm = (predictions - np.mean(predictions)) / p_std
        labels_norm = (labels - np.mean(labels)) / l_std

        # Pearson correlation as score
        correlation = float(np.mean(predictions_norm * labels_norm))
        return correlation

    def _normalize_to_basis_points(self, raw_deltas):
        """
        Map raw deltas to 0–10000 basis points.
        Highest delta → 10000, lowest → 0, linear interpolation.
        """
        if not raw_deltas:
            return {}

        values = list(raw_deltas.values())
        min_delta = min(values)
        max_delta = max(values)
        spread = max_delta - min_delta

        scores = {}
        for wallet, delta in raw_deltas.items():
            if spread < 1e-12:
                scores[wallet] = RST_BENCHMARK
            else:
                scores[wallet] = int(round((delta - min_delta) / spread * 10000))

        return scores

    # ── RST adjustment ──────────────────────────────────────────────────────

    def adjust_rst(self, scores, token_client=None):
        """
        Adjust RST (Reputation Score Token) based on contribution scores.

        Args:
            scores: list of dicts from score_epoch()
            token_client: object with earn_rst(wallet, amount) and
                         slash_rst(wallet, amount) methods.
                         If None, returns adjustments without executing.

        Returns:
            list of {wallet, action, amount} adjustments
        """
        adjustments = []

        for entry in scores:
            wallet = entry["wallet"]
            score = entry["unique_score"]

            if score > RST_BENCHMARK:
                amount = score - RST_BENCHMARK
                action = "earn"
                if token_client is not None:
                    token_client.earn_rst(wallet, amount)
            elif score < RST_BENCHMARK:
                amount = RST_BENCHMARK - score
                action = "slash"
                if token_client is not None:
                    token_client.slash_rst(wallet, amount)
            else:
                amount = 0
                action = "unchanged"

            adjustments.append({
                "wallet": wallet,
                "action": action,
                "amount": amount,
                "score": score,
            })

        return adjustments

    # ── Free rider detection ────────────────────────────────────────────────

    def identify_free_riders(self, scores):
        """
        Identify contributors with negative unique contribution.
        These nodes are submitting noise/random gradients and should be slashed.

        Args:
            scores: list of dicts from score_epoch()

        Returns:
            list of wallet addresses classified as harmful
        """
        return [
            entry["wallet"]
            for entry in scores
            if entry["classification"] == "harmful"
        ]

    # ── Contribution history ────────────────────────────────────────────────

    def get_contribution_history(self, wallet, epochs=30):
        """
        Retrieve trend of unique scores for a wallet over recent epochs.

        Args:
            wallet: contributor wallet address
            epochs: number of recent epochs to include

        Returns:
            list of {epoch_ts, unique_score, classification} dicts, chronological
        """
        if not os.path.exists(self._history_path):
            return []

        records = []
        try:
            with open(self._history_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("wallet") == wallet:
                        records.append(entry)
        except OSError:
            return []

        # Return most recent N
        records.sort(key=lambda x: x.get("timestamp", ""))
        return records[-epochs:]

    def _append_history(self, scores):
        """Append epoch scores to the history log."""
        ts = datetime.now(timezone.utc).isoformat()
        os.makedirs(os.path.dirname(self._history_path), exist_ok=True)
        try:
            with open(self._history_path, "a") as f:
                for entry in scores:
                    record = {
                        "timestamp": ts,
                        "wallet": entry["wallet"],
                        "unique_score": entry["unique_score"],
                        "raw_delta": entry["raw_delta"],
                        "classification": entry["classification"],
                    }
                    f.write(json.dumps(record) + "\n")
        except OSError as e:
            log.warning("Failed to write contribution history: %s", e)


# ── Main demo ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s  %(message)s")

    print("=== NEXUS Leave-One-Out Contribution Scorer Demo ===\n")

    scorer = ContributionScorer(history_path="/tmp/nexus_contribution_test.jsonl")

    # Simulate 5 contributors with gradients of dimension 16
    rng = np.random.RandomState(42)
    n_features = 16

    # True signal direction (what the model should learn)
    true_weights = rng.randn(n_features)
    true_weights = true_weights / np.linalg.norm(true_weights)

    # Contributors with varying quality
    contributors = {
        "0xAlice_HighQuality": true_weights + rng.randn(n_features) * 0.1,
        "0xBob_GoodQuality":   true_weights + rng.randn(n_features) * 0.3,
        "0xCarol_Average":     true_weights + rng.randn(n_features) * 0.6,
        "0xDave_NoiseSubmitter": rng.randn(n_features),  # pure noise
        "0xEve_Adversarial":   -true_weights + rng.randn(n_features) * 0.2,  # anti-signal
    }

    # Validation set: features + labels generated from true weights
    n_samples = 200
    features = rng.randn(n_samples, n_features)
    labels = features @ true_weights + rng.randn(n_samples) * 0.1

    validation_set = {"features": features, "labels": labels}

    # Run leave-one-out scoring
    scores = scorer.score_epoch(contributors, validation_set)

    # Print leaderboard
    print("--- Epoch Leaderboard ---")
    print(f"  {'Wallet':<30s} {'Score':>7s} {'Delta':>10s} {'Class':<10s}")
    print("  " + "-" * 60)
    for s in scores:
        print(f"  {s['wallet']:<30s} {s['unique_score']:>7d} {s['raw_delta']:>10.6f} {s['classification']:<10s}")

    # RST adjustments
    print(f"\n--- RST Adjustments (benchmark={RST_BENCHMARK}) ---")
    adjustments = scorer.adjust_rst(scores)
    for a in adjustments:
        symbol = "+" if a["action"] == "earn" else "-" if a["action"] == "slash" else "="
        print(f"  {a['wallet']:<30s} {symbol}{a['amount']:>5d} RST  ({a['action']})")

    # Free riders
    print("\n--- Free Rider Detection ---")
    free_riders = scorer.identify_free_riders(scores)
    if free_riders:
        for fr in free_riders:
            print(f"  FLAGGED: {fr}")
    else:
        print("  No free riders detected")

    # Contribution history
    print("\n--- Contribution History (0xAlice_HighQuality) ---")
    history = scorer.get_contribution_history("0xAlice_HighQuality", epochs=5)
    for h in history:
        print(f"  {h['timestamp']}  score={h['unique_score']:>7d}  {h['classification']}")

    print("\nDone.")
