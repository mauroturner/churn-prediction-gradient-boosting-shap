"""Source ingestion: the download with its fingerprint (RF01, RF02) and, for the local mode, the hash registered the first time.

The zip is untrusted input (D02). ``download_file`` checks every address before it requests it (``check_hop``: HTTPS on the default port to
a listed host, no user information, spaces, control characters or backslashes), follows redirects one checked hop at a time up to
``max_redirects``, holds the announced length and the bytes received to ``max_bytes`` and the whole call to ``max_seconds``, streams the
body to a staging file of its own while hashing it, and moves it to the destination only if the SHA-256 is the accepted one (V01, V02).
A different hash keeps the whole download as ``<dest>.part`` and leaves the destination exactly as it was. The code is project 03's
corrected downloader (its D41, D48, D49), adapted; the extraction, the reading of the workbook and the task ``fetch_source`` come in U05.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from churnrisk.config import host_allowed, url_host
from churnrisk.files import sha256_file, write_atomic
from churnrisk.schema import SourceError

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
