"""The seal and the launch (U09; D17; M05; AC18): another configuration after the seal changes nothing that is sealed."""

from __future__ import annotations

import json

import pytest

from promolift.registry import SealError, canonical_sha256, differing_keys, launch_seal_outcome, read_seal, sealed_view, write_launch_seal
from tests.unit.test_seal import launch_document, sealed_test_part, with_key


def test_another_config_after_the_seal_is_post_seal_and_the_seal_stays(cfg, tmp_path):
    seal = tmp_path / "model_seal.json"
    write_launch_seal(seal, launch_document(cfg))
    before = seal.read_bytes()
    other_cfg = with_key(cfg, "ranking.min_series")
    other = launch_document(other_cfg, effects={"different": True})
    assert launch_seal_outcome(seal, other) == "post_seal" and write_launch_seal(seal, other) == "post_seal" and seal.read_bytes() == before
    assert differing_keys(launch_document(cfg)["sealed_config"], other["sealed_config"]) == ["ranking.min_series"]
    assert differing_keys({"a": {"b": 1}, "c": [1, 2]}, {"a": {"b": 1}, "c": [1, 3]}) == ["c"]


# --- the test part (U11; D17, D18; AC18) -----------------------------------------------------------------------------------------------------


def test_evaluating_the_test_under_another_config_before_the_test_seal_is_refused(cfg, tmp_path):
    from promolift.registry import EvaluationRefusedError, check_test_evaluation

    seal = tmp_path / "model_seal.json"
    other_view = sealed_view(with_key(cfg, "ranking.min_series"), "1" * 64, "2" * 64)
    with pytest.raises(EvaluationRefusedError, match="no hay sello"):
        check_test_evaluation(seal, sealed_view(cfg, "1" * 64, "2" * 64))
    write_launch_seal(seal, launch_document(cfg))
    before = seal.read_bytes()
    assert check_test_evaluation(seal, sealed_view(cfg, "1" * 64, "2" * 64)) == "first"
    with pytest.raises(EvaluationRefusedError, match="ranking.min_series"):
        check_test_evaluation(seal, other_view)
    assert seal.read_bytes() == before and not list(tmp_path.glob("*.tmp"))


def test_the_test_part_is_written_once_and_never_rewritten_and_the_launch_part_keeps_its_previous_behaviour(cfg, tmp_path):
    from promolift.registry import SealMismatchError, TEST_KEYS, check_test_evaluation, write_test_seal

    seal = tmp_path / "model_seal.json"
    launch = launch_document(cfg)
    view = sealed_view(cfg, "1" * 64, "2" * 64)
    with pytest.raises(SealError, match="no hay sello"):
        write_test_seal(seal, sealed_test_part(launch))
    write_launch_seal(seal, launch)
    launch_bytes_only = seal.read_bytes()
    part = sealed_test_part(launch)
    assert write_test_seal(seal, part) == "written" and read_seal(seal)["launch"] == json.loads(launch_bytes_only)["launch"] and set(read_seal(seal)["test"]) == set(TEST_KEYS)
    sealed = seal.read_bytes()
    assert write_test_seal(seal, {**part, "run_key": "another-run", "as_of": "2025-01-01 00:00:00"}) == "unchanged" and seal.read_bytes() == sealed     # what may change on a repetition
    with pytest.raises(SealMismatchError, match="criteria"):
        write_test_seal(seal, {**part, "criteria": [{"id": "C01", "value": 0.5}]})
    assert write_test_seal(seal, {**part, "config_sha256": canonical_sha256({"other": 1}), "criteria": []}) == "post_seal" and seal.read_bytes() == sealed
    assert check_test_evaluation(seal, view) == "repeat"
    assert check_test_evaluation(seal, sealed_view(with_key(cfg, "ranking.min_series"), "1" * 64, "2" * 64)) == "post_seal"       # the test is sealed: another configuration is apart
    # the launch part: the same launch is still unchanged and another configuration still post_seal, with a test part in the file
    assert write_launch_seal(seal, launch) == "unchanged" and write_launch_seal(seal, launch_document(with_key(cfg, "ranking.min_series"))) == "post_seal" and seal.read_bytes() == sealed
    for bad in ({**part, "extra": 1}, {k: v for k, v in part.items() if k != "days"}):
        with pytest.raises(SealError, match="claves"):
            write_test_seal(seal, bad)
    broken = json.loads(sealed)
    del broken["test"]["days"]
    seal.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(SealError, match="parte de la prueba"):
        read_seal(seal)
