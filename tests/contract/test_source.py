"""The contract of the source (U04; RF01-RF03, V01-V07; AC01-AC03, AC10): every malformed variant fails the rule that owns it and writes nothing,
the valid fixture is read once into the canonical tables, a rejected source leaves what was there untouched and the canonical tables carry no
forbidden column."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from promolift.cube import open_cube
from promolift.ingest import INTERIM_MANIFEST, LOCK_NAME, canonical_state, fetch_source, read_canonical
from promolift.schema import FORBIDDEN_COLUMNS, SourceError
from tests.fixtures.make_fixture import MALFORMED_RULES


def tree_hashes(root: Path) -> dict[str, str]:
    """The SHA-256 of every file under `root` (empty if it does not exist)."""
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def test_each_malformed_variant_fails_its_rule_and_writes_nothing(malformed, cfg_for, tmp_path):
    expected_rules = set()
    for kind, rule in sorted(MALFORMED_RULES.items()):
        bad = malformed(kind)
        config = cfg_for(bad.dir, malformed=bad)
        with pytest.raises(SourceError) as raised:
            fetch_source(config)
        assert raised.value.rule_id == rule, (kind, str(raised.value))
        assert raised.value.EXIT_CODE == 3 and raised.value.problems and all(p["rule_id"] == rule for p in raised.value.problems), kind
        assert not (tmp_path / "interim").exists(), f"{kind}: a rejected source writes nothing in data/interim/"
        assert not (bad.dir / LOCK_NAME).exists() and not any(tmp_path.glob("raw*")), kind
        expected_rules.add(rule)
    assert expected_rules == {"V01", "V02", "V03", "V04", "V05", "V06", "V07"}, "every blocking rule of the source has a variant"


@pytest.mark.parametrize("kind", ["wrong_hash", "extra_column", "short_list", "duplicate_key", "missing_day"])
def test_a_rejected_source_leaves_the_canonical_tables_that_were_there_byte_for_byte(kind, malformed, cfg_for, small_truth, tmp_path):
    good = cfg_for(small_truth.dir)
    assert fetch_source(good)["built"] is True
    before = tree_hashes(tmp_path / "interim")
    assert INTERIM_MANIFEST in before and len(before) == 1 + 2 + 2 * 97
    bad = malformed(kind)
    with pytest.raises(SourceError):
        fetch_source(cfg_for(bad.dir, malformed=bad))
    assert tree_hashes(tmp_path / "interim") == before


def test_the_messages_name_the_rule_and_the_runbook_where_the_runbook_helps(malformed, cfg_for):
    messages = {}
    for kind in ("wrong_hash", "extra_column", "renamed_column", "short_list", "duplicate_key", "two_groups", "missing_day", "oversize"):
        bad = malformed(kind)
        with pytest.raises(SourceError) as raised:
            fetch_source(cfg_for(bad.dir, malformed=bad))
        messages[kind] = str(raised.value)
    assert all(re.match(r"V0[1-7]: ", m) for m in messages.values())
    assert "R1" in messages["wrong_hash"] and "R2" in messages["extra_column"] and "R2" in messages["short_list"]
    assert "extra" in messages["extra_column"] and "price_factor" in messages["renamed_column"] and "discount" in messages["renamed_column"]
    assert "hours_sale" in messages["short_list"] and "23" in messages["short_list"]
    assert "se repite" in messages["duplicate_key"] and "20240328" in messages["duplicate_key"]
    assert "producto" in messages["two_groups"] and "serie" in messages["missing_day"]


def test_the_valid_fixture_is_read_once_into_the_canonical_tables(cfg_for, small_truth, tmp_path):
    config = cfg_for(small_truth.dir)
    result = fetch_source(config)
    assert result["built"] is True and (result["train_sha256"], result["eval_sha256"]) == (small_truth.train_sha256, small_truth.eval_sha256)
    assert (result["series"], result["days"], result["series_days"]) == (60, 97, 60 * 97) and result["rows"] == {"train": 5400, "eval": 420}
    assert result["day_state"] == small_truth.rule_counts()["day_state"] and result["sale_amount_mismatch"] == 0 and result["stock_count_mismatch"] == 0
    assert [result[f"{k}_{split}"] for k in ("sale_amount_mismatch", "stock_count_mismatch") for split in ("train", "eval")] == [0, 0, 0, 0], "kept per file for V26 and V27 of the run (U16)"
    folder = tmp_path / "interim"
    assert canonical_state(folder) == (small_truth.train_sha256, small_truth.eval_sha256)
    assert sorted(p.name for p in folder.iterdir()) == ["canonical", INTERIM_MANIFEST, "series.parquet", "series_days.parquet"]
    again = fetch_source(config)
    assert again["built"] is False and again["series_days"] == 60 * 97 and tree_hashes(folder) == tree_hashes(folder)
    manifest = json.loads((folder / INTERIM_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["counts"]["series"] == 60 and manifest["counts"]["rows"] == {"train": 5400, "eval": 420}


def test_a_second_fetch_changes_no_file_and_another_source_rebuilds_them(cfg_for, small_truth, tmp_path):
    from tests.fixtures.make_fixture import make_fixture

    config = cfg_for(small_truth.dir)
    fetch_source(config)
    folder = tmp_path / "interim"
    first = tree_hashes(folder)
    mtimes = {p: p.stat().st_mtime_ns for p in folder.rglob("*") if p.is_file()}
    assert fetch_source(config)["built"] is False
    assert tree_hashes(folder) == first and {p: p.stat().st_mtime_ns for p in folder.rglob("*") if p.is_file()} == mtimes
    other = make_fixture(tmp_path / "other_source", series=60, seed=7)
    rebuilt = fetch_source(cfg_for(other.dir))
    assert rebuilt["built"] is True and canonical_state(folder) == (other.train_sha256, other.eval_sha256)
    assert tree_hashes(folder) != first and set(tree_hashes(folder)) == set(first)


def test_a_changed_canonical_file_is_rebuilt_from_the_source(cfg_for, small_truth, tmp_path):
    config = cfg_for(small_truth.dir)
    fetch_source(config)
    folder = tmp_path / "interim"
    target = folder / "canonical" / "20240510.sales.npy"
    good = target.read_bytes()
    target.write_bytes(good[:-1] + bytes([good[-1] ^ 0x01]))
    assert canonical_state(folder) is None
    assert fetch_source(config)["built"] is True and target.read_bytes() == good and canonical_state(folder) is not None


def test_the_quick_mode_registers_its_hashes_only_after_the_files_were_read(cfg_for, small_truth, malformed, copy_of):
    own = copy_of(small_truth.dir)                  # the registry is written next to the files: never into the session's folder
    quick = cfg_for(own, train_bytes=0, train_sha256="", eval_bytes=0, eval_sha256="")
    lock = quick.source.train_path.parent / LOCK_NAME
    bad = malformed("short_list")
    bad_quick = cfg_for(bad.dir, train_bytes=0, train_sha256="", eval_bytes=0, eval_sha256="")
    with pytest.raises(SourceError, match="V04"):
        fetch_source(bad_quick)
    assert not (bad.dir / LOCK_NAME).exists()
    assert fetch_source(quick)["built"] is True
    document = json.loads(lock.read_text(encoding="utf-8"))
    assert document["files"]["train"]["sha256"] == small_truth.train_sha256 and document["files"]["eval"]["size"] == small_truth.eval_bytes
    assert fetch_source(quick)["built"] is False
    lock.unlink()
    assert fetch_source(quick)["built"] is False and lock.exists(), "a canonical state that is current registers the hashes that are missing"


def test_canonical_frames_carry_no_forbidden_column(cfg_for, small_truth, tmp_path):
    config = cfg_for(small_truth.dir)
    fetch_source(config)
    folder = tmp_path / "interim"
    series, series_days = read_canonical(folder)
    for frame in (series, series_days):
        assert not set(frame.columns) & set(FORBIDDEN_COLUMNS)
    for name in ("series.parquet", "series_days.parquet"):
        assert not set(pq.read_schema(folder / name).names) & set(FORBIDDEN_COLUMNS)
    cube = open_cube(folder)
    assert cube.sales(20240328).shape == (60, 24) and cube.stock(20240328).shape == (60, 24)
    # nothing the generator put in sale_amount, stock_hour6_22_cnt or the weather reaches a tensor: the tensors are only the two hourly lists
    for key in cube.date_keys.tolist()[:3]:
        assert cube.sales(key).dtype == np.float32 and cube.stock(key).dtype == np.int8


def test_a_pinned_source_registers_no_hashes(cfg_for, small_truth, copy_of):
    own = copy_of(small_truth.dir)
    fetch_source(cfg_for(own))
    assert not (own / LOCK_NAME).exists(), "only the quick mode, which has no accepted hashes, keeps a registry of the first ones it saw"
