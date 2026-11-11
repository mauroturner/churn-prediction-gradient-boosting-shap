"""The contract of the source and of the canonical lines: the one place that names them (plan, section 6).

U04 brings the error of a source rule; U05 adds the workbook's columns, the code kinds and the lists of allowed, label and identifier columns.
"""

from __future__ import annotations

from typing import Any


class SourceError(RuntimeError):
    """A rule of the source (V01 to V06) failed; ``problems`` says what, one dict per failing item (never a customer number or an invoice)."""

    def __init__(self, rule_id: str, message: str, problems: list[dict[str, Any]] | None = None) -> None:
        super().__init__(f"{rule_id}: {message}")
        self.rule_id = rule_id
        self.problems = problems if problems is not None else []
