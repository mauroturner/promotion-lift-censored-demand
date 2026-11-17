"""The contract of the source and of the canonical tables: the one place that names them (plan, section 6).

``SOURCE_SCHEMA`` is the schema of the two Parquet files of FreshRetailNet-50K, in file order and with the types pyarrow reads from them (checked
against both real files, U04): 19 columns, the 7 identifiers, the day ``dt`` as text, the 9 daily fields and the two hourly lists of 24 values.
``DAILY_KEPT`` are the three daily fields the pipeline uses; ``FORBIDDEN_COLUMNS`` are the six it never lets past the reader (the two sums contain the
sale of the hours a mask hides, and the weather is the day's own and differs between stores of one city, D05). ``TARGET_COLUMNS`` name the
quantities that must never be an input. The lists never share a name.
"""

from __future__ import annotations

from datetime import date

import pyarrow as pa

HOURS = 24

# the file's list element is named "element" (the Parquet standard), and the hourly status is a list of int64
SOURCE_SCHEMA = pa.schema([
    ("city_id", pa.int64()), ("store_id", pa.int64()), ("management_group_id", pa.int64()), ("first_category_id", pa.int64()),
    ("second_category_id", pa.int64()), ("third_category_id", pa.int64()), ("product_id", pa.int64()), ("dt", pa.string()),
    ("sale_amount", pa.float64()), ("hours_sale", pa.list_(pa.field("element", pa.float64()))), ("stock_hour6_22_cnt", pa.int32()),
    ("hours_stock_status", pa.list_(pa.field("element", pa.int64()))), ("discount", pa.float64()), ("holiday_flag", pa.int32()),
    ("activity_flag", pa.int32()), ("precpt", pa.float64()), ("avg_temperature", pa.float64()), ("avg_humidity", pa.float64()),
    ("avg_wind_level", pa.float64()),
])
SOURCE_COLUMNS: tuple[str, ...] = tuple(SOURCE_SCHEMA.names)
ID_COLUMNS: tuple[str, ...] = ("city_id", "store_id", "management_group_id", "first_category_id", "second_category_id", "third_category_id",
                               "product_id")
HOUR_COLUMNS: tuple[str, ...] = ("hours_sale", "hours_stock_status")
DAILY_COLUMNS: tuple[str, ...] = ("sale_amount", "stock_hour6_22_cnt", "discount", "holiday_flag", "activity_flag", "precpt", "avg_temperature",
                                  "avg_humidity", "avg_wind_level")
DAILY_KEPT: tuple[str, ...] = ("discount", "activity_flag", "holiday_flag")
# What must never reach a recovery, a counterfactual or a forecast (RNF06 a; D05): the sums of the hours and the weather
FORBIDDEN_COLUMNS: tuple[str, ...] = ("sale_amount", "stock_hour6_22_cnt", "precpt", "avg_temperature", "avg_humidity", "avg_wind_level")
# What the methods predict or are judged on: the sale of the hours a mask hides and the sale of the hours with stock
TARGET_COLUMNS: tuple[str, ...] = ("hidden_sale", "observed_instock")

# Arrow schemas of the two canonical tables (data/interim/series.parquet and series_days.parquet)
SERIES_COLUMNS: tuple[str, ...] = ("series_key", *ID_COLUMNS)
SERIES_SCHEMA = pa.schema([("series_key", pa.int32()), *[(name, pa.int64()) for name in ID_COLUMNS]])
SERIES_DAYS_COLUMNS: tuple[str, ...] = ("series_key", "date_key", "activity_flag", "discount", "holiday_flag", "day_state", "band")
SERIES_DAYS_SCHEMA = pa.schema([
    ("series_key", pa.int32()), ("date_key", pa.int32()), ("activity_flag", pa.int8()), ("discount", pa.float64()), ("holiday_flag", pa.int8()),
    ("day_state", pa.int8()), ("band", pa.int8()),
])


def is_forbidden(name: str) -> bool:
    """Whether a column name is one of ``FORBIDDEN_COLUMNS``."""
    return name in FORBIDDEN_COLUMNS


def date_key(day: date | str) -> int:
    """``YYYYMMDD`` as an int of a date or of a ``YYYY-MM-DD`` text (anything else is a ``ValueError``)."""
    if isinstance(day, str):
        day = date.fromisoformat(day) if len(day) == 10 and day[4] == "-" and day[7] == "-" else _bad(day)
    return day.year * 10_000 + day.month * 100 + day.day


def _bad(text: str) -> date:
    raise ValueError(f"se esperaba una fecha AAAA-MM-DD, se recibió {text!r}")


class SourceError(RuntimeError):
    """A rule of the source (V01 to V07) failed; the exit code of the command line is 3. ``problems`` says what, one dict per failing item
    (a rule, a column, a count: never a row's value)."""

    EXIT_CODE = 3

    def __init__(self, rule_id: str, message: str, problems: list[dict] | None = None) -> None:
        super().__init__(f"{rule_id}: {message}")
        self.rule_id = rule_id
        self.problems = problems if problems is not None else []
