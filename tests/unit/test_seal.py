"""The fingerprint and the launch part of the seal (U09; RF16, D17; M05; AC18): every key that can change a sealed value is in ``config_sha256``, the sealed
calculations receive only the sealed view, the seal is written once, a repetition reproduces it and another configuration is post-seal."""

from __future__ import annotations

import copy
import dataclasses
import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from promolift.config import FINGERPRINT_KEYS, UNSEALED_KEYS, SealedConfig
from promolift.registry import (
    SealError,
    SealMismatchError,
    canonical_sha256,
    config_fingerprint,
    differing_keys,
    launch_seal_outcome,
    read_seal,
    seal_state,
    sealed_document,
    sealed_view,
    write_launch_seal,
)

TRAIN, EVAL = "1" * 64, "2" * 64
SRC = Path(__file__).resolve().parents[2] / "src" / "promolift"
SEALED_MODULES = ("days.py", "split.py", "masks.py", "recovery.py", "effect.py", "bootstrap.py", "ranking.py", "forecast.py")


def changed(value):
    """Another value of the same type as `value`."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value * 1.5 + 0.01
    if isinstance(value, str):
        return value[:-1] + ("0" if value[-1] != "0" else "1")
    if isinstance(value, date):
        return value + timedelta(days=1)
    if isinstance(value, tuple):
        return (*value[:-1], changed(value[-1]))
    raise AssertionError(f"no way to change {value!r}")


def with_key(cfg, key: str):
    section, name = key.split(".")
    part = getattr(cfg, section)
    return dataclasses.replace(cfg, **{section: dataclasses.replace(part, **{name: changed(getattr(part, name))})})


def test_changing_any_fingerprinted_key_changes_config_sha256(cfg):
    base = config_fingerprint(sealed_view(cfg, TRAIN, EVAL))
    for key in FINGERPRINT_KEYS:
        assert config_fingerprint(sealed_view(with_key(cfg, key), TRAIN, EVAL)) != base, key
    assert config_fingerprint(sealed_view(cfg, "3" * 64, EVAL)) != base and config_fingerprint(sealed_view(cfg, TRAIN, "3" * 64)) != base     # the two files read


def test_changing_a_key_declared_unsealed_changes_nothing_that_is_sealed(cfg):
    base = config_fingerprint(sealed_view(cfg, TRAIN, EVAL))
    for key in UNSEALED_KEYS:
        section, name = key.split(".")
        value = getattr(getattr(cfg, section), name)
        other = changed(str(value)) if isinstance(value, Path) else changed(value)
        part = dataclasses.replace(getattr(cfg, section), **{name: Path(other) if isinstance(value, Path) else other})
        assert config_fingerprint(sealed_view(dataclasses.replace(cfg, **{section: part}), TRAIN, EVAL)) == base, key


def test_the_fingerprint_is_the_sha256_of_the_canonical_json_of_the_sealed_view_and_the_file_hash_of_the_toml_is_never_in_it(cfg):
    view = sealed_view(cfg, TRAIN, EVAL)
    document = sealed_document(view)
    assert isinstance(view, SealedConfig) and config_fingerprint(view) == canonical_sha256(document)
    text = json.dumps(document, sort_keys=True)
    assert "config_file_sha256" not in text and TRAIN in text and EVAL in text
    assert document["calendar"]["first_day"] == "2024-03-28" and document["split"]["test"] == ["2024-06-26", "2024-07-02"]
    assert canonical_sha256({"b": 1, "a": [1.5, "x"]}) == canonical_sha256({"a": [1.5, "x"], "b": 1})


def test_sealed_calculations_receive_only_the_sealed_view():
    for module in SEALED_MODULES:
        text = (SRC / module).read_text(encoding="utf-8")
        assert not re.search(r"\bPipelineConfig\b", text), f"{module} names PipelineConfig"
        assert not re.search(r"\.paths\b|\.site\b", text), f"{module} reads an unsealed section"
    fields = {f.name for f in dataclasses.fields(SealedConfig)}
    assert fields == {"source", "calendar", "days", "split", "recovery", "effect", "bootstrap", "ranking", "forecast", "variants", "criteria",
                      "train_sha256_seen", "eval_sha256_seen"}


# --- the launch part of the seal --------------------------------------------------------------------------------------------------------


def launch_document(cfg, **changes):
    view = sealed_view(cfg, TRAIN, EVAL)
    document = {
        "run_key": "run-1", "as_of": "2024-06-26 00:00:00", "train_sha256": TRAIN, "eval_sha256": EVAL, "config_sha256": config_fingerprint(view),
        "sealed_config": sealed_document(view), "model_version": "v1", "artifact_sha256": "a" * 64, "r3_sha256": None,
        "recovery": {"method": "r2", "kappa": 0.25, "wape_v1": 0.30012345, "pmf": [0.5, 0.5]},
        "effects": {"overall": {"raw": {"lift": 0.5}, "recovered": {"lift": 0.6}}, "cells": [{"key": "g1-b2", "lift": 0.7, "ci_low": 0.6, "ci_high": 0.8}]},
        "validation": {"replication": {"spearman": 0.9}, "forecast": {"f1_naive": {"wape": 0.35}}, "recovery_v2": {"r1": 0.38}},
        "validation_digest": "d" * 64,
    }
    return {**document, **changes}


def test_the_seal_is_written_once_and_a_repetition_with_the_same_configuration_reproduces_it(cfg, tmp_path):
    seal = tmp_path / "reports" / "model_seal.json"
    document = launch_document(cfg)
    assert read_seal(seal) is None and seal_state(seal, document["config_sha256"]) == "none"
    assert launch_seal_outcome(seal, document) == "written" and not seal.exists()          # the outcome is decided before anything is written
    assert write_launch_seal(seal, document) == "written"
    raw = seal.read_bytes()
    assert b"\r" not in raw and json.loads(raw)["version"] == 1 and json.loads(raw)["launch"]["config_sha256"] == document["config_sha256"]
    assert seal_state(seal, document["config_sha256"]) == "match" and seal_state(seal, "f" * 64) == "post_seal"
    again = launch_document(cfg, run_key="run-2", as_of="2024-07-01 00:00:00", artifact_sha256="b" * 64)       # what a repetition may change
    assert launch_seal_outcome(seal, again) == "unchanged" and write_launch_seal(seal, again) == "unchanged" and seal.read_bytes() == raw
    rounded = launch_document(cfg, recovery={"method": "r2", "kappa": 0.25, "wape_v1": 0.30012349, "pmf": [0.5, 0.5]})
    assert write_launch_seal(seal, rounded) == "unchanged"                                  # equal at 6 decimals


def test_the_same_configuration_with_another_sealed_value_is_refused_and_names_each_value(cfg, tmp_path):
    seal = tmp_path / "model_seal.json"
    write_launch_seal(seal, launch_document(cfg))
    before = seal.read_bytes()
    other = copy.deepcopy(launch_document(cfg))
    other["effects"]["overall"]["recovered"]["lift"] = 0.61
    other["effects"]["cells"][0]["ci_high"] = 0.9
    other["recovery"]["method"] = "r1"
    for call in (launch_seal_outcome, write_launch_seal):
        with pytest.raises(SealMismatchError) as caught:
            call(seal, other)
        message = str(caught.value)
        assert "effects.overall.recovered.lift" in message and "0.6" in message and "0.61" in message and "recovery.method" in message
        assert "effects.cells.g1-b2.ci_high" in message
    assert seal.read_bytes() == before


def test_a_file_that_is_not_a_seal_is_an_error_and_never_an_absent_one(cfg, tmp_path):
    seal = tmp_path / "model_seal.json"
    for content in ("not json", json.dumps({"version": 2}), json.dumps({"version": 1, "launch": {"config_sha256": "x"}}), json.dumps({"version": 1, "extra": 1})):
        seal.write_text(content, encoding="utf-8")
        with pytest.raises(SealError):
            read_seal(seal)
        with pytest.raises(SealError):
            seal_state(seal, "f" * 64)
        with pytest.raises(SealError):
            write_launch_seal(seal, launch_document(cfg))
        assert seal.read_text(encoding="utf-8") == content          # nothing was replaced


def test_a_seal_part_with_a_missing_key_or_a_bad_fingerprint_or_a_value_that_is_not_a_number_is_refused_before_writing(cfg, tmp_path):
    seal = tmp_path / "model_seal.json"
    good = launch_document(cfg)
    for bad in ({k: v for k, v in good.items() if k != "recovery"}, {**good, "extra": 1}, {**good, "config_sha256": "zz"},
                {**good, "recovery": {"method": "r2", "wape_v1": float("nan")}}, {**good, "sealed_config": {"other": 1}}):
        with pytest.raises(SealError):
            write_launch_seal(seal, bad)
        assert not seal.exists()


def test_two_writers_that_race_for_the_seal_leave_one_whole_file(cfg, tmp_path):
    seal = tmp_path / "model_seal.json"
    document = launch_document(cfg)
    seal.write_text(json.dumps({"version": 1, "launch": document}, sort_keys=True), encoding="utf-8")        # someone else created it between the decision and the write
    assert write_launch_seal(seal, document) == "unchanged"
    assert json.loads(seal.read_text(encoding="utf-8"))["launch"]["run_key"] == "run-1"
