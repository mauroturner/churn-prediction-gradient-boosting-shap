"""The artifact of the frozen model, loaded only when its bytes still have the registered SHA-256 (M03, AC23; D40; plan, section 15).
Adapted from project 03's ``registry.py`` (its D30); the seal and the fingerprint of the configuration come in U16.

``pickle`` runs code when it loads, so a file that someone replaced must never reach it. ``load_artifact`` reads the bytes of the file
**once**, computes their SHA-256, compares it with the registered one and only then hands *those same bytes* to ``pickle.loads``: there is no
window between checking and loading, and nothing is unpickled from a file whose fingerprint is not the registered one. The fingerprint
protects against a file that was replaced or damaged; it does not make ``pickle`` safe against someone who can rewrite the file and the
registry together (D40). The SHAP explainer is not saved: it is rebuilt from the model.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import pickle
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from churnrisk.bgnbd import BGNBDParams
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
