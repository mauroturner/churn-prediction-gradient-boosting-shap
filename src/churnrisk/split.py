"""The split in time (RF14, D08, D44): the block of every cut and the purges between the blocks.

Blocks, by cut date: ``before`` (before ``train_first``), ``train``, ``purge_1`` (between training and V1), ``valid_v1``, ``valid_v2``,
``purge_2`` (between V2 and the test), ``test`` and ``post_test`` (after ``test_last``: scored and tracked, never evaluated). Every boundary
between two blocks of different use needs ``c_before + N <= c_after``: training to V1 and V2 to the test. V1 and V2 are both validation and
have no purge between them (D08). The window of the last test cut must end inside the data. The configuration checks all this when it is
loaded (D48); ``check_purges`` checks it again, for any horizon, before the cuts are written (the second line, as project 03's D78).
"""

from __future__ import annotations

from datetime import date, timedelta

from churnrisk.config import SealedConfig

BLOCKS = ("before", "train", "purge_1", "valid_v1", "valid_v2", "purge_2", "test", "post_test")
BLOCKS_ES = {
    "before": "antes del entrenamiento", "train": "entrenamiento", "purge_1": "purga antes de la validación", "valid_v1": "validación V1",
    "valid_v2": "validación V2", "purge_2": "purga antes de la prueba", "test": "prueba", "post_test": "posterior a la prueba (censurado)",
}


class PurgeError(ValueError):
    """A boundary between two blocks has no purge of at least N days, or the last test window ends after the data; the message names it."""


def block(cut: date, view: SealedConfig) -> str:
    """The block of `cut` (day 1 of a month)."""
    if cut.day != 1:
        raise ValueError(f"un corte es el día 1 de un mes, se recibió {cut}")
    s = view.split
    if cut < s.train_first:
        return "before"
    if cut <= s.train_last:
        return "train"
    if cut < s.v1_first:
        return "purge_1"
    if cut <= s.v1_last:
        return "valid_v1"
    if cut < s.v2_first:
        raise ValueError(f"el corte {cut} queda entre V1 y V2, que no tienen purga ni otro bloque entre ellos (D08)")
    if cut <= s.v2_last:
        return "valid_v2"
    if cut < s.test_first:
        return "purge_2"
    if cut <= s.test_last:
        return "test"
    return "post_test"


def is_censored(cut: date, view: SealedConfig, horizon_days: int | None = None) -> bool:
    """Whether the window of `cut` ends after the last date of the data, so its label is never complete (D44)."""
    n = view.label.horizon_days if horizon_days is None else horizon_days
    return cut + timedelta(days=n - 1) > view.deliveries.last_date


def blocks(view: SealedConfig) -> dict[date, str]:
    """The block of every cut of the configuration, in order."""
    from churnrisk.cuts import cut_dates   # cuts.py imports this module

    return {cut: block(cut, view) for cut in cut_dates(view)}


def check_purges(view: SealedConfig, horizon_days: int) -> None:
    """``PurgeError`` naming the boundary unless training to V1 and V2 to the test are purged by `horizon_days` and the last test window ends
    inside the data."""
    s, n = view.split, timedelta(days=horizon_days)
    for before, after, last, first in (("train", "valid_v1", s.train_last, s.v1_first), ("valid_v2", "test", s.v2_last, s.test_first)):
        if last + n > first:
            raise PurgeError(f"borde {before} → {after}: se esperaba una purga de N = {horizon_days} días: {last} + {horizon_days} días = {last + n} "
                             f"<= {first}, y no se cumple")
    end = s.test_last + n - timedelta(days=1)
    if end > view.deliveries.last_date:
        raise PurgeError(f"test_last: la ventana del último corte de prueba ({s.test_last}) termina el {end}, después del fin de los datos "
                         f"({view.deliveries.last_date})")
