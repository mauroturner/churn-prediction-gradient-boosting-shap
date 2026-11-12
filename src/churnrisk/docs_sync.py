"""What ``python -m churnrisk docs-sync`` writes into the documentation (RF24, AC25, AC40; plan, section 25; D82, D87).

The results block of the README is the summary the ``report`` task writes (``reports/evaluation_summary.md``), copied between the
``results`` markers with the same ``sync_block`` the tests of U17 pin. The summary starts with its own ``## Resultados``: the README already
has the plan's ``## Los resultados`` above the block, so every heading of the summary goes one level down inside it and the README keeps
exactly the second-level headings of the plan. Nothing else of the summary changes, so a test can rebuild the summary from the block.
"""

from __future__ import annotations

import re
from pathlib import Path

from churnrisk.reporting import RESULTS_END, RESULTS_START, sync_block

_HEADING = re.compile(r"^(#+ )", flags=re.MULTILINE)


def readme_block(summary_md: str) -> str:
    """The summary as the README holds it: every Markdown heading one level down, the rest byte for byte."""
    return _HEADING.sub(r"#\1", summary_md)


def sync_readme(readme: Path, summary_md: Path) -> bool:
    """Copy `summary_md` into the results block of `readme`; True if the README changed (a second run changes nothing)."""
    return sync_block(Path(readme), RESULTS_START, RESULTS_END, readme_block(Path(summary_md).read_text(encoding="utf-8")))


__all__ = ["readme_block", "sync_readme"]
