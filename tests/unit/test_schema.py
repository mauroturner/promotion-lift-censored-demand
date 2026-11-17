"""The contract of the source and of the canonical tables (U04; plan, section 6; AC02, AC03, AC10): the one place that names the columns, the lists
that never share a name and the error that carries the exit code 3."""

from __future__ import annotations

import pyarrow.parquet as pq
import pytest

from promolift import schema
from tests.conftest import REAL_EVAL, REAL_TRAIN
from tests.fixtures.make_fixture import SOURCE_ARROW_SCHEMA


def test_the_source_schema_has_the_19_columns_of_the_real_files_in_their_order_and_types():
    assert schema.SOURCE_SCHEMA.equals(SOURCE_ARROW_SCHEMA), "the reader's schema and the generator's are the same one"
    assert len(schema.SOURCE_COLUMNS) == 19 and schema.SOURCE_COLUMNS == tuple(schema.SOURCE_SCHEMA.names)
    assert sorted(schema.ID_COLUMNS + ("dt",) + schema.DAILY_COLUMNS + schema.HOUR_COLUMNS) == sorted(schema.SOURCE_COLUMNS)
    assert str(schema.SOURCE_SCHEMA.field("hours_sale").type) == "list<element: double>"
    assert str(schema.SOURCE_SCHEMA.field("hours_stock_status").type) == "list<element: int64>"
    assert str(schema.SOURCE_SCHEMA.field("stock_hour6_22_cnt").type) == "int32" and str(schema.SOURCE_SCHEMA.field("dt").type) == "string"
    assert schema.HOURS == 24 and len(schema.ID_COLUMNS) == 7 and len(schema.DAILY_COLUMNS) == 9 and len(schema.HOUR_COLUMNS) == 2


def test_the_kept_the_forbidden_the_identifier_and_the_target_lists_never_share_a_name():
    groups = {"ids": set(schema.ID_COLUMNS), "kept": set(schema.DAILY_KEPT), "forbidden": set(schema.FORBIDDEN_COLUMNS),
              "targets": set(schema.TARGET_COLUMNS), "hours": set(schema.HOUR_COLUMNS)}
    names = sorted(groups)
    for i, one in enumerate(names):
        for other in names[i + 1:]:
            assert groups[one] & groups[other] == set(), (one, other)
    assert set(schema.DAILY_KEPT) | set(schema.FORBIDDEN_COLUMNS) == set(schema.DAILY_COLUMNS)
    assert set(schema.DAILY_KEPT) == {"discount", "activity_flag", "holiday_flag"}
    assert set(schema.FORBIDDEN_COLUMNS) == {"sale_amount", "stock_hour6_22_cnt", "precpt", "avg_temperature", "avg_humidity", "avg_wind_level"}
    assert set(schema.TARGET_COLUMNS) == {"hidden_sale", "observed_instock"}


def test_the_canonical_tables_name_no_forbidden_column_and_their_schemas_match_their_lists():
    for table_schema in (schema.SERIES_SCHEMA, schema.SERIES_DAYS_SCHEMA):
        assert not set(table_schema.names) & set(schema.FORBIDDEN_COLUMNS)
    assert schema.SERIES_SCHEMA.names == list(schema.SERIES_COLUMNS) and schema.SERIES_DAYS_SCHEMA.names == list(schema.SERIES_DAYS_COLUMNS)
    assert schema.SERIES_COLUMNS == ("series_key", *schema.ID_COLUMNS)
    assert schema.SERIES_DAYS_COLUMNS == ("series_key", "date_key", "activity_flag", "discount", "holiday_flag", "day_state", "band")
    assert [str(schema.SERIES_DAYS_SCHEMA.field(n).type) for n in ("series_key", "date_key", "day_state", "band", "discount")] == [
        "int32", "int32", "int8", "int8", "double"]


def test_is_forbidden_names_every_forbidden_column_and_nothing_else():
    assert all(schema.is_forbidden(name) for name in schema.FORBIDDEN_COLUMNS)
    assert not any(schema.is_forbidden(name) for name in (*schema.DAILY_KEPT, *schema.ID_COLUMNS, "hours_sale", "dt", "series_key"))


def test_the_date_key_is_the_day_as_yyyymmdd():
    from datetime import date

    assert schema.date_key(date(2024, 3, 28)) == 20240328 and schema.date_key("2024-07-02") == 20240702
    with pytest.raises(ValueError):
        schema.date_key("2024-7-2")


def test_a_source_error_carries_its_rule_and_the_exit_code_3():
    error = schema.SourceError("V04", "una lista no tiene 24 valores", [{"rule_id": "V04", "column": "hours_sale"}])
    assert str(error) == "V04: una lista no tiene 24 valores" and error.rule_id == "V04" and error.EXIT_CODE == 3
    assert error.problems == [{"rule_id": "V04", "column": "hours_sale"}] and schema.SourceError("V01", "x").problems == []
    assert isinstance(error, RuntimeError)


@pytest.mark.real_data
@pytest.mark.parametrize("path", [REAL_TRAIN, REAL_EVAL], ids=["train", "eval"])
def test_the_schema_is_the_one_of_the_real_files(path):
    """Read from the Parquet footer only: no value of eval.parquet is read (D17)."""
    assert pq.read_schema(path).remove_metadata().equals(schema.SOURCE_SCHEMA)
