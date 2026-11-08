"""M3 prediction helpers shared by the offline trainer (classifier.py) and the app (blend.py).

Nothing in here touches answer_key.json or training data: it only turns a saved bundle plus feature dicts into class
probabilities, so the app can use the classifier without importing the training script.
"""
from __future__ import annotations

import numpy as np

from .features import as_matrix

NORMAL = "normal"
CLASSES = [NORMAL, "pipeline_leak", "pump_degradation", "pump_failure"]


def to_class_order(p: np.ndarray, classes) -> np.ndarray:
    out = np.zeros((len(p), len(CLASSES)))
    for j, c in enumerate(classes):
        out[:, CLASSES.index(str(c))] = p[:, j]
    return out


def sharpen(p: np.ndarray, temperature: float) -> np.ndarray:
    """Temperature scaling: T > 1 softens over-confident probabilities, T < 1 sharpens them."""
    q = np.clip(p, 1e-9, 1.0) ** (1.0 / temperature)
    return q / q.sum(axis=1, keepdims=True)


def predict_proba(bundle: dict, rows: list[dict]) -> np.ndarray:
    """Probabilities in CLASSES order, shape (n, 4). rows: feature dicts (or {"x": ...} dicts)."""
    feats = [r["x"] if "x" in r else r for r in rows]
    p = to_class_order(bundle["model"].predict_proba(as_matrix(feats)), bundle["classes"])
    return sharpen(p, bundle.get("temperature", 1.0))
