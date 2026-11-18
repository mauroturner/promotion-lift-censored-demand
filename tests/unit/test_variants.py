"""The variants never choose (U11; AC23; D16, C10): no function that chooses reads their table or imports them, and they are computed only after the launch part of the
seal exists."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "promolift"
CHOOSING = ("recovery.py", "effect.py", "ranking.py", "forecast.py", "bootstrap.py", "masks.py", "launch.py", "daily.py", "days.py", "split.py")


def test_no_choosing_function_reads_a_variant_table():
    for name in CHOOSING:
        text = (SRC / name).read_text(encoding="utf-8")
        tree = ast.parse(text)
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imported |= {f"{node.module}.{alias.name}" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
        assert not any(m.endswith("variants") or ".variants" in m or m.endswith("evaluation") or m.endswith("reporting") for m in imported), name
        assert "eval_variants" not in text and "eval_criteria" not in text, name
    assert (SRC / "variants.py").is_file()
