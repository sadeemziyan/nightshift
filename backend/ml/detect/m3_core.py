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


# ---------------------------------------------------------------- "why?": what-if explanations
SENSOR_LABELS = {"pflow": "pump flow", "pdis": "pump discharge pressure", "rflow": "receive flow", "rpsi": "pipeline pressure"}


def _group(feature: str) -> str | None:
    """Which sensor (or the pump state) a feature belongs to; None for features that are not evidence."""
    if feature in ("stall_share", "fault_share"):
        return "pump_state"
    for k in SENSOR_LABELS:
        if k in feature:
            return k
    return None


def _say(group: str, x: dict) -> str:
    if group == "pump_state":
        if x.get("fault_share", 0.0) > 0.5:
            return "pump reports a fault while the tank is above its start level"
        if x.get("stall_share", 0.0) > 0.5:
            return "pump is stopped although the tank is above its start level"
        return "pump state normal"
    z = max((x.get(f"{group}_z12", 0.0), x.get(f"{group}_z36", 0.0)), key=abs)
    label = SENSOR_LABELS[group]
    if abs(z) < 2.0:
        return f"{label} unchanged"
    return f"{label} {abs(z):.0f} healthy spreads {'below' if z < 0 else 'above'} its normal"


def explain(bundle: dict, x: dict, call: str, top: int = 3, min_impact: float = 0.05) -> list[dict]:
    """What-if explanation of a call: for each sensor, set its features to "normal" (zero) and see how far the probability of
    `call` drops. A big drop means that sensor is a main reason for the call. Needs no extra library and is model-agnostic.
    Returns [{"factor": plain English, "impact": drop in probability}] biggest first; [] when the call is "normal"."""
    if call == NORMAL:
        return []
    groups: dict[str, list[str]] = {}
    for f in x:
        g = _group(f)
        if g:
            groups.setdefault(g, []).append(f)
    rows = [dict(x)]
    for g, feats in groups.items():
        r = dict(x)
        for f in feats:
            r[f] = 0.0
        rows.append(r)
    p = predict_proba(bundle, rows)[:, CLASSES.index(call)]
    out = [{"factor": _say(g, x), "impact": round(float(p[0] - p[i + 1]), 3)} for i, g in enumerate(groups)]
    out = [o for o in out if o["impact"] >= min_impact]
    return sorted(out, key=lambda o: -o["impact"])[:top]
