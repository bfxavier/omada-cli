import pytest

from omada_cli import cli, commands


@pytest.fixture
def wired(monkeypatch, fake_client, cfg):
    """Patch cli so main() runs against the fake client, no network/config."""
    monkeypatch.setattr(cli, "load_config", lambda profile=None: cfg)
    monkeypatch.setattr(cli, "resolve_password", lambda c: "pw")

    class Connectable:
        def __init__(self, **kw):
            self.kw = kw

        def connect(self):
            fake_client.dry_run = self.kw.get("dry_run", False)
            return fake_client

    monkeypatch.setattr(cli, "OmadaClient", Connectable)
    return fake_client


def test_parser_lists_all_commands():
    p = cli.build_parser()
    # smoke: a representative spread parses without error
    for argv in (["status"], ["channel", "office", "100", "80"],
                 ["roam", "set", "all", "--5", "-76"], ["ssid", "list"],
                 ["power", "x", "5", "20"]):
        assert p.parse_args(argv).cmd == argv[0]


def test_version_exits(capsys):
    with pytest.raises(SystemExit) as ei:
        cli.main(["--version"])
    assert ei.value.code == 0
    assert "omada" in capsys.readouterr().out


def test_main_status_ok(wired, capsys):
    assert cli.main(["status"]) == 0
    assert "Office" in capsys.readouterr().out


def test_main_global_flag_before_subcommand(wired, capsys):
    assert cli.main(["--json", "status"]) == 0
    out = capsys.readouterr().out
    assert out.strip().startswith("[")  # JSON array


def test_main_global_flag_after_subcommand(wired, capsys):
    assert cli.main(["status", "--json"]) == 0
    assert capsys.readouterr().out.strip().startswith("[")


def test_main_dry_run_write(wired, capsys):
    # fake client records dry_run flag; dry-run path prints nothing to patches
    assert cli.main(["power", "office", "5", "19", "--dry-run"]) == 0
    assert wired.dry_run is True


def test_main_config_error_returns_2(monkeypatch):
    def boom(profile=None):
        raise cli.ConfigError("bad config")
    monkeypatch.setattr(cli, "load_config", boom)
    assert cli.main(["status"]) == 2


def test_main_omada_error_returns_1(monkeypatch, cfg):
    monkeypatch.setattr(cli, "load_config", lambda profile=None: cfg)
    monkeypatch.setattr(cli, "resolve_password", lambda c: "pw")

    class Boom:
        def __init__(self, **kw):
            pass

        def connect(self):
            raise cli.OmadaError("unreachable")
    monkeypatch.setattr(cli, "OmadaClient", Boom)
    assert cli.main(["status"]) == 1


def test_main_no_conn_command(monkeypatch, cfg):
    called = {}
    monkeypatch.setattr(cli, "load_config", lambda profile=None: cfg)
    monkeypatch.setattr(commands, "cmd_setup_pass",
                        lambda client, c, a: called.setdefault("hit", client))
    assert cli.main(["setup-pass"]) == 0
    assert called["hit"] is None  # no client built for no-conn commands


def test_cmd_setup_interactive(monkeypatch, cfg, tmp_path):
    from omada_cli import config as cfgmod
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "newpw")
    saved = {}
    monkeypatch.setattr(cli, "save_config", lambda c: saved.setdefault("c", c) or "/tmp/cfg")
    monkeypatch.setattr(cfgmod, "keychain_set", lambda a, p: saved.setdefault("pw", p))
    cli.cmd_setup(None, dict(cfgmod.DEFAULTS), object())
    assert saved["pw"] == "newpw"
