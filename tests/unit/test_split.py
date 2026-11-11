"""The split in time (U10, AC11; RF14, D08): the blocks by cut date, a purge of at least N days at every boundary between two blocks, the
cuts of the purges in no block, and a configuration that breaks a boundary refused with the name of the boundary."""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta

import pytest

from churnrisk.config import SealedConfig
from churnrisk.cuts import cut_dates
from churnrisk.split import BLOCKS, PurgeError, block, blocks, check_purges, is_censored

SHA = "c" * 64
D = date


def view(cfg, **split) -> SealedConfig:
    """The sealed view, with some dates of [split] replaced without going through load_config (which refuses them first, D48)."""
    sealed = SealedConfig.of(cfg, SHA)
    return dataclasses.replace(sealed, split=dataclasses.replace(sealed.split, **split)) if split else sealed


# --- the RED of U10 -----------------------------------------------------------------------------------------------------


def test_every_block_boundary_has_a_purge_of_at_least_n_days(cfg):
    sealed = view(cfg)
    n = timedelta(days=sealed.label.horizon_days)
    check_purges(sealed, sealed.label.horizon_days)
    by_block: dict[str, list[date]] = {}
    for cut in cut_dates(sealed):
        by_block.setdefault(block(cut, sealed), []).append(cut)
    assert by_block == {
        "train": [D(2010, m, 1) for m in range(6, 13)], "purge_1": [D(2011, 1, 1), D(2011, 2, 1)], "valid_v1": [D(2011, 3, 1), D(2011, 4, 1)],
        "valid_v2": [D(2011, 5, 1)], "purge_2": [D(2011, 6, 1), D(2011, 7, 1)], "test": [D(2011, 8, 1), D(2011, 9, 1)],
        "post_test": [D(2011, 10, 1), D(2011, 11, 1), D(2011, 12, 1)],
    }
    # every boundary between two blocks of different use is purged by N days; V1 and V2 are both validation and have none (D08)
    for before, after in (("train", "valid_v1"), ("valid_v2", "test")):
        assert max(by_block[before]) + n <= min(by_block[after]), (before, after)
    assert max(by_block["train"]) + n == min(by_block["valid_v1"]), "2010-12-01 + 90 days = 2011-03-01: the purge is exact"
    # a configuration that breaks a boundary is refused, naming it
    with pytest.raises(PurgeError, match="train → valid_v1"):
        check_purges(view(cfg, train_last=D(2011, 1, 1)), 90)
    with pytest.raises(PurgeError, match="valid_v2 → test"):
        check_purges(view(cfg, v2_last=D(2011, 6, 1)), 90)
    with pytest.raises(PurgeError, match="test_last"):
        check_purges(view(cfg, test_last=D(2011, 10, 1)), 90)
    # a longer horizon breaks the boundary of the December cut (2010-12-01 + 120 days > 2011-03-01: the n120 variant, plan 17)
    with pytest.raises(PurgeError, match=r"train → valid_v1.*2010-12-01 \+ 120"):
        check_purges(sealed, 120)


def test_the_cuts_of_the_purges_belong_to_no_block_used_and_the_censored_ones_are_marked(cfg):
    sealed = view(cfg)
    table = blocks(sealed)
    assert list(table) == cut_dates(sealed) and set(table.values()) <= set(BLOCKS)
    used = {"train", "valid_v1", "valid_v2", "test"}
    for cut in (D(2011, 1, 1), D(2011, 2, 1), D(2011, 6, 1), D(2011, 7, 1)):
        assert table[cut] not in used
    assert [c for c in table if is_censored(c, sealed)] == [D(2011, 10, 1), D(2011, 11, 1), D(2011, 12, 1)], "their windows end after 2011-12-09"
    assert not is_censored(D(2011, 9, 1), sealed), "the last test cut's window ends on 2011-11-29"
    # a window that ends exactly on the last day of the data is complete; one day longer, it is censored
    assert not is_censored(D(2011, 9, 1), sealed, horizon_days=100) and is_censored(D(2011, 9, 1), sealed, horizon_days=101)
    assert block(D(2010, 5, 1), sealed) == "before"
    with pytest.raises(ValueError, match="día 1"):
        block(D(2011, 3, 2), sealed)
