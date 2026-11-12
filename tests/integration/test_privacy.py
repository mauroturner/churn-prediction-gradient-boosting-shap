"""No customer number of the fixture in any versioned byte or run log (plan, section 24.2: the class «un identificador en un archivo o en una
imagen publicada»; AC28, AC29, AC42; D26, D92). The fixture's customer numbers have 5 digits from 90001, outside the real range, so a search of
the bytes finds them (plan, section 24).

Two sources, both built once per session and both written by the functions of the tasks:

- the quick replay of the session through the command line (``replay_states``: the launch and the monthly runs up to ``M2011-10``, and a task
  that failed), which wrote, under ``data/quick``, every kind of file the versioned folders of the project hold (the Parquet of the star model,
  the site files and their manifests, the summary, the seal, the validation reports with their examples and the HTML design), the run states,
  a traceback included, and what the commands wrote to stdout and stderr;
- the sealed quick history (``quick_history``: the whole plan, the test sealed), for what only exists once the test is sealed: the test part
  of the seal, the sealed rows of the star model (``star_files``), the examples of the site (``site_files``), the sealed summary, the HTML of
  that run and the seven figures (``figures_written``).

The text files are read byte by byte and the Parquet value by value (every integer and every text of every column) and through their
metadata. The private fact, which does hold the customer numbers and is never versioned, is the control that the search finds them."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pyarrow.parquet as pq

# a number of five digits on its own: not part of a longer number, a decimal, a run key or a hexadecimal hash (a SHA-256 can hold «c90050f»)
FIVE_DIGITS = re.compile(rb"(?<![0-9A-Za-z.])(\d{5})(?![0-9A-Za-z.])")
VERSIONED = ("outputs/powerbi", "outputs/site", "reports", "dashboard")     # under data/quick, the folders the project versions
RUN_STATES = "interim/runs"


def in_bytes(data: bytes, ids: set[int]) -> int:
    return len({int(n) for n in FIVE_DIGITS.findall(data)} & ids)


def in_parquet(path: Path, ids: set[int]) -> int:
    """Customer numbers in a Parquet file: in its metadata, as a whole integer of any column or inside any text."""
    table = pq.read_table(path)
    found = in_bytes(b" ".join(k + b"=" + v for k, v in (table.schema.metadata or {}).items()), ids)
    for column in table.columns:
        for value in column.to_pylist():
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, int) and value in ids:
                found += 1
            elif isinstance(value, str):
                found += in_bytes(value.encode("utf-8"), ids)
    return found


def in_file(path: Path, ids: set[int]) -> int:
    return in_parquet(path, ids) if path.suffix == ".parquet" else in_bytes(path.read_bytes(), ids)


def sealed_outputs(quick_history, star_files, site_files, tmp_path: Path) -> dict[str, bytes | Path]:
    """What the sealed quick history publishes: its Parquet and site files, its seal, its summary and the HTML of its last run."""
    from churnrisk.dashboard.render import render_design
    from churnrisk.dashboard.semantic_model import MODEL
    from churnrisk.reporting import build_summary, summary_markdown
    from churnrisk.warehouse import connect

    cfg, out_dir, private_dir, _paths, meta, warehouse = star_files
    files: dict[str, bytes | Path] = {f"powerbi/{p.name}": p for p in sorted(Path(out_dir).iterdir())}
    files |= {f"site/{p.name}": p for p in sorted(Path(site_files).iterdir())}
    files["seal"] = Path(quick_history.cfg.paths.seal)
    conn = connect(warehouse)
    try:
        summary = build_summary(conn, cfg, run_key=meta.run_key, as_of=meta.as_of, source_sha256=meta.source_sha256)
    finally:
        conn.close()
    assert summary["evaluation_status"] == "sealed"
    files["summary.json"] = json.dumps(summary, ensure_ascii=False).encode("utf-8")
    files["summary.md"] = summary_markdown(summary).encode("utf-8")
    files["html"] = render_design(MODEL, out_dir, private_dir, tmp_path / "powerbi-design.html", meta, min_cell_customers=cfg.site.min_cell_customers)
    return files


def test_no_fixture_customer_id_in_any_versioned_byte_or_run_log(replay_states, quick_replay, small_truth, quick_history, star_files, site_files,
                                                                    figures_written, fixture_truth, tmp_path):
    # the quick replay through the command line, on the small fixture
    ids = set(small_truth.customer_ids)
    quick = Path(replay_states.quick)
    files = sorted(p for folder in (*VERSIONED, RUN_STATES) for p in (quick / folder).rglob("*") if p.is_file())
    names = {p.relative_to(quick).as_posix() for p in files}
    assert sum(n.endswith(".parquet") for n in names) == 26 and {"outputs/powerbi/manifest.json", "outputs/site/manifest.json"} <= names
    assert {f"outputs/site/{n}.json" for n in ("summary", "validation_rules", "label", "algorithms", "retention")} <= names
    assert {"reports/model_seal.json", "reports/evaluation_summary.json", "reports/evaluation_summary.md", "reports/validation/latest.json",
            "dashboard/powerbi-design.html"} <= names
    # six run states: the launch, M1 (validated and left so), the three runs of the replays (M2011-08 to M2011-10) and the lone task that
    # failed; and a validation report (JSON and Markdown) for each run that validated a delivery
    assert sum(n.startswith("reports/validation/history/") for n in names) >= 8 and sum(n.startswith(RUN_STATES) for n in names) == 6
    assert any("Traceback" in (quick / n).read_text(encoding="utf-8") for n in names if n.startswith(RUN_STATES))
    found = {p.relative_to(quick).as_posix(): in_file(p, ids) for p in files}
    found |= {f"log {i}": in_bytes((r.out + r.err).encode("utf-8"), ids) for i, r in enumerate([quick_replay.result, *replay_states.results])}
    assert {name: count for name, count in found.items() if count} == {}, "customer numbers of the fixture (how many in each file)"
    assert in_parquet(quick / "outputs" / "private" / "fact_customer_cut.parquet", ids) > 0, "the control: the private fact holds them"
    # what only the sealed test publishes, from the quick history on the standard fixture
    standard = set(fixture_truth.customer_ids)
    sealed = sealed_outputs(quick_history, star_files, site_files, tmp_path)
    assert '"test"' in sealed["seal"].read_text(encoding="utf-8") and json.loads(sealed["site/algorithms.json"].read_text(encoding="utf-8"))["examples"]
    assert sum(name.endswith(".parquet") for name in sealed) == 26 and len(figures_written[2]) == 7
    found = {name: (in_bytes(item, standard) if isinstance(item, bytes) else in_file(item, standard)) for name, item in sealed.items()}
    found |= {f"figure {name}": in_bytes(data, standard) for name, data in figures_written[2].items()}
    assert {name: count for name, count in found.items() if count} == {}, "customer numbers of the fixture (how many in each file)"
    assert in_parquet(Path(star_files[2]) / "fact_customer_cut.parquet", standard) > 0, "the control: the private fact holds them"
