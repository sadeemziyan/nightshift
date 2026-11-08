"""Runtime M3: a learned second opinion on top of the rule events, and early warnings the rules have not raised yet.

    events = detect_with_m3(ds, t)          # same events as detect_with_models, plus an "m3" field on each
    warns  = early_warnings(ds, t)          # facilities the classifier flags but the rules have not (yet)

The rules stay the authority: an event's category, onset and ongoing/resolved status never come from the classifier.
M3 adds the probability it assigns to each class and whether it agrees. Agreement raises the confidence a little;
disagreement lowers it and says so in the evidence, because "the two methods disagree, inspect both" is useful to an
operator. If the model file is missing or anything raises, the input events come back unchanged (CLAUDE.md hard rule 7).

This module never reads answer_key.json: it loads models/m3.joblib, which is trained offline by classifier.py.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from backend.engine.loader import Dataset

from . import baseline, enrich
from .features import window_features
from .m3_core import CLASSES, explain, predict_proba

log = logging.getLogger(__name__)
MODEL_PATH = Path(__file__).resolve().parents[3] / "models" / "m3.joblib"
_BUNDLE: dict = {}


def _bundle():
    """The saved classifier, or None if it is not there / cannot be read."""
    if "b" not in _BUNDLE:
        try:
            import joblib
            _BUNDLE["b"] = joblib.load(MODEL_PATH) if MODEL_PATH.exists() else None
        except Exception:
            log.exception("could not load %s; running without M3", MODEL_PATH)
            _BUNDLE["b"] = None
    return _BUNDLE["b"]


def _probs(ds: Dataset, models: dict, facility_id: str, t: int, bundle: dict, why: bool = False) -> dict | None:
    """{class: probability}; with why=True the result is (probabilities, factors) where factors explain the top call."""
    fr = baseline.residuals(ds, facility_id, t, models)
    x = window_features(fr, t, ds.interval_s)
    if x is None:
        return None
    p = predict_proba(bundle, [x])[0]
    probs = {c: round(float(v), 3) for c, v in zip(CLASSES, p)}
    if not why:
        return probs
    return probs, explain(bundle, x, max(probs, key=probs.get))


def detect_with_m3(ds: Dataset, t: int | None = None) -> list[dict]:
    t = ds.now_unix if t is None else int(t)
    events = enrich.detect_with_models(ds, t)
    bundle = _bundle()
    if bundle is None:
        return events
    try:
        models = enrich._models(ds, t)
    except Exception:
        log.exception("M1 fit failed inside blend; returning events without M3")
        return events
    out = []
    for ev in events:
        try:
            # score the facility at the end of the event if it is over, otherwise now
            at = min(t, ev["end_unix"]) if ev["end_unix"] is not None else t
            got = _probs(ds, models, ev["facility_id"], at, bundle, why=True)
            if got is None:
                out.append(ev)
                continue
            probs, factors = got
            call = max(probs, key=probs.get)
            agrees = call == ev["category"]
            e = dict(ev)
            e["m3"] = {"probs": probs, "call": call, "agrees": agrees, "factors": factors}
            if ev["status"] == "ongoing":
                if agrees:
                    e["confidence"] = round(min(0.99, max(ev["confidence"], probs[call])), 2)
                else:
                    e["confidence"] = round(min(ev["confidence"], 0.75), 2)
                    e["evidence"] = list(ev["evidence"]) + [
                        f"the learned classifier reads this as {call.replace('_', ' ')} ({probs[call]:.0%}); "
                        f"the rules say {ev['category'].replace('_', ' ')} - check both"]
                    log.info("M3 disagrees on %s: rules=%s m3=%s", ev["event_id"], ev["category"], call)
            out.append(e)
        except Exception:
            log.exception("M3 failed for %s; keeping the rule result", ev["event_id"])
            out.append(ev)
    return out


def early_warnings(ds: Dataset, t: int | None = None, threshold: float = 0.8, min_history_h: float = 24.0) -> list[dict]:
    """Facilities where M3 sees a problem with probability >= threshold but no rule event is ongoing for that category.

    Nothing is raised until the dataset has min_history_h hours of readings before t: with less, the learned normal is too
    thin to trust (in the full-week replay the false warnings all came from the first day and a half)."""
    t = ds.now_unix if t is None else int(t)
    bundle = _bundle()
    if bundle is None:
        return []
    if t - int(ds.telemetry["ts_unix"].min()) < min_history_h * 3600:
        return []
    try:
        models = enrich._models(ds, t)
        ongoing = {(e["facility_id"], e["category"]) for e in enrich.rules.detect(ds, t) if e["status"] == "ongoing"}
        out = []
        for fid in ds.facilities:
            if not models[fid].ready:
                continue
            got = _probs(ds, models, fid, t, bundle, why=True)
            if not got:
                continue
            probs, factors = got
            call = max(probs, key=probs.get)
            if call != "normal" and probs[call] >= threshold and (fid, call) not in ongoing:
                out.append({"facility_id": fid, "system_id": ds.facility(fid)["system_id"], "category": call,
                            "probability": probs[call], "probs": probs, "factors": factors, "source": "model", "t": t})
        return sorted(out, key=lambda w: -w["probability"])
    except Exception:
        log.exception("early_warnings failed; returning none")
        return []
