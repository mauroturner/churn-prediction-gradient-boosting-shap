"""No customer number of the fixture in any versioned byte or run log (plan, section 24.2: the class «un identificador en un archivo o en una
imagen publicada»; AC28, AC29, AC42; D26, D92). The fixture's customer numbers have 5 digits from 90001, outside the real range, so a search of
the bytes finds them (plan, section 24).

The quick replay of the session (``replay_states``: the documented replay up to the run that seals the test, and a failed task) wrote, under
``data/quick``, every file the versioned folders of the project hold: the Parquet of the star model, the site files and their manifests, the
summary, the seal, the validation reports with their examples and the HTML design; and the run states, tracebacks included. Each is read: the
text files byte by byte, the Parquet value by value (every integer and every text of every column) and through their metadata. What the
commands wrote to stdout and stderr is read too. The figures are those the session draws from the quick history's site files
(``figures_written``), byte by byte. The private fact, which does hold the customer numbers and is never versioned, is the control that the
search finds them where they are."""

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


def test_no_fixture_customer_id_in_any_versioned_byte_or_run_log(replay_states, quick_replay, small_truth, figures_written, fixture_truth):
    ids = set(small_truth.customer_ids)
    quick = Path(replay_states.quick)
    files = sorted(p for folder in (*VERSIONED, RUN_STATES) for p in (quick / folder).rglob("*") if p.is_file())
    names = {p.relative_to(quick).as_posix() for p in files}
    # the scan is not vacuous: the replay wrote every kind of file the plan names, the test part of the seal and a traceback included
    assert sum(n.endswith(".parquet") for n in names) == 26 and {"outputs/powerbi/manifest.json", "outputs/site/manifest.json"} <= names
    assert {f"outputs/site/{n}.json" for n in ("summary", "validation_rules", "label", "algorithms", "retention")} <= names
    assert {"reports/model_seal.json", "reports/evaluation_summary.json", "reports/evaluation_summary.md", "reports/validation/latest.json",
            "dashboard/powerbi-design.html"} <= names
    # seven run states: the launch, M1 (validated and left so), the four runs of the replays (M2011-08 to M2011-11) and the lone task that
    # failed; and a validation report (JSON and Markdown) for each run that validated a delivery
    assert sum(n.startswith("reports/validation/history/") for n in names) >= 10 and sum(n.startswith(RUN_STATES) for n in names) == 7
    assert '"test"' in (quick / "reports" / "model_seal.json").read_text(encoding="utf-8")
    assert json.loads((quick / "outputs" / "site" / "algorithms.json").read_text(encoding="utf-8"))["examples"], "the examples are published"
    assert any("Traceback" in (quick / n).read_text(encoding="utf-8") for n in names if n.startswith(RUN_STATES))
    found = {p.relative_to(quick).as_posix(): (in_parquet(p, ids) if p.suffix == ".parquet" else in_bytes(p.read_bytes(), ids)) for p in files}
    logs = [quick_replay.result, *replay_states.results]
    found |= {f"log {i}": in_bytes((r.out + r.err).encode("utf-8"), ids) for i, r in enumerate(logs)}
    assert {name: count for name, count in found.items() if count} == {}, "customer numbers of the fixture (how many in each file)"
    standard = set(fixture_truth.customer_ids)
    pictures = {name: in_bytes(data, standard) for name, data in figures_written[2].items()}
    assert len(pictures) == 7 and {name: count for name, count in pictures.items() if count} == {}
    # the control: the private fact, never versioned, holds them, and the same search finds them there
    assert in_parquet(quick / "outputs" / "private" / "fact_customer_cut.parquet", ids) > 0
