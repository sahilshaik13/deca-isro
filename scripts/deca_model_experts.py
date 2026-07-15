#!/usr/bin/env python3
"""DECA advanced heads — cluster manifold layer + mixture-of-experts.

These are *candidate* fault-classifier heads for the School Exam. They plug into
the exact same inference path (``predict_weighted_multiclass``) because each
exposes ``predict_proba`` and ``classes_`` just like an sklearn Pipeline. The
promotion gate (fresh blind paper) remains the only judge, so a head is only
promoted when it genuinely beats the baseline — nothing here fabricates data.

Components
----------
ClusterAugment
    Unsupervised KMeans "clusters" layer. Appends centroid distances + soft
    memberships to the feature matrix so the booster can reason about which
    behavioural regime a window belongs to (healthy plateau vs stressed edge).

MixtureOfExperts
    A generalist multiclass booster + one one-vs-rest *specialist* booster per
    fault class, blended by a logistic "gating" meta-learner trained on
    out-of-fold predictions (a stacked / "deep thinking" combiner). Each expert
    can specialise on its fault's fingerprint without the majority class
    drowning it, and the gate learns when to trust which expert.
"""
from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin, clone
from sklearn.cluster import KMeans
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.preprocessing import StandardScaler


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / np.clip(e.sum(axis=1, keepdims=True), 1e-12, None)


class ClusterAugment(BaseEstimator, TransformerMixin):
    """Append KMeans centroid distances + soft memberships to the features.

    Fits on whatever rows it sees (post-impute). Distances give a smooth
    manifold embedding; softmax(-dist) gives a soft cluster assignment. Both are
    concatenated to the original columns, so downstream trees keep every raw
    signal *plus* the regime context.
    """

    def __init__(self, n_clusters: int = 8, random_state: int = 42, enabled: bool = True):
        self.n_clusters = n_clusters
        self.random_state = random_state
        self.enabled = enabled

    def fit(self, X, y=None):
        X = np.nan_to_num(np.asarray(X, dtype=np.float64))
        if not self.enabled:
            return self
        k = int(min(self.n_clusters, max(2, X.shape[0] // 50)))
        self.k_ = k
        self.scaler_ = StandardScaler().fit(X)
        self.km_ = KMeans(n_clusters=k, n_init=10, random_state=self.random_state)
        self.km_.fit(self.scaler_.transform(X))
        return self

    def transform(self, X):
        X = np.nan_to_num(np.asarray(X, dtype=np.float64))
        if not self.enabled:
            return X
        dist = self.km_.transform(self.scaler_.transform(X))  # (n, k)
        member = _softmax(-dist)
        return np.hstack([X, dist, member])


def _model_classes(model) -> list[int]:
    """Classes for a Pipeline (delegates to final step) or a MoE head."""
    return list(model.classes_)


class MixtureOfExperts(BaseEstimator):
    """Generalist booster + per-fault specialists, blended by a logistic gate.

    Parameters
    ----------
    base_factory : callable -> Pipeline
        Builds the generalist multiclass head (final step named ``xgb``).
    expert_factory : callable -> Pipeline
        Builds a binary one-vs-rest specialist head (final step named ``xgb``).
    expert_class_ids : list[int]
        Fault class ids that get a dedicated expert (usually the rare faults).
    random_state : int
    n_splits : int
        CV folds for the out-of-fold stack that trains the gate.
    """

    def __init__(
        self,
        base_factory,
        expert_factory,
        expert_class_ids,
        *,
        random_state: int = 42,
        n_splits: int = 3,
    ):
        self.base_factory = base_factory
        self.expert_factory = expert_factory
        self.expert_class_ids = list(expert_class_ids)
        self.random_state = random_state
        self.n_splits = n_splits

    # -- helpers ---------------------------------------------------------
    def _cv(self, y):
        y = np.asarray(y, dtype=int)
        _, counts = np.unique(y, return_counts=True)
        n_splits = int(max(2, min(self.n_splits, counts.min())))
        return StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=self.random_state)

    def _stack(self, X) -> np.ndarray:
        cols = [self.base_.predict_proba(X)]
        for cid in self.expert_class_ids:
            cols.append(self.experts_[cid].predict_proba(X)[:, 1:2])
        return np.hstack(cols)

    # -- sklearn API -----------------------------------------------------
    def fit(self, X, y, sample_weight=None):
        y = np.asarray(y, dtype=int)
        self.classes_ = np.array(sorted(np.unique(y)))
        cv = self._cv(y)

        # Out-of-fold meta features (leak-free): generalist proba + expert proba.
        base_oof = cross_val_predict(
            clone(self.base_factory()), X, y, cv=cv, method="predict_proba"
        )
        stack_cols = [base_oof]
        present = [c for c in self.expert_class_ids if int(np.sum(y == c)) >= cv.get_n_splits()]
        for cid in present:
            yb = (y == cid).astype(int)
            oof = cross_val_predict(
                clone(self.expert_factory()), X, yb, cv=cv, method="predict_proba"
            )
            stack_cols.append(oof[:, 1:2])
        self.expert_class_ids = present
        Z = np.hstack(stack_cols)

        # Final full-data fits (with weights) used at inference.
        self.base_ = self.base_factory()
        self.base_.fit(X, y, xgb__sample_weight=sample_weight)
        self.experts_ = {}
        for cid in present:
            yb = (y == cid).astype(int)
            spw = _binary_balance_weights(yb, sample_weight)
            self.experts_[cid] = self.expert_factory()
            self.experts_[cid].fit(X, yb, xgb__sample_weight=spw)

        self.meta_ = LogisticRegression(
            max_iter=2000, C=1.0, class_weight="balanced", multi_class="multinomial"
        )
        self.meta_.fit(Z, y)
        self._meta_reorder_ = [list(self.meta_.classes_).index(c) for c in self.classes_]
        return self

    def predict_proba(self, X):
        Z = self._stack(X)
        P = self.meta_.predict_proba(Z)
        return P[:, self._meta_reorder_]

    def predict(self, X):
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]


def _binary_balance_weights(y_bin: np.ndarray, base_weight=None) -> np.ndarray:
    """Inverse-frequency weights for a one-vs-rest expert, times any base weight."""
    y_bin = np.asarray(y_bin, dtype=int)
    n = len(y_bin)
    pos = max(1, int(y_bin.sum()))
    neg = max(1, n - pos)
    w = np.where(y_bin == 1, n / (2.0 * pos), n / (2.0 * neg)).astype(np.float64)
    if base_weight is not None:
        w = w * np.asarray(base_weight, dtype=np.float64)
    return w
