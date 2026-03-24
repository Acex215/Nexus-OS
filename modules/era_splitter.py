"""
Era-splitting for time-series behavioral training data.

Prevents overfitting by ensuring models generalize across temporal eras
rather than memorizing specific time windows. Inspired by Numerai's
era-splitting methodology.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass
class Era:
    era_id: int
    start_epoch: int
    end_epoch: int
    data: np.ndarray  # rows of feature vectors


@dataclass
class CrossValidationResult:
    fold_scores: List[float]
    mean_score: float
    variance: float


class EraSplitter:

    def split_by_epoch(self, data: np.ndarray, era_length_epochs: int = 7) -> List[Era]:
        """Divide training data into eras of N epochs each.

        Each era is a contiguous block of time. The first column of data
        is assumed to be the epoch index.
        """
        if len(data) == 0:
            return []

        epochs = data[:, 0]
        min_epoch = int(epochs.min())
        max_epoch = int(epochs.max())

        eras = []
        era_id = 0
        for start in range(min_epoch, max_epoch + 1, era_length_epochs):
            end = start + era_length_epochs - 1
            mask = (epochs >= start) & (epochs <= end)
            era_data = data[mask]
            if len(era_data) > 0:
                eras.append(Era(
                    era_id=era_id,
                    start_epoch=start,
                    end_epoch=min(end, max_epoch),
                    data=era_data,
                ))
                era_id += 1

        return eras

    def create_train_test_split(
        self, eras: List[Era], test_ratio: float = 0.3
    ) -> Tuple[List[Era], List[Era]]:
        """Split eras into train/test sets.

        Test eras are always the FUTURE (latest) eras to prevent
        temporal data leakage. No random sampling.
        """
        if not eras:
            return [], []

        sorted_eras = sorted(eras, key=lambda e: e.start_epoch)
        split_idx = max(1, int(len(sorted_eras) * (1 - test_ratio)))
        return sorted_eras[:split_idx], sorted_eras[split_idx:]

    def cross_validate_eras(
        self, model: Any, eras: List[Era], fold_count: int = 5
    ) -> CrossValidationResult:
        """Walk-forward cross-validation across eras.

        Fold 1: train on eras 0..k, test on era k+1
        Fold 2: train on eras 0..k+1, test on era k+2
        ...

        The model must implement fit(X, y) and score(X, y).
        Data columns: first column = epoch, last column = target,
        middle columns = features.
        """
        sorted_eras = sorted(eras, key=lambda e: e.start_epoch)

        if len(sorted_eras) < 2:
            return CrossValidationResult(fold_scores=[], mean_score=0.0, variance=0.0)

        min_train_eras = max(1, len(sorted_eras) - fold_count - 1)
        fold_scores = []

        for test_idx in range(max(1, len(sorted_eras) - fold_count), len(sorted_eras)):
            train_data = np.vstack([e.data for e in sorted_eras[:test_idx]])
            test_data = sorted_eras[test_idx].data

            X_train, y_train = train_data[:, 1:-1], train_data[:, -1]
            X_test, y_test = test_data[:, 1:-1], test_data[:, -1]

            model.fit(X_train, y_train)
            score = model.score(X_test, y_test)
            fold_scores.append(score)

        mean_score = float(np.mean(fold_scores))
        variance = float(np.var(fold_scores))

        return CrossValidationResult(
            fold_scores=fold_scores,
            mean_score=mean_score,
            variance=variance,
        )

    def detect_overfitting(
        self, train_scores: List[float], test_scores: List[float]
    ) -> Dict[str, Any]:
        """Flag overfitting when train performance exceeds test by >20%.

        Returns dict with overfitting_detected, gap_percent, and recommendation.
        """
        if not train_scores or not test_scores:
            return {
                "overfitting_detected": False,
                "gap_percent": 0.0,
                "recommendation": "Insufficient data to assess overfitting.",
            }

        mean_train = float(np.mean(train_scores))
        mean_test = float(np.mean(test_scores))

        if mean_test == 0:
            gap_percent = 100.0 if mean_train > 0 else 0.0
        else:
            gap_percent = ((mean_train - mean_test) / abs(mean_test)) * 100.0

        overfitting = gap_percent > 20.0

        if overfitting:
            recommendation = (
                f"Train/test gap is {gap_percent:.1f}%. "
                "Reduce model complexity, increase regularization, "
                "or collect more diverse era data."
            )
        else:
            recommendation = f"Train/test gap is {gap_percent:.1f}%. Model generalizes adequately across eras."

        return {
            "overfitting_detected": overfitting,
            "gap_percent": round(gap_percent, 2),
            "recommendation": recommendation,
        }

    def get_era_statistics(self, eras: List[Era]) -> List[Dict[str, Any]]:
        """Return per-era statistics.

        Feature columns are all columns except the first (epoch) and last (target).
        """
        stats = []
        for era in sorted(eras, key=lambda e: e.start_epoch):
            features = era.data[:, 1:-1] if era.data.shape[1] > 2 else era.data[:, 1:]
            stats.append({
                "era_id": era.era_id,
                "start_epoch": era.start_epoch,
                "end_epoch": era.end_epoch,
                "sample_count": len(era.data),
                "feature_mean": float(np.mean(features)),
                "feature_std": float(np.std(features)),
            })
        return stats

    def should_submit_gradient(
        self, model: Any, data: np.ndarray, era_length_epochs: int = 7, min_folds: int = 3
    ) -> Tuple[bool, Dict[str, Any]]:
        """Integration point for federated pipeline.

        Before submitting a local gradient, split data by era and run
        cross-era validation. Only approve submission if the model
        generalizes (no overfitting detected).

        Returns (should_submit, diagnostics).
        """
        eras = self.split_by_epoch(data, era_length_epochs)

        if len(eras) < 2:
            return False, {"reason": "Not enough eras for validation", "era_count": len(eras)}

        train_eras, test_eras = self.create_train_test_split(eras, test_ratio=0.3)

        if not test_eras:
            return False, {"reason": "No test eras after split"}

        cv_result = self.cross_validate_eras(model, eras, fold_count=min_folds)

        # Compute train scores on training eras for overfitting check
        train_data = np.vstack([e.data for e in train_eras])
        X_train, y_train = train_data[:, 1:-1], train_data[:, -1]
        model.fit(X_train, y_train)
        train_score = model.score(X_train, y_train)

        overfit = self.detect_overfitting([train_score], cv_result.fold_scores)

        diagnostics = {
            "era_count": len(eras),
            "cv_mean_score": cv_result.mean_score,
            "cv_variance": cv_result.variance,
            "overfitting": overfit,
            "era_stats": self.get_era_statistics(eras),
        }

        return not overfit["overfitting_detected"], diagnostics
