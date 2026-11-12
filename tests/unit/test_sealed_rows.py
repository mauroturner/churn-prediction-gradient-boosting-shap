"""One rule for which rows of an evaluation fact a reader shows (R2-sealed-rows-docstring-mismatch of U23, R2-duplicated-sealed-filter of
U22): the sealed rows when there are any, else every row as it is. The site export and the HTML design both take it from
``export.prefer_sealed``; neither filters ``seal_state`` on its own."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

SRC = Path(__file__).resolve().parents[2] / "src" / "churnrisk"


def test_neither_the_site_export_nor_the_design_filters_the_sealed_rows_on_its_own():
    for module in ("site_export.py", "dashboard/render.py"):
        text = (SRC / module).read_text(encoding="utf-8")
        assert '["seal_state"] == "sealed"' not in text and "['seal_state'] == 'sealed'" not in text, f"{module} filters the sealed rows itself"


def test_prefer_sealed_gives_the_sealed_rows_or_else_every_row_whatever_its_state():
    from churnrisk.export import prefer_sealed

    both = pd.DataFrame({"seal_state": ["post_seal", "sealed", "post_seal", "sealed"], "v": [1, 2, 3, 4]})
    assert prefer_sealed(both)["v"].tolist() == [2, 4]
    after = pd.DataFrame({"seal_state": ["post_seal", "post_seal"], "v": [1, 2]})
    assert prefer_sealed(after)["v"].tolist() == [1, 2], "no sealed row: every row, post-seal ones included, labelled by their own state"
    plain = pd.DataFrame({"v": [5, 6]})
    assert prefer_sealed(plain)["v"].tolist() == [5, 6], "a fact with no seal_state column is returned whole"
    empty = pd.DataFrame(columns=["seal_state", "v"])
    assert prefer_sealed(empty).empty and list(prefer_sealed(empty).columns) == ["seal_state", "v"]
    assert "every row" in prefer_sealed.__doc__ and "post_seal" in prefer_sealed.__doc__, "the docstring says what the fallback returns"
