import json

import pytest

from omada_cli import config as cfgmod


@pytest.fixture
def cfgfile(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", str(p))
    monkeypatch.setattr(cfgmod, "CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("OMADA_PASS", raising=False)
    for v in ("OMADA_BASE_URL", "OMADA_USER", "OMADA_SITE", "OMADA_CONTROLLER_ID"):
        monkeypatch.delenv(v, raising=False)
    return p


def test_defaults_when_no_file(cfgfile):
    cfg = cfgmod.load_config()
    assert cfg["username"] == "admin"
    assert cfg["verify_tls"] is False


def test_file_overrides_defaults(cfgfile):
    cfgfile.write_text(json.dumps({"username": "bruno", "site": "Home"}))
    cfg = cfgmod.load_config()
    assert cfg["username"] == "bruno" and cfg["site"] == "Home"


def test_env_overrides_file(cfgfile, monkeypatch):
    cfgfile.write_text(json.dumps({"username": "bruno"}))
    monkeypatch.setenv("OMADA_USER", "env-user")
    assert cfgmod.load_config()["username"] == "env-user"


def test_profiles(cfgfile):
    cfgfile.write_text(json.dumps({
        "default_profile": "home",
        "profiles": {"home": {"base_url": "https://h"}, "work": {"base_url": "https://w"}}}))
    assert cfgmod.load_config()["base_url"] == "https://h"
    assert cfgmod.load_config(profile="work")["base_url"] == "https://w"


def test_profile_missing(cfgfile):
    cfgfile.write_text(json.dumps({"profiles": {"home": {}}}))
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.load_config(profile="ghost")


def test_resolve_password_env(monkeypatch):
    monkeypatch.setenv("OMADA_PASS", "frompass")
    assert cfgmod.resolve_password({"username": "u"}) == "frompass"


def test_resolve_password_config(monkeypatch):
    monkeypatch.delenv("OMADA_PASS", raising=False)
    cfg = {"username": "u", "password_source": "config", "password": "pw"}
    assert cfgmod.resolve_password(cfg) == "pw"


def test_resolve_password_config_missing(monkeypatch):
    monkeypatch.delenv("OMADA_PASS", raising=False)
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.resolve_password({"username": "u", "password_source": "config"})


def test_resolve_password_keychain(monkeypatch):
    monkeypatch.delenv("OMADA_PASS", raising=False)
    monkeypatch.setattr(cfgmod, "keychain_get", lambda a: "kc-secret")
    cfg = {"username": "u", "password_source": "keychain"}
    assert cfgmod.resolve_password(cfg) == "kc-secret"


def test_resolve_password_keychain_missing(monkeypatch):
    monkeypatch.delenv("OMADA_PASS", raising=False)
    monkeypatch.setattr(cfgmod, "keychain_get", lambda a: None)
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.resolve_password({"username": "u"})


def test_save_config_strips_password(cfgfile):
    cfg = dict(cfgmod.DEFAULTS, username="bruno", password="leak")
    path = cfgmod.save_config(cfg)
    saved = json.loads(open(path).read())
    assert saved["username"] == "bruno"
    assert "password" not in saved


def test_keychain_get_success(monkeypatch):
    class R:
        stdout = "secret\n"
    monkeypatch.setattr(cfgmod.subprocess, "run", lambda *a, **k: R())
    assert cfgmod.keychain_get("u") == "secret"


def test_keychain_get_missing(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr(cfgmod.subprocess, "run", boom)
    assert cfgmod.keychain_get("u") is None


def test_keychain_set(monkeypatch):
    calls = {}
    monkeypatch.setattr(cfgmod.subprocess, "run",
                        lambda args, **k: calls.setdefault("args", args))
    cfgmod.keychain_set("u", "pw")
    assert "add-generic-password" in calls["args"]
