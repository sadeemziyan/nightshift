"""Fault simulator: labelled leaks, wear and pump failures made from REAL healthy stretches of a dataset.

    ds_sim = inject(ds, facility_id, "pipeline_leak", onset_unix, severity=0.10, ramp_h=8, kappa=8)
    cases  = sample_cases(ds, n=400, rng=rng, systems=["S1", "S2"])
    rows   = training_rows(ds, models, cases, rng)         # features + label, ready for classifier.fit

Why it exists: we have only 23 real labelled events and we do not want to train on EOG's answer key. Here we know the
label for sure because we put the fault in ourselves, and the healthy data underneath is real, so M1/M2 produce
real-looking features. Nothing is written to disk and the loaded files are never changed (the injected copy lives in
memory and is flagged `simulated`). This module never reads answer_key.json: the healthy stretches come from the
sensor-only rule detector.

What each fault does to the readings (from what the sensors show during real events, see docs/sensors.md):
  pipeline_leak     receive flow and pipeline pressure fall; the pump itself looks normal
  pump_degradation  pump flow and discharge pressure fall, the pipeline follows the pump; pipeline pressure unchanged
  pump_failure      pump status 2, flow 0, pressures fall to the disposal level, the tank fills from the wells' inflow
The size, speed and pressure sensitivity of each fault are drawn from wide ranges (SimConfig), on purpose: a classifier
trained on one fixed shape would only learn that shape.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np

from backend.engine import detect as rules
from backend.engine.loader import Dataset

from . import baseline
from .features import window_features

KINDS = ("pipeline_leak", "pump_degradation", "pump_failure")
NORMAL = "normal"


@dataclass(frozen=True)
class SimConfig:
    """Simulation settings (ranges the simulator draws from). They describe faults, not any plant."""
    leak_loss: tuple = (0.03, 0.20)         # share of the pump's flow lost from the pipeline, at full size
    wear_loss: tuple = (0.04, 0.22)         # share of the pump's flow lost to wear, at full size
    leak_ramp_h: tuple = (1.0, 20.0)        # hours to reach full size
    wear_ramp_h: tuple = (8.0, 36.0)
    leak_kappa: tuple = (3.0, 14.0)         # psi of pipeline pressure lost per 1% of flow lost
    wear_kappa: tuple = (1.5, 7.0)          # psi of discharge pressure lost per 1% of pump flow lost
    pre_h: float = 6.0                      # healthy hours kept before each fault (negatives come from here)
    post_h: float = 12.0                    # hours after onset that decision times are drawn from
    burn_in_h: float = 6.0                  # ignore the first hours of a dataset (little history yet)
    margin_h: float = 6.0                   # stay this far from any real event the rules found


CFG = SimConfig()


@dataclass
class Case:
    facility_id: str
    kind: str
    onset_unix: int
    severity: float = 0.0
    ramp_h: float = 1.0
    kappa: float = 0.0


def is_simulated(ds: Dataset) -> bool:
    return bool(getattr(ds, "simulated", False))


def _log_uniform(rng, lo_hi) -> float:
    lo, hi = lo_hi
    return float(np.exp(rng.uniform(np.log(lo), np.log(hi))))


def healthy_spans(ds: Dataset, t: int | None = None, cfg: SimConfig = CFG) -> dict[str, list[tuple[int, int]]]:
    """Per facility, the time spans with no problem found by the sensor-only rule detector (plus a margin)."""
    t = ds.now_unix if t is None else int(t)
    events = rules.detect(ds, t)
    start = int(min(s.index[0] for s in ds._series.values() if len(s))) + int(cfg.burn_in_h * 3600)
    margin = int(cfg.margin_h * 3600)
    need = int((cfg.pre_h + cfg.post_h) * 3600)
    out: dict[str, list[tuple[int, int]]] = {}
    for fid in ds.facilities:
        busy = sorted((e["onset_unix"] - margin, (e["end_unix"] if e["end_unix"] is not None else t) + margin)
                      for e in events if e["facility_id"] == fid)
        free, cur = [], start
        for lo, hi in busy:
            if lo - cur >= need:
                free.append((cur, lo))
            cur = max(cur, hi)
        if t - cur >= need:
            free.append((cur, t))
        out[fid] = free
    return out


def inject(ds: Dataset, facility_id: str, kind: str, onset_unix: int, severity: float = 0.1,
           ramp_h: float = 8.0, kappa: float = 6.0) -> Dataset:
    """A copy of ds in which one fault starts at onset_unix. The original is not changed. Flagged `simulated`."""
    if kind not in KINDS:
        raise ValueError(f"unknown fault kind {kind!r}")
    fac = ds.facility(facility_id)
    pump, pipe, tank = fac["pump"]["id"], fac["pipeline"]["id"], fac["tank"]["id"]
    status = ds.series(pump, "status")
    idx = status.index
    t = idx.to_numpy().astype(float)
    running = status.to_numpy() == 1
    after = t >= onset_unix
    ramp = np.clip((t - onset_unix) / max(ramp_h * 3600.0, 1.0), 0.0, 1.0) * after
    series = dict(ds._series)

    def get(asset, metric):
        return ds.series(asset, metric).reindex(idx).astype(float).to_numpy().copy()

    def put(asset, metric, values):
        import pandas as pd
        series[(asset, metric)] = pd.Series(values, index=idx)

    if kind == "pipeline_leak":
        loss = severity * ramp
        put(pipe, "receive_flow_bpd", get(pipe, "receive_flow_bpd") * (1.0 - loss * running))
        put(pipe, "pressure_psi", get(pipe, "pressure_psi") - kappa * loss * 100.0 * running)
    elif kind == "pump_degradation":
        loss = severity * ramp
        put(pump, "flow_bpd", get(pump, "flow_bpd") * (1.0 - loss * running))
        put(pipe, "receive_flow_bpd", get(pipe, "receive_flow_bpd") * (1.0 - loss * running))
        put(pump, "discharge_psi", get(pump, "discharge_psi") - kappa * loss * 100.0 * running)
    else:  # pump_failure: from onset the pump reports a fault and the tank only fills
        disposal = fac.get("disposal_psi")
        pflow, pdis = get(pump, "flow_bpd"), get(pump, "discharge_psi")
        rflow, rpsi = get(pipe, "receive_flow_bpd"), get(pipe, "pressure_psi")
        level = get(tank, "level_pct")
        st = status.to_numpy().astype(float).copy()
        st[after] = 2.0
        pflow[after], rflow[after] = 0.0, 0.0
        if disposal is not None:
            pdis[after], rpsi[after] = disposal, disposal
        inflow = ds.series(facility_id, "inflow_bpd").reindex(idx).astype(float).to_numpy()
        if not np.isfinite(inflow).any():
            inflow = sum(ds.series(w, "water_bpd").reindex(idx).astype(float).to_numpy() for w in fac["wells"])
        cap = float(fac["tank"]["capacity_bbl"])
        step = np.nan_to_num(inflow, nan=0.0) * ds.interval_s / 86400.0 / cap * 100.0
        first = int(np.argmax(after))
        base = level[first - 1] if first > 0 else level[first]
        level[first:] = base + np.cumsum(step[first:])
        put(pump, "flow_bpd", pflow); put(pump, "discharge_psi", pdis)
        put(pipe, "receive_flow_bpd", rflow); put(pipe, "pressure_psi", rpsi)
        put(tank, "level_pct", level); put(pump, "status", st)
    sim = dataclasses.replace(ds, _series=series)
    sim.simulated = True
    return sim


def sample_cases(ds: Dataset, n: int, rng: np.random.Generator, systems: list[str] | None = None,
                 kinds=KINDS, spans: dict | None = None, cfg: SimConfig = CFG) -> list[Case]:
    """n random faults, kinds taken in turn so each has the same share. Onsets sit inside healthy spans."""
    spans = spans if spans is not None else healthy_spans(ds, cfg=cfg)
    facs = [f for f in ds.facilities if spans.get(f) and (systems is None or ds.facility(f)["system_id"] in systems)]
    cases: list[Case] = []
    tries = 0
    while len(cases) < n and facs and tries < 20 * n:
        tries += 1
        kind = kinds[len(cases) % len(kinds)]
        fid = facs[int(rng.integers(len(facs)))]
        pre, post = int(cfg.pre_h * 3600), int(cfg.post_h * 3600)
        lo, hi = spans[fid][int(rng.integers(len(spans[fid])))]
        if hi - lo < pre + post:
            continue
        onset = int(rng.uniform(lo + pre, hi - post))
        idx = ds.series(ds.facility(fid)["pump"]["id"], "status")
        pos = int(np.searchsorted(idx.index.to_numpy(), onset))
        if pos >= len(idx):
            continue
        if kind == "pump_failure" and idx.iloc[pos] != 1:     # a pump can only fail while it is running
            window = idx.iloc[pos:pos + 288]
            ok = window.index[window.to_numpy() == 1]
            if not len(ok):
                continue
            pos = int(idx.index.get_loc(ok[0]))
        onset = int(idx.index[pos])
        if kind == "pipeline_leak":
            cases.append(Case(fid, kind, onset, _log_uniform(rng, cfg.leak_loss), _log_uniform(rng, cfg.leak_ramp_h),
                              _log_uniform(rng, cfg.leak_kappa)))
        elif kind == "pump_degradation":
            cases.append(Case(fid, kind, onset, _log_uniform(rng, cfg.wear_loss), _log_uniform(rng, cfg.wear_ramp_h),
                              _log_uniform(rng, cfg.wear_kappa)))
        else:
            cases.append(Case(fid, kind, onset))
    return cases


def training_rows(ds: Dataset, models: dict, cases: list[Case], rng: np.random.Generator,
                  per_case: int = 4, normal_share: float = 0.5, spans: dict | None = None,
                  systems: list[str] | None = None, cfg: SimConfig = CFG) -> list[dict]:
    """Rows {"x": features, "y": label, "group": case id, "hours": hours since onset (None for normal), "facility"}.

    Per case, `per_case` decision times after onset (label = the fault) and 1 before onset (label = normal, a hard
    negative). Extra normal rows come from healthy stretches of the untouched data until normal is `normal_share`."""
    rows: list[dict] = []
    for gi, c in enumerate(cases):
        sim = inject(ds, c.facility_id, c.kind, c.onset_unix, c.severity, c.ramp_h, c.kappa)
        t_hi = c.onset_unix + int(cfg.post_h * 3600)
        fr = baseline.residuals(sim, c.facility_id, t_hi, models)
        if fr.empty:
            continue
        hi_h = cfg.post_h if c.kind != "pump_failure" else min(cfg.post_h, 6.0)
        for h in rng.uniform(0.25, hi_h, size=per_case):
            t = c.onset_unix + int(h * 3600)
            x = window_features(fr, t, ds.interval_s)
            if x:
                rows.append({"x": x, "y": c.kind, "group": gi, "hours": float(h), "facility": c.facility_id})
        t = c.onset_unix - int(rng.uniform(0.5, cfg.pre_h) * 3600)
        x = window_features(fr, t, ds.interval_s)
        if x:
            rows.append({"x": x, "y": NORMAL, "group": gi, "hours": None, "facility": c.facility_id})
    want = int(len(rows) * normal_share / max(1e-9, 1.0 - normal_share)) - sum(r["y"] == NORMAL for r in rows)
    spans = spans if spans is not None else healthy_spans(ds, cfg=cfg)
    facs = [f for f in ds.facilities if spans.get(f) and (systems is None or ds.facility(f)["system_id"] in systems)]
    clean: dict = {}
    for k in range(max(0, want)):
        if not facs:
            break
        fid = facs[int(rng.integers(len(facs)))]
        lo, hi = spans[fid][int(rng.integers(len(spans[fid])))]
        t = int(rng.uniform(lo + cfg.pre_h * 3600, hi))
        if fid not in clean:
            clean[fid] = baseline.residuals(ds, fid, ds.now_unix, models)
        x = window_features(clean[fid], t, ds.interval_s)
        if x:
            rows.append({"x": x, "y": NORMAL, "group": len(cases) + k, "hours": None, "facility": fid})
    return rows
