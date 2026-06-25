"""Extra coverage: remaining command branches + MCP main loop / _client."""
import io
import json

from omada_cli import commands as c
from omada_cli import mcp_server as mcp


def test_aps(fake_client, cfg, args, capsys):
    c.cmd_aps(fake_client, cfg, args())
    assert "EAP655-Wall" in capsys.readouterr().out


def test_devices_includes_switch(fake_client, cfg, args, capsys):
    c.cmd_devices(fake_client, cfg, args())
    assert "SG2008P" in capsys.readouterr().out


def test_sites(fake_client, cfg, args, capsys):
    c.cmd_sites(fake_client, cfg, args())
    assert "Default" in capsys.readouterr().out


def test_alerts_events(fake_client, cfg, args, capsys):
    c.cmd_alerts(fake_client, cfg, args(events=True, limit=10))
    assert "hello" in capsys.readouterr().out


def test_alerts_empty(fake_client, cfg, args, capsys):
    c.cmd_alerts(fake_client, cfg, args(events=False, limit=10))
    assert "no entries" in capsys.readouterr().out


def test_clients_sort_rate_and_name(fake_client, cfg, args, capsys):
    c.cmd_clients(fake_client, cfg, args(band=None, ap=None, min_rssi=None,
                                         wired=True, sort="rate"))
    c.cmd_clients(fake_client, cfg, args(band=None, ap=None, min_rssi=None,
                                         wired=True, sort="name"))
    assert "NAS" in capsys.readouterr().out  # wired included


def test_clients_json(fake_client, cfg, args, capsys):
    c.cmd_clients(fake_client, cfg, args(band=None, ap=None, min_rssi=None,
                                         wired=False, sort="rssi", json=True))
    assert isinstance(json.loads(capsys.readouterr().out), list)


def test_fastroam_and_forcedisassoc(fake_client, cfg, args):
    c.cmd_fastroam(fake_client, cfg, args(state="off"))
    c.cmd_forcedisassoc(fake_client, cfg, args(state="on"))
    keys = [list(b)[0] for _, b in fake_client.patches]
    assert keys.count("roaming") == 2


def test_locate_experimental(fake_client, cfg, args, capsys):
    c.cmd_locate(fake_client, cfg, args(ap="office", state="on"))
    _, body = fake_client.patches[-1]
    assert body["locateEnable"] is True


def test_restore_with_setting(fake_client, cfg, args, tmp_path):
    snap = tmp_path / "s.json"
    c.cmd_backup(fake_client, cfg, args(file=str(snap)))
    fake_client.patches.clear()
    c.cmd_restore(fake_client, cfg, args(file=str(snap), setting=True))
    assert any(t == "setting" for t, _ in fake_client.patches)


def test_raw_patch_global_path(fake_client, cfg, args, capsys):
    c.cmd_raw(fake_client, cfg, args(method="PATCH", path="/eaps/X",
                                     body='{"k":1}'))
    assert "X" in capsys.readouterr().out


def test_roam_get_json(fake_client, cfg, args, capsys):
    c.cmd_roam(fake_client, cfg, args(action="get", json=True))
    assert isinstance(json.loads(capsys.readouterr().out), list)


def test_resolve_ap_ambiguous(fake_client, cfg):
    import pytest

    from omada_cli.client import OmadaError
    # add a second AP whose name also contains "office" (Office + Office Annex)
    fake_client._devices.append(dict(fake_client._devices[0], name="Office Annex",
                                      mac="AA-BB-CC-00-00-77"))
    # not in cfg map, so it falls through to device-name matching → 2 hits
    cfg2 = {"aps": {}}
    with pytest.raises(OmadaError, match="several"):
        c.resolve_ap(fake_client, cfg2, "office")
    with pytest.raises(OmadaError, match="unknown"):
        c.resolve_ap(fake_client, cfg2, "zzz")


# -- MCP main loop + _client --------------------------------------------------
def test_mcp_main_loop(monkeypatch, fake_client, cfg, capsys):
    monkeypatch.setitem(mcp._state, "client", fake_client)
    monkeypatch.setitem(mcp._state, "cfg", cfg)
    lines = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "omada_controller", "arguments": {}}}),
        "",  # blank line ignored
        "not json",  # ignored
    ])
    monkeypatch.setattr("sys.stdin", io.StringIO(lines))
    assert mcp.main() == 0
    outs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert outs[0]["result"]["serverInfo"]["name"] == "omada-cli"
    assert len(outs) == 2  # initialize + tools/call (notification produced none)


def test_mcp_client_lazy_build(monkeypatch, fake_client, cfg):
    monkeypatch.setitem(mcp._state, "client", None)
    monkeypatch.setitem(mcp._state, "cfg", None)
    monkeypatch.setattr(mcp, "load_config", lambda profile=None: cfg)
    monkeypatch.setattr(mcp, "resolve_password", lambda c: "pw")

    class Conn:
        def __init__(self, **kw):
            pass

        def connect(self):
            return fake_client
    monkeypatch.setattr(mcp, "OmadaClient", Conn)
    client, got_cfg = mcp._client()
    assert client is fake_client and got_cfg is cfg


def test_mcp_other_handlers(monkeypatch, fake_client, cfg):
    monkeypatch.setitem(mcp._state, "client", fake_client)
    monkeypatch.setitem(mcp._state, "cfg", cfg)
    assert mcp.t_aps({})[0]["model"] == "EAP655-Wall"
    assert "Home" in [w["ssid"] for w in mcp.t_wlans({})]
    assert mcp.t_spectrum({})["clientsPerChannel"]
    assert mcp.t_roam_get({})
    assert mcp.t_set_power({"ap": "office", "band": "5", "dbm": 18})["ok"]
    assert mcp.t_set_radio({"ap": "office", "band": "5", "state": "off"})["ok"]
