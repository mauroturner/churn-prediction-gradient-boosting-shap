"""The peak memory of the process with the name of its counter (RNF03, AC40; D39; plan, section 22): every task of a run records it."""

from __future__ import annotations

import sys

from churnrisk import pipeline
from churnrisk.sysinfo import MemoryPeaks, peak_memory
from tests.fixtures.history import quick_config


def test_every_task_records_its_peak_with_its_counter(tmp_path):
    peaks = peak_memory()
    assert isinstance(peaks, MemoryPeaks) and peaks.working_set_mb > 0
    assert peaks.counter == ("PeakWorkingSetSize" if sys.platform == "win32" else "ru_maxrss")
    assert (peaks.commit_mb is not None and peaks.commit_mb > 0) == (sys.platform == "win32")
    cfg = quick_config(tmp_path)
    ctx = pipeline._context(cfg, "S1", pipeline.datetime.now(pipeline.UTC))
    spec = pipeline.TaskSpec("fetch_source", lambda ctx: {"rows": 3}, 0, 0, 1)
    result = pipeline._run_spec(spec, ctx)
    assert result["rows"] == 3 and result["peak_working_set_mb"] >= round(peaks.working_set_mb, 1) and result["memory_counter"] == peaks.counter
    assert result["seconds"] >= 0 and pipeline._read_state(ctx.state_path)["tasks"]["fetch_source"]["memory_counter"] == peaks.counter
