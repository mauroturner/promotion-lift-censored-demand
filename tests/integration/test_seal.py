"""The seal and the launch (U09; D17; M05; AC18): another configuration after the seal changes nothing that is sealed."""

from __future__ import annotations

from promolift.registry import differing_keys, launch_seal_outcome, write_launch_seal
from tests.unit.test_seal import launch_document, with_key


def test_another_config_after_the_seal_is_post_seal_and_the_seal_stays(cfg, tmp_path):
    seal = tmp_path / "model_seal.json"
    write_launch_seal(seal, launch_document(cfg))
    before = seal.read_bytes()
    other_cfg = with_key(cfg, "ranking.min_series")
    other = launch_document(other_cfg, effects={"different": True})
    assert launch_seal_outcome(seal, other) == "post_seal" and write_launch_seal(seal, other) == "post_seal" and seal.read_bytes() == before
    assert differing_keys(launch_document(cfg)["sealed_config"], other["sealed_config"]) == ["ranking.min_series"]
    assert differing_keys({"a": {"b": 1}, "c": [1, 2]}, {"a": {"b": 1}, "c": [1, 3]}) == ["c"]
