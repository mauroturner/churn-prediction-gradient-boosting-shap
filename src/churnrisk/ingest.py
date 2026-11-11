"""Source ingestion (RF01-RF04): the download with its fingerprint, the extraction, the reading of the workbook and the canonical lines.

The zip and the workbook are untrusted input (D02). ``download_file`` checks every address before it requests it (``check_hop``: HTTPS on
the default port to a listed host, no user information, spaces, control characters or backslashes), follows redirects one checked hop at a
time up to ``max_redirects``, holds the announced length and the bytes received to ``max_bytes`` and the whole call to ``max_seconds``,
streams the body to a staging file of its own while hashing it, and moves it to the destination only if the SHA-256 is the accepted one
(V01, V02). A different hash keeps the whole download as ``<dest>.part`` and leaves the destination exactly as it was; the code is
project 03's corrected downloader (its D41, D48, D49), adapted. In local mode, ``local_source`` checks the size and the registered hash.

``extract_member`` takes the single expected member out of the zip, under a size cap and with its own hash in http mode (V03);
``read_source`` reads the configured sheets once, checks their eight exact columns (V04) and every type (V05), checks that the days the two
sheets share hold the same rows (V06), drops sheet 2's copies of them and keeps and flags the rows repeated inside a sheet (project 02, D03).
``fetch_source`` is the first task: it runs all of it once per fingerprint and writes ``source_lines.parquet`` and, last, the manifest
of its hash (project 03, D50). A rejected source writes nothing.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import math
import os
import re
import secrets
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import openpyxl
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from churnrisk.config import PipelineConfig, host_allowed, url_host
from churnrisk.files import atomic_path, sha256_file, write_atomic
from churnrisk.schema import (
    CANONICAL_SCHEMA,
    COLUMN_NAMES,
    CUSTOMER_ID_RANGE,
    LINE_ID_SHEET_FACTOR,
    WORKBOOK_COLUMNS,
    SourceError,
    code_kinds,
)

logger = logging.getLogger(__name__)

USER_AGENT = "churnrisk-pipeline/0.1"
MANIFEST_NAME = "source_manifest.json"
MANIFEST_VERSION = 1
STAGING_ATTEMPTS = 100            # a clash of random 64-bit names is not expected; the loop is for the day it happens
REDIRECT_CODES = (301, 302, 303, 307, 308)
HTTPS_PORT = 443
DEADLINE_SLACK_S = 0.05           # a socket timeout can fire a few milliseconds before the time it was given (Windows ticks every 15.6 ms)


class DownloadError(RuntimeError):
    """The download did not end with the whole file (network, status, timeout, truncation). Not a rule: it can be retried."""


class DownloadDeadlineError(DownloadError):
    """The download did not finish within ``source.max_seconds``: a source that drips bytes never trips the read timeout (project 03, D49)."""


class _LocalFault(Exception):
    """Carries an ``OSError`` that happened on this machine making or writing the staging file, so that it is not taken for a transport failure."""


def _refuse(message: str, **details: Any) -> SourceError:
    return SourceError("V02", message, [{"rule_id": "V02", **details}])


def _shown(url: str) -> str:
    """An address without its query: a signed link carries its signature there, and a signature does not belong in a message or a log."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return "<dirección ilegible>"
    text = f"{parts.scheme}://{parts.hostname or ''}{parts.path}"
    text = text[:120] + "..." if len(text) > 120 else text
    return text + ("?..." if parts.query else "")


def check_hop(url: str, allowed_hosts: tuple[str, ...] | list[str], insecure_hosts: frozenset[str] = frozenset(), hop: int = 0) -> str:
    """Check an address before connecting to it and return its host; refuse it (V02) otherwise.

    An address is accepted when it is plain (no user information, spaces, control characters or backslashes), its scheme is ``https`` on the
    default port (``http`` and any port only for a host in `insecure_hosts`, which only a test passes) and its host is one of `allowed_hosts`.
    The first address and every ``Location`` of a redirect go through here, so a redirect cannot lead anywhere the first address could not.
    """
    text = url if isinstance(url, str) else ""
    where = {"hop": hop, "url": _shown(text) if text else ""}
    if not text or any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F or ch == "\\" for ch in text):
        raise _refuse(f"la dirección {where['url']!r} no es una dirección que se pueda seguir (vacía, con espacios, caracteres de control o barras invertidas).", **where)
    try:
        parts = urllib.parse.urlsplit(text)
    except ValueError:
        raise _refuse(f"la dirección {where['url']!r} no es una dirección que se pueda seguir.", **where) from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise _refuse(f"el esquema {scheme!r} de {where['url']} no se admite: solo https.", scheme=scheme, **where)
    host = url_host(text)
    if host is None:
        raise _refuse(f"la dirección {where['url']!r} no es una dirección que se pueda seguir (usuario en la dirección, sin host o con un puerto ilegible).", **where)
    insecure = host in insecure_hosts
    if scheme == "http" and not insecure:
        raise _refuse(f"la dirección {where['url']} no es HTTPS: cada salto de la descarga debe serlo.", host=host, scheme=scheme, **where)
    if not insecure and parts.port not in (None, HTTPS_PORT):
        raise _refuse(f"la dirección {where['url']} usa el puerto {parts.port}; solo se admite el puerto {HTTPS_PORT}.", host=host, port=parts.port, **where)
    if not host_allowed(host, allowed_hosts):
        raise _refuse(
            f"el host {host!r} de {where['url']} no está en la lista de hosts permitidos {list(allowed_hosts)} ([source] allowed_hosts). "
            "Si UCI empezó a redirigir a otro host, agregarlo es una decisión nueva: ver docs/runbook.md, R2 y R11.", host=host, **where,
        )
    return host


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect inside urllib: the download does it, one checked hop at a time."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # urllib's signature
        return None


def _expired(deadline: float | None) -> bool:
    """Whether the overall deadline has passed, or is so close that a timeout that has just fired was cut by it and not by the read timeout."""
    return deadline is not None and time.perf_counter() >= deadline - DEADLINE_SLACK_S


def _deadline_error(max_seconds: float, received: int | None = None, *, host: str | None = None, hop: int | None = None) -> DownloadDeadlineError:
    after = "" if received is None else f" tras recibir {received} bytes"
    if host is not None:
        after += f" de {host}" if hop is None else f" mientras se esperaba el salto {hop} ({host})"
    return DownloadDeadlineError(
        f"La descarga superó el tiempo máximo de {max_seconds:g} s (source.max_seconds){after}; se interrumpió y no se guardó nada. "
        "Si el origen es lento, se puede subir ese límite; si no responde, ver docs/runbook.md, R2."
    )


def _open(url: str, allowed_hosts, max_redirects: int, insecure: frozenset[str], timeout_s: int, deadline: float | None, max_seconds: float | None):
    """Open `url` and follow its redirects by hand; every address is checked before it is requested. Returns the open response.

    With a `deadline` (a ``time.perf_counter()`` value) a hop that starts after it is not requested, and a hop cut by it, for the shorter time it
    was given, is a ``DownloadDeadlineError`` and not a timeout of the read.
    """
    opener = urllib.request.build_opener(_NoRedirect)
    current = url
    for hop in range(max_redirects + 1):
        host = check_hop(current, allowed_hosts, insecure, hop)
        timeout = float(timeout_s)
        if deadline is not None:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise _deadline_error(max_seconds or 0.0, host=host, hop=hop + 1)
            timeout = max(0.001, min(timeout, remaining))
        logger.info("download hop %d: %s (%s)", hop + 1, host, urllib.parse.urlsplit(current).scheme)
        request = urllib.request.Request(current, headers={"User-Agent": USER_AGENT})
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            code = error.code
            location = error.headers.get("Location") if code in REDIRECT_CODES else None
            error.close()
            if code in REDIRECT_CODES:
                if not location:
                    raise _refuse(f"{_shown(current)} respondió HTTP {code} sin cabecera Location.", hop=hop + 1) from None
                if hop == max_redirects:
                    raise _refuse(f"la descarga pide más de {max_redirects} redirecciones (la {hop + 1} sale de {_shown(current)}); no se sigue.",
                                  hop=hop + 1, max_redirects=max_redirects) from None
                current = urllib.parse.urljoin(current, location)
                continue
            if code == 404:
                raise DownloadError(f"No se encontró la fuente en {_shown(current)} (HTTP 404). UCI pudo haber movido el archivo: ver docs/runbook.md, R11.") from None
            raise DownloadError(f"{_shown(current)} respondió HTTP {code}.") from None
        except (TimeoutError, urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            timed_out = isinstance(error, TimeoutError) or isinstance(reason, TimeoutError)
            if deadline is not None and (time.perf_counter() >= deadline or (timed_out and _expired(deadline))):
                raise _deadline_error(max_seconds or 0.0, host=host, hop=hop + 1) from error
            if timed_out:
                raise DownloadError(f"Se agotó el tiempo de espera de {timeout_s} s al conectar con {_shown(current)}.") from error
            raise DownloadError(f"No se pudo conectar con {_shown(current)}: {reason}.") from error
        if response.status != 200:
            response.close()
            raise DownloadError(f"{_shown(current)} respondió HTTP {response.status} y se esperaba 200.")
        return response
    raise AssertionError("unreachable: the last hop either returns or raises")  # pragma: no cover


def _create_staging(dest: Path) -> tuple[int, Path]:
    """Create the folder of `dest` and an empty staging file in it, exclusively and under a random name; return ``(descriptor, path)``.

    ``O_EXCL`` means an existing file is never reused and ``O_NOFOLLOW`` that a link planted under the chosen name is not followed; the mode is
    the one ``open(path, "wb")`` would give, so ``os.replace`` does not carry a stricter one into `dest`.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    for _ in range(STAGING_ATTEMPTS):
        path = dest.with_name(f"{dest.name}.{secrets.token_hex(8)}.staging")
        try:
            return os.open(path, flags, 0o666), path
        except FileExistsError:
            continue
    raise FileExistsError(f"No se pudo crear un archivo de preparación junto a {dest} tras {STAGING_ATTEMPTS} intentos")


def download_file(
    url: str, dest: Path, accepted_sha256: str, allowed_hosts: list[str] | tuple[str, ...], max_redirects: int, max_bytes: int,
    max_seconds: float | None, chunk_bytes: int, timeout_s: int, *, insecure_hosts: frozenset[str] | set[str] = frozenset(),
) -> tuple[Path, str]:
    """Download `url` to a staging file of its own, hashing it on the fly; move it to `dest` only if the SHA-256 is `accepted_sha256`. Returns ``(dest, sha256)``.

    Every address is checked before it is requested (V02, ``check_hop``); the length announced and the bytes received are held to `max_bytes`
    (V02); a different hash (V01) keeps the whole download as ``<dest>.part`` (replacing an earlier one) and leaves `dest` as it was. Nothing is
    created until the first response has arrived: a refused address leaves no folder, no staging file and no part. A transport failure, a status
    other than 200 or a body shorter than announced is a ``DownloadError``, logged before it is raised. A folder or staging file that cannot be
    created and a chunk that cannot be written are local faults: each raises its own ``OSError``, logged with its traceback. `max_seconds` is the
    deadline of the whole call, redirects included (None: none); passing it is a ``DownloadDeadlineError`` with the staging file removed.
    `insecure_hosts` lets a test use plain HTTP on named hosts (a local server); the pipeline never passes it.
    """
    started = time.perf_counter()
    deadline = None if max_seconds is None else started + max_seconds

    def took() -> float:
        return time.perf_counter() - started

    dest = Path(dest)
    part = dest.with_name(dest.name + ".part")
    insecure = frozenset(host.lower() for host in insecure_hosts)
    digest = hashlib.sha256()
    received = 0
    staging: Path | None = None

    def discard() -> None:
        if staging is not None:
            staging.unlink(missing_ok=True)

    check_hop(url, allowed_hosts, insecure)  # before any connection: a refused address costs nothing
    sending: str | None = None
    try:
        with _open(url, allowed_hosts, max_redirects, insecure, timeout_s, deadline, max_seconds) as response:
            sending = url_host(response.geturl())
            length = response.headers.get("Content-Length", "")
            announced = int(length) if length.isascii() and length.isdigit() else None
            if announced is not None and announced > max_bytes:
                raise _refuse(f"la descarga anuncia {announced} bytes, por encima del límite de {max_bytes}.", announced=announced, max_bytes=max_bytes)
            try:
                descriptor, staging = _create_staging(dest)
            except OSError as local:
                raise _LocalFault from local
            logger.info("download start: announced size %s to %s", announced, staging)
            with os.fdopen(descriptor, "wb") as handle:
                while chunk := response.read1(chunk_bytes):
                    received += len(chunk)
                    if deadline is not None and time.perf_counter() >= deadline:
                        raise _deadline_error(max_seconds or 0.0, received, host=sending)
                    if received > max_bytes:
                        raise _refuse(f"la respuesta supera el límite de {max_bytes} bytes.", received=received, max_bytes=max_bytes)
                    try:
                        handle.write(chunk)
                    except OSError as local:   # a full disk is not a cut connection, and retrying the download would not help
                        raise _LocalFault from local
                    digest.update(chunk)
        if announced is not None and received != announced:
            raise DownloadError(f"Se recibieron {received} bytes pero se anunciaron {announced}.")
    except _LocalFault as fault:
        cause = fault.__cause__
        discard()
        if staging is None:
            logger.warning("download could not start (local fault) after %.1f s: %s", took(), cause, exc_info=cause)
        else:
            logger.warning("download stopped by a local fault after %d bytes and %.1f s: %s", received, took(), cause, exc_info=cause)
        raise cause from None
    except SourceError as error:
        discard()
        logger.warning("download refused after %.1f s: %s", took(), error)
        raise
    except DownloadError as error:
        discard()
        logger.warning("download failed after %.1f s: %s", took(), error)
        raise
    except (TimeoutError, http.client.HTTPException, OSError) as error:
        discard()
        if isinstance(error, TimeoutError) and _expired(deadline):
            failure: DownloadError = _deadline_error(max_seconds or 0.0, received, host=sending)
        elif isinstance(error, TimeoutError):
            failure = DownloadError(f"Se agotó el tiempo de espera de {timeout_s} s al leer la respuesta.")
        else:
            failure = DownloadError(f"La conexión se cortó tras {received} bytes: {error}.")
        logger.warning("download failed after %.1f s: %s", took(), failure)
        raise failure from error
    except BaseException:
        discard()
        raise
    assert staging is not None  # a response was read to the end
    actual = digest.hexdigest()
    if actual != accepted_sha256:
        os.replace(staging, part)
        logger.error("download hash mismatch after %.1f s: got %s, accepted %s; kept %s", took(), actual, accepted_sha256, part)
        raise SourceError(
            "V01",
            f"la huella SHA-256 del zip descargado es {actual} y la aceptada es {accepted_sha256}; se conservó {part} para inspeccionarlo y no se reemplazó {dest}.",
            [{"rule_id": "V01", "expected": accepted_sha256, "actual": actual, "kept": str(part)}],
        )
    os.replace(staging, dest)
    try:
        part.unlink(missing_ok=True)  # the accepted file supersedes what an earlier failure kept for inspection
    except OSError as error:  # the download is finished and verified: a stale part that cannot be cleared must not turn it into a failure
        logger.warning("download accepted but the earlier %s could not be removed: %s", part, error)
    logger.info("download end: %s, %d bytes, sha256 %s, in %.1f s", dest, received, actual, took())
    return dest, actual


# --- the manifest of the source and the local mode (RF01) --------------------------------------------------------------


@dataclass(frozen=True)
class SourceManifest:
    """The zip the canonical lines were built from (``<raw_dir>/source_manifest.json``): in local mode, its hash is the registered one."""

    mode: str
    source: str        # the URL, or the local path
    sha256: str
    size: int
    fetched_at: str
    zip_path: str      # the file name in raw_dir (http mode) or the local path (local mode)


def read_source_manifest(path: Path) -> SourceManifest | None:
    """The manifest, or None if there is none. Anything else than the exact format is a ``ValueError``."""
    path = Path(path)
    if not path.exists():
        return None
    names = {f.name for f in fields(SourceManifest)}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("version") != MANIFEST_VERSION or set(document) != {"version", "source"}:
            raise KeyError(f"versión o claves inesperadas: {sorted(document)}")
        raw = document["source"]
        if set(raw) != names:
            raise KeyError(f"claves distintas de las esperadas: {sorted(set(raw) ^ names)}")
        return SourceManifest(**raw)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"{path} no es un manifiesto de la fuente válido: {error}") from error


def write_source_manifest(path: Path, manifest: SourceManifest) -> None:
    write_atomic(Path(path), json.dumps({"version": MANIFEST_VERSION, "source": asdict(manifest)}, indent=2, ensure_ascii=False) + "\n")


def local_source(zip_path: Path, manifest_path: Path, max_bytes: int) -> tuple[str, int]:
    """Check a local zip before anything reads it; return ``(sha256, size)``. Nothing is written.

    A zip larger than `max_bytes` is refused before it is hashed (V02, the same cap as a download); once a hash is registered in the manifest,
    any other is refused (V01, runbook R1). The task registers the first hash only after the content has been read without a failing rule (U05).
    """
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise FileNotFoundError(f"no existe el zip local: {zip_path}")
    size = zip_path.stat().st_size
    if size > max_bytes:
        raise _refuse(f"el zip local {zip_path} pesa {size} bytes, por encima del límite de {max_bytes} ([source] max_bytes).", size=size, max_bytes=max_bytes)
    digest = sha256_file(zip_path)
    registered = read_source_manifest(manifest_path)
    if registered is not None and registered.sha256 != digest:
        raise SourceError(
            "V01",
            f"el zip {zip_path} tiene la huella SHA-256 {digest} y la registrada es {registered.sha256}; no se cambió nada (runbook R1).",
            [{"rule_id": "V01", "expected": registered.sha256, "actual": digest, "kept": str(zip_path)}],
        )
    return digest, size


# --- extraction (V03) ------------------------------------------------------------------------------------------------

ZIP_NAME = "online_retail_ii.zip"
CANONICAL_NAME = "source_lines.parquet"
INTERIM_MANIFEST = "interim_manifest.json"
INTERIM_MANIFEST_VERSION = 1
ATTRIBUTION = "Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5CG6D (CC BY 4.0)"
FINGERPRINT_KEY = b"churnrisk.source_sha256"
ATTRIBUTION_KEY = b"churnrisk.attribution"
SOURCE_REPORT_KEY = b"churnrisk.source_report"
EXAMPLES = 5                                   # examples kept for each column that does not convert (V05)
MASKED_COLUMNS = ("Invoice", "Customer ID")    # identifiers (D26): an example says the type and the length of the value, never the value
_HEX64 = re.compile(r"[0-9a-f]{64}")


def _bare_name(member: str) -> bool:
    return bool(member) and "/" not in member and "\\" not in member and member not in (".", "..") and not Path(member).is_absolute()


def extract_member(zip_path: Path, member: str, max_member_bytes: int, member_sha256: str, *, out_dir: Path | None = None) -> Path:
    """Extract the single expected `member` of the zip to a file of its own in `out_dir` (the zip's folder by default) and return its path (V03).

    The zip must hold exactly that member, by that exact name (no path, no ``..``), unencrypted and no larger than `max_member_bytes`, checked
    against the declared size and again while it is written; with a `member_sha256` (http mode), the bytes must hash to it. The name on disk is
    random and never one read from the archive. A refused member leaves no file behind.
    """
    if not _bare_name(member):
        raise ValueError(f"member: se esperaba un nombre de archivo sin ruta, se recibió {member!r}")
    zip_path = Path(zip_path)
    out_dir = Path(out_dir) if out_dir is not None else zip_path.parent

    def refuse(message: str, **details: Any) -> SourceError:
        return SourceError("V03", message, [{"rule_id": "V03", "zip": zip_path.name, **details}])

    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as error:
        raise refuse(f"{zip_path.name} no es un archivo zip válido ({error}).") from error
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if names != [member]:
            raise refuse(f"el zip debe contener solo el miembro «{member}», sin ruta, pero contiene {names}.", members=names)
        info = infos[0]
        if info.flag_bits & 0x1:
            raise refuse(f"el miembro «{member}» está cifrado.")
        if info.file_size > max_member_bytes:
            raise refuse(f"el miembro «{member}» declara {info.file_size} bytes, por encima del límite de {max_member_bytes} ([source] max_member_bytes).",
                         size=info.file_size, max_member_bytes=max_member_bytes)
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{secrets.token_hex(8)}.{member}"
        digest = hashlib.sha256()
        written = 0
        try:
            with archive.open(info) as source, target.open("xb") as handle:
                while chunk := source.read(1 << 20):
                    written += len(chunk)
                    if written > max_member_bytes:
                        raise refuse(f"el miembro «{member}» supera el límite de {max_member_bytes} bytes al descomprimirse.", size=written,
                                     max_member_bytes=max_member_bytes)
                    handle.write(chunk)
                    digest.update(chunk)
        except SourceError:
            target.unlink(missing_ok=True)
            raise
        except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError) as error:
            target.unlink(missing_ok=True)
            raise refuse(f"el miembro «{member}» está dañado o no se puede descomprimir ({error}).") from error
        except BaseException:
            target.unlink(missing_ok=True)
            raise
    actual = digest.hexdigest()
    if member_sha256 and actual != member_sha256:
        target.unlink(missing_ok=True)
        raise refuse(f"la huella SHA-256 del miembro «{member}» es {actual} y la aceptada es {member_sha256} ([source] member_sha256).",
                     expected=member_sha256, actual=actual)
    logger.info("extracted %s (%d bytes, sha256 %s)", member, written, actual)
    return target


# --- reading the workbook (V04, V05, V06) ------------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceReport:
    """What the reading of the workbook found; the validation (I03, V28) and the reports quote it. Counts only: no value of a line."""

    rows_by_sheet: dict[str, int]
    overlap_start: date | None
    overlap_end: date | None
    overlap_rows: int              # rows of sheet 2 dropped because sheet 1 holds the same rows (I03)
    overlap_value_gbp: float       # their gross value, |quantity x price|
    canonical_lines: int
    repeated_lines: int            # rows equal to an earlier row of their own sheet, kept and flagged (V28)
    blank_rows: dict[str, int] = field(default_factory=dict)
    extra_sheets: tuple[str, ...] = ()


def _v04(message: str, **details: Any) -> SourceError:
    return SourceError("V04", message, [{"rule_id": "V04", **details}])


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or (isinstance(value, str) and not value.strip())


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value == int(value):
        return int(value)
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _text(value: Any) -> str | None:
    """A non-blank text, or an integer cell written as its digits (the workbook mixes both for invoices and codes)."""
    if isinstance(value, str):
        return value if value.strip() else None
    number = _integer(value)
    return None if number is None else str(number)


def _timestamp(value: Any) -> datetime | None:
    return value if isinstance(value, datetime) else None


_MISSING = object()   # a blank customer, which is allowed (a guest)


def _customer(value: Any) -> Any:
    if _is_blank(value):
        return _MISSING
    number = _integer(value)
    return number if number is not None and CUSTOMER_ID_RANGE[0] <= number <= CUSTOMER_ID_RANGE[1] else None


_CONVERTERS = (("Invoice", _text), ("StockCode", _text), ("Quantity", _integer), ("InvoiceDate", _timestamp), ("Price", _number), ("Customer ID", _customer))


def _shown_value(column: str, value: Any) -> str:
    if column in MASKED_COLUMNS:
        return f"<{type(value).__name__} de {len(str(value))} caracteres>"
    text = repr(value)
    return text[:60] + "..." if len(text) > 60 else text


def _read_sheet(sheet, name: str) -> tuple[dict[str, list], list[int], int, list[dict]]:
    """The eight columns of one sheet as converted lists, the data row of each line (from 1), the blank rows skipped and the V05 problems."""
    width = len(WORKBOOK_COLUMNS)
    kept: list[tuple] = []
    source_rows: list[int] = []
    blank = 0
    rows = sheet.iter_rows(values_only=True)
    try:   # closing the generator releases the sheet's file at once: on Windows an open handle would keep the extracted member from being removed
        header = list(next(rows, ()))
        while header and header[-1] is None:
            header.pop()
        if tuple(header) != WORKBOOK_COLUMNS:
            present = [str(h) for h in header]
            raise _v04(
                f"la hoja «{name}» no tiene exactamente las columnas {', '.join(WORKBOOK_COLUMNS)}, en ese orden; tiene {', '.join(present) or 'ninguna'}.",
                sheet=name, columns=present, missing=[c for c in WORKBOOK_COLUMNS if c not in present], extra=[c for c in present if c not in WORKBOOK_COLUMNS],
            )
        for number, row in enumerate(rows, start=1):
            if len(row) > width and any(value is not None for value in row[width:]):
                raise _v04(f"la hoja «{name}» tiene datos fuera de las {width} columnas en la fila {number} (fila {number + 1} en Excel).", sheet=name, row=number)
            values = tuple(row[:width]) + (None,) * max(0, width - len(row))
            if all(value is None for value in values):
                blank += 1
                continue
            kept.append(values)
            source_rows.append(number)
    finally:
        rows.close()
    columns = dict(zip(WORKBOOK_COLUMNS, map(list, zip(*kept, strict=True)), strict=True)) if kept else {c: [] for c in WORKBOOK_COLUMNS}
    problems: list[dict] = []
    for column, convert in _CONVERTERS:
        converted = [convert(value) for value in columns[column]]
        bad = [i for i, value in enumerate(converted) if value is None]
        if bad:
            problems.append({"rule_id": "V05", "sheet": name, "column": column, "count": len(bad), "examples": [
                {"row": source_rows[i], "value": _shown_value(column, columns[column][i])} for i in bad[:EXAMPLES]]})
        columns[column] = [None if value is _MISSING else value for value in converted]
    columns["Description"] = [None if _is_blank(v) else str(v) for v in columns["Description"]]
    columns["Country"] = ["" if _is_blank(v) else str(v) for v in columns["Country"]]
    return columns, source_rows, blank, problems


_COMPARED = list(COLUMN_NAMES.values())


def _typed(columns: dict[str, list], source_rows: list[int], number: int) -> pd.DataFrame:
    frame = pd.DataFrame({
        "sheet": np.full(len(source_rows), number, dtype="int64"),
        "source_row": np.asarray(source_rows, dtype="int64"),
        "invoice": pd.Series(columns["Invoice"], dtype=object),
        "stock_code": pd.Series(columns["StockCode"], dtype=object),
        "description": pd.Series(columns["Description"], dtype=object),
        "quantity": pd.Series(columns["Quantity"], dtype="int64"),
        "invoice_ts": pd.to_datetime(pd.Series(columns["InvoiceDate"], dtype=object)).astype("datetime64[ns]"),
        "price": pd.Series(columns["Price"], dtype="float64"),
        "customer_id": pd.array(columns["Customer ID"], dtype="Int64"),
        "country": pd.Series(columns["Country"], dtype=object),
    })
    frame["is_repeated_line"] = frame.duplicated(subset=_COMPARED, keep="first")
    return frame


def _row_hashes(frame: pd.DataFrame) -> pd.Series:
    return pd.util.hash_pandas_object(frame[_COMPARED], index=False)


def _same_rows(first: pd.DataFrame, second: pd.DataFrame) -> tuple[bool, int, int]:
    """Whether both frames hold the same multiset of rows; if not, how many rows of each side have no pair (project 02)."""
    h1, h2 = _row_hashes(first), _row_hashes(second)
    if len(first) == len(second):
        a = first.loc[h1.sort_values(kind="stable").index, _COMPARED].reset_index(drop=True)
        b = second.loc[h2.sort_values(kind="stable").index, _COMPARED].reset_index(drop=True)
        if a.equals(b):
            return True, 0, 0
    only_first = h1.value_counts().sub(h2.value_counts(), fill_value=0).clip(lower=0).sum()
    only_second = h2.value_counts().sub(h1.value_counts(), fill_value=0).clip(lower=0).sum()
    return False, int(only_first), int(only_second)


def read_source(xlsx: Path, cfg: PipelineConfig) -> tuple[pd.DataFrame, SourceReport]:
    """Read the configured sheets of the workbook into one table of canonical lines, in sheet and row order.

    Raises ``SourceError`` for V04 (a sheet missing, or a header that is not the eight columns in order), V05 (a value that does not convert:
    ``Quantity`` an integer, ``Price`` a number, ``InvoiceDate`` a date and time, ``Invoice`` and ``StockCode`` not empty, ``Customer ID`` an
    integer of five digits or empty) and V06 (the days the sheets share do not hold the same multiset of rows). Sheet 2's copies of those days
    are dropped; rows repeated inside a sheet are kept with ``is_repeated_line``. ``invoice_date`` is the first date of each invoice.
    """
    sheets = cfg.source.sheets
    try:
        book = openpyxl.load_workbook(Path(xlsx), read_only=True, data_only=True)
    except Exception as error:  # an untrusted file: any failure to open it is the rule's failure, with its cause
        raise _v04(f"el libro no se puede abrir como .xlsx ({type(error).__name__}: {error}).") from error
    try:
        present = list(book.sheetnames)
        missing = [name for name in sheets if name not in present]
        if missing:
            raise SourceError("V04", f"el libro no tiene la hoja «{missing[0]}» (hojas presentes: {', '.join(present) or 'ninguna'}).",
                              [{"rule_id": "V04", "sheet": name, "missing_sheet": True, "present": present} for name in missing])
        read = [_read_sheet(book[name], name) for name in sheets]
    finally:
        book.close()
    problems = [problem for _c, _r, _b, found in read for problem in found]
    if problems:
        described = "; ".join(f"hoja «{p['sheet']}», columna «{p['column']}»: {p['count']} valores no cumplen el tipo" for p in problems)
        raise SourceError("V05", described + ".", problems)

    frames = [_typed(columns, rows, number) for number, (columns, rows, _b, _p) in enumerate(read, start=1)]
    overlap_start = overlap_end = None
    dropped, dropped_value = 0, 0.0
    if len(frames) == 2 and len(frames[0]) and len(frames[1]):
        first, second = frames
        first_days, second_days = first["invoice_ts"].dt.normalize(), second["invoice_ts"].dt.normalize()
        if second_days.min() <= first_days.max():
            start, end = second_days.min(), first_days.max()
            in_first, in_second = first_days >= start, second_days <= end
            same, only_first, only_second = _same_rows(first[in_first], second[in_second])
            if not same:
                raise SourceError(
                    "V06",
                    f"los días que comparten las hojas ({start.date()} a {end.date()}) no tienen las mismas filas: {only_first} filas de la hoja 1 y "
                    f"{only_second} de la hoja 2 no tienen su par.",
                    [{"rule_id": "V06", "start": start.date().isoformat(), "end": end.date().isoformat(), "only_in_first": only_first, "only_in_second": only_second}],
                )
            overlap_start, overlap_end = start.date(), end.date()
            dropped = int(in_second.sum())
            dropped_value = round(float((second.loc[in_second, "quantity"] * second.loc[in_second, "price"]).abs().sum()), 2)
            frames[1] = second[~in_second]
    canonical = pd.concat(frames, ignore_index=True)
    canonical["line_id"] = (canonical["sheet"] * LINE_ID_SHEET_FACTOR + canonical["source_row"]).astype("int64")
    canonical["invoice_date"] = canonical.groupby("invoice")["invoice_ts"].transform("min").dt.normalize()
    canonical["code_kind"] = code_kinds(canonical["stock_code"])
    canonical = canonical[CANONICAL_SCHEMA.names].reset_index(drop=True)
    report = SourceReport(
        rows_by_sheet={name: len(rows) for name, (_c, rows, _b, _p) in zip(sheets, read, strict=True)},
        overlap_start=overlap_start, overlap_end=overlap_end, overlap_rows=dropped, overlap_value_gbp=dropped_value,
        canonical_lines=len(canonical), repeated_lines=int(canonical["is_repeated_line"].sum()),
        blank_rows={name: blank for name, (_c, _r, blank, _p) in zip(sheets, read, strict=True)},
        extra_sheets=tuple(name for name in present if name not in sheets),
    )
    logger.info("canonical read: %d lines (%d copies of the shared days dropped, %d repeated)", len(canonical), dropped, report.repeated_lines)
    return canonical, report


# --- the canonical lines on disk, with their manifest written last (project 03, D50) ----------------------------------------


class InterimError(ValueError):
    """The canonical lines are not the file their manifest names: missing, changed, from another source, or without a manifest."""


def _report_json(report: SourceReport) -> bytes:
    document = asdict(report)
    for key in ("overlap_start", "overlap_end"):
        document[key] = document[key].isoformat() if document[key] else None
    document["extra_sheets"] = list(report.extra_sheets)
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _report_from(raw: bytes) -> SourceReport:
    document = json.loads(raw)
    for key in ("overlap_start", "overlap_end"):
        document[key] = date.fromisoformat(document[key]) if document[key] else None
    document["extra_sheets"] = tuple(document["extra_sheets"])
    return SourceReport(**document)


def write_canonical(frame: pd.DataFrame, report: SourceReport, interim_dir: Path, source_sha256: str) -> Path:
    """Write ``source_lines.parquet`` atomically and then ``interim_manifest.json`` with its hash and the source's: a failure between the two leaves
    a file that does not match its manifest, which every reader refuses and the task rebuilds, never a table read from another source."""
    interim_dir = Path(interim_dir)
    table = pa.Table.from_pandas(frame, schema=CANONICAL_SCHEMA, preserve_index=False)
    metadata = {**(table.schema.metadata or {}), FINGERPRINT_KEY: source_sha256.encode("ascii"), ATTRIBUTION_KEY: ATTRIBUTION.encode("utf-8"),
                SOURCE_REPORT_KEY: _report_json(report)}
    target = interim_dir / CANONICAL_NAME
    with atomic_path(target) as temporary:
        pq.write_table(table.replace_schema_metadata(metadata), temporary)
    manifest = {"version": INTERIM_MANIFEST_VERSION, "source_sha256": source_sha256, "files": {CANONICAL_NAME: sha256_file(target)}}
    write_atomic(interim_dir / INTERIM_MANIFEST, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return target


def _canonical_problem(interim_dir: Path) -> tuple[str | None, dict]:
    folder = Path(interim_dir)
    path = folder / INTERIM_MANIFEST
    if not path.is_file():
        return f"falta {INTERIM_MANIFEST} en {folder}: las líneas canónicas no tienen su manifiesto", {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        valid = (isinstance(document, dict) and set(document) == {"version", "source_sha256", "files"} and document["version"] == INTERIM_MANIFEST_VERSION
                 and isinstance(document["source_sha256"], str) and _HEX64.fullmatch(document["source_sha256"]) is not None
                 and isinstance(document["files"], dict) and set(document["files"]) == {CANONICAL_NAME}
                 and isinstance(document["files"][CANONICAL_NAME], str) and _HEX64.fullmatch(document["files"][CANONICAL_NAME]) is not None)
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        return f"{INTERIM_MANIFEST} no es un manifiesto válido de las líneas canónicas", {}
    target = folder / CANONICAL_NAME
    if not target.is_file():
        return f"falta {CANONICAL_NAME}, que el manifiesto nombra", {}
    if sha256_file(target) != document["files"][CANONICAL_NAME]:
        return f"{CANONICAL_NAME} no coincide con la huella que dice el manifiesto: es de otra escritura", {}
    try:
        metadata = pq.read_schema(target).metadata or {}
    except (OSError, pa.ArrowException):
        return f"{CANONICAL_NAME} no se puede leer", {}
    if metadata.get(FINGERPRINT_KEY) != document["source_sha256"].encode("ascii") or SOURCE_REPORT_KEY not in metadata:
        return f"{CANONICAL_NAME} no es de la fuente que dice el manifiesto", {}
    return None, metadata


def canonical_state(interim_dir: Path) -> tuple[str, SourceReport] | None:
    """``(source_sha256, report)`` of the canonical lines, or None if they are not the file their manifest names."""
    problem, metadata = _canonical_problem(interim_dir)
    if problem is not None:
        return None
    return metadata[FINGERPRINT_KEY].decode("ascii"), _report_from(metadata[SOURCE_REPORT_KEY])


def read_canonical(interim_dir: Path) -> tuple[pd.DataFrame, SourceReport]:
    """The canonical lines and their report; ``InterimError`` if the file is not the one its manifest names."""
    problem, metadata = _canonical_problem(interim_dir)
    if problem is not None:
        raise InterimError(problem)
    table = pq.read_table(Path(interim_dir) / CANONICAL_NAME)
    frame = table.drop(["customer_id"]).to_pandas()
    frame.insert(CANONICAL_SCHEMA.names.index("customer_id"), "customer_id",
                 pd.Series(table.column("customer_id").to_numpy(zero_copy_only=False)).astype("Int64"))
    for column in ("invoice_ts", "invoice_date"):
        frame[column] = frame[column].astype("datetime64[ns]")
    return frame, _report_from(metadata[SOURCE_REPORT_KEY])


# --- the first task ----------------------------------------------------------------------------------------------------


class _HasConfig(Protocol):
    cfg: PipelineConfig


def fetch_source(ctx: _HasConfig, *, insecure_hosts: frozenset[str] | set[str] = frozenset()) -> dict[str, Any]:
    """Task 1: make sure the zip is the pinned one (http) or the registered one (local), and the canonical lines are built from it.

    http mode downloads the zip only if it is not in ``raw_dir`` and checks its SHA-256 against ``accepted_sha256`` (V01) and its member's against
    ``member_sha256`` (V03); local mode checks the size and the registered SHA-256 and registers the first one it sees only once the workbook was
    read without a failing rule. A rejected source writes nothing. The canonical lines are rebuilt only when they are missing, do not match their
    manifest or come from another zip, so repeating the task changes nothing. `insecure_hosts` is for tests only (see ``download_file``).
    """
    cfg = ctx.cfg
    source, raw_dir, interim_dir = cfg.source, cfg.paths.raw_dir, cfg.paths.interim_dir
    if source.mode not in ("http", "local"):   # a configuration built without load_config skips its check: an unknown mode is not silently local
        raise ValueError(f"[source] mode: se esperaba 'http' o 'local', se recibió {source.mode!r}")
    manifest_path = raw_dir / MANIFEST_NAME
    downloaded, download_seconds = False, 0.0
    if source.mode == "http":
        zip_path = raw_dir / ZIP_NAME
        if zip_path.exists():
            digest = sha256_file(zip_path)
            if digest != source.accepted_sha256:
                raise SourceError("V01", f"el zip {zip_path} tiene la huella SHA-256 {digest} y la aceptada es {source.accepted_sha256}; no se cambió nada (runbook R1).",
                                  [{"rule_id": "V01", "expected": source.accepted_sha256, "actual": digest, "kept": str(zip_path)}])
        else:
            started = time.perf_counter()
            _, digest = download_file(source.url, zip_path, source.accepted_sha256, source.allowed_hosts, source.max_redirects, source.max_bytes,
                                      source.max_seconds, source.chunk_bytes, source.timeout_s, insecure_hosts=insecure_hosts)
            download_seconds, downloaded = round(time.perf_counter() - started, 3), True
        location, member_sha256 = source.url, source.member_sha256
    else:
        if source.local_path is None:
            raise ValueError("[source] local_path: con mode = 'local' hace falta la ruta del zip")
        zip_path = source.local_path
        digest, _size = local_source(zip_path, manifest_path, source.max_bytes)
        location, member_sha256 = str(zip_path), ""
    size = zip_path.stat().st_size
    manifest = SourceManifest(mode=source.mode, source=location, sha256=digest, size=size, fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
                              zip_path=zip_path.name if source.mode == "http" else str(zip_path))
    result: dict[str, Any] = {"zip_path": str(zip_path), "sha256": digest, "size": size, "downloaded": downloaded, "download_seconds": download_seconds}

    state = canonical_state(interim_dir)
    if state is not None and state[0] == digest:
        current = read_source_manifest(manifest_path)
        if current is None or current.sha256 != digest:
            write_source_manifest(manifest_path, manifest)
        report = state[1]
        logger.info("canonical lines already built from %s", digest)
        return result | {"built": False, "lines": report.canonical_lines, "overlap_rows": report.overlap_rows, "repeated_lines": report.repeated_lines}

    with tempfile.TemporaryDirectory(prefix="churnrisk-extract-") as folder:   # the member never stays: only the canonical lines do
        xlsx = extract_member(zip_path, source.member, source.max_member_bytes, member_sha256, out_dir=Path(folder))
        frame, report = read_source(xlsx, cfg)
    write_canonical(frame, report, interim_dir, digest)
    write_source_manifest(manifest_path, manifest)
    return result | {"built": True, "lines": report.canonical_lines, "overlap_rows": report.overlap_rows, "repeated_lines": report.repeated_lines}
