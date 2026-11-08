"""Phase 3 checks: fault simulator, M3 features, classifier, evaluation output.

Run from the repo root:   python -m backend.ml.detect.tests.test_m3
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from backend.engine.loader import load
from backend.ml.detect import baseline, classifier, evaluate, simulate
from backend.ml.detect.features import FEATURES, window_features

ROOT = Path(__file__).resolve().parents[4]
FULL = ROOT / "data" / "full_week"
_STATE: dict = {}


def world():
    if not _STATE:
        ds = load(str(FULL))
        _STATE.update(ds=ds, models=baseline.fit(ds), spans=simulate.healthy_spans(ds))
    return _STATE["ds"], _STATE["models"], _STATE["spans"]


def one_case(kind):
    ds, _, spans = world()
    rng = np.random.default_rng(1)
    return next(c for c in simulate.sample_cases(ds, 6, rng, spans=spans) if c.kind == kind)


def test_injection_leaves_the_original_untouched_and_is_flagged():
    ds, _, _ = world()
    c = one_case("pipeline_leak")
    pipe = ds.facility(c.facility_id)["pipeline"]["id"]
    before = ds.series(pipe, "pressure_psi").copy()
    sim = simulate.inject(ds, c.facility_id, c.kind, c.onset_unix, 0.2, 2.0, 8.0)
    assert simulate.is_simulated(sim) and not simulate.is_simulated(ds)
    assert ds.series(pipe, "pressure_psi").equals(before)
    assert not sim.series(pipe, "pressure_psi").equals(before)


def test_each_fault_moves_the_expected_sensors():
    ds, models, _ = world()
    for kind, down, flat in (("pipeline_leak", "rpsi", "pflow"), ("pump_degradation", "pflow", "rpsi")):
        c = one_case(kind)
        sim = simulate.inject(ds, c.facility_id, kind, c.onset_unix, 0.2, 2.0, 8.0)
        fr = baseline.residuals(sim, c.facility_id, c.onset_unix + 12 * 3600, models)
        x = window_features(fr, c.onset_unix + 12 * 3600, ds.interval_s)
        assert x[f"{down}_z36"] < -3, (kind, x)
        assert abs(x[f"{flat}_z36"]) < 3, (kind, x)
    c = one_case("pump_failure")
    sim = simulate.inject(ds, c.facility_id, "pump_failure", c.onset_unix)
    fr = baseline.residuals(sim, c.facility_id, c.onset_unix + 2 * 3600, models)
    x = window_features(fr, c.onset_unix + 2 * 3600, ds.interval_s)
    assert x["fault_share"] == 1.0 and x["stall_share"] == 1.0
    level = sim.series(ds.facility(c.facility_id)["tank"]["id"], "level_pct")
    after = level[level.index >= c.onset_unix]
    assert after.iloc[-1] > after.iloc[0], "the tank must fill after a simulated pump failure"


def test_features_are_finite_and_complete():
    ds, models, _ = world()
    fid = next(iter(ds.facilities))
    fr = baseline.residuals(ds, fid, ds.now_unix, models)
    x = window_features(fr, ds.now_unix, ds.interval_s)
    assert set(x) == set(FEATURES)
    assert all(np.isfinite(v) for v in x.values())


def test_simulated_cases_stay_clear_of_real_problems():
    ds, _, spans = world()
    from backend.engine.detect import detect
    events = detect(ds)
    for c in simulate.sample_cases(ds, 30, np.random.default_rng(2), spans=spans):
        for e in events:
            if e["facility_id"] == c.facility_id:
                end = e["end_unix"] if e["end_unix"] is not None else ds.now_unix
                assert not (e["onset_unix"] - 3600 <= c.onset_unix <= end + 3600), (c, e["event_id"])


def test_group_folds_keep_every_class_in_training():
    """Regression: an unshuffled group split put each fault type in its own fold, so training never saw it."""
    groups = np.array([i // 5 for i in range(300)])
    kinds = np.array([(g % 3) for g in groups])
    for tr, te in classifier._group_folds(groups, 3, 0):
        assert set(kinds[tr]) == {0, 1, 2}
        assert not set(groups[tr]) & set(groups[te])


def test_classifier_trains_calibrates_and_calls_a_failure():
    ds, models, spans = world()
    rng = np.random.default_rng(3)
    rows = simulate.training_rows(ds, models, simulate.sample_cases(ds, 90, rng, spans=spans), rng, spans=spans)
    bundle = classifier.fit_classifier(rows)
    assert bundle["calibrated"] and 0.3 <= bundle["temperature"] <= 10
    P = classifier.predict_proba(bundle, rows)
    assert P.shape == (len(rows), 4) and np.allclose(P.sum(axis=1), 1.0)
    c = one_case("pump_failure")
    sim = simulate.inject(ds, c.facility_id, "pump_failure", c.onset_unix)
    fr = baseline.residuals(sim, c.facility_id, c.onset_unix + 2 * 3600, models)
    p = classifier.predict_proba(bundle, [window_features(fr, c.onset_unix + 2 * 3600, ds.interval_s)])[0]
    assert classifier.CLASSES[int(p.argmax())] == "pump_failure" and p.max() > 0.8


def test_ensemble_keeps_rule_calls_and_adds_model_calls():
    rules_p = np.array([[0, 1, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0.0]])
    model_p = np.array([[0.9, 0.1, 0, 0], [0.05, 0.9, 0.05, 0], [0.97, 0.01, 0.01, 0.01]])
    out = evaluate.either_flags(rules_p, model_p)
    assert np.allclose(out.sum(axis=1), 1.0)
    assert out[0].argmax() == 1      # rules fire: their call stands even if the model is unsure
    assert out[1].argmax() == 1      # only the model fires: it can raise the alarm
    assert out[2].argmax() == 0      # both quiet: normal


def _string_constants_outside_docstrings(path: Path) -> list[str]:
    import ast
    tree = ast.parse(path.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant):
                docstrings.add(id(node.body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


def test_only_the_offline_scripts_may_open_the_answer_key():
    """Hard rule 2: no app code path may name answer_key.json in code. Docstrings and comments may mention it."""
    # offline scripts only; optimizer/validate.py is Sadeem's offline plan-cost check against the key (not in the app path)
    allowed = {"scorecard.py", "evaluate.py", "classifier.py", "check_m1.py", "validate.py"}
    for path in (ROOT / "backend").rglob("*.py"):
        if "tests" in path.parts or path.name in allowed:
            continue
        hits = [v for v in _string_constants_outside_docstrings(path) if "answer_key" in v]
        assert not hits, (str(path), hits)


def test_explanations_name_the_sensor_that_drives_each_call():
    ds, models, spans = world()
    rng = np.random.default_rng(4)
    rows = simulate.training_rows(ds, models, simulate.sample_cases(ds, 90, rng, spans=spans), rng, spans=spans)
    bundle = classifier.fit_classifier(rows)
    from backend.ml.detect.m3_core import explain
    want = {"pipeline_leak": "pipeline pressure", "pump_failure": "pump", "pump_degradation": "pump"}
    for kind, word in want.items():
        c = one_case(kind)
        sim = simulate.inject(ds, c.facility_id, kind, c.onset_unix, 0.2, 2.0, 8.0)
        t = c.onset_unix + (10 if kind != "pump_failure" else 2) * 3600
        x = window_features(baseline.residuals(sim, c.facility_id, t, models), t, ds.interval_s)
        p = classifier.predict_proba(bundle, [x])[0]
        call = classifier.CLASSES[int(p.argmax())]
        if call != kind:                     # a mild simulated case may not be called yet; the explanation is only for calls
            continue
        why = explain(bundle, x, call)
        assert why and word in why[0]["factor"] and why[0]["impact"] > 0.05, (kind, why)
    assert explain(bundle, x, "normal") == []


def test_blend_adds_a_second_opinion_and_falls_back_without_the_model():
    from backend.ml.detect import blend, enrich
    ds, _, _ = world()
    ev = blend.detect_with_m3(ds)
    base = enrich.detect_with_models(ds)
    assert len(ev) == len(base) and all("m3" in e for e in ev)
    assert [e["category"] for e in ev] == [e["category"] for e in base], "the rules stay the authority on category"
    assert all(abs(sum(e["m3"]["probs"].values()) - 1.0) < 0.02 for e in ev)
    json.dumps(ev)
    saved = dict(blend._BUNDLE)
    try:
        blend._BUNDLE["b"] = None                           # model file missing: events come back unchanged
        again = blend.detect_with_m3(ds)
        assert all("m3" not in e for e in again) and len(again) == len(base)
        assert blend.early_warnings(ds) == []
    finally:
        blend._BUNDLE.clear()
        blend._BUNDLE.update(saved)


def test_breaking_a_model_on_purpose_never_crashes_the_app():
    """Hard rule 7: if M1 or M3 fails, the app still returns the rule-based alerts."""
    from unittest import mock

    from backend.engine.detect import detect
    from backend.ml.detect import blend, enrich
    ds, _, _ = world()
    rule_ids = sorted(e["event_id"] for e in detect(ds))
    saved = dict(blend._BUNDLE)

    class Broken:
        classes_ = np.array(classifier.CLASSES)

        def predict_proba(self, X):
            raise RuntimeError("model exploded")

    try:
        # 1. M1 cannot be fitted
        enrich._CACHE.clear()
        with mock.patch.object(baseline, "fit", side_effect=RuntimeError("M1 exploded")):
            ev = blend.detect_with_m3(ds)
        assert sorted(e["event_id"] for e in ev) == rule_ids and all(e["source"] == "rules" for e in ev)
        enrich._CACHE.clear()
        # 2. M3 raises while predicting
        blend._BUNDLE["b"] = {"model": Broken(), "classes": classifier.CLASSES, "temperature": 1.0}
        ev = blend.detect_with_m3(ds)
        assert len(ev) == len(rule_ids) and all("m3" not in e for e in ev)
        assert blend.early_warnings(ds) == []
        # 3. the saved model file is junk
        blend._BUNDLE.clear()
        junk = ROOT / "backend" / "ml" / "detect" / "plots" / "_junk_model.joblib"
        junk.parent.mkdir(exist_ok=True)
        junk.write_bytes(b"not a model")
        try:
            with mock.patch.object(blend, "MODEL_PATH", junk):
                ev = blend.detect_with_m3(ds)
        finally:
            junk.unlink()
        assert len(ev) == len(rule_ids) and all("m3" not in e for e in ev)
    finally:
        enrich._CACHE.clear()
        blend._BUNDLE.clear()
        blend._BUNDLE.update(saved)


def test_app_modules_do_not_import_the_training_script():
    for name in ("blend.py", "m3_core.py", "enrich.py", "features.py", "simulate.py"):
        text = (ROOT / "backend" / "ml" / "detect" / name).read_text()
        assert "import classifier" not in text and "from .classifier" not in text and "from . import classifier" not in text, name


def test_model_eval_file_matches_the_api_contract():
    path = ROOT / "docs" / "model_eval.json"
    assert path.exists(), "run: python -m backend.ml.detect.evaluate"
    d = json.loads(path.read_text())
    assert d["method"] == "leave-one-system-out" and d["generated_unix"]
    assert len(d["folds"]) >= 4
    for f in d["folds"]:
        assert {"held_out_system", "precision", "recall", "mean_minutes_late"} <= set(f)
    for k in ("rules", "models", "ensemble"):
        assert {"recall", "mean_minutes_late"} <= set(d["comparison"][k])
    assert d["calibration_bins"] and all({"p_mean", "observed", "n"} <= set(b) for b in d["calibration_bins"])


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
