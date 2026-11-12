"""The figures of the documentation (U28, AC42; RF29; plan, section 25; D84), drawn with matplotlib from the verified site files of the quick
history (``site_files``): the seven files, the data behind each one, nothing drawn from another source, a hidden cell drawn as a gap, the
figures of the test saying so before the seal, and nothing written when a file is not the one its manifest names. Adapted from project 03's
``tests/unit/test_figures.py``."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib.image as mpimg
import pytest

from churnrisk import figures
from churnrisk.site_export import SiteSetError

EXPECTED = ["churn_by_cut.png", "label_n_by_m.png", "gain_curve.png", "cost_curve.png", "calibration.png", "shap_importance.png", "retention_by_cut.png"]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FIGURES_PY = Path(__file__).resolve().parents[2] / "src" / "churnrisk" / "figures.py"


def refresh_manifest(folder: Path) -> None:
    """The manifest of `folder` rewritten for the bytes its files hold now: a test that edits a site file keeps the folder one export."""
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    for name in manifest["files"]:
        data = (folder / name).read_bytes()
        manifest["files"][name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture(scope="module")
def site(site_files) -> dict:
    return figures.load_site(site_files)


@pytest.fixture(scope="module")
def drawn(site) -> dict:
    return figures.draw_all(site)


@pytest.fixture(scope="module")
def written(figures_written):
    """The seven files written once from the site files into a folder that held a figure of an earlier run: ``(folder, paths, {name: bytes})``
    (the session's ``figures_written``, which the test of privacy reads too)."""
    return figures_written


# --- the RED of U28 ----------------------------------------------------------------------------------------------------------------------


def test_figures_are_drawn_only_from_the_verified_site_files(written, site_files, tmp_path):
    """AC42 (project 03, D77): the seven PNG files come from the site files read through ``read_site`` (each checked against
    ``manifest.json``), the module reads nothing else (no warehouse, no Parquet, no customer-level fact), and a folder whose file is not the
    one its manifest names is refused with nothing written."""
    out, paths, _bytes = written
    assert [p.name for p in paths] == EXPECTED == list(figures.FIGURE_NAMES)
    assert sorted(p.name for p in out.iterdir()) == sorted(EXPECTED), "nothing else, not even a temporary file"
    for path in paths:
        assert path.read_bytes()[:8] == PNG_SIGNATURE
        height, width = mpimg.imread(path).shape[:2]
        assert width >= 900 and height >= 450, "readable at the full width of a README"
    tree = ast.parse(FIGURES_PY.read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not imported & {"sqlite3", "pandas", "pyarrow", "churnrisk.warehouse", "churnrisk.export", "churnrisk.pipeline"}, imported
    assert "read_site" in {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "churnrisk.site_export" for a in n.names}
    mixed = tmp_path / "mixed"
    shutil.copytree(site_files, mixed)
    document = json.loads((mixed / "label.json").read_text(encoding="utf-8"))
    document["rates_by_cut"][0]["churn_rate"] = 0.999
    (mixed / "label.json").write_text(json.dumps(document), encoding="utf-8")       # the manifest still names the old bytes
    with pytest.raises(SiteSetError, match="label.json"):
        figures.make_figures(mixed, tmp_path / "out")
    assert not (tmp_path / "out").exists()


# --- the files ----------------------------------------------------------------------------------------------------------------------------


def test_drawing_twice_gives_the_same_files_and_a_figure_changes_only_with_its_data(site_files, drawn, written, tmp_path):
    again = {name: figures._png(figure) for name, figure in drawn.items()}      # the module's second drawing of the same files, rendered
    assert again == written[2], "a versioned figure changes only when its data do"
    changed = tmp_path / "site"
    shutil.copytree(site_files, changed)
    document = json.loads((changed / "algorithms.json").read_text(encoding="utf-8"))
    document["importance"][0]["mean_abs_shap"] += 0.5
    (changed / "algorithms.json").write_text(json.dumps(document), encoding="utf-8")
    refresh_manifest(changed)
    new = {p.name: p.read_bytes() for p in figures.make_figures(changed, tmp_path / "b")}
    assert {name for name in EXPECTED if new[name] != written[2][name]} == {"shap_importance.png"}


def test_nothing_is_written_if_a_figure_fails_or_a_site_file_is_missing(site_files, tmp_path, monkeypatch):
    out = tmp_path / "figures"
    monkeypatch.setattr(figures, "draw_calibration", lambda _site: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        figures.make_figures(site_files, out)
    assert not out.exists()
    monkeypatch.undo()
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(FileNotFoundError, match=r"label\.json.*python -m churnrisk run"):
        figures.make_figures(bare, out)
    assert not out.exists()


def test_nothing_is_written_if_one_of_the_files_cannot_be_written(site_files, tmp_path, monkeypatch):
    """R2-figures-makefigures-atomicity-doc (U28): a write that fails halfway (a full disk, a permission) replaces no figure of an earlier run, leaves no
    temporary file and no new folder behind: the files are all staged first and replaced only when every one was written."""
    out = tmp_path / "figures"
    out.mkdir()
    (out / "gain_curve.png").write_bytes(b"old")
    real, calls = Path.write_bytes, []

    def write_bytes(self, data):
        if self.name.endswith(".tmp") and ".png." in self.name:
            calls.append(self.name)
            if len(calls) == 4:
                raise OSError(28, "No space left on device")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", write_bytes)
    with pytest.raises(OSError, match="No space left"):
        figures.make_figures(site_files, out)
    assert len(calls) == 4, "the fourth file was the one that failed"
    assert {p.name: p.read_bytes() for p in out.iterdir()} == {"gain_curve.png": b"old"}, "no figure replaced and no temporary file left"
    fresh = tmp_path / "fresh"
    calls.clear()
    with pytest.raises(OSError, match="No space left"):
        figures.make_figures(site_files, fresh)
    assert not fresh.exists(), "a folder the call created is removed with the files it never got"


# --- the data behind each figure ------------------------------------------------------------------------------------------------------


def test_the_churn_figure_draws_the_rate_of_every_cut_with_a_label_and_leaves_the_others_as_gaps(drawn, site):
    [ax] = drawn["churn_by_cut.png"].axes
    rows = site["label"]["rates_by_cut"]
    assert [p.get_height() for p in ax.patches] == [0.0 if r["churn_rate"] is None else r["churn_rate"] for r in rows]
    assert [t.get_text() for t in ax.get_xticklabels()] == [r["cut"][:7] for r in rows]
    assert any(r["churn_rate"] is None for r in rows), "the censored cuts have no label: drawn as gaps"


def test_the_definition_figure_draws_the_rate_for_each_n_and_m_and_the_silences_that_return(drawn, site):
    left, right = drawn["label_n_by_m.png"].axes
    cells = site["label"]["n_by_m"]
    assert sorted(p.get_height() for p in left.patches) == sorted(c["churn_rate"] for c in cells)
    returns = site["label"]["silence_return"]
    assert [p.get_height() for p in right.patches] == [r["return_share"] for r in returns]
    assert [t.get_text() for t in right.get_xticklabels()] == [f"N = {r['n']}" for r in returns]


def test_the_gain_figure_draws_each_method_of_the_test_against_the_line_of_contacting_at_random(drawn, site):
    [ax] = drawn["gain_curve.png"].axes
    methods = list(dict.fromkeys(g["method"] for g in site["algorithms"]["gain"]))
    lines = ax.lines
    assert len(lines) == len(methods) + 1
    for line, method in zip(lines, methods, strict=False):
        rows = [g for g in site["algorithms"]["gain"] if g["method"] == method]
        assert list(line.get_xdata()) == [0.0] + [g["share_contacted"] for g in rows] and list(line.get_ydata()) == [0.0] + [g["share_captured"] for g in rows]
    assert list(lines[-1].get_xdata()) == [0.0, 1.0] == list(lines[-1].get_ydata())


def test_the_cost_figure_draws_the_model_and_b_star_at_each_break_even_and_marks_the_assumed_one(drawn, site):
    [ax] = drawn["cost_curve.png"].axes
    rows = site["algorithms"]["cost_curve"]
    model, b_star, assumed = ax.lines
    assert list(model.get_xdata()) == [r["break_even"] for r in rows] and list(model.get_ydata()) == [r["nb_model"] for r in rows]
    assert list(b_star.get_ydata()) == [r["nb_b_star"] for r in rows]
    assert list(assumed.get_xdata()) == [site["algorithms"]["threshold"]["break_even"]] * 2


def test_the_calibration_figure_draws_the_bins_the_site_publishes_on_the_diagonal(drawn, site):
    [ax] = drawn["calibration.png"].axes
    shown = [c for c in site["algorithms"]["calibration"] if not c["suppressed"]]
    points, diagonal = ax.lines
    assert list(points.get_xdata()) == [c["p_mean"] for c in shown] and list(points.get_ydata()) == [c["observed"] for c in shown]
    assert list(diagonal.get_xdata()) == [0.0, 1.0]


def test_the_importance_figure_draws_the_mean_absolute_shap_of_each_feature(drawn, site):
    [ax] = drawn["shap_importance.png"].axes
    rows = site["algorithms"]["importance"]
    assert [p.get_width() for p in ax.patches] == [r["mean_abs_shap"] for r in rows]
    assert [t.get_text() for t in ax.get_yticklabels()] == [r["feature_es"] for r in rows]


def test_the_retention_figure_draws_the_contacts_of_each_cut_and_who_churned_against_who_was_expected(drawn, site):
    left, right = drawn["retention_by_cut.png"].axes
    cuts = site["retention"]["cuts"]
    contacted = [0.0 if c["contacted"] is None else c["contacted"] for c in cuts]
    rest = [0.0 if c["scored"] is None or c["contacted"] is None else c["scored"] - c["contacted"] for c in cuts]
    assert [p.get_height() for p in left.patches] == rest + contacted
    expected, observed = right.lines
    last = [c["by_as_of"][-1] for c in cuts]
    assert list(expected.get_ydata()) == [r["expected_churners"] for r in last]
    shown = [(i, r["churned"]) for i, r in enumerate(last) if r["churned"] is not None]
    assert list(observed.get_xdata()) == [i for i, _ in shown] and list(observed.get_ydata()) == [v for _, v in shown]


# --- before the seal and with a hidden cell ----------------------------------------------------------------------------------------------


def test_before_the_seal_the_figures_of_the_test_say_so_instead_of_staying_empty(site):
    early = json.loads(json.dumps(site))
    early["algorithms"].update(gain=[], calibration=[])           # what the site publishes until the test is sealed (D17)
    made = figures.draw_all(early)
    for name in ("gain_curve.png", "calibration.png"):
        assert {" ".join(t.get_text().split()) for ax in made[name].axes for t in ax.texts} == {figures.PENDING}, name
    assert made["churn_by_cut.png"].axes[0].patches and made["cost_curve.png"].axes[0].lines, "what exists is still drawn"


def test_a_hidden_cell_is_a_gap_and_never_a_number(site):
    hidden = json.loads(json.dumps(site))
    hidden["label"]["rates_by_cut"][0].update(suppressed=True, customers=None, churn_rate=None)
    hidden["algorithms"]["calibration"][0].update(suppressed=True, rows=None, p_mean=None, observed=None)
    hidden["retention"]["cuts"][0].update(scored=None, contacted=None, contact_share=None)
    made = figures.draw_all(hidden)
    churn = made["churn_by_cut.png"].axes[0]
    assert churn.patches[0].get_height() == 0.0 and any(t.get_text() == "celda oculta" for t in churn.texts)
    shown = [c for c in site["algorithms"]["calibration"] if not c["suppressed"]]
    assert len(made["calibration.png"].axes[0].lines[0].get_xdata()) == len(shown) - 1, "the hidden bin is not drawn"
    left = made["retention_by_cut.png"].axes[0]
    assert left.patches[0].get_height() == 0.0 and any(t.get_text() == "celda oculta" for t in left.texts)


def test_a_hidden_cell_of_the_definition_figure_is_a_gap_and_never_a_number(site):
    """R3-1 (U28): a rate of ``n_by_m`` or a return share of ``silence_return`` that the site publishes as ``null`` is drawn as the other figures draw a
    hidden cell (no bar height, ``celda oculta``), never as a number and never as an error."""
    hidden = json.loads(json.dumps(site))
    hidden["label"]["n_by_m"][0]["churn_rate"] = None
    hidden["label"]["silence_return"][0]["return_share"] = None
    left, right = figures.draw_all(hidden)["label_n_by_m.png"].axes
    cells = site["label"]["n_by_m"]
    assert sorted(p.get_height() for p in left.patches) == sorted([0.0] + [c["churn_rate"] for c in cells[1:]])
    assert any(t.get_text() == "celda oculta" for t in left.texts), "the empty cell says why it is empty"
    returns = site["label"]["silence_return"]
    assert [p.get_height() for p in right.patches] == [0.0] + [r["return_share"] for r in returns[1:]]
    assert sum(t.get_text() == "celda oculta" for t in right.texts) == 1 and not any("None" in t.get_text() for t in left.texts + right.texts)


DRAW_IN_ANOTHER_PROCESS = """
import json
import sys
import types
from pathlib import Path
reader = types.ModuleType("churnrisk.site_export")      # drawing does not depend on the reader of the site files, which pulls in scikit-learn (2 s)
reader.SiteSetError, reader.read_site = FileNotFoundError, None
sys.modules["churnrisk.site_export"] = reader
from churnrisk import figures
folder, out = Path(sys.argv[1]), Path(sys.argv[2])
site = {key: json.loads((folder / f"{key}.json").read_text(encoding="utf-8")) for key in ("label", "algorithms")}
out.mkdir()
for name, draw, key in (("gain_curve.png", figures.draw_gain_curve, "algorithms"), ("churn_by_cut.png", figures.draw_churn_by_cut, "label")):
    (out / name).write_bytes(figures._png(draw(site[key])))
"""


def test_a_figure_drawn_in_another_process_later_is_the_same_bytes(site_files, written, tmp_path):
    """R3-3 (U28): the claim is that a PNG carries no timestamp or program version, so it is the same file in a new process some seconds later (the metadata of
    a PNG has a one-second clock): two figures drawn here and by a separate ``python`` are byte for byte the same, not only two renderings of one process."""
    env = {**os.environ, "PYTHONPATH": str(FIGURES_PY.parents[1]), "PYTHONHASHSEED": "random"}
    done = subprocess.run([sys.executable, "-c", DRAW_IN_ANOTHER_PROCESS, str(site_files), str(tmp_path / "other")], env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    for name in ("gain_curve.png", "churn_by_cut.png"):
        assert (tmp_path / "other" / name).read_bytes() == written[2][name], name
