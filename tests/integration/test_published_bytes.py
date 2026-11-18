"""Nothing of this computer is in what is published (U14; RNF12; AC26; project 05's D43): not the path of a folder, not the user's name, not the host."""

from __future__ import annotations

import socket
from pathlib import Path

from promolift.reporting import build_summary, write_summary
from promolift.warehouse import connect


def test_published_files_carry_no_local_path(star_export, site_files, rendered_html, figures_written_for_bytes, evaluated_week, tmp_path):
    conn = connect(star_export.db)
    try:
        summary = build_summary(conn, star_export.view, run=star_export.run, seal_path=star_export.seal)
    finally:
        conn.close()
    reports = write_summary(summary, tmp_path / "reports")
    published = [*star_export.out.iterdir(), *site_files.out.iterdir(), rendered_html.path, star_export.seal, *reports, *figures_written_for_bytes]
    assert len(published) > 40
    needles = {str(Path(p)) for p in (star_export.folder, site_files.out, rendered_html.path.parent, tmp_path, star_export.cfg.paths.interim_dir)}
    needles |= {n.replace("\\", "/") for n in needles} | {n.replace("\\", "\\\\") for n in needles}
    needles |= {Path.home().name, socket.gethostname(), "C:\\", "C:/", "/Users/", "/home/", "AppData", "pytest-of-"}
    for path in published:
        data = path.read_bytes()
        for needle in needles:
            if needle and len(needle) > 3:
                assert needle.encode("utf-8") not in data and needle.encode("utf-16-le") not in data, (path.name, needle)
