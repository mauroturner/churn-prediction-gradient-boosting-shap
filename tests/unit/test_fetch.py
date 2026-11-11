"""Download, fingerprint and redirects to allowed hosts only, and the local source's registered hash (U04, item 2: the download is
untrusted): AC01 and AC02, RF01, RF02, V01, V02 (D02, D50)."""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import re
import secrets
import time
import urllib.parse
from pathlib import Path

import pytest

from churnrisk import ingest
from churnrisk.ingest import (
    MANIFEST_NAME,
    STAGING_ATTEMPTS,
    USER_AGENT,
    DownloadDeadlineError,
    DownloadError,
    SourceManifest,
    check_hop,
    download_file,
    local_source,
    read_source_manifest,
    write_source_manifest,
)
from churnrisk.schema import SourceError
from tests.fixtures.http_server import ALT_HOST as ALT
from tests.fixtures.http_server import FileServer

LOCAL = frozenset({"127.0.0.1"})
BODY = b"PK\x03\x04 not a real zip, only bytes to hash " * 100   # 4,000 bytes: the download never opens what it receives
UCI = "archive.ics.uci.edu"
DRIP = "/drip?step=1050&pause=0.5"     # 4 pieces, half a second apart: about 2 s in all (project 03, D91)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


GOOD = sha(BODY)
BAD = "0" * 64


def snapshot(folder: Path) -> dict[str, str]:
    """Relative path -> SHA-256 of every file under `folder` (empty if it does not exist)."""
    if not folder.exists():
        return {}
    return {p.relative_to(folder).as_posix(): sha(p.read_bytes()) for p in sorted(folder.rglob("*")) if p.is_file()}


def leftovers(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.rglob("*") if p.is_file())


def get(server: FileServer, path: str, dest: Path, digest: str = GOOD, *, hosts=("127.0.0.1",), redirects: int = 3, cap: int = 10_000_000,
        seconds: float | None = 30, chunk: int = 1000, timeout: int = 10, insecure=LOCAL):
    return download_file(server.url(path), dest, digest, list(hosts), redirects, cap, seconds, chunk, timeout, insecure_hosts=insecure)


# --- check_hop: the rule applied to every address, the first and each redirect ---------------------------------------


@pytest.mark.parametrize(("url", "host"), [
    ("https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip", UCI),
    ("https://ARCHIVE.ics.uci.edu:443/a", UCI),
    ("https://files.example.org/a?signature=abc", "files.example.org"),
])
def test_check_hop_accepts_https_to_a_listed_host(url, host):
    assert check_hop(url, (UCI, ".example.org")) == host


@pytest.mark.parametrize(("url", "match"), [
    ("http://archive.ics.uci.edu/a", "HTTPS"),
    ("ftp://archive.ics.uci.edu/a", "esquema"),
    ("file:///etc/passwd", "esquema"),
    ("https://evil.example.com/a", "no está en la lista"),
    ("https://archive.ics.uci.edu.evil.com/a", "no está en la lista"),
    ("https://ics.uci.edu/a", "no está en la lista"),
    ("https://archive.ics.uci.edu@evil.com/a", "dirección"),
    ("https://evil.com@archive.ics.uci.edu/a", "dirección"),
    ("https://evil.com\\@archive.ics.uci.edu/a", "dirección"),
    ("https://archive.ics.uci.edu/a b", "dirección"),
    ("https://archive.ics.uci.edu/a\r\nX: y", "dirección"),
    ("https://archive.ics.uci.edu:8443/a", "puerto"),
    ("//archive.ics.uci.edu/a", "esquema"),
    ("", "dirección"),
])
def test_check_hop_refuses_with_rule_v02_and_says_why(url, match):
    with pytest.raises(SourceError, match=rf"^V02:.*{match}") as error:
        check_hop(url, (UCI, ".example.org"))
    assert error.value.rule_id == "V02" and error.value.problems


def test_check_hop_lets_a_test_use_plain_http_on_named_hosts_only():
    assert check_hop("http://127.0.0.1:8080/x", ("127.0.0.1",), frozenset({"127.0.0.1"})) == "127.0.0.1"
    with pytest.raises(SourceError, match="HTTPS"):
        check_hop("http://127.0.0.2:8080/x", ("127.0.0.1", ALT), frozenset({"127.0.0.1"}))
    with pytest.raises(SourceError, match="HTTPS"):
        check_hop("http://127.0.0.1:8080/x", ("127.0.0.1",))


# --- the file, the hash and the part (AC01) --------------------------------------------------------------------------


def test_download_writes_the_file_and_returns_its_hash(tmp_path):
    with FileServer(BODY) as server:
        dest, digest = get(server, "/file.zip", tmp_path / "raw" / "f.zip")
    assert dest == tmp_path / "raw" / "f.zip" and dest.read_bytes() == BODY and digest == GOOD
    assert leftovers(tmp_path / "raw") == ["f.zip"], "no part and no staging file are left"
    assert server.paths() == ["/file.zip"] and [m for m, _p, _h in server.requests] == ["GET"]
    assert server.requests[0][2]["User-Agent"] == USER_AGENT and USER_AGENT.startswith("churnrisk-pipeline/")


def test_hash_mismatch_leaves_part_and_changes_nothing(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "f.zip").write_bytes(b"the accepted file from before")
    before = snapshot(raw)
    with FileServer(BODY) as server, pytest.raises(SourceError) as error:
        get(server, "/file.zip", raw / "f.zip", BAD)
    assert error.value.rule_id == "V01" and GOOD in str(error.value) and BAD in str(error.value)
    assert error.value.problems == [{"rule_id": "V01", "expected": BAD, "actual": GOOD, "kept": str(raw / "f.zip.part")}]
    after = snapshot(raw)
    assert after.pop("f.zip.part") == GOOD, "the whole download is kept, under .part, to be inspected"
    assert after == before, "the file that was there is untouched and nothing else was written"


def test_hash_mismatch_with_no_previous_file_creates_no_destination(tmp_path):
    with FileServer(BODY) as server, pytest.raises(SourceError, match="V01"):
        get(server, "/file.zip", tmp_path / "raw" / "f.zip", BAD)
    assert leftovers(tmp_path / "raw") == ["f.zip.part"]


def test_an_accepted_download_removes_the_part_an_earlier_failure_kept(tmp_path):
    with FileServer(BODY) as server:
        with pytest.raises(SourceError):
            get(server, "/file.zip", tmp_path / "f.zip", BAD)
        assert (tmp_path / "f.zip.part").exists()
        get(server, "/file.zip", tmp_path / "f.zip")
    assert leftovers(tmp_path) == ["f.zip"]


def test_a_part_that_cannot_be_removed_does_not_fail_an_accepted_download(tmp_path, caplog, monkeypatch):
    (tmp_path / "f.zip.part").write_bytes(b"old")
    real_unlink = Path.unlink

    def refuse(self, *args, **kwargs):
        if self.name.endswith(".part"):
            raise PermissionError("locked")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse)
    with FileServer(BODY) as server, caplog.at_level(logging.WARNING, logger="churnrisk"):
        dest, digest = get(server, "/file.zip", tmp_path / "f.zip")
    assert dest.read_bytes() == BODY and digest == GOOD
    assert any("could not be removed" in r.getMessage() for r in caplog.records)


def test_a_response_without_content_length_is_accepted_when_the_hash_matches(tmp_path):
    with FileServer(BODY) as server:
        dest, digest = get(server, "/no-length", tmp_path / "f.zip", chunk=100)
    assert dest.read_bytes() == BODY and digest == GOOD


def test_a_truncated_download_is_a_download_error_and_leaves_nothing(tmp_path):
    with FileServer(BODY) as server, pytest.raises(DownloadError, match="bytes"):
        get(server, "/truncated", tmp_path / "raw" / "f.zip")
    assert leftovers(tmp_path) == []


@pytest.mark.parametrize(("path", "needle"), [("/status/404", "404"), ("/status/500", "500"), ("/nothing-here", "404"), ("/status/206", "206")])
def test_http_errors_and_other_statuses_are_download_errors_that_name_the_status(tmp_path, path, needle):
    with FileServer(BODY) as server, pytest.raises(DownloadError, match=needle) as error:
        get(server, path, tmp_path / "f.zip")
    if needle == "404":
        assert "R11" in str(error.value)
    assert leftovers(tmp_path) == []


def test_a_refused_connection_is_a_download_error(tmp_path):
    with FileServer(BODY) as server:
        url = server.url("/file.zip")
    with pytest.raises(DownloadError, match="conectar"):
        download_file(url, tmp_path / "f.zip", GOOD, ["127.0.0.1"], 3, 10**7, 30, 1000, 2, insecure_hosts=LOCAL)
    assert leftovers(tmp_path) == []


def test_every_transport_failure_is_logged_before_it_is_raised(tmp_path, caplog):
    with FileServer(BODY) as server, caplog.at_level(logging.WARNING, logger="churnrisk"):
        for path in ("/status/500", "/truncated"):
            with pytest.raises(DownloadError):
                get(server, path, tmp_path / "f.zip")
    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(messages) == 2 and all(m.startswith("download failed") for m in messages)


# --- the size cap (V02, AC02) ----------------------------------------------------------------------------------------


def test_a_download_above_the_cap_is_refused_before_it_is_written_when_the_length_is_announced(tmp_path):
    with FileServer(BODY) as server, pytest.raises(SourceError, match=r"^V02:.*límite") as error:
        get(server, "/file.zip", tmp_path / "raw" / "f.zip", cap=len(BODY) - 1)
    assert error.value.problems[0]["max_bytes"] == len(BODY) - 1
    assert not (tmp_path / "raw").exists(), "nothing was created"
    with FileServer(BODY) as server:
        dest, _ = get(server, "/file.zip", tmp_path / "ok" / "f.zip", cap=len(BODY))
    assert dest.read_bytes() == BODY, "a body of exactly the cap is accepted"


def test_a_huge_announced_length_is_refused_without_reading_a_byte(tmp_path):
    with FileServer(BODY) as server, pytest.raises(SourceError, match=r"^V02:.*1000000000000"):
        get(server, "/huge", tmp_path / "f.zip")
    assert leftovers(tmp_path) == []


def test_an_endless_body_without_length_is_cut_at_the_cap_and_removed(tmp_path):
    with FileServer(BODY) as server, pytest.raises(SourceError, match=r"^V02:.*supera el límite"):
        get(server, "/endless", tmp_path / "raw" / "f.zip", cap=1_000_000, chunk=65536)
    assert leftovers(tmp_path) == []


# --- redirects: only to allowed hosts, over HTTPS, a bounded number of times (AC02) ----------------------------------


def test_redirect_to_unlisted_host_is_refused_before_following(tmp_path):
    with FileServer(BODY) as server:
        target = server.url("/file.zip", host=ALT)
        with pytest.raises(SourceError, match=r"^V02:.*127.0.0.2.*no está en la lista") as error:
            get(server, f"/redirect?to={target}", tmp_path / "raw" / "f.zip", insecure=frozenset({"127.0.0.1", ALT}))
        assert server.paths() == [f"/redirect?to={target}"], "the second address was never requested"
        assert not any(h.startswith(ALT) for h in server.hosts())
    assert error.value.problems[0]["host"] == ALT and error.value.problems[0]["hop"] == 1
    assert not (tmp_path / "raw").exists(), "nothing was created: no folder, no staging file, no part"


def test_redirect_to_a_listed_host_is_followed_and_the_hash_still_decides(tmp_path):
    both = frozenset({"127.0.0.1", ALT})
    with FileServer(BODY) as server:
        target = server.url("/file.zip", host=ALT)
        dest, digest = get(server, f"/redirect?to={target}", tmp_path / "f.zip", hosts=("127.0.0.1", ALT), insecure=both)
        assert dest.read_bytes() == BODY and digest == GOOD
        assert [h.split(":")[0] for h in server.hosts()] == ["127.0.0.1", ALT]
        with pytest.raises(SourceError, match="V01"):
            get(server, f"/redirect?to={target}", tmp_path / "other.zip", BAD, hosts=("127.0.0.1", ALT), insecure=both)


def test_a_redirect_to_plain_http_is_refused_even_to_a_listed_host(tmp_path):
    """The shape of a downgrade: the next hop is listed, but it is plain http on a host that is not one of the test's."""
    with FileServer(BODY) as server:
        target = server.url("/file.zip", host=ALT)
        with pytest.raises(SourceError, match=r"^V02:.*HTTPS"):
            get(server, f"/redirect?to={target}", tmp_path / "f.zip", hosts=("127.0.0.1", ALT), insecure=LOCAL)
        assert len(server.requests) == 1
    assert leftovers(tmp_path) == []


@pytest.mark.parametrize(("location", "match"), [
    ("ftp://127.0.0.1/file.zip", "esquema"),
    ("file:///etc/passwd", "esquema"),
    ("http://127.0.0.1@127.0.0.2/file.zip", "dirección"),
    ("http://127.0.0.1\\@127.0.0.2/file.zip", "dirección"),
    ("https://evil.example.com/file.zip", "no está en la lista"),
])
def test_every_unsafe_redirect_target_is_refused_and_not_requested(tmp_path, location, match):
    with FileServer(BODY) as server:
        with pytest.raises(SourceError, match=rf"^V02:.*{match}"):
            get(server, "/redirect?to=" + urllib.parse.quote(location, safe=""), tmp_path / "f.zip", insecure=frozenset({"127.0.0.1", ALT}))
        assert len(server.requests) == 1
    assert leftovers(tmp_path) == []


def test_a_relative_redirect_is_resolved_against_the_current_address(tmp_path):
    with FileServer(BODY) as server:
        dest, digest = get(server, "/redirect?to=/file.zip", tmp_path / "f.zip")
        assert server.paths() == ["/redirect?to=/file.zip", "/file.zip"]
    assert digest == GOOD and dest.read_bytes() == BODY


@pytest.mark.parametrize(("length", "limit", "ok"), [(0, 0, True), (3, 3, True), (4, 3, False), (1, 0, False)])
def test_the_number_of_redirects_is_bounded(tmp_path, length, limit, ok):
    with FileServer(BODY) as server:
        if ok:
            dest, _ = get(server, f"/chain/{length}", tmp_path / "f.zip", redirects=limit)
            assert dest.read_bytes() == BODY and len(server.requests) == length + 1
        else:
            with pytest.raises(SourceError, match=r"^V02:.*redirecciones") as error:
                get(server, f"/chain/{length}", tmp_path / "f.zip", redirects=limit)
            assert len(server.requests) == limit + 1, "the redirect over the limit is not followed"
            assert error.value.problems[0]["max_redirects"] == limit
            assert leftovers(tmp_path) == []


def test_a_redirect_loop_ends_at_the_limit_and_a_redirect_without_location_is_refused(tmp_path):
    with FileServer(BODY) as server:
        with pytest.raises(SourceError, match=r"^V02:.*redirecciones"):
            get(server, "/loop", tmp_path / "f.zip", redirects=3)
        assert len(server.requests) == 4
        with pytest.raises(SourceError, match=r"^V02:.*Location"):
            get(server, "/no-location", tmp_path / "f.zip")
    assert leftovers(tmp_path) == []


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_every_redirect_status_goes_through_the_same_checks(tmp_path, code):
    with FileServer(BODY) as server:
        dest, _ = get(server, f"/redirect?to=/file.zip&code={code}", tmp_path / "f.zip")
        assert dest.read_bytes() == BODY and server.paths()[-1] == "/file.zip"
        with pytest.raises(SourceError, match=r"^V02:"):
            get(server, f"/redirect?to=ftp://127.0.0.1/x&code={code}", tmp_path / "g.zip")


def test_the_log_names_the_host_of_every_hop(tmp_path, caplog):
    both = frozenset({"127.0.0.1", ALT})
    with FileServer(BODY) as server, caplog.at_level(logging.INFO, logger="churnrisk"):
        target = server.url("/file.zip", host=ALT)
        get(server, f"/redirect?to={target}", tmp_path / "f.zip", hosts=("127.0.0.1", ALT), insecure=both)
    hops = [r.getMessage() for r in caplog.records if r.getMessage().startswith("download hop")]
    assert len(hops) == 2 and "127.0.0.1" in hops[0] and ALT in hops[1]


@pytest.mark.parametrize(("url", "match"), [
    ("file:///etc/passwd", "esquema"), ("ftp://127.0.0.1/x", "esquema"), ("http://127.0.0.1:9/x", "HTTPS"), ("https://evil.example.com/x", "no está en la lista"),
])
def test_the_first_address_is_checked_before_connecting_and_nothing_is_created(tmp_path, url, match):
    with pytest.raises(SourceError, match=rf"^V02:.*{match}"):
        download_file(url, tmp_path / "raw" / "f.zip", GOOD, [UCI], 3, 10**7, 30, 1000, 5)
    assert not (tmp_path / "raw").exists()


# --- the overall deadline (V02, AC02) ----------------------------------------------------------------------------------


def test_a_download_that_passes_max_seconds_is_cut_with_its_own_error_and_writes_nothing(tmp_path, caplog):
    """The one test that waits: the body drips for about 2 s, the deadline is 0.6 s and the read timeout 30 s."""
    with FileServer(BODY) as server, caplog.at_level(logging.INFO, logger="churnrisk"):
        started = time.monotonic()
        with pytest.raises(DownloadDeadlineError) as error:
            get(server, DRIP, tmp_path / "raw" / "f.zip", seconds=0.6, chunk=1050, timeout=30)
        elapsed = time.monotonic() - started
    assert isinstance(error.value, DownloadError), "a transport failure: the run can be retried"
    assert elapsed < 1.9, "it stopped long before the whole body and the read timeout"
    assert re.search(r"tiempo máximo de 0\.6 s", str(error.value)) and "bytes" in str(error.value)
    assert leftovers(tmp_path) == [], "no destination, no part and no staging file"
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1 and warnings[0].startswith("download failed")


def test_a_deadline_already_spent_requests_nothing_and_a_refused_address_keeps_its_rule(tmp_path):
    with FileServer(BODY) as server:
        with pytest.raises(DownloadDeadlineError):
            get(server, "/chain/3", tmp_path / "f.zip", seconds=1e-9)
        assert server.requests == [], "a spent deadline stops before the first hop"
    with pytest.raises(SourceError, match=r"^V02:.*HTTPS"):
        download_file("http://127.0.0.1:9/x", tmp_path / "f.zip", GOOD, ["127.0.0.1"], 3, 10**7, 0.0001, 1000, 30)
    assert leftovers(tmp_path) == []


def test_a_timeout_that_fires_at_the_deadline_is_the_deadline_and_one_far_from_it_is_a_timeout(tmp_path, monkeypatch):
    """Socket timeouts can fire a few milliseconds early: a hop cut by the time the deadline gave it is reported as the deadline."""
    import urllib.request

    def cut_after(seconds: float):
        def fake_open(self, request, data=None, timeout=None):
            time.sleep(seconds)
            raise TimeoutError("timed out")

        return fake_open

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", cut_after(0.27))
    with pytest.raises(DownloadDeadlineError, match="tiempo máximo de 0.3 s"):
        download_file(f"https://{UCI}/x", tmp_path / "f.zip", GOOD, [UCI], 3, 10**7, 0.3, 1000, 30)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", cut_after(0.0))
    with pytest.raises(DownloadError, match="Se agotó el tiempo de espera de 30 s") as error:
        download_file(f"https://{UCI}/x", tmp_path / "f.zip", GOOD, [UCI], 3, 10**7, 5, 1000, 30)
    assert not isinstance(error.value, DownloadDeadlineError)
    assert leftovers(tmp_path) == []


# --- local faults keep their own type --------------------------------------------------------------------------------


def test_a_destination_folder_that_cannot_be_created_is_an_os_error_not_a_download_error(tmp_path, caplog):
    (tmp_path / "blocked").write_bytes(b"a file where a folder should be")
    with FileServer(BODY) as server, caplog.at_level(logging.WARNING, logger="churnrisk"):
        with pytest.raises(OSError) as error:
            get(server, "/file.zip", tmp_path / "blocked" / "sub" / "f.zip")
    assert not isinstance(error.value, (DownloadError, SourceError))
    assert any(r.exc_info for r in caplog.records), "logged with its traceback"


def test_a_full_disk_while_writing_is_an_os_error_and_removes_the_staging_file(tmp_path, monkeypatch, caplog):
    real_fdopen = os.fdopen

    class Full:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.handle.close()

        def write(self, data):
            raise OSError(errno.ENOSPC, "no space left on device")

    monkeypatch.setattr(os, "fdopen", lambda fd, mode="r", *a, **k: Full(real_fdopen(fd, mode, *a, **k)))
    with FileServer(BODY) as server, caplog.at_level(logging.WARNING, logger="churnrisk"):
        with pytest.raises(OSError) as error:
            get(server, "/file.zip", tmp_path / "raw" / "f.zip")
    assert error.value.errno == errno.ENOSPC and not isinstance(error.value, DownloadError)
    assert leftovers(tmp_path) == []
    assert any("local fault" in r.getMessage() and r.exc_info for r in caplog.records)


def test_the_staging_file_is_created_exclusively_under_a_random_name(tmp_path, monkeypatch):
    descriptor, first = ingest._create_staging(tmp_path / "f.zip")
    os.close(descriptor)
    descriptor, second = ingest._create_staging(tmp_path / "f.zip")
    os.close(descriptor)
    assert first != second and first.parent == tmp_path and first.name.startswith("f.zip.") and first.name.endswith(".staging")
    monkeypatch.setattr(secrets, "token_hex", lambda n: "fixed")
    monkeypatch.setattr(ingest, "STAGING_ATTEMPTS", 3)
    descriptor, _ = ingest._create_staging(tmp_path / "g.zip")
    os.close(descriptor)
    with pytest.raises(FileExistsError, match="3 intentos"):
        ingest._create_staging(tmp_path / "g.zip")
    assert STAGING_ATTEMPTS == 100


# --- the manifest and the local source's registered hash (RF01, V01) ----------------------------------------------------


def test_the_manifest_round_trips_and_refuses_anything_else(tmp_path):
    manifest = SourceManifest(mode="local", source=str(tmp_path / "x.zip"), sha256=GOOD, size=12, fetched_at="2026-11-11T10:00:00+00:00", zip_path="x.zip")
    path = tmp_path / "raw" / MANIFEST_NAME
    assert read_source_manifest(path) is None
    write_source_manifest(path, manifest)
    assert read_source_manifest(path) == manifest and leftovers(path.parent) == [MANIFEST_NAME]
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["version"] == 1 and set(document) == {"version", "source"}
    for broken in ("not json", "[]", '{"version": 2, "source": {}}', json.dumps({**document, "extra": 1}), json.dumps({"version": 1, "source": {"mode": "x"}})):
        path.write_text(broken, encoding="utf-8")
        with pytest.raises(ValueError, match="manifiesto"):
            read_source_manifest(path)


def test_local_mode_takes_the_first_hash_and_refuses_another_one_without_changing_anything(tmp_path):
    zip_path, manifest_path = tmp_path / "quick" / "fixture.zip", tmp_path / "raw" / MANIFEST_NAME
    zip_path.parent.mkdir()
    zip_path.write_bytes(BODY)
    assert local_source(zip_path, manifest_path, max_bytes=len(BODY)) == (GOOD, len(BODY))
    assert not manifest_path.exists(), "checking writes nothing: the task registers the hash once the content has been read"
    write_source_manifest(manifest_path, SourceManifest("local", str(zip_path), GOOD, len(BODY), "2026-11-11T10:00:00+00:00", str(zip_path)))
    assert local_source(zip_path, manifest_path, max_bytes=len(BODY))[0] == GOOD, "the registered hash is accepted again"
    zip_path.write_bytes(BODY + b"changed")
    before = snapshot(tmp_path)
    with pytest.raises(SourceError) as error:
        local_source(zip_path, manifest_path, max_bytes=10**7)
    assert error.value.rule_id == "V01" and "registrada" in str(error.value) and GOOD in str(error.value)
    assert error.value.problems == [{"rule_id": "V01", "expected": GOOD, "actual": sha(BODY + b"changed"), "kept": str(zip_path)}]
    assert snapshot(tmp_path) == before


def test_local_mode_refuses_a_zip_over_max_bytes_before_hashing_it_and_needs_the_file(tmp_path, malformed):
    big = malformed("oversize")
    with pytest.raises(SourceError, match=r"^V02:.*67108864") as error:
        local_source(big, tmp_path / MANIFEST_NAME, max_bytes=64 * 1024 * 1024)
    assert error.value.problems[0]["size"] == big.stat().st_size
    with pytest.raises(FileNotFoundError, match="no existe el zip local"):
        local_source(tmp_path / "absent.zip", tmp_path / MANIFEST_NAME, max_bytes=10)
    assert leftovers(tmp_path) == []
