"""Rules first, models on top: the learned layer that turns rule events into scored, explained alerts.

    events = detect_with_models(ds, t)

1. The rule-based detector (backend.engine.detect) always runs first. It is the fallback.
2. M1 (baseline.py) scores every reading against that equipment's learned normal.
3. M2 (drift.py) refines the onset time and gives a 0..1 score that grows as evidence builds.
4. The reason text names the signals that contribute most, in healthy spreads.
Each enriched event keeps the contract in docs/api.md and carries source "model+rules". If any model step
raises, that event (or the whole call) falls back to the rule result with source "rules" and never crashes
(CLAUDE.md hard rule 7).
"""
from __future__ import annotations

import logging
from collections import OrderedDict

import numpy as np

from backend.engine import detect as rules
from backend.engine.loader import Dataset, iso

from . import baseline, drift

log = logging.getLogger(__name__)
TAIL = 12            # readings used for "how it looks right now"
ONSET_MAX_EARLIER_S = 6 * 3600   # a refined onset may not be more than this before the rule onset
_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()


def _models(ds: Dataset, t: int) -> dict:
    key = (str(ds.folder), int(t))
    if key not in _CACHE:
        _CACHE[key] = baseline.fit(ds, t)
        while len(_CACHE) > 6:
            _CACHE.popitem(last=False)
    return _CACHE[key]


def _inside(df, ev: dict):
    """Rows inside the event: from its onset to its end (or to the end of the known data if ongoing)."""
    hi = df.index <= ev["end_unix"] if ev["end_unix"] is not None else np.ones(len(df), dtype=bool)
    return df[(df.index >= ev["onset_unix"]) & hi]


def _evidence_state(ev: dict, run, w: int = TAIL) -> dict:
    """Median M1 scores over the last readings inside the event (not after it was repaired)."""
    inside = _inside(run, ev)
    tail = inside.tail(w) if len(inside) else run.tail(w)
    return {c: float(tail[f"{c}_z"].median()) for c in baseline.SENSORS}


def _refine_onset(ev: dict, run) -> tuple[int, str]:
    """Return (onset_unix, method). Leaks use the CUSUM change point, wear uses the fitted ramp."""
    ts = run.index.to_numpy()
    if ev["category"] == "pipeline_leak":
        z = (-run["rpsi_z"]).to_numpy()
    else:
        z = (-run["pflow_z"]).to_numpy()
    s, alarm = drift.cusum(z)
    idx = np.where((s > drift.H_ALARM) & (ts >= ev["detected_unix"] - 6 * 3600))[0]
    if not len(idx):
        return ev["onset_unix"], "rules"
    a = int(idx[0])
    # fit the ramp only through the event itself, not through the recovered readings after a repair
    end_idx = int(np.searchsorted(ts, ev["end_unix"])) if ev["end_unix"] is not None else None
    est = drift.estimate_onset(ts, z, a, end_idx=end_idx)
    onset = est["ramp"] if (ev["category"] == "pump_degradation" and est["ramp"] is not None) else est["cusum"]
    method = "ramp" if (onset == est["ramp"] and est["ramp"] is not None) else "cusum"
    if not (ev["onset_unix"] - ONSET_MAX_EARLIER_S <= onset <= ev["detected_unix"]):
        return ev["onset_unix"], "rules"
    return int(onset), method


def _unchanged(z: float) -> str:
    return "unchanged" if abs(z) < 2.0 else f"also off (z={z:+.1f})"


def _reason(ds, fb, ev, st, hours) -> str:
    on = fb.normal_on
    if ev["category"] == "pipeline_leak":
        drop = max(0.0, -st["rpsi"] * on["rpsi"][1])
        short = max(0.0, -st["rflow"] * fb.rflow_spread) / max(on["pflow"][0], 1e-9) * 100.0
        return (f"pipeline pressure {drop:.0f} psi below its learned normal (z={st['rpsi']:+.1f}) for {hours:.1f} h; "
                f"receive flow {short:.1f}% short of what the pump sends (z={st['rflow']:+.1f}); "
                f"pump output {_unchanged(st['pflow'])}")
    if ev["category"] == "pump_degradation":
        pct = max(0.0, -st["pflow"] * on["pflow"][1] / max(on["pflow"][0], 1e-9) * 100.0)
        dpsi = max(0.0, -st["pdis"] * on["pdis"][1])
        return (f"pump output {pct:.1f}% below its learned normal (z={st['pflow']:+.1f}) for {hours:.1f} h; "
                f"discharge pressure {dpsi:.0f} psi low (z={st['pdis']:+.1f}); pipeline pressure {_unchanged(st['rpsi'])}")
    flow_norm = on["pflow"][0]
    return (f"pump flow {max(0.0, flow_norm + st['pflow'] * on['pflow'][1]):.0f} bpd against a learned normal of "
            f"{flow_norm:.0f} bpd (z={st['pflow']:+.0f}) while the tank is above its start level; "
            f"discharge pressure has fallen to the disposal level (z={st['pdis']:+.0f})")


def _enrich_one(ds, models, frames, ev, t) -> dict:
    fid = ev["facility_id"]
    fb = models[fid]
    if not fb.ready:
        return ev
    fr = frames.setdefault(fid, baseline.residuals(ds, fid, t, models))
    run = fr[fr["status"] == 1]
    out = dict(ev)
    if ev["category"] == "pump_failure":
        win = _inside(fr, ev)
        st = {c: float(win[f"{c}_z"].tail(TAIL).median()) for c in baseline.SENSORS}
        peak = float((-win["pflow_z"]).max()) if len(win) else 0.0
        score = drift.drift_score(peak)
        hours = (t - ev["onset_unix"]) / 3600.0
    else:
        onset, method = _refine_onset(ev, run)
        out["onset_unix"], out["onset_ts"] = onset, iso(onset)
        out["event_id"] = f"{ev['asset_id']}@{onset}"
        sub = {**ev, "onset_unix": onset}
        st = _evidence_state(sub, run)
        z = (-run["rpsi_z"] if ev["category"] == "pipeline_leak" else -run["pflow_z"]).to_numpy()
        s, _ = drift.cusum(z)
        in_event = (run.index >= onset) & ((run.index <= ev["end_unix"]) if ev["end_unix"] is not None else True)
        score = drift.drift_score(float(s[in_event].max()) if in_event.any() else 0.0)
        hours = int(in_event.sum()) * ds.interval_s / 3600.0
    out["score"] = round(score, 2)
    out["confidence"] = round(min(0.99, max(ev["confidence"], 0.5 + 0.49 * score)), 2)
    out["evidence"] = [_reason(ds, fb, ev, st, hours)] + list(ev["evidence"])
    out["source"] = "model+rules"
    return out


def detect_with_models(ds: Dataset, t: int | None = None) -> list[dict]:
    t = ds.now_unix if t is None else int(t)
    events = rules.detect(ds, t)
    try:
        models = _models(ds, t)
    except Exception:
        log.exception("M1 fit failed; returning rule-based results")
        return events
    frames: dict = {}
    out = []
    for ev in events:
        try:
            out.append(_enrich_one(ds, models, frames, ev, t))
        except Exception:
            log.exception("model enrichment failed for %s; keeping the rule result", ev["event_id"])
            out.append(ev)
    return sorted(out, key=lambda e: (e["onset_unix"], e["asset_id"]))
