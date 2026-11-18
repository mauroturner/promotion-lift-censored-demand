"""What the tests that launch the model share (U09): the run they launch as and the call."""

from __future__ import annotations

from datetime import datetime

from promolift.cube import store_delivery_cube
from promolift.launch import fit_model
from promolift.registry import RunMeta

RUN = RunMeta("run-launch", datetime(2024, 6, 26))


def launch(cfg, conn, truth, **kwargs):
    """``fit_model`` of the fixture `truth` as the run of the launch."""
    return fit_model(cfg, conn, RUN, train_sha256=truth.train_sha256, eval_sha256=truth.eval_sha256, **kwargs)


def rebuilt_interim(published, folder, modify=None):
    """The cube of every delivery of the plan stored in `folder`, with `modify(date_keys, sales)` applied to each delivery's sales first."""
    for spec in published.plan:
        _entry, _days, (date_keys, sales, stock) = published.items[spec.delivery_id]
        store_delivery_cube(folder, spec.delivery_id, date_keys, sales if modify is None else modify(spec.delivery_id, date_keys, sales.copy()), stock)
    return folder
