"""Pipeline configuration: one TOML file, typed, immutable and checked key by key.

``config/pipeline.toml`` holds every default. A file may start from another one with a top-level ``extends = "<path>"``
(``config/pipeline.quick.toml`` does). Every relative path is resolved against the project folder, never against the working
directory (decision D32): the paths inside the configuration (``[paths]`` and ``source.local_path``) against ``$CHURNRISK_HOME``
when it is set, otherwise the parent of the folder that holds the main configuration file; a relative configuration file
(``$CHURNRISK_CONFIG`` or the ``path`` argument, which ``--config`` passes) against ``$CHURNRISK_HOME`` or, without it, the
folder of this package's project.

Anything unknown, missing, mistyped or inconsistent is a ``ValueError`` that names the key. That includes a key the chosen
``source.mode`` would ignore: an option that is accepted and silently not used is the defect projects 01 and 02 both had.

Every leaf of the configuration is either in ``FINGERPRINT_KEYS`` (it can change a sealed value, so it enters the seal's
``config_sha256``) or in ``UNSEALED_KEYS`` (it cannot), never both and never neither (decision D19). The sealed calculations
receive ``SealedConfig``, which holds only the fingerprinted keys and the observed hash of the source zip.
"""

from __future__ import annotations

import dataclasses
import math
import os
import re
import tomllib
import types
import urllib.parse
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = DEFAULT_PROJECT_ROOT / "config" / "pipeline.toml"

ENV_CONFIG = "CHURNRISK_CONFIG"
ENV_HOME = "CHURNRISK_HOME"
FEATURE_SET_NAMES = ("f0", "f1", "f2")
STRONGEST_CANDIDATE_NAMES = ("b4_frequency", "b2_rfm", "b3_bgnbd")
SENSITIVITY_VARIANT_NAMES = ("n60", "n120", "m180", "no_december")

_SHA256 = re.compile(r"[0-9a-f]{64}")
# a folder name that is the same on every system: it starts with a letter, a digit, "_" or "-" (so "." and ".." are not names, and nothing is hidden),
# has dots only between other characters, and does not end in a dot (Windows drops it, so "v1." and "v1" would be one folder)
_FOLDER_NAME = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*")
MAX_SEED = 2**32 - 1   # the largest seed that numpy's legacy generators and scikit-learn accept
_HOST_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?")
_TYPE_NAMES = {
    bool: "verdadero o falso", int: "un entero", float: "un número", str: "un texto", date: "una fecha (AAAA-MM-DD)", Path: "una ruta",
}


@dataclass(frozen=True)
class SourceConfig:
    mode: str
    url: str
    allowed_hosts: tuple[str, ...]
    max_redirects: int
    max_seconds: float
    local_path: Path | None
    accepted_sha256: str
    member: str
    member_sha256: str
    max_bytes: int
    max_member_bytes: int
    sheets: tuple[str, ...]
    chunk_bytes: int
    timeout_s: int


@dataclass(frozen=True)
class DeliveriesConfig:
    first_date: date
    launch_as_of: date
    last_date: date


@dataclass(frozen=True)
class LabelConfig:
    horizon_days: int
    active_days: int
    first_cut: date
    last_cut: date


@dataclass(frozen=True)
class SplitConfig:
    train_first: date
    train_last: date
    v1_first: date
    v1_last: date
    v2_first: date
    v2_last: date
    test_first: date
    test_last: date


@dataclass(frozen=True)
class FeaturesConfig:
    candidate_sets: tuple[str, ...]
    short_window_days: int
    long_window_days: int
    country_min_customers: int


@dataclass(frozen=True)
class ModelConfig:
    learning_rate: tuple[float, ...]
    max_leaf_nodes: tuple[int, ...]
    min_samples_leaf: tuple[int, ...]
    l2_regularization: float
    max_iter: int
    random_state: int
    calibration: str
    model_version: str


@dataclass(frozen=True)
class BaselinesConfig:
    bgnbd_fit_cut: date
    bgnbd_max_iter: int
    strongest_candidates: tuple[str, ...]


@dataclass(frozen=True)
class CostsConfig:
    offer_cost: float
    rescue_rate: float
    retained_value: float
    threshold_min: float
    threshold_max: float
    threshold_step: float
    sensitivity_min: float
    sensitivity_max: float
    sensitivity_step: float


@dataclass(frozen=True)
class EvaluationConfig:
    bootstrap_resamples: int
    bootstrap_seed: int
    calibration_bins: int
    roc_points: int
    gain_points: int
    top_shares: tuple[float, ...]
    shap_top_reasons: int


@dataclass(frozen=True)
class SensitivityConfig:
    variants: tuple[str, ...]
    n60_horizon_days: int
    n120_horizon_days: int
    m180_active_days: int


@dataclass(frozen=True)
class CriteriaConfig:
    c07_max_ece: float
    c07_max_bias: float
    leak_tripwire_auc: float
    shap_additivity_tol: float


@dataclass(frozen=True)
class SiteConfig:
    max_total_bytes: int
    min_cell_customers: int


@dataclass(frozen=True)
class PathsConfig:
    raw_dir: Path
    interim_dir: Path
    warehouse: Path
    models_dir: Path
    outputs_dir: Path
    private_dir: Path
    site_dir: Path
    reports_dir: Path
    seal: Path
    dashboard_html: Path
    readme: Path
    figures_dir: Path


@dataclass(frozen=True)
class PipelineConfig:
    source: SourceConfig
    deliveries: DeliveriesConfig
    label: LabelConfig
    split: SplitConfig
    features: FeaturesConfig
    model: ModelConfig
    baselines: BaselinesConfig
    costs: CostsConfig
    evaluation: EvaluationConfig
    sensitivity: SensitivityConfig
    criteria: CriteriaConfig
    site: SiteConfig
    paths: PathsConfig
    project_root: Path


# --- the seal's view of the configuration (D19) ------------------------------------------------------------------------


@dataclass(frozen=True)
class SealedSourceConfig:
    """The one key of ``[source]`` that can change a sealed value: which sheets are read. Transport, limits and accepted hashes cannot;
    the hash of the zip that was actually read enters as ``SealedConfig.source_sha256``."""

    sheets: tuple[str, ...]


@dataclass(frozen=True)
class SealedConfig:
    """What the sealed calculations receive (cuts, features, split, baselines, BG/NBD, model, SHAP, threshold, evaluation and
    sensitivity): only the keys of ``FINGERPRINT_KEYS`` and the observed hash of the source. A key outside it cannot reach a sealed value."""

    source: SealedSourceConfig
    deliveries: DeliveriesConfig
    label: LabelConfig
    split: SplitConfig
    features: FeaturesConfig
    model: ModelConfig
    baselines: BaselinesConfig
    costs: CostsConfig
    evaluation: EvaluationConfig
    sensitivity: SensitivityConfig
    criteria: CriteriaConfig
    source_sha256: str

    @classmethod
    def of(cls, cfg: PipelineConfig, source_sha256: str) -> SealedConfig:
        """The sealed view of `cfg` for a source whose zip hashed to `source_sha256`."""
        if not _SHA256.fullmatch(source_sha256):
            raise ValueError(f"source_sha256: se esperaban 64 caracteres hexadecimales en minúscula, se recibió {source_sha256!r}")
        sections = {f.name: getattr(cfg, f.name) for f in dataclasses.fields(cls) if f.name not in ("source", "source_sha256")}
        return cls(source=SealedSourceConfig(sheets=cfg.source.sheets), **sections, source_sha256=source_sha256)


def config_leaves(cls: type, prefix: str = "") -> Iterator[str]:
    """The full name of every leaf of a configuration dataclass, ``section.key``, in declaration order."""
    hints = get_type_hints(cls)
    for f in dataclasses.fields(cls):
        name = f"{prefix}{f.name}"
        if dataclasses.is_dataclass(hints[f.name]):
            yield from config_leaves(hints[f.name], f"{name}.")
        else:
            yield name


# Every key that can change a sealed value, named one by one so that a new key fails tests/unit/test_config.py until it is classified.
# Including one too many only turns a cosmetic change into a post_seal run; one too few is project 03's defect B4 (D19). The observed
# hash of the zip (source_sha256) is not configured: SealedConfig adds it.
FINGERPRINT_KEYS: tuple[str, ...] = (
    "source.sheets",
    "deliveries.first_date", "deliveries.launch_as_of", "deliveries.last_date",
    "label.horizon_days", "label.active_days", "label.first_cut", "label.last_cut",
    "split.train_first", "split.train_last", "split.v1_first", "split.v1_last", "split.v2_first", "split.v2_last", "split.test_first", "split.test_last",
    "features.candidate_sets", "features.short_window_days", "features.long_window_days", "features.country_min_customers",
    "model.learning_rate", "model.max_leaf_nodes", "model.min_samples_leaf", "model.l2_regularization", "model.max_iter", "model.random_state",
    "model.calibration", "model.model_version",
    "baselines.bgnbd_fit_cut", "baselines.bgnbd_max_iter", "baselines.strongest_candidates",
    "costs.offer_cost", "costs.rescue_rate", "costs.retained_value", "costs.threshold_min", "costs.threshold_max", "costs.threshold_step",
    "costs.sensitivity_min", "costs.sensitivity_max", "costs.sensitivity_step",
    "evaluation.bootstrap_resamples", "evaluation.bootstrap_seed", "evaluation.calibration_bins", "evaluation.roc_points", "evaluation.gain_points",
    "evaluation.top_shares", "evaluation.shap_top_reasons",
    "sensitivity.variants", "sensitivity.n60_horizon_days", "sensitivity.n120_horizon_days", "sensitivity.m180_active_days",
    "criteria.c07_max_ece", "criteria.c07_max_bias", "criteria.leak_tripwire_auc", "criteria.shap_additivity_tol",
)
# Every key that cannot: how the source is fetched and checked (the hash of the zip that was read enters instead), the site's limits
# and where the files go.
UNSEALED_KEYS: tuple[str, ...] = (
    "source.mode", "source.url", "source.allowed_hosts", "source.max_redirects", "source.max_seconds", "source.local_path", "source.accepted_sha256",
    "source.member", "source.member_sha256", "source.max_bytes", "source.max_member_bytes", "source.chunk_bytes", "source.timeout_s",
    "site.max_total_bytes", "site.min_cell_customers",
    "paths.raw_dir", "paths.interim_dir", "paths.warehouse", "paths.models_dir", "paths.outputs_dir", "paths.private_dir", "paths.site_dir",
    "paths.reports_dir", "paths.seal", "paths.dashboard_html", "paths.readme", "paths.figures_dir",
)


# --- hosts: shared by the configuration check and the download (V02) ------------------------------------------------


def url_host(url: str) -> str | None:
    """The host of an ``http(s)`` URL, lower case and without a trailing dot, or None if the URL is not one the download may follow.

    A URL with user information (``user@host``), a backslash, a space or a control character is refused as a whole: those are the
    spellings in which two parsers can read different hosts from the same text, so the host that was checked would not be the host
    that is connected to (project 03, D48).
    """
    if not isinstance(url, str) or not url or any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F or ch == "\\" for ch in url):
        return None
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port  # raises ValueError on a malformed port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or "@" in parts.netloc or not parts.hostname:
        return None
    del port
    return parts.hostname.lower().rstrip(".")


def host_allowed(host: str, allowed_hosts: Sequence[str]) -> bool:
    """Whether `host` is one of `allowed_hosts`: an exact name, or a suffix when the entry starts with a dot (``.example.org``)."""
    host = host.lower().rstrip(".")
    if not host:
        return False
    for entry in allowed_hosts:
        entry = entry.lower()
        if entry.startswith("."):
            if host.endswith(entry) and len(host) > len(entry):
                return True
        elif host == entry:
            return True
    return False


# --- loading --------------------------------------------------------------------------------------------------------


def _is_optional_path(annotation: Any) -> bool:
    origin = get_origin(annotation)
    return origin in (Union, types.UnionType) and set(get_args(annotation)) == {Path, type(None)}


def _resolve(value: str, root: Path, where: str) -> Path:
    if not value.strip():
        raise ValueError(f"{where}: se esperaba una ruta, se recibió un texto vacío")
    path = Path(value)
    if path.is_absolute():
        return path  # an absolute path is explicit: it may point anywhere on purpose
    joined = Path(os.path.normpath(root / path))
    base = Path(os.path.normpath(root))
    if joined != base and base not in joined.parents:
        raise ValueError(
            f"{where}: la ruta relativa {value!r} sale de la carpeta del proyecto ({base}); "
            "use una ruta absoluta si el destino está fuera a propósito"
        )
    return joined


def _coerce(value: Any, annotation: Any, where: str, root: Path) -> Any:
    """Convert a TOML value to the annotated type or raise ValueError naming `where`."""
    if _is_optional_path(annotation):
        if isinstance(value, str):
            return _resolve(value, root, where) if value.strip() else None
        raise ValueError(f"{where}: se esperaba una ruta escrita como texto, se recibió {value!r}")
    origin = get_origin(annotation)
    if origin is tuple:
        (element, _ellipsis) = get_args(annotation)
        if not isinstance(value, list):
            raise ValueError(f"{where}: se esperaba una lista, se recibió {type(value).__name__}")
        return tuple(_coerce(v, element, where, root) for v in value)
    if annotation is bool:
        ok = isinstance(value, bool)
    elif annotation is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif annotation is float:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        value = float(value) if ok else value
    elif annotation is str:
        ok = isinstance(value, str)
    elif annotation is date:
        ok = isinstance(value, date) and not isinstance(value, datetime)
    elif annotation is Path:
        if isinstance(value, str):
            return _resolve(value, root, where)
        ok = False
    else:  # pragma: no cover - only reachable by adding an unsupported annotation
        raise TypeError(f"{where}: unsupported annotation {annotation!r}")
    if not ok:
        raise ValueError(f"{where}: se esperaba {_TYPE_NAMES.get(annotation, annotation)}, se recibió {value!r}")
    return value


def _build_section(cls: type, data: Any, name: str, root: Path) -> Any:
    if not isinstance(data, dict):
        raise ValueError(f"[{name}]: se esperaba una tabla, se recibió {type(data).__name__}")
    hints = get_type_hints(cls)
    fields = [f.name for f in dataclasses.fields(cls)]
    unknown = sorted(set(data) - set(fields))
    if unknown:
        raise ValueError(f"[{name}]: clave desconocida {unknown[0]!r}")
    missing = [f for f in fields if f not in data]
    if missing:
        raise ValueError(f"[{name}]: falta la clave {missing[0]!r}")
    return cls(**{f: _coerce(data[f], hints[f], f"[{name}] {f}", root) for f in fields})


# --- consistency checks ---------------------------------------------------------------------------------------------


def _positive(value: float, where: str) -> None:
    if not value > 0:
        raise ValueError(f"{where}: se esperaba un valor mayor que 0, se recibió {value!r}")


def _seed(value: int, where: str) -> None:
    if not 0 <= value <= MAX_SEED:
        raise ValueError(f"{where}: se esperaba un entero de 0 a {MAX_SEED}, se recibió {value!r}")


def _fraction(value: float, where: str, *, closed_high: bool = False) -> None:
    if not (0 < value <= 1 if closed_high else 0 < value < 1):
        interval = "(0, 1]" if closed_high else "(0, 1)"
        raise ValueError(f"{where}: se esperaba un valor en {interval}, se recibió {value!r}")


def _unique_names(values: tuple[str, ...], allowed: tuple[str, ...], where: str) -> None:
    if not values or len(set(values)) != len(values):
        raise ValueError(f"{where}: se esperaba una lista no vacía y sin repetidos, se recibió {list(values)}")
    for value in values:
        if value not in allowed:
            raise ValueError(f"{where}: {value!r} no es un valor conocido ({', '.join(allowed)})")


def _first_of_month(value: date, where: str) -> None:
    if value.day != 1:
        raise ValueError(f"{where}: un corte es el día 1 de un mes, se recibió {value}")


def _check_host_entry(entry: str) -> None:
    where = "[source] allowed_hosts"
    if entry != entry.lower() or not entry.strip():
        raise ValueError(f"{where}: se esperaba un nombre de host en minúscula y sin espacios, se recibió {entry!r}")
    name = entry[1:] if entry.startswith(".") else entry
    labels = name.split(".")
    if not all(_HOST_LABEL.fullmatch(label) for label in labels):
        raise ValueError(f"{where}: {entry!r} no es un nombre de host (sin esquema, puerto ni ruta)")
    if entry.startswith(".") and len(labels) < 2:
        raise ValueError(f"{where}: el sufijo {entry!r} es demasiado amplio; use al menos dos etiquetas, como '.example.org'")


def _check_source(source: SourceConfig) -> None:
    if source.mode not in ("http", "local"):
        raise ValueError(f"[source] mode: se esperaba 'http' o 'local', se recibió {source.mode!r}")
    if not source.allowed_hosts:
        raise ValueError("[source] allowed_hosts: se esperaba al menos un host permitido")
    for entry in source.allowed_hosts:
        _check_host_entry(entry)
    if source.mode == "local":
        if source.local_path is None:
            raise ValueError("[source] local_path: con mode = 'local' hace falta la ruta del zip (el modo rápido usa data/quick/online_retail_fixture.zip)")
        for key in ("accepted_sha256", "member_sha256"):
            if getattr(source, key):
                raise ValueError(f"[source] {key}: con mode = 'local' se registra la primera huella que se ve y esta clave se ignoraría; déjela vacía")
        if source.url:
            raise ValueError(
                "[source] url: con mode = 'local' se lee local_path y esta clave se ignoraría; déjela vacía (el archivo de modo rápido debe decir "
                'url = "" para no heredar la dirección del origen real)'
            )
    else:
        if not source.url.startswith("https://"):
            raise ValueError(f"[source] url: se esperaba una URL https://, se recibió {source.url!r}")
        host = url_host(source.url)
        if host is None:
            raise ValueError(f"[source] url: no es una dirección que la descarga pueda seguir (sin usuario, espacios ni barras invertidas): {source.url!r}")
        if not host_allowed(host, source.allowed_hosts):
            raise ValueError(f"[source] url: el host {host!r} no está en allowed_hosts {list(source.allowed_hosts)}")
        for key, what in (("accepted_sha256", "del zip aceptado"), ("member_sha256", "del libro dentro del zip")):
            if not _SHA256.fullmatch(getattr(source, key)):
                raise ValueError(f"[source] {key}: con mode = 'http' hacen falta los 64 caracteres hexadecimales en minúscula {what}")
        if source.local_path is not None:
            raise ValueError("[source] local_path: con mode = 'http' esta clave se ignoraría; déjela vacía")
    if source.max_redirects < 0:
        raise ValueError(f"[source] max_redirects: se esperaba 0 o más, se recibió {source.max_redirects!r}")
    name = source.member
    if not name or "/" in name or "\\" in name or ":" in name or name in (".", "..") or Path(name).is_absolute():
        raise ValueError(f"[source] member: se esperaba el nombre de un archivo sin ruta, se recibió {name!r}")
    if not source.sheets or len(set(source.sheets)) != len(source.sheets) or not all(sheet.strip() for sheet in source.sheets):
        raise ValueError(f"[source] sheets: se esperaba una lista no vacía de nombres de hoja, sin repetidos, se recibió {list(source.sheets)}")
    for key in ("max_bytes", "max_member_bytes", "chunk_bytes", "timeout_s"):
        _positive(getattr(source, key), f"[source] {key}")
    if not math.isfinite(source.max_seconds) or source.max_seconds <= 0:
        raise ValueError(f"[source] max_seconds: se esperaba un número de segundos mayor que 0 y finito (el tiempo máximo de toda la descarga), se recibió {source.max_seconds!r}")


def _check_calendar(cfg: PipelineConfig) -> None:
    """The deliveries, the cuts and the blocks of D08, with a purge of at least N days at every boundary between two blocks."""
    d, lab, s = cfg.deliveries, cfg.label, cfg.split
    if not d.first_date < d.launch_as_of < d.last_date:
        raise ValueError("[deliveries]: first_date, launch_as_of y last_date deben estar en orden creciente")
    if (d.launch_as_of + timedelta(days=1)).day != 1:
        raise ValueError(f"[deliveries] launch_as_of: las entregas mensuales empiezan el día siguiente, así que debe ser el último día de un mes, se recibió {d.launch_as_of}")
    _positive(lab.horizon_days, "[label] horizon_days")
    _positive(lab.active_days, "[label] active_days")
    cuts = (("label", "first_cut", lab.first_cut), ("label", "last_cut", lab.last_cut)) + tuple(
        ("split", f.name, getattr(s, f.name)) for f in dataclasses.fields(s)
    ) + (("baselines", "bgnbd_fit_cut", cfg.baselines.bgnbd_fit_cut),)
    for section, key, value in cuts:
        _first_of_month(value, f"[{section}] {key}")
    if not d.first_date < lab.first_cut <= lab.last_cut <= d.last_date:
        raise ValueError(f"[label] first_cut: se esperaba first_date < first_cut <= last_cut <= last_date, se recibió {lab.first_cut} y {lab.last_cut}")
    n = timedelta(days=lab.horizon_days)
    blocks = (("train", s.train_first, s.train_last), ("valid_v1", s.v1_first, s.v1_last), ("valid_v2", s.v2_first, s.v2_last), ("test", s.test_first, s.test_last))
    for name, first, last in blocks:
        if first > last:
            raise ValueError(f"[split] {name}: el primer corte ({first}) es posterior al último ({last})")
    if s.train_first < lab.first_cut:
        raise ValueError(f"[split] train_first: no puede ser anterior a first_cut de [label] ({lab.first_cut})")
    if s.test_last > lab.last_cut:
        raise ValueError(f"[split] test_last: no puede ser posterior a last_cut de [label] ({lab.last_cut})")
    # V1 and V2 are both validation, with overlapping windows and no purge between them (D8); every other boundary needs c_prev + N <= c_next
    boundaries = (("train", "valid_v1", s.train_last, s.v1_first, n), ("valid_v1", "valid_v2", s.v1_last, s.v2_first, timedelta(days=1)),
                  ("valid_v2", "test", s.v2_last, s.test_first, n))
    for before, after, last, first, gap in boundaries:
        if last + gap > first:
            purge = f"una purga de N = {lab.horizon_days} días: {last} + {lab.horizon_days} días = {last + gap}" if gap == n else "que el bloque siguiente empiece después"
            raise ValueError(f"[split] borde {before} → {after}: se esperaba {purge} <= {first}")
    if s.test_last + n - timedelta(days=1) > d.last_date:
        raise ValueError(f"[split] test_last: la ventana del último corte de prueba termina el {s.test_last + n - timedelta(days=1)}, después de last_date ({d.last_date})")
    if s.v2_last + n - timedelta(days=1) > d.launch_as_of:
        raise ValueError(f"[split] v2_last: el lanzamiento elige el umbral en V2, así que su ventana debe cerrar el {d.launch_as_of} o antes, y termina el {s.v2_last + n - timedelta(days=1)}")
    if s.test_first != d.launch_as_of + timedelta(days=1):
        raise ValueError(f"[split] test_first: el lanzamiento puntúa el corte del día siguiente a su fecha de cálculo ({d.launch_as_of + timedelta(days=1)}), se recibió {s.test_first}")
    if not s.train_first <= cfg.baselines.bgnbd_fit_cut <= s.train_last:
        raise ValueError(f"[baselines] bgnbd_fit_cut: BG/NBD se ajusta con la historia anterior a un corte de entrenamiento ({s.train_first} a {s.train_last}), se recibió {cfg.baselines.bgnbd_fit_cut}")


def _check(cfg: PipelineConfig) -> None:
    _check_source(cfg.source)
    _check_calendar(cfg)

    f = cfg.features
    _unique_names(f.candidate_sets, FEATURE_SET_NAMES, "[features] candidate_sets")
    _positive(f.short_window_days, "[features] short_window_days")
    if not f.long_window_days > f.short_window_days:
        raise ValueError(f"[features] long_window_days: se esperaba más días que short_window_days ({f.short_window_days}), se recibió {f.long_window_days!r}")
    _positive(f.country_min_customers, "[features] country_min_customers")

    m = cfg.model
    for key in ("learning_rate", "max_leaf_nodes", "min_samples_leaf"):
        grid = getattr(m, key)
        where = f"[model] {key}"
        if not grid or len(set(grid)) != len(grid):
            raise ValueError(f"{where}: se esperaba una lista no vacía y sin repetidos, se recibió {list(grid)}")
        for value in grid:
            _positive(value, where)
    if any(v < 2 for v in m.max_leaf_nodes):
        raise ValueError(f"[model] max_leaf_nodes: se esperaban valores de 2 o más, se recibió {list(m.max_leaf_nodes)}")
    if m.l2_regularization < 0:
        raise ValueError(f"[model] l2_regularization: se esperaba 0 o más, se recibió {m.l2_regularization!r}")
    _positive(m.max_iter, "[model] max_iter")
    _seed(m.random_state, "[model] random_state")
    if m.calibration != "isotonic":
        raise ValueError(f"[model] calibration: el único método implementado es 'isotonic' (D14), se recibió {m.calibration!r}")
    if not _FOLDER_NAME.fullmatch(m.model_version) or m.model_version.endswith("."):
        raise ValueError(
            f"[model] model_version: se esperaba un nombre de carpeta simple (letras, números, «_», «-» y puntos entre otros caracteres; sin espacios, separadores "
            f"de ruta ni punto al empezar o al terminar, y distinto de «.» y «..»), se recibió {m.model_version!r}"
        )

    b = cfg.baselines
    _positive(b.bgnbd_max_iter, "[baselines] bgnbd_max_iter")
    _unique_names(b.strongest_candidates, STRONGEST_CANDIDATE_NAMES, "[baselines] strongest_candidates")

    c = cfg.costs
    for key in ("offer_cost", "retained_value"):
        _positive(getattr(c, key), f"[costs] {key}")
    _fraction(c.rescue_rate, "[costs] rescue_rate", closed_high=True)
    for key in ("threshold_min", "threshold_max", "sensitivity_min", "sensitivity_max"):
        _fraction(getattr(c, key), f"[costs] {key}")
    if not c.threshold_min < c.threshold_max:
        raise ValueError(f"[costs] threshold_min: se esperaba threshold_min < threshold_max, se recibió {c.threshold_min!r} y {c.threshold_max!r}")
    _positive(c.threshold_step, "[costs] threshold_step")
    if not c.sensitivity_min <= c.sensitivity_max:
        raise ValueError(f"[costs] sensitivity_min: se esperaba sensitivity_min <= sensitivity_max, se recibió {c.sensitivity_min!r} y {c.sensitivity_max!r}")
    _positive(c.sensitivity_step, "[costs] sensitivity_step")

    e = cfg.evaluation
    _positive(e.bootstrap_resamples, "[evaluation] bootstrap_resamples")
    _seed(e.bootstrap_seed, "[evaluation] bootstrap_seed")
    for key in ("calibration_bins", "roc_points", "gain_points"):
        if getattr(e, key) < 2:
            raise ValueError(f"[evaluation] {key}: se esperaba 2 o más, se recibió {getattr(e, key)!r}")
    if not e.top_shares or len(set(e.top_shares)) != len(e.top_shares):
        raise ValueError(f"[evaluation] top_shares: se esperaba una lista no vacía y sin repetidos, se recibió {list(e.top_shares)}")
    for share in e.top_shares:
        _fraction(share, "[evaluation] top_shares")
    _positive(e.shap_top_reasons, "[evaluation] shap_top_reasons")

    v = cfg.sensitivity
    _unique_names(v.variants, SENSITIVITY_VARIANT_NAMES, "[sensitivity] variants")
    for key in ("n60_horizon_days", "n120_horizon_days", "m180_active_days"):
        _positive(getattr(v, key), f"[sensitivity] {key}")

    k = cfg.criteria
    _fraction(k.c07_max_ece, "[criteria] c07_max_ece")
    _fraction(k.c07_max_bias, "[criteria] c07_max_bias")
    if not 0.5 < k.leak_tripwire_auc <= 1:
        raise ValueError(f"[criteria] leak_tripwire_auc: se esperaba un valor en (0,5, 1], se recibió {k.leak_tripwire_auc!r}")
    if not math.isfinite(k.shap_additivity_tol) or not 0 < k.shap_additivity_tol < 1:
        raise ValueError(f"[criteria] shap_additivity_tol: se esperaba un valor en (0, 1) en log-odds, se recibió {k.shap_additivity_tol!r}")

    _positive(cfg.site.max_total_bytes, "[site] max_total_bytes")
    _positive(cfg.site.min_cell_customers, "[site] min_cell_customers")


# --- reading --------------------------------------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], top: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in top.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_toml(path: Path, _seen: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Read a TOML file, following ``extends`` (relative to the file) and merging over its base."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no se encontró el archivo de configuración: {path}")
    resolved = path.resolve()
    if resolved in _seen:
        raise ValueError(f"los archivos de configuración se extienden entre sí en un ciclo en {path}")
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    parent = data.pop("extends", None)
    if parent is None:
        return data
    if not isinstance(parent, str):
        raise ValueError(f"{path}: extends debe ser una ruta escrita como texto")
    parent_path = Path(parent)
    if not parent_path.is_absolute():
        parent_path = path.parent / parent_path
    return _deep_merge(_read_toml(parent_path, (*_seen, resolved)), data)


def _home() -> Path | None:
    home = os.environ.get(ENV_HOME)
    if not home:
        return None
    root = Path(home).resolve()
    if not root.is_dir():
        raise ValueError(f"{ENV_HOME}: {home!r} no es una carpeta existente")
    return root


def load_config(path: Path | None = None) -> PipelineConfig:
    """Load the configuration.

    `path` is the main file; without it, ``$CHURNRISK_CONFIG`` and then ``config/pipeline.toml`` of the project. A relative `path` or
    ``$CHURNRISK_CONFIG`` is taken from ``$CHURNRISK_HOME`` or, without it, from this package's project: the working directory may be
    another copy's folder, and its configuration is never read in silence. The paths inside are resolved against ``$CHURNRISK_HOME`` or
    the parent of the folder that holds the main file. Anything unknown, missing, mistyped or inconsistent is a ``ValueError`` naming the key.
    """
    home = _home()
    if path is None:
        env = os.environ.get(ENV_CONFIG)
        path = Path(env) if env else DEFAULT_CONFIG
    path = Path(path)
    if not path.is_absolute():
        path = (home or DEFAULT_PROJECT_ROOT) / path
    data = _read_toml(path)
    root = home or path.resolve().parent.parent

    sections = [f.name for f in dataclasses.fields(PipelineConfig) if f.name != "project_root"]
    unknown = sorted(set(data) - set(sections))
    if unknown:
        raise ValueError(f"sección desconocida [{unknown[0]}]")
    missing = [s for s in sections if s not in data]
    if missing:
        raise ValueError(f"falta la sección [{missing[0]}]")
    hints = get_type_hints(PipelineConfig)
    built = {name: _build_section(hints[name], data[name], name, root) for name in sections}
    cfg = PipelineConfig(**built, project_root=root)
    _check(cfg)
    return cfg
