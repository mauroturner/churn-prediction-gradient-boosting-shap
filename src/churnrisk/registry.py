"""The artifact of the frozen model, loaded only when its bytes still have the registered SHA-256 (M03, AC23; D40; plan, section 15).
Adapted from project 03's ``registry.py`` (its D30), with its seal (D17, D64, D78, D89) over the sealed view of D19.

``pickle`` runs code when it loads, so a file that someone replaced must never reach it. ``load_artifact`` reads the bytes of the file
**once**, computes their SHA-256, compares it with the registered one and only then hands *those same bytes* to ``pickle.loads``: there is no
window between checking and loading, and nothing is unpickled from a file whose fingerprint is not the registered one. The fingerprint
protects against a file that was replaced or damaged; it does not make ``pickle`` safe against someone who can rewrite the file and the
registry together (D40). The SHAP explainer is not saved: it is rebuilt from the model.
"""

from __future__ import annotations

import dataclasses
import errno
import hashlib
import hmac
import json
import logging
import math
import os
import pickle
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from churnrisk.bgnbd import BGNBDParams
from churnrisk.config import SealedConfig
from churnrisk.files import write_atomic

logger = logging.getLogger(__name__)

PICKLE_PROTOCOL = 5
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ArtifactMismatchError(RuntimeError):
    """M03: the artifact does not have the registered SHA-256; it was not deserialized (docs/runbook.md, R6)."""


@dataclass(frozen=True)
class ModelBundle:
    """What the launch freezes (plan, section 15): the model in use (``model.RiskModel``: the calibrated model, its pipeline, its feature
    set and the country groups), the isotonic calibrators of the baselines, the BG/NBD parameters and B*."""

    model_version: str
    model: Any
    baseline_calibrators: dict[str, Any]
    bgnbd: BGNBDParams
    b_star: str


def artifact_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_artifact(bundle: ModelBundle, path: Path) -> str:
    """Serialize `bundle` with the standard library's ``pickle`` (protocol 5), write it atomically to `path` and return the SHA-256 of the
    bytes written. If it cannot be serialized, nothing is written and a file already at `path` is left as it was."""
    data = pickle.dumps(bundle, protocol=PICKLE_PROTOCOL)
    write_atomic(Path(path), data)
    return artifact_sha256(data)


def load_artifact(path: Path, expected_sha256: str) -> ModelBundle:
    """The bundle saved at `path`, deserialized only if its bytes have the SHA-256 `expected_sha256` (M03).

    The file is read once; the fingerprint is computed over those bytes and, if equal, the same bytes are deserialized. Otherwise
    ``ArtifactMismatchError`` is raised before any byte reaches ``pickle``. A fingerprint that is not 64 lower-case hexadecimal digits is a
    ``ValueError`` and the file is not even read; bytes with the registered fingerprint that are not a ``ModelBundle`` are a ``TypeError``.
    """
    if not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256):
        raise ValueError("la huella registrada del artefacto debe ser un SHA-256 de 64 dígitos hexadecimales en minúscula")
    name = Path(path).name
    data = Path(path).read_bytes()
    actual = artifact_sha256(data)
    if not hmac.compare_digest(actual, expected_sha256):
        logger.error("M03: artifact %s has sha256 %s and %s was registered; not loaded", name, actual, expected_sha256)
        raise ArtifactMismatchError(
            f"M03: el artefacto {name} tiene la huella {actual} y la registrada es {expected_sha256}: no se deserializó. "
            "Se restaura el archivo registrado o se vuelve a entrenar desde el lanzamiento (docs/runbook.md, R6)"
        )
    bundle = pickle.loads(data)  # noqa: S301 - only bytes whose SHA-256 is the registered one (D40)
    if not isinstance(bundle, ModelBundle):
        raise TypeError(f"M03: el artefacto {name} tiene la huella registrada pero no es un ModelBundle, es {type(bundle).__name__}")
    return bundle


# --- the seal and its fingerprint (U16; D19, plan section 15) -----------------------------------------------------------------------------------

SEAL_VERSION = 1
SEAL_DECIMALS = 6                     # a repetition must reproduce the sealed values rounded to this many decimals
SEAL_MODE = 0o600                     # owner only, where the mode is the access control (project 03, D64 and D78)
LAUNCH_KEYS = (
    "run_key", "as_of", "source_sha256", "config_sha256", "sealed_config", "model_version", "feature_set", "params", "country_groups", "threshold",
    "b_star", "bgnbd", "valid_scores_sha256",
)
TEST_KEYS = ("run_key", "as_of", "config_sha256", "criteria", "metrics", "per_cut", "variants")
_NOT_COMPARED = ("run_key",)          # what a repetition may change: the run that computed the values
# what the system answers to a hard link on a file system that has none (FAT and exFAT, some network shares); any other error is a real one
_NO_HARD_LINKS = frozenset({errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV, errno.ENOSYS})
_WINDOWS_NO_HARD_LINKS = frozenset({1, 50})      # ERROR_INVALID_FUNCTION and ERROR_NOT_SUPPORTED
_ABSENT = object()


class SealError(RuntimeError):
    """The seal file cannot be read as a seal, or what is asked of it is not allowed."""


class SealMismatchError(SealError):
    """A repetition with the sealed configuration did not reproduce the sealed values (docs/runbook.md, R7)."""


def sealed_view(cfg: Any, source_sha256: str) -> SealedConfig:
    """The sealed view of the configuration `cfg` for a source whose zip hashed to `source_sha256`: what the sealed calculations receive."""
    return SealedConfig.of(cfg, source_sha256)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise SealError(f"un valor de la configuración sellada no es JSON: {type(value).__name__}")


def sealed_document(view: SealedConfig) -> dict[str, Any]:
    """The whole sealed view as JSON: one object per section with its keys (dates as ``AAAA-MM-DD``, lists for tuples) and ``source_sha256``."""
    return _json_ready(dataclasses.asdict(view))


def canonical_sha256(document: Any) -> str:
    """SHA-256 of the canonical JSON of `document` (sorted keys, fixed separators, ASCII)."""
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def config_fingerprint(view: SealedConfig) -> str:
    """``config_sha256``: the SHA-256 of the canonical JSON of the whole sealed view, so every key that can change a sealed value changes it."""
    return canonical_sha256(sealed_document(view))


_IDENTIFIERS = ("id", "scope", "variant", "cut", "method", "metric")   # what names an entry of a list of objects (a criterion, a cut, a variant)


def _flat(document: Any, prefix: str = "") -> dict[str, Any]:
    """``{dotted path: value}`` of the leaves of nested objects. A list of objects is entered entry by entry, each named by its identifiers
    (``criteria.C01.value``, ``per_cut.2011-08-01|model.auc``) or by its position; any other list is one leaf."""
    if isinstance(document, Mapping):
        out: dict[str, Any] = {}
        for key, value in document.items():
            out.update(_flat(value, f"{prefix}.{key}" if prefix else str(key)))
        return out if out else {prefix: {}}
    if isinstance(document, (list, tuple)) and document and all(isinstance(item, Mapping) for item in document):
        out = {}
        for position, item in enumerate(document):
            name = "|".join(str(item[k]) for k in _IDENTIFIERS if k in item) or str(position)
            out.update({f"{prefix}.{name}.{key}": value for key, value in _flat(item).items()})
        return out
    return {prefix: document}


def differing_keys(sealed: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    """The keys (``section.key``) whose values differ between two sealed documents of the configuration, sorted."""
    a, b = _flat(sealed), _flat(current)
    return sorted(key for key in set(a) | set(b) if a.get(key, _ABSENT) != b.get(key, _ABSENT))


def _rounded(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SealError("un valor del sello no es un número finito")
        return round(value, SEAL_DECIMALS)
    if isinstance(value, Mapping):
        return {str(key): _rounded(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(item) for item in value]
    raise SealError(f"un valor del sello no es JSON: {type(value).__name__}")


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def read_seal(seal_path: Path) -> dict | None:
    """The seal at `seal_path`, or None if there is no file. A file that is not a seal is a ``SealError``: it is never taken for an absent one."""
    path = Path(seal_path)
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SealError(f"el sello {path.name} no se puede leer: {error}") from error
    if not isinstance(document, dict) or document.get("version") != SEAL_VERSION or not set(document) <= {"version", "launch", "test"}:
        raise SealError(f"el sello {path.name} no tiene la forma de la versión {SEAL_VERSION}")
    launch = document.get("launch")
    if not isinstance(launch, dict) or set(launch) != set(LAUNCH_KEYS) or not _is_sha256(launch.get("config_sha256")):
        raise SealError(f"la parte del lanzamiento del sello {path.name} no tiene sus claves o su huella")
    test = document.get("test")
    if test is not None and (not isinstance(test, dict) or set(test) != set(TEST_KEYS) or not _is_sha256(test.get("config_sha256"))):
        raise SealError(f"la parte de la prueba del sello {path.name} no tiene sus claves o su huella")
    return document


def seal_state(seal_path: Path, config_sha256: str) -> Literal["none", "match", "post_seal"]:
    """``none`` if there is no seal, ``match`` if its configuration is `config_sha256` and ``post_seal`` if it is another one (M05)."""
    document = read_seal(seal_path)
    if document is None:
        return "none"
    return "match" if document["launch"]["config_sha256"] == config_sha256 else "post_seal"


def _dump(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _lacks_hard_links(error: OSError) -> bool:
    return error.errno in _NO_HARD_LINKS or getattr(error, "winerror", None) in _WINDOWS_NO_HARD_LINKS


def _say_who_can_read(path: Path) -> None:
    """Where the mode bits are not the access control (Windows), the creation of a seal says so, with the folder whose access list decides."""
    if os.name != "posix":
        logger.warning("seal %s: the owner-only mode 0o%o is not enforced on this system (os.name %s); who can read it is decided by the access "
                       "list of the folder %s (runbook R7)", path.name, SEAL_MODE, os.name, path.parent)


def _create_without_link(path: Path, data: bytes) -> bool:
    """The creation for a file system without hard links: the exclusive create is the check; a half file is removed if the write fails."""
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), SEAL_MODE)
    except FileExistsError:
        return False
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    os.close(descriptor)
    return True


def _create_exclusive(path: Path, data: bytes) -> bool:
    """Create `path` with `data` only if it does not exist, all or nothing: True if created, False if a file was already there. The data goes
    to a temporary file that is hard-linked to `path`, which fails if `path` exists and never shows half a file; without hard links, an
    exclusive create is the check (project 03, D64 and D78)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        try:
            os.link(name, path)
            created = True
        except FileExistsError:
            return False
        except OSError as error:
            if not _lacks_hard_links(error):
                raise
            created = _create_without_link(path, data)
        if created:
            _say_who_can_read(path)
        return created
    finally:
        Path(name).unlink(missing_ok=True)


def _check_part(part: Mapping[str, Any], keys: tuple[str, ...], what: str) -> None:
    missing, extra = [k for k in keys if k not in part], sorted(set(part) - set(keys))
    if missing or extra:
        raise SealError(f"la parte {what} debe tener exactamente las claves {list(keys)}; faltan {missing}, sobran {extra}")
    if not _is_sha256(part["config_sha256"]):
        raise SealError(f"config_sha256 de la parte {what} debe ser un SHA-256 de 64 dígitos hexadecimales")
    _rounded(dict(part))                 # refuses a value that is not JSON, or not finite, before anything is compared or written


def _differences(sealed: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    a = _flat(_rounded({k: v for k, v in sealed.items() if k not in _NOT_COMPARED}))
    b = _flat(_rounded({k: v for k, v in current.items() if k not in _NOT_COMPARED}))
    return sorted(key for key in set(a) | set(b) if a.get(key, _ABSENT) != b.get(key, _ABSENT))


def write_launch_seal(seal_path: Path, launch: Mapping[str, Any]) -> Literal["written", "unchanged", "post_seal"]:
    """Write the launch part of the seal once (an exclusive creation or a hard link). Returns what happened.

    ``written``: there was no seal and now it has `launch`. ``unchanged``: the seal has this configuration and every sealed value of the launch,
    rounded to 6 decimals, is this one (nothing is rewritten). ``post_seal``: the seal has another configuration and is left as it is; the
    warning names the keys that differ (M05). The same configuration with another sealed value is a ``SealMismatchError`` that names each one
    (runbook R7).
    """
    _check_part(launch, LAUNCH_KEYS, "del lanzamiento")
    if canonical_sha256(launch["sealed_config"]) != launch["config_sha256"]:
        raise SealError("config_sha256 no es la huella de la configuración sellada de la parte del lanzamiento")
    path = Path(seal_path)
    if read_seal(path) is None and _create_exclusive(path, _dump({"version": SEAL_VERSION, "launch": dict(launch)})):
        logger.info("seal: launch part written to %s (config %s)", path.name, launch["config_sha256"][:12])
        return "written"
    sealed = read_seal(path)["launch"]
    if sealed["config_sha256"] != launch["config_sha256"]:
        logger.warning("seal: this configuration (%s) is not the sealed one (%s): post_seal; the keys that differ: %s", launch["config_sha256"][:12],
                       sealed["config_sha256"][:12], ", ".join(differing_keys(sealed["sealed_config"], launch["sealed_config"])))
        return "post_seal"
    differ = _differences(sealed, launch)
    if differ:
        then, now = _flat(_rounded(sealed)), _flat(_rounded(dict(launch)))
        named = "; ".join(f"{key}: {then.get(key)!r} sellado, {now.get(key)!r} en esta corrida" for key in differ[:6])
        raise SealMismatchError(f"M05: la configuración es la sellada pero el lanzamiento no la reproduce: {named}"
                                f"{' y otros' if len(differ) > 6 else ''} (docs/runbook.md, R7)")
    return "unchanged"


def write_test_seal(seal_path: Path, test: Mapping[str, Any]) -> Literal["written", "unchanged", "post_seal"]:
    """Add the test part to the seal once. Returns what happened.

    ``written``: the seal had only its launch part, which is kept as it was, and now has `test` too; the file is read back and must say what was
    written. ``unchanged``: it already has a test part whose values, rounded to 6 decimals, are these. ``post_seal``: `test` was evaluated with
    another configuration than the sealed one; the seal is left as it is. Any other difference is a ``SealMismatchError`` that names the values:
    every key that can change a sealed value is in ``config_sha256``, so there is no third case (plan, section 15).
    """
    _check_part(test, TEST_KEYS, "de la prueba")
    path = Path(seal_path)
    document = read_seal(path)
    if document is None:
        raise SealError("no hay sello: la parte de la prueba se escribe después de la del lanzamiento")
    if test["config_sha256"] != document["launch"]["config_sha256"]:
        logger.warning("seal: the test was evaluated with another configuration than the sealed one: post_seal; the seal is left as it is")
        return "post_seal"
    if document.get("test") is not None:
        differ = _differences(document["test"], test)
        if not differ:
            return "unchanged"
        raise SealMismatchError("la evaluación de la prueba con la configuración sellada no reproduce los valores sellados, redondeados a 6 "
                                f"decimales: {', '.join(differ[:6])}{' y otros' if len(differ) > 6 else ''} (docs/runbook.md, R7)")
    write_atomic(path, _dump({**document, "test": dict(test)}))
    # one writer at a time (D31), but the read, the decision and the write are not one step: read it back, and say so if it is not what was written
    kept = read_seal(path) or {}
    if kept.get("launch") != document["launch"] or _rounded(kept.get("test")) != _rounded(dict(test)):
        logger.error("seal: the test part written by run %s is not what the file says (runbook R7)", test["run_key"])
        raise SealMismatchError("lo que consta en el sello no es lo que esta corrida escribió: otra escritura lo cambió (docs/runbook.md, R7)")
    logger.info("seal: test part written to %s", path.name)
    return "written"


def valid_scores_fingerprint(scores: pd.DataFrame) -> str:
    """``valid_scores_sha256``: the SHA-256 of the risks of the validation rounded to 6 decimals, one ``cut_date:risk`` line per row in the order
    of (``cut_date``, internal position); `scores` has the index ``(cut_date, customer_id)`` and the column ``risk``. No customer number enters."""
    ordered = scores.sort_index(kind="stable")
    cuts = ordered.index.get_level_values("cut_date")
    text = "".join(f"{pd.Timestamp(c).date().isoformat()}:{float(r):.6f}\n" for c, r in zip(cuts, ordered["risk"], strict=True))
    return hashlib.sha256(text.encode("ascii")).hexdigest()
