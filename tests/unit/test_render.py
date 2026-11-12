"""The HTML design of the report (U22, AC28; RF26; D26, D72): every page, visual, measure, parameter and relationship of the specification;
nothing loaded from outside and no script; under 2 MB; text from the data escaped; the customer column of the list masked, and no customer
number of the fixture anywhere in its bytes."""

from __future__ import annotations

import dataclasses
import html as html_lib
import re
import shutil
from pathlib import Path

import pandas as pd
import pytest

from churnrisk.dashboard.render import MASK, mask, render_design
from churnrisk.dashboard.semantic_model import MODEL, Visual
from churnrisk.ingest import ATTRIBUTION

EVIL_COUNTRY = "<script>alert(1)</script>"
EVIL_RULE = "<img src=x onerror=alert(1)>"


@pytest.fixture(scope="module")
def design(star_files, tmp_path_factory) -> tuple[Path, str]:
    """The design rendered once for this module from the session's star model (``rendered_html``, plan 24.1)."""
    cfg, out_dir, private_dir, _paths, meta, _w = star_files
    path = render_design(MODEL, out_dir, private_dir, tmp_path_factory.mktemp("design") / "dashboard" / "powerbi-design.html", meta,
                         min_cell_customers=cfg.site.min_cell_customers)
    return path, path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def evil(star_files, tmp_path_factory) -> str:
    """The same files with text that would run if a page took it as it is: a country and the name of a rule."""
    _cfg, out_dir, private_dir, _paths, meta, _w = star_files
    folder = tmp_path_factory.mktemp("evil")
    shutil.copytree(out_dir, folder / "powerbi")
    shutil.copytree(private_dir, folder / "private")
    country = pd.read_parquet(folder / "powerbi" / "dim_country.parquet")
    country["country_es"] = EVIL_COUNTRY
    country.to_parquet(folder / "powerbi" / "dim_country.parquet", index=False)
    rules = pd.read_parquet(folder / "powerbi" / "fact_validation.parquet")
    if rules.empty:                          # a quick history validates nothing: one rule row of a run, so its name reaches the page
        rules = pd.DataFrame([{**{c: None for c in rules.columns}, "run_key": "r9", "rule_id": "V10", "severity": "bloqueante", "status": "falla"}])
    rules["name_es"] = EVIL_RULE
    rules.to_parquet(folder / "powerbi" / "fact_validation.parquet", index=False)
    return render_design(MODEL, folder / "powerbi", folder / "private", folder / "evil.html", meta, min_cell_customers=1).read_text(encoding="utf-8")


def text_of(html: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", " ", html))


# --- the RED of U22 -------------------------------------------------------------------------------------------------------------


def test_html_has_every_page_escapes_data_text_and_masks_the_customer_column(design, evil, star_files, fixture_truth):
    """AC28: every page, visual, measure, parameter and relationship is in the document; a country or a rule name holding markup is shown as
    text, never as markup; the list of page 1 has its customer column masked, one «•» per digit; and no customer number of the fixture appears
    in the document's bytes."""
    _path, html = design
    text = text_of(html)
    for number, page in enumerate(MODEL.pages, start=1):
        assert f"Página {number}: {page.name_es}" in text
        for v in page.visuals:
            assert f'aria-label="{html_lib.escape(v.title_es)}"' in html, v.title_es
    for m in MODEL.measures:
        assert f"{m.name_es} =\n" in text, m.name_es
    for p in MODEL.parameters:
        assert p.name_es in text and p.generateseries() in text, p.name_es
    for r in MODEL.relationships:
        assert r.rel_id in text, r.rel_id
    assert EVIL_COUNTRY not in evil and html_lib.escape(EVIL_COUNTRY) in evil
    assert EVIL_RULE not in evil and html_lib.escape(EVIL_RULE) in evil
    _cfg, _out, private_dir, _paths, _meta, _w = star_files
    customers = pd.read_parquet(private_dir / "fact_customer_cut.parquet")
    last = customers[customers["cut_key"] == customers["cut_key"].max()]
    masked = re.findall(r'<span class="masked">([^<]*)</span>', html)
    assert len(masked) == min(len(last), 14) and all(m == MASK * 5 for m in masked), masked[:3]
    assert mask(90123) == "•••••" and mask(123456) == "••••••"
    found = {int(n) for n in re.findall(r"(?<!\d)(\d{5})(?!\d)", html)} & set(fixture_truth.customer_ids)
    assert not found, f"customer numbers in the design: {sorted(found)[:5]}"


# --- the document ---------------------------------------------------------------------------------------------------------------


def test_nothing_is_loaded_from_outside_there_is_no_script_and_it_weighs_under_2_mb(design):
    path, html = design
    assert path.stat().st_size < 2 * 1024 * 1024
    assert "<script" not in html.lower() and "javascript:" not in html.lower()
    for attribute in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert attribute.startswith("#"), attribute
    assert not re.search(r"@import|url\((?!#)", html), "no stylesheet or image from outside"
    assert html.startswith("<!doctype html>\n<html lang=\"es\">") and html.count("<html") == 1


def test_it_states_the_run_the_attribution_and_what_was_not_verified(design, star_files):
    _cfg, _out, _private, _paths, meta, _w = star_files
    text = text_of(design[1])
    assert meta.run_key in text and meta.as_of.isoformat() in text and ATTRIBUTION in text
    assert "Ninguna medida se ejecutó" in text and "Los costos son supuestos" in text and "Contactos con el panel" in text
    assert "outputs/private" in text and "enmascarada" in text


def test_every_table_has_its_power_query_from_the_right_folder(design):
    text = text_of(design[1])
    for table in MODEL.tables:
        folder = "CarpetaPrivada" if table.private else "CarpetaSalidas"
        assert f'Parquet.Document(File.Contents({folder} & "\\{table.name}.parquet"))' in text, table.name


def test_rendering_twice_gives_the_same_bytes(design, star_files, tmp_path):
    cfg, out_dir, private_dir, _paths, meta, _w = star_files
    again = render_design(MODEL, out_dir, private_dir, tmp_path / "again.html", meta, min_cell_customers=cfg.site.min_cell_customers)
    assert again.read_bytes() == design[0].read_bytes()


def test_the_cards_of_page_1_are_the_figures_of_the_last_scored_cut(design, star_files):
    _cfg, _out, private_dir, _paths, _meta, _w = star_files
    customers = pd.read_parquet(private_dir / "fact_customer_cut.parquet")
    last = customers[customers["cut_key"] == customers["cut_key"].max()]
    html = design[1]

    def card(title: str) -> str:
        block = html.split(f'aria-label="{html_lib.escape(title)}"', 1)[1]
        return html_lib.unescape(re.search(r'<div class="big">([^<]*)</div>', block).group(1))

    assert card("Clientes puntuados") == f"{len(last):,}".replace(",", ".")
    assert card("Contactos (umbral sellado)") == str(int(last["is_contact"].sum()))
    assert card("Riesgo medio") == f"{last['risk'].mean() * 100:.1f} %".replace(".", ",")
    assert card("Contactos con el panel") == str(int((last["risk"] >= 0.5).sum())), "the panel starts at the sealed break-even, 0.5"


def test_a_minimum_cell_that_is_not_a_positive_integer_and_an_incoherent_model_write_nothing(star_files, tmp_path):
    _cfg, out_dir, private_dir, _paths, meta, _w = star_files
    for bad in (0, -1, 2.5, True):
        with pytest.raises(ValueError, match="min_cell_customers"):
            render_design(MODEL, out_dir, private_dir, tmp_path / "x.html", meta, min_cell_customers=bad)
    broken = dataclasses.replace(MODEL, pages=(dataclasses.replace(MODEL.pages[0], visuals=(Visual("card", "a", ("[No hay tal]",), 0, 0, 2, 1),)),))
    with pytest.raises(ValueError, match="incoherente"):
        render_design(broken, out_dir, private_dir, tmp_path / "x.html", meta)
    assert not (tmp_path / "x.html").exists()


def test_without_exported_files_the_whole_document_is_still_written_with_empty_previews(star_files, tmp_path):
    _cfg, _out, _private, _paths, meta, _w = star_files
    html = render_design(MODEL, tmp_path / "none", tmp_path / "none_private", tmp_path / "empty.html", meta).read_text(encoding="utf-8")
    assert all(f"Página {i}: {p.name_es}" in text_of(html) for i, p in enumerate(MODEL.pages, start=1))
    assert 'class="masked"' not in html
