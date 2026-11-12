"""The seal and its fingerprint (U16, AC20, AC21; D19; plan, section 15). ``config_sha256`` is the SHA-256 of the whole sealed view, so every key
that can change a sealed value changes it (project 03's B4, D89); the sealed calculations receive only that view; each part of the seal is
written once, a repetition with the same configuration must reproduce it and another configuration is ``post_seal`` and leaves it as it was."""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import date, timedelta
from pathlib import Path

import pytest

from churnrisk.config import FINGERPRINT_KEYS, UNSEALED_KEYS, SealedConfig
from churnrisk.registry import (
    SealError,
    SealMismatchError,
    config_fingerprint,
    differing_keys,
    read_seal,
    seal_state,
    sealed_document,
    sealed_view,
    write_launch_seal,
    write_test_seal,
)

SHA = "a" * 64
SOURCE_DIR = Path(__file__).resolve().parents[2] / "src" / "churnrisk"


def changed(value):
    """Another value of the same type: what a different configuration would hold for that key."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value * 1.5 + 0.01
    if isinstance(value, date):
        return value + timedelta(days=1)
    if isinstance(value, str):
        return value + "x"
    if isinstance(value, tuple):
        return (*value[:-1], changed(value[-1])) if value else ("x",)
    raise TypeError(type(value))


def with_leaf(obj, dotted: str, value):
    """`obj` (a frozen dataclass) with the leaf `dotted` (``section.key``) replaced."""
    head, _, rest = dotted.partition(".")
    if not rest:
        return dataclasses.replace(obj, **{head: value})
    return dataclasses.replace(obj, **{head: with_leaf(getattr(obj, head), rest, value)})


def leaf(obj, dotted: str):
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return obj


# --- the RED of U16 -----------------------------------------------------------------------------------------------------


def test_changing_any_fingerprinted_key_changes_config_sha256(cfg):
    """Each of the 55 keys of FINGERPRINT_KEYS and the observed hash of the zip change config_sha256; no key of UNSEALED_KEYS does, because
    it never reaches the sealed view."""
    view = sealed_view(cfg, SHA)
    base = config_fingerprint(view)
    assert len(base) == 64 and base == config_fingerprint(sealed_view(cfg, SHA)), "the same view, the same fingerprint"
    unchanged = [key for key in FINGERPRINT_KEYS if config_fingerprint(with_leaf(view, key, changed(leaf(view, key)))) == base]
    assert unchanged == [], f"keys that change a sealed value but not config_sha256: {unchanged}"
    assert config_fingerprint(sealed_view(cfg, "b" * 64)) != base, "the observed hash of the zip enters the fingerprint"
    for key in UNSEALED_KEYS:
        value = leaf(cfg, key)
        other = cfg.project_root / "x.zip" if value is None else value.parent / "other" if isinstance(value, Path) else changed(value)
        assert config_fingerprint(sealed_view(with_leaf(cfg, key, other), SHA)) == base, key


def test_the_sealed_document_is_the_whole_view_in_canonical_json(cfg):
    view = sealed_view(cfg, SHA)
    document = sealed_document(view)
    assert set(document) == {f.name for f in dataclasses.fields(SealedConfig)}
    assert document["source_sha256"] == SHA and document["label"]["first_cut"] == "2010-06-01" and document["model"]["learning_rate"] == [0.05, 0.1]
    flat = {f"{section}.{key}" for section, keys in document.items() if isinstance(keys, dict) for key in keys}
    assert flat == set(FINGERPRINT_KEYS)
    assert json.loads(json.dumps(document)) == document, "JSON-ready, so the seal stores it whole and names a difference key by key"


def test_sealed_calculations_receive_only_the_sealed_view():
    """D19: the modules whose results are sealed never receive the whole configuration (a static test over their source). sensitivity.py joins
    the list when it exists (U18)."""
    modules = ("cuts", "features", "split", "baselines", "bgnbd", "model", "explain", "threshold", "scoring", "evaluation", "leakage_demo")
    for name in modules:
        text = (SOURCE_DIR / f"{name}.py").read_text(encoding="utf-8")
        assert "PipelineConfig" not in text and "load_config" not in text, f"{name}.py receives the whole configuration"


# --- the launch part ----------------------------------------------------------------------------------------------------


def launch_part(cfg, **changes) -> dict:
    view = sealed_view(cfg, SHA)
    part = {
        "run_key": "r1", "as_of": "2011-07-31", "source_sha256": SHA, "config_sha256": config_fingerprint(view), "sealed_config": sealed_document(view),
        "model_version": "v1", "feature_set": "f1", "params": {"learning_rate": 0.05, "max_leaf_nodes": 15, "min_samples_leaf": 200},
        "country_groups": ["United Kingdom", "Otros"], "threshold": 0.51, "b_star": "b4_frequency",
        "bgnbd": {"r": 0.9, "alpha": 75.8, "a": 0.17, "b": 105.9, "log_likelihood": -59505.36112345}, "valid_scores_sha256": "c" * 64,
    }
    return {**part, **changes}


def test_the_launch_part_is_written_once_and_a_repetition_must_reproduce_it(cfg, tmp_path, caplog):
    path = tmp_path / "reports" / "model_seal.json"
    assert seal_state(path, config_fingerprint(sealed_view(cfg, SHA))) == "none" and read_seal(path) is None
    assert write_launch_seal(path, launch_part(cfg)) == "written"
    sealed = path.read_bytes()
    assert read_seal(path) == {"version": 1, "launch": launch_part(cfg)}
    nudged = {**launch_part(cfg)["bgnbd"], "r": 0.9 + 1e-9, "log_likelihood": -59505.36112345 + 4e-8}   # equal to 6 decimals, not to 8
    assert write_launch_seal(path, launch_part(cfg, run_key="r7", bgnbd=nudged)) == "unchanged"
    assert path.read_bytes() == sealed, "a repetition that reproduces the seal rewrites nothing"
    # the same configuration with other sealed values is a failed reproduction that names each value
    with pytest.raises(SealMismatchError, match=r"b_star: 'b4_frequency' sellado, 'b2_rfm' en esta corrida; threshold: 0\.51 sellado, 0\.52 en esta corrida"):
        write_launch_seal(path, launch_part(cfg, threshold=0.52, b_star="b2_rfm"))
    for key, value in (("valid_scores_sha256", "d" * 64), ("feature_set", "f2"), ("country_groups", ["Otros"])):
        with pytest.raises(SealMismatchError, match=key):
            write_launch_seal(path, launch_part(cfg, **{key: value}))
    assert path.read_bytes() == sealed
    # another configuration is post_seal: the seal stays as it was and the warning names the keys that differ
    other = dataclasses.replace(cfg, costs=dataclasses.replace(cfg.costs, offer_cost=6.0))
    view = sealed_view(other, SHA)
    with caplog.at_level(logging.WARNING, logger="churnrisk.registry"):
        outcome = write_launch_seal(path, launch_part(cfg, config_sha256=config_fingerprint(view), sealed_config=sealed_document(view), threshold=0.6))
    assert outcome == "post_seal" and path.read_bytes() == sealed
    assert "costs.offer_cost" in caplog.text and seal_state(path, config_fingerprint(view)) == "post_seal"
    assert seal_state(path, config_fingerprint(sealed_view(cfg, SHA))) == "match"


def test_a_launch_part_that_is_not_one_is_refused_before_anything_is_written(cfg, tmp_path):
    path = tmp_path / "model_seal.json"
    with pytest.raises(SealError, match="exactamente las claves"):
        write_launch_seal(path, {k: v for k, v in launch_part(cfg).items() if k != "b_star"})
    with pytest.raises(SealError, match="config_sha256 no es la huella"):
        write_launch_seal(path, launch_part(cfg, config_sha256="e" * 64))
    assert not path.exists()


# --- the test part ------------------------------------------------------------------------------------------------------


def evaluated_part(cfg, **changes) -> dict:
    part = {
        "run_key": "r5", "as_of": "2011-11-30", "config_sha256": config_fingerprint(sealed_view(cfg, SHA)),
        "criteria": [{"id": "C01", "value": 0.7512345, "baseline_value": 0.76, "ci_low": None, "ci_high": None, "passed": False, "verdict_es": "no supera"}],
        "metrics": {"model": {"auc": 0.75}}, "per_cut": [{"cut": "2011-08-01", "auc": 0.74}], "variants": [{"variant": "n60", "auc_model": 0.7}],
    }
    return {**part, **changes}




def test_the_test_part_is_added_once_and_compared_to_6_decimals(cfg, tmp_path, caplog):
    path = tmp_path / "model_seal.json"
    with pytest.raises(SealError, match="después de la del lanzamiento"):
        write_test_seal(path, evaluated_part(cfg))
    write_launch_seal(path, launch_part(cfg))
    launch_bytes = json.loads(path.read_text(encoding="utf-8"))["launch"]
    assert write_test_seal(path, evaluated_part(cfg)) == "written"
    document = read_seal(path)
    assert document["launch"] == launch_bytes and document["test"] == evaluated_part(cfg), "the launch part is kept as it was"
    sealed = path.read_bytes()
    nudged = evaluated_part(cfg, run_key="r9", criteria=[{**evaluated_part(cfg)["criteria"][0], "value": 0.7512345 + 4e-8}])
    assert write_test_seal(path, nudged) == "unchanged" and path.read_bytes() == sealed
    with pytest.raises(SealMismatchError, match=r"C01\.value"):
        write_test_seal(path, evaluated_part(cfg, criteria=[{**evaluated_part(cfg)["criteria"][0], "value": 0.7513}]))
    with pytest.raises(SealMismatchError, match=r"per_cut"):
        write_test_seal(path, evaluated_part(cfg, per_cut=[{"cut": "2011-08-01", "auc": 0.75}]))
    with caplog.at_level(logging.WARNING, logger="churnrisk.registry"):
        assert write_test_seal(path, evaluated_part(cfg, config_sha256="f" * 64, metrics={"model": {"auc": 0.9}})) == "post_seal"
    assert path.read_bytes() == sealed and "post_seal" in caplog.text


def test_a_file_that_is_not_a_seal_is_never_taken_for_an_absent_one(cfg, tmp_path):
    path = tmp_path / "model_seal.json"
    for text in ("not json", "[]", '{"version": 2, "launch": {}}', '{"version": 1}', '{"version": 1, "launch": {"config_sha256": "x"}}'):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(SealError):
            read_seal(path)
        with pytest.raises(SealError):
            write_launch_seal(path, launch_part(cfg))
        assert path.read_text(encoding="utf-8") == text


def test_differing_keys_names_each_key_of_the_view_that_differs(cfg):
    a = sealed_document(sealed_view(cfg, SHA))
    other = dataclasses.replace(cfg, label=dataclasses.replace(cfg.label, horizon_days=60), costs=dataclasses.replace(cfg.costs, rescue_rate=0.3))
    assert differing_keys(a, sealed_document(sealed_view(other, "b" * 64))) == ["costs.rescue_rate", "label.horizon_days", "source_sha256"]
    assert differing_keys(a, a) == []


def test_the_fingerprint_of_the_validation_risks_rounds_to_6_decimals_follows_the_cuts_and_holds_no_customer():
    import hashlib

    import pandas as pd

    from churnrisk.registry import valid_scores_fingerprint

    index = pd.MultiIndex.from_tuples([(date(2011, 3, 1), 90001), (date(2011, 3, 1), 90002), (date(2011, 5, 1), 90001)], names=["cut_date", "customer_id"])
    risks = pd.DataFrame({"risk": [0.25, 0.5, 0.125]}, index=index)
    expected = hashlib.sha256(b"2011-03-01:0.250000\n2011-03-01:0.500000\n2011-05-01:0.125000\n").hexdigest()
    assert valid_scores_fingerprint(risks) == expected, "one cut:risk line per row, in the order of the cut and the internal position"
    assert valid_scores_fingerprint(risks.iloc[::-1]) == expected, "the order of the rows given does not matter"
    assert valid_scores_fingerprint(risks.assign(risk=risks["risk"] + 4e-8)) == expected
    assert valid_scores_fingerprint(risks.assign(risk=[0.25, 0.5, 0.126])) != expected

