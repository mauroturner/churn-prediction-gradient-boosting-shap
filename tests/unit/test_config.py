"""Configuration (U02): paths against the project folder, the seal's two lists of keys, the http mode's guarantees and every key
refused by name (RNF04, AC21 in part, AC33, AC34; D19, D32)."""

from __future__ import annotations

import dataclasses
import re
from datetime import date
from pathlib import Path

import pytest

from churnrisk.config import (
    DEFAULT_CONFIG,
    ENV_CONFIG,
    ENV_HOME,
    FINGERPRINT_KEYS,
    UNSEALED_KEYS,
    PipelineConfig,
    SealedConfig,
    config_leaves,
    host_allowed,
    load_config,
    url_host,
)

PROJECT = Path(__file__).resolve().parents[2]
ZIP_HASH = "572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb"
XLSX_HASH = "bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980"


def variant(tmp_path: Path, snippet: str = "", replace: tuple[str, str] | None = None, name: str = "pipeline.toml") -> Path:
    """A configuration inside `tmp_path/config/`: the real file with one textual replacement, or an ``extends`` of it plus `snippet`."""
    folder = tmp_path / "config"
    folder.mkdir(exist_ok=True)
    target = folder / name
    if replace is not None:
        text = DEFAULT_CONFIG.read_text(encoding="utf-8")
        assert replace[0] in text, f"{replace[0]!r} is not in the default configuration"
        target.write_text(text.replace(*replace, 1), encoding="utf-8")
    else:
        target.write_text(f'extends = "{DEFAULT_CONFIG.as_posix()}"\n{snippet}', encoding="utf-8")
    return target


def refused(tmp_path: Path, match: str, snippet: str = "", replace: tuple[str, str] | None = None) -> None:
    with pytest.raises(ValueError, match=match):
        load_config(variant(tmp_path, snippet, replace))


# --- the default configuration -------------------------------------------------------------------------------------


def test_default_configuration_has_the_values_of_the_plan(cfg):
    assert isinstance(cfg, PipelineConfig) and cfg.project_root == PROJECT
    s = cfg.source
    assert (s.mode, s.accepted_sha256, s.member_sha256, s.local_path) == ("http", ZIP_HASH, XLSX_HASH, None)
    assert s.url == "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip" and s.allowed_hosts == ("archive.ics.uci.edu",)
    assert (s.max_redirects, s.max_seconds, s.max_bytes, s.max_member_bytes) == (3, 900.0, 64 * 1024 * 1024, 100 * 1024 * 1024)
    assert s.member == "online_retail_II.xlsx" and s.sheets == ("Year 2009-2010", "Year 2010-2011")
    assert (cfg.deliveries.first_date, cfg.deliveries.launch_as_of, cfg.deliveries.last_date) == (date(2009, 12, 1), date(2011, 7, 31), date(2011, 12, 9))
    assert (cfg.label.horizon_days, cfg.label.active_days, cfg.label.first_cut, cfg.label.last_cut) == (90, 90, date(2010, 6, 1), date(2011, 12, 1))
    assert dataclasses.astuple(cfg.split) == (
        date(2010, 6, 1), date(2010, 12, 1), date(2011, 3, 1), date(2011, 4, 1), date(2011, 5, 1), date(2011, 5, 1), date(2011, 8, 1), date(2011, 9, 1))
    assert cfg.features.candidate_sets == ("f0", "f1", "f2") and cfg.features.country_min_customers == 10
    assert (cfg.model.learning_rate, cfg.model.max_leaf_nodes, cfg.model.min_samples_leaf) == ((0.05, 0.1), (15, 31), (50, 200))
    assert cfg.baselines.strongest_candidates == ("b4_frequency", "b2_rfm", "b3_bgnbd") and cfg.baselines.bgnbd_fit_cut == date(2010, 12, 1)
    assert (cfg.costs.offer_cost, cfg.costs.rescue_rate, cfg.costs.retained_value) == (5.0, 0.2, 50.0)
    assert cfg.evaluation.top_shares == (0.10, 0.20) and cfg.evaluation.shap_top_reasons == 3
    assert cfg.sensitivity.variants == ("n60", "n120", "m180", "no_december")
    assert (cfg.criteria.c07_max_ece, cfg.criteria.leak_tripwire_auc, cfg.criteria.shap_additivity_tol) == (0.03, 0.95, 1e-6)
    assert (cfg.site.max_total_bytes, cfg.site.min_cell_customers) == (204800, 10)


def test_the_configuration_is_immutable(cfg):
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.costs.offer_cost = 1.0  # type: ignore[misc]


# --- paths (D32, RNF04, AC34) --------------------------------------------------------------------------------------


def test_relative_paths_resolve_against_project_root_from_another_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_HOME, raising=False)
    monkeypatch.delenv(ENV_CONFIG, raising=False)
    for load in (lambda: load_config(PROJECT / "config" / "pipeline.toml"), lambda: load_config(Path("config") / "pipeline.toml"), load_config):
        cfg = load()
        assert cfg.project_root == PROJECT
        for field in dataclasses.fields(cfg.paths):
            path = getattr(cfg.paths, field.name)
            assert path.is_absolute() and PROJECT in path.parents, field.name
        assert cfg.paths.warehouse == PROJECT / "data" / "warehouse" / "churnrisk.sqlite"
        assert cfg.paths.private_dir == PROJECT / "outputs" / "private"
        assert cfg.paths.seal == PROJECT / "reports" / "model_seal.json"
    # the working directory holds another copy's configuration: it is never read in silence
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.toml").write_text("this is not the project's configuration", encoding="utf-8")
    assert load_config(Path("config") / "pipeline.toml").project_root == PROJECT


def test_a_relative_churnrisk_config_is_taken_from_the_project_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_HOME, raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.quick.toml").write_text("[source]\nmode = 'other copy'\n", encoding="utf-8")
    monkeypatch.setenv(ENV_CONFIG, "config/pipeline.quick.toml")
    cfg = load_config()
    assert cfg.source.mode == "local" and cfg.paths.warehouse == PROJECT / "data" / "quick" / "churnrisk.sqlite"


def test_churnrisk_home_moves_the_project_folder_and_must_exist(tmp_path, monkeypatch):
    home = tmp_path / "elsewhere"
    (home / "config").mkdir(parents=True)
    (home / "config" / "pipeline.toml").write_text(DEFAULT_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv(ENV_HOME, str(home))
    assert load_config(DEFAULT_CONFIG).paths.warehouse == home.resolve() / "data" / "warehouse" / "churnrisk.sqlite"
    monkeypatch.setenv(ENV_CONFIG, "config/pipeline.toml")
    assert load_config().project_root == home.resolve()
    monkeypatch.setenv(ENV_HOME, str(tmp_path / "does-not-exist"))
    with pytest.raises(ValueError, match=ENV_HOME):
        load_config(DEFAULT_CONFIG)


def test_quick_configuration_keeps_every_output_under_data_quick(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_HOME, raising=False)
    cfg = load_config(PROJECT / "config" / "pipeline.quick.toml")
    quick = PROJECT / "data" / "quick"
    assert cfg.source.mode == "local" and cfg.source.local_path == quick / "online_retail_fixture.zip"
    assert (cfg.source.url, cfg.source.accepted_sha256, cfg.source.member_sha256) == ("", "", "")
    for field in dataclasses.fields(cfg.paths):
        assert quick in getattr(cfg.paths, field.name).parents, field.name
    assert cfg.model.learning_rate == (0.1,) and cfg.model.max_iter == 50 and cfg.evaluation.bootstrap_resamples == 200
    default = load_config(DEFAULT_CONFIG)
    assert (cfg.deliveries, cfg.label, cfg.split) == (default.deliveries, default.label, default.split), "the quick run replays the same calendar"


def test_a_relative_path_cannot_leave_the_project_folder(tmp_path):
    refused(tmp_path, r"\[paths\] raw_dir.*sale de la carpeta del proyecto", replace=('raw_dir = "data/raw"', 'raw_dir = "../elsewhere"'))
    refused(tmp_path, r"\[paths\] seal.*sale de la carpeta", replace=('seal = "reports/model_seal.json"', 'seal = "data/../../x.json"'))
    refused(tmp_path, r"\[source\] local_path.*sale de la carpeta", snippet='[source]\nmode = "local"\nurl = ""\naccepted_sha256 = ""\nmember_sha256 = ""\nlocal_path = "../x.zip"\n')


def test_a_dotdot_that_stays_inside_the_project_is_normalised_and_an_absolute_path_is_kept(tmp_path):
    path = variant(tmp_path, replace=('raw_dir = "data/raw"', 'raw_dir = "data/quick/../raw"'))
    assert load_config(path).paths.raw_dir == tmp_path / "data" / "raw"
    outside = (tmp_path / "outside").as_posix()
    path = variant(tmp_path, replace=('raw_dir = "data/raw"', f'raw_dir = "{outside}"'))
    assert load_config(path).paths.raw_dir == Path(outside)


def test_an_empty_path_is_refused(tmp_path):
    refused(tmp_path, r"\[paths\] private_dir.*texto vacío", replace=('private_dir = "outputs/private"', 'private_dir = ""'))


# --- the seal's keys (D19, AC21) -----------------------------------------------------------------------------------


def test_every_config_key_is_fingerprinted_or_declared_unsealed():
    leaves = [leaf for leaf in config_leaves(PipelineConfig) if leaf != "project_root"]
    assert len(leaves) == len(set(leaves))
    fingerprinted, unsealed = set(FINGERPRINT_KEYS), set(UNSEALED_KEYS)
    assert len(FINGERPRINT_KEYS) == len(fingerprinted) and len(UNSEALED_KEYS) == len(unsealed), "a key is listed twice"
    assert fingerprinted & unsealed == set(), "a key is both fingerprinted and declared unsealed"
    assert sorted(set(leaves) - fingerprinted - unsealed) == [], "a key is neither fingerprinted nor declared unsealed"
    assert sorted((fingerprinted | unsealed) - set(leaves)) == [], "a listed key is not in the configuration"
    # the plan, section 4: [source] enters only with its sheets; every key of these sections enters; [site] and [paths] stay out
    for section in ("deliveries", "label", "split", "features", "model", "baselines", "costs", "evaluation", "sensitivity", "criteria"):
        assert {leaf for leaf in leaves if leaf.startswith(f"{section}.")} <= fingerprinted, section
    assert {leaf for leaf in fingerprinted if leaf.startswith("source.")} == {"source.sheets"}
    assert {leaf for leaf in leaves if leaf.startswith(("site.", "paths."))} <= unsealed


def test_the_sealed_view_holds_exactly_the_fingerprinted_keys_and_the_observed_hash(cfg):
    assert set(config_leaves(SealedConfig)) == set(FINGERPRINT_KEYS) | {"source_sha256"}
    view = SealedConfig.of(cfg, ZIP_HASH)
    for key in FINGERPRINT_KEYS:
        section, name = key.split(".")
        assert getattr(getattr(view, section), name) == getattr(getattr(cfg, section), name), key
    assert view.source_sha256 == ZIP_HASH
    assert not hasattr(view, "paths") and not hasattr(view, "site") and not hasattr(view.source, "url")
    with pytest.raises(ValueError, match="source_sha256"):
        SealedConfig.of(cfg, ZIP_HASH.upper())


# --- http and local modes (RF01, RF02, V01-V03) --------------------------------------------------------------------


def test_http_mode_requires_https_url_listed_host_and_both_hashes(tmp_path):
    good = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
    assert load_config(variant(tmp_path, snippet=f'[source]\nurl = "{good}"\n')).source.url == good
    refused(tmp_path, r"\[source\] url.*https://", snippet='[source]\nurl = "http://archive.ics.uci.edu/x.zip"\n')
    refused(tmp_path, r"\[source\] url.*https://", snippet='[source]\nurl = "ftp://archive.ics.uci.edu/x.zip"\n')
    refused(tmp_path, r"\[source\] url.*no está en allowed_hosts", snippet='[source]\nurl = "https://evil.example.com/x.zip"\n')
    refused(tmp_path, r"\[source\] url.*no está en allowed_hosts", snippet='[source]\nurl = "https://uci.edu/x.zip"\n')
    refused(tmp_path, r"\[source\] url.*no es una dirección", snippet='[source]\nurl = "https://evil.example.com@archive.ics.uci.edu/x"\n')
    for key, value in (("accepted_sha256", ZIP_HASH), ("member_sha256", XLSX_HASH)):
        for bad in ("", value.upper(), value[:-1]):
            refused(tmp_path, rf"\[source\] {key}.*64 caracteres", snippet=f'[source]\n{key} = "{bad}"\n')


def test_http_mode_refuses_a_local_path_it_would_ignore(tmp_path):
    refused(tmp_path, r"\[source\] local_path.*se ignoraría", snippet='[source]\nlocal_path = "data/raw/x.zip"\n')


def test_local_mode_needs_its_path_and_refuses_the_keys_it_would_ignore(tmp_path):
    local = '[source]\nmode = "local"\nurl = ""\naccepted_sha256 = ""\nmember_sha256 = ""\n'
    refused(tmp_path, r"\[source\] local_path.*hace falta", snippet=local)
    assert load_config(variant(tmp_path, snippet=local + 'local_path = "data/x.zip"\n')).source.local_path == tmp_path / "data" / "x.zip"
    refused(tmp_path, r"\[source\] accepted_sha256.*se ignoraría", snippet=local.replace('accepted_sha256 = ""', f'accepted_sha256 = "{ZIP_HASH}"') + 'local_path = "x.zip"\n')
    refused(tmp_path, r"\[source\] member_sha256.*se ignoraría", snippet=local.replace('member_sha256 = ""', f'member_sha256 = "{XLSX_HASH}"') + 'local_path = "x.zip"\n')
    refused(tmp_path, r"\[source\] url.*se ignoraría", snippet='[source]\nmode = "local"\naccepted_sha256 = ""\nmember_sha256 = ""\nlocal_path = "x.zip"\n')


@pytest.mark.parametrize("mode", ["ftp", "HTTP", "Local", "", "http ", "s3"])
def test_mode_must_be_http_or_local(tmp_path, mode):
    refused(tmp_path, r"\[source\] mode", snippet=f'[source]\nmode = "{mode}"\n')


@pytest.mark.parametrize("value", [
    '["archive.ics.uci.edu", "HTTPS.example.com"]',   # upper case
    '["https://archive.ics.uci.edu"]',                # a scheme
    '["archive.ics.uci.edu:443"]',                    # a port
    '["archive.ics.uci.edu/static"]',                 # a path
    '[".edu"]',                                       # a suffix that is a whole top-level domain
    '["."]', '[]', '[""]', '["bad host.edu"]',
])
def test_allowed_hosts_entries_are_checked(tmp_path, value):
    refused(tmp_path, r"\[source\] allowed_hosts", snippet=f"[source]\nallowed_hosts = {value}\n")


@pytest.mark.parametrize(("host", "expected"), [
    ("archive.ics.uci.edu", True), ("ARCHIVE.ics.UCI.edu", True), ("archive.ics.uci.edu.", True),
    ("ics.uci.edu", False), ("evil.archive.ics.uci.edu", False), ("archive.ics.uci.edu.evil.com", False),
    ("files.example.org", True), ("example.org", False), ("evilexample.org", False), ("", False),
])
def test_host_allowed_matches_exact_names_and_dotted_suffixes_only(host, expected):
    assert host_allowed(host, ("archive.ics.uci.edu", ".example.org")) is expected


@pytest.mark.parametrize(("url", "host"), [
    ("https://archive.ics.uci.edu/a/b?x=1#f", "archive.ics.uci.edu"),
    ("HTTPS://Archive.ICS.uci.edu:443/a", "archive.ics.uci.edu"),
    ("http://127.0.0.1:8080/x", "127.0.0.1"),
    ("https://evil.com@archive.ics.uci.edu/a", None),       # user information
    ("https://evil.com\\@archive.ics.uci.edu/a", None),     # a backslash: two parsers read different hosts
    ("https://archive.ics.uci.edu /a", None),               # whitespace
    ("https://archive.ics.uci.edu/a\r\nHost: evil.com", None),
    ("ftp://archive.ics.uci.edu/a", None), ("file:///etc/passwd", None), ("//archive.ics.uci.edu/a", None),
    ("https://:443/a", None), ("https://archive.ics.uci.edu:notaport/a", None), ("", None),
])
def test_url_host_reads_one_unambiguous_host_or_refuses_the_url(url, host):
    assert url_host(url) == host


# --- mistakes in the file are named (AC33) -------------------------------------------------------------------------


def test_unknown_key_is_rejected_with_its_name(tmp_path):
    refused(tmp_path, r"\[costs\].*'offer_costs'", snippet="[costs]\noffer_costs = 1.0\n")
    refused(tmp_path, r"\[label\].*'horizon'", snippet="[label]\nhorizon = 60\n")


def test_unknown_section_missing_section_and_missing_key_are_named(tmp_path):
    refused(tmp_path, r"sección desconocida \[extras\]", snippet="[extras]\nx = 1\n")
    text = DEFAULT_CONFIG.read_text(encoding="utf-8")
    without_site = re.sub(r"\[site\].*?(?=\[paths\])", "", text, flags=re.S)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "a.toml").write_text(without_site, encoding="utf-8")
    with pytest.raises(ValueError, match=r"falta la sección \[site\]"):
        load_config(tmp_path / "config" / "a.toml")
    refused(tmp_path, r"\[costs\]: falta la clave 'rescue_rate'", replace=("rescue_rate = 0.2", ""))


@pytest.mark.parametrize(("snippet", "match"), [
    ("[costs]\noffer_cost = \"5\"\n", r"\[costs\] offer_cost.*un número"),
    ("[costs]\noffer_cost = true\n", r"\[costs\] offer_cost.*un número"),
    ("[model]\nmax_iter = 300.5\n", r"\[model\] max_iter.*un entero"),
    ("[model]\nlearning_rate = 0.1\n", r"\[model\] learning_rate.*una lista"),
    ("[model]\nlearning_rate = [\"a\"]\n", r"\[model\] learning_rate.*un número"),
    ("[label]\nfirst_cut = \"2010-06-01\"\n", r"\[label\] first_cut.*una fecha"),
    ("[split]\ntrain_last = 2010-12-01T10:00:00\n", r"\[split\] train_last.*una fecha"),
    ("[paths]\nraw_dir = 3\n", r"\[paths\] raw_dir.*ruta"),
    ("[source]\nmax_redirects = false\n", r"\[source\] max_redirects.*un entero"),
    ("[source]\nsheets = \"Year 2009-2010\"\n", r"\[source\] sheets.*una lista"),
])
def test_a_value_of_the_wrong_type_is_named(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


def test_extends_cycle_and_missing_base_are_refused(tmp_path):
    folder = tmp_path / "config"
    folder.mkdir()
    (folder / "a.toml").write_text('extends = "b.toml"\n', encoding="utf-8")
    (folder / "b.toml").write_text('extends = "a.toml"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="ciclo"):
        load_config(folder / "a.toml")
    (folder / "c.toml").write_text('extends = "nothing.toml"\n', encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        load_config(folder / "c.toml")
    with pytest.raises(FileNotFoundError):
        load_config(folder / "absent.toml")


# --- numeric bounds, names and lists: every limit has a test with its invalid values -------------------------------


@pytest.mark.parametrize(("section", "key", "bad"), [
    ("source", "max_bytes", 0), ("source", "max_member_bytes", 0), ("source", "chunk_bytes", 0), ("source", "timeout_s", -1),
    ("source", "max_redirects", -1), ("source", "max_seconds", 0), ("source", "max_seconds", "inf"),
    ("label", "horizon_days", 0), ("label", "active_days", -90),
    ("features", "short_window_days", 0), ("features", "long_window_days", 90), ("features", "country_min_customers", 0),
    ("model", "max_iter", 0), ("model", "l2_regularization", -1.0), ("model", "random_state", -1), ("model", "random_state", 2**32),
    ("baselines", "bgnbd_max_iter", 0),
    ("costs", "offer_cost", 0.0), ("costs", "offer_cost", -5.0), ("costs", "retained_value", 0.0),
    ("costs", "rescue_rate", 0.0), ("costs", "rescue_rate", 1.5), ("costs", "rescue_rate", -0.2),
    ("costs", "threshold_step", 0.0), ("costs", "threshold_min", 0.0), ("costs", "threshold_max", 1.0),
    ("costs", "sensitivity_min", 0.0), ("costs", "sensitivity_max", 1.0), ("costs", "sensitivity_step", 0.0),
    ("evaluation", "bootstrap_resamples", 0), ("evaluation", "bootstrap_seed", -1), ("evaluation", "calibration_bins", 1),
    ("evaluation", "roc_points", 1), ("evaluation", "gain_points", 1), ("evaluation", "shap_top_reasons", 0),
    ("sensitivity", "n60_horizon_days", 0), ("sensitivity", "n120_horizon_days", 0), ("sensitivity", "m180_active_days", 0),
    ("criteria", "c07_max_ece", 0.0), ("criteria", "c07_max_ece", 1.0), ("criteria", "c07_max_bias", 0.0),
    ("criteria", "leak_tripwire_auc", 0.5), ("criteria", "leak_tripwire_auc", 1.2),
    ("criteria", "shap_additivity_tol", 0.0), ("criteria", "shap_additivity_tol", 1.0),
    ("site", "max_total_bytes", 0), ("site", "min_cell_customers", 0),
])
def test_numeric_bounds_reject_their_invalid_values_naming_the_key(tmp_path, section, key, bad):
    refused(tmp_path, rf"\[{section}\] {key}", snippet=f"[{section}]\n{key} = {bad}\n")   # "inf" is TOML's infinity


def test_the_edges_of_the_valid_ranges_are_accepted(tmp_path):
    ok = "[costs]\nrescue_rate = 1.0\nsensitivity_min = 0.5\nsensitivity_max = 0.5\n[model]\nl2_regularization = 0.0\n[source]\nmax_redirects = 0\n"
    cfg = load_config(variant(tmp_path, snippet=ok))
    assert cfg.costs.rescue_rate == 1.0 and cfg.model.l2_regularization == 0.0 and cfg.source.max_redirects == 0


@pytest.mark.parametrize(("snippet", "match"), [
    ("[costs]\nthreshold_min = 0.6\nthreshold_max = 0.5\n", r"\[costs\] threshold_min"),
    ("[costs]\nsensitivity_min = 0.8\nsensitivity_max = 0.2\n", r"\[costs\] sensitivity_min"),
    ("[model]\nlearning_rate = []\n", r"\[model\] learning_rate.*no vacía"),
    ("[model]\nmax_leaf_nodes = [15, 15]\n", r"\[model\] max_leaf_nodes.*sin repetidos"),
    ("[model]\nmax_leaf_nodes = [1]\n", r"\[model\] max_leaf_nodes.*2 o más"),
    ("[model]\nmin_samples_leaf = [0]\n", r"\[model\] min_samples_leaf"),
    ("[model]\ncalibration = \"sigmoid\"\n", r"\[model\] calibration.*isotonic"),
    ("[model]\nmodel_version = \"v 1\"\n", r"\[model\] model_version"),
    ("[model]\nmodel_version = \"../v1\"\n", r"\[model\] model_version"),
    ("[features]\ncandidate_sets = []\n", r"\[features\] candidate_sets"),
    ("[features]\ncandidate_sets = [\"f0\", \"f3\"]\n", r"\[features\] candidate_sets.*f3"),
    ("[features]\ncandidate_sets = [\"f0\", \"f0\"]\n", r"\[features\] candidate_sets"),
    ("[baselines]\nstrongest_candidates = [\"b2_rfm\", \"b1_recency\"]\n", r"\[baselines\] strongest_candidates.*b1_recency"),
    ("[baselines]\nstrongest_candidates = []\n", r"\[baselines\] strongest_candidates"),
    ("[sensitivity]\nvariants = [\"n60\", \"n30\"]\n", r"\[sensitivity\] variants.*n30"),
    ("[evaluation]\ntop_shares = []\n", r"\[evaluation\] top_shares"),
    ("[evaluation]\ntop_shares = [0.1, 1.0]\n", r"\[evaluation\] top_shares"),
    ("[source]\nmember = \"../online_retail_II.xlsx\"\n", r"\[source\] member"),
    ("[source]\nmember = \"\"\n", r"\[source\] member"),
    ("[source]\nsheets = []\n", r"\[source\] sheets"),
    ("[source]\nsheets = [\"Year 2009-2010\", \"Year 2009-2010\"]\n", r"\[source\] sheets"),
])
def test_grids_names_and_lists_are_checked(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


# --- the calendar: cuts on day 1, the blocks of D08 and their purges of N days (RF11, RF14, AC11 in part) ----------


@pytest.mark.parametrize(("snippet", "match"), [
    ("[label]\nfirst_cut = 2010-06-02\n", r"\[label\] first_cut.*día 1"),
    ("[split]\nv2_first = 2011-05-15\nv2_last = 2011-05-15\n", r"\[split\] v2_first.*día 1"),
    ("[baselines]\nbgnbd_fit_cut = 2010-11-30\n", r"\[baselines\] bgnbd_fit_cut.*día 1"),
    ("[split]\ntrain_last = 2011-01-01\n", r"borde train → valid_v1.*N = 90.*2011-01-01 \+ 90 días = 2011-04-01 <= 2011-03-01"),
    ("[label]\nhorizon_days = 120\n", r"borde train → valid_v1.*N = 120"),
    ("[split]\nv2_first = 2011-06-01\nv2_last = 2011-06-01\n", r"borde valid_v2 → test"),
    ("[split]\nv1_last = 2011-05-01\n", r"borde valid_v1 → valid_v2"),
    ("[split]\ntrain_first = 2011-01-01\n", r"\[split\] train.*posterior"),
    ("[split]\ntrain_first = 2010-05-01\n", r"\[split\] train_first.*first_cut"),
    ("[split]\ntest_last = 2011-10-01\n", r"\[split\] test_last.*2011-12-29.*last_date"),
    ("[label]\nlast_cut = 2011-08-01\n", r"\[split\] test_last.*last_cut"),
    ("[deliveries]\nlaunch_as_of = 2011-07-28\n", r"\[deliveries\] launch_as_of.*último día de un mes"),
    ("[deliveries]\nlaunch_as_of = 2011-06-30\n", r"\[split\] v2_last.*2011-06-30.*2011-07-29"),
    ("[deliveries]\nlaunch_as_of = 2011-08-31\n", r"\[split\] test_first.*2011-09-01"),
    ("[deliveries]\nfirst_date = 2011-08-01\n", r"\[deliveries\]: first_date"),
    ("[label]\nlast_cut = 2012-01-01\n", r"\[label\] first_cut.*last_date"),
    ("[baselines]\nbgnbd_fit_cut = 2011-03-01\n", r"\[baselines\] bgnbd_fit_cut.*entrenamiento"),
])
def test_the_calendar_is_checked_with_the_name_of_the_boundary(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


def test_every_split_date_is_used_by_the_check(tmp_path):
    """Moving any one date of [split] outside its place is refused: none is accepted and then ignored."""
    moved = {
        "train_first": "2010-05-01", "train_last": "2011-01-01", "v1_first": "2011-02-01", "v1_last": "2011-05-01",
        "v2_first": "2011-04-01", "v2_last": "2011-06-01", "test_first": "2011-09-01", "test_last": "2011-10-01",
    }
    for key, value in moved.items():
        with pytest.raises(ValueError, match=r"\[split\]"):
            load_config(variant(tmp_path, snippet=f"[split]\n{key} = {value}\n"))
    assert load_config(variant(tmp_path, snippet="[split]\nv1_last = 2011-03-01\n")).split.v1_last == date(2011, 3, 1)
