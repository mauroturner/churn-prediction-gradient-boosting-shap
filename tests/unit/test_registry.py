"""The artifact of the frozen model (U13, high-risk item 2; AC23 in part; D40, M03): nothing is deserialized from a file whose bytes do not
have the registered SHA-256.

The proof that the fingerprint is checked before ``pickle`` sees any byte uses a file that, if unpickled, creates a marker file (a real side
effect): it is refused with the documented error and the marker does not exist. The same bytes with their own fingerprint do create it, so
the absence of the marker is not trivial (project 03's test, adapted)."""

from __future__ import annotations

import hashlib
import pickle
from pathlib import Path

import numpy as np
import pytest
from sklearn.isotonic import IsotonicRegression

from churnrisk import registry
from churnrisk.bgnbd import BGNBDParams
from churnrisk.registry import ArtifactMismatchError, ModelBundle, load_artifact, save_artifact


class Marker:
    """When unpickled, it opens (and so creates) the file at `path`: a side effect that a test can see."""

    def __init__(self, path: Path) -> None:
        self.path = str(path)

    def __reduce__(self):
        return (open, (self.path, "w"))


def evil_bytes(marker: Path) -> bytes:
    return pickle.dumps(Marker(marker), protocol=5)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SpyPickle:
    """Stands for the ``pickle`` module inside the registry and records what reaches ``loads``."""

    def __init__(self) -> None:
        self.loaded: list[bytes] = []

    def dumps(self, obj, protocol=None):
        return pickle.dumps(obj, protocol=protocol)

    def loads(self, data):
        self.loaded.append(bytes(data))
        return pickle.loads(data)


# --- the RED of U13 -------------------------------------------------------------------------------------------------------


def test_artifact_with_other_hash_is_refused_before_loading(tmp_path, monkeypatch):
    marker = tmp_path / "side_effect.marker"
    artifact = tmp_path / "v1.pkl"
    artifact.write_bytes(evil_bytes(marker))
    spy = SpyPickle()
    monkeypatch.setattr(registry, "pickle", spy)
    registered = sha(b"the bytes that were registered, not these")
    with pytest.raises(ArtifactMismatchError, match=r"M03.*R6"):
        load_artifact(artifact, registered)
    assert not marker.exists(), "nothing was unpickled: the side effect did not happen"
    assert spy.loaded == [], "no byte reached pickle"
    assert artifact.read_bytes() == evil_bytes(marker), "the refused file is left as it was"


# --- the artifact ---------------------------------------------------------------------------------------------------------


def test_the_same_bytes_with_their_own_fingerprint_do_load_and_anything_but_a_bundle_is_refused_after(tmp_path):
    marker = tmp_path / "side_effect.marker"
    artifact = tmp_path / "v1.pkl"
    artifact.write_bytes(evil_bytes(marker))
    with pytest.raises(TypeError, match="ModelBundle"):
        load_artifact(artifact, sha(artifact.read_bytes()))
    assert marker.exists(), "control: this file does have a side effect when it is unpickled"


def small_bundle() -> ModelBundle:
    calibrator = IsotonicRegression(out_of_bounds="clip").fit([0.0, 1.0, 2.0, 3.0], [0, 0, 1, 1])
    return ModelBundle(model_version="v1", model={"what": "a fitted RiskModel in the launch"}, baseline_calibrators={"b4_frequency": calibrator},
                       bgnbd=BGNBDParams(0.9, 75.0, 0.2, 100.0), b_star="b4_frequency")


def test_a_saved_bundle_loads_back_from_its_own_bytes(tmp_path):
    path = tmp_path / "models" / "v1.pkl"
    digest = save_artifact(small_bundle(), path)
    assert digest == sha(path.read_bytes()) and path.read_bytes()[:2] == b"\x80\x05", "pickle protocol 5, and the fingerprint of the bytes written"
    loaded = load_artifact(path, digest)
    assert isinstance(loaded, ModelBundle) and (loaded.model_version, loaded.b_star, loaded.bgnbd) == ("v1", "b4_frequency", BGNBDParams(0.9, 75.0, 0.2, 100.0))
    np.testing.assert_array_equal(loaded.baseline_calibrators["b4_frequency"].predict([0.5, 2.5]), small_bundle().baseline_calibrators["b4_frequency"].predict([0.5, 2.5]))
    assert list(path.parent.iterdir()) == [path], "no temporary file is left next to the artifact"


def test_a_bundle_that_cannot_be_serialized_leaves_the_file_that_was_there(tmp_path):
    path = tmp_path / "v1.pkl"
    digest = save_artifact(small_bundle(), path)
    before = path.read_bytes()
    broken = ModelBundle(model_version="v1", model=lambda x: x, baseline_calibrators={}, bgnbd=BGNBDParams(1, 1, 1, 1), b_star="b2_rfm")
    with pytest.raises((pickle.PicklingError, AttributeError, TypeError)):
        save_artifact(broken, path)
    assert path.read_bytes() == before and sha(before) == digest and list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("expected", ["", "ABC", "A" * 64, "g" * 64, None])
def test_a_registered_fingerprint_that_is_not_a_sha256_is_refused_before_the_file_is_read(tmp_path, expected):
    with pytest.raises(ValueError, match="SHA-256"):
        load_artifact(tmp_path / "does-not-exist.pkl", expected)


def test_the_error_names_the_file_and_both_fingerprints_but_never_its_folder(tmp_path):
    artifact = tmp_path / "folder" / "v1.pkl"
    artifact.parent.mkdir()
    artifact.write_bytes(b"\x80\x05N.")
    registered = sha(b"other")
    with pytest.raises(ArtifactMismatchError) as error:
        load_artifact(artifact, registered)
    message = str(error.value)
    assert "v1.pkl" in message and registered in message and sha(artifact.read_bytes()) in message
    assert str(artifact.parent) not in message
