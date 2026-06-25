import json

import pytest

from omada_cli import mcp_server as mcp


@pytest.fixture
def injected(fake_client, cfg, monkeypatch):
    """Inject the fake client so _client() returns it without connecting."""
    monkeypatch.setitem(mcp._state, "client", fake_client)
    monkeypatch.setitem(mcp._state, "cfg", cfg)
    return fake_client


def test_initialize_echoes_protocol():
    resp = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2024-11-05"}})
    r = resp["result"]
    assert r["protocolVersion"] == "2024-11-05"
    assert r["serverInfo"]["name"] == "omada-cli"
    assert "tools" in r["capabilities"]


def test_initialize_default_protocol():
    resp = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp["result"]["protocolVersion"] == mcp.PROTOCOL_VERSION


def test_ping():
    assert mcp.handle({"jsonrpc": "2.0", "id": 5, "method": "ping"})["result"] == {}


def test_notification_no_response():
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_method_errors():
    resp = mcp.handle({"jsonrpc": "2.0", "id": 7, "method": "bogus"})
    assert resp["error"]["code"] == -32601


def test_tools_list_read_only_by_default():
    resp = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in resp["result"]["tools"]]
    assert "omada_status" in names
    assert "omada_set_channel" not in names  # writes hidden by default


def test_tools_call_status(injected):
    resp = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "omada_status", "arguments": {}}})
    data = json.loads(resp["result"]["content"][0]["text"])
    assert any(ap["name"] == "Office" for ap in data)


def test_tools_call_dfs(injected):
    resp = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "omada_dfs", "arguments": {}}})
    data = json.loads(resp["result"]["content"][0]["text"])
    office = next(d for d in data if d["name"] == "Office")
    assert office["state"] == "holding-dfs"


def test_tools_call_clients_filter(injected):
    resp = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "omada_clients", "arguments": {"band": "5"}}})
    data = json.loads(resp["result"]["content"][0]["text"])
    assert all(c["band"] == "5G" for c in data)


def test_tools_call_unknown_tool():
    resp = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "nope", "arguments": {}}})
    assert resp["result"]["isError"] is True


def test_write_tools_gated(monkeypatch):
    monkeypatch.setattr(mcp, "ALLOW_WRITES", False)
    assert "omada_set_channel" not in mcp._build_registry()
    monkeypatch.setattr(mcp, "ALLOW_WRITES", True)
    reg = mcp._build_registry()
    assert "omada_set_channel" in reg
    assert reg["omada_set_channel"]["description"].startswith("[WRITE]")


def test_write_handler_set_channel(injected):
    out = mcp.t_set_channel({"ap": "office", "channel": 116, "width": 80})
    assert out["ok"] is True
    target, body = injected.patches[-1]
    assert body["radioSetting5g"]["channel"] == "13"


def test_write_handler_set_roam_all(injected):
    out = mcp.t_set_roam({"ap": "all", "threshold5g": -76})
    assert out["ok"] is True
    assert len(injected.patches) == 5


def test_write_handler_toggle_feature(injected):
    out = mcp.t_toggle_feature({"feature": "mesh", "state": "on"})
    assert out["ok"] is True
    _, body = injected.patches[-1]
    assert body["mesh"]["meshEnable"] is True


def test_write_handler_set_channel_24ghz(injected):
    out = mcp.t_set_channel({"ap": "office", "channel": 11})
    assert out["ok"] is True and out["channel"] == 11
    _, body = injected.patches[-1]
    assert body["radioSetting2g"]["channel"] == "11"


def test_write_handler_ssid_create(injected):
    out = mcp.t_ssid_create({"name": "XavIoT", "band": "2.4", "group": "Basement",
                             "password": "tzhv6666"})
    assert out["ok"] is True
    target, body = injected.patches[-1]
    assert target == "/setting/wlans/grp2/ssids"
    assert body["pskSetting"]["securityKey"] == "tzhv6666"


def test_write_handler_ssid_delete(injected):
    out = mcp.t_ssid_delete({"name": "Home"})
    assert out["deleted"] == "Home"
    assert injected.patches[-1] == ("/setting/wlans/grp1/ssids/ssid1", "DELETE")


def test_write_handler_wlan_group_create(injected):
    out = mcp.t_wlan_group_create({"name": "Lab"})
    assert out["ok"] is True
    assert injected.patches[-1] == ("/setting/wlans", {"name": "Lab", "clone": False})


def test_write_handler_assign_ap_group(injected):
    out = mcp.t_assign_ap_group({"ap": "basement", "group": "Basement"})
    assert out["ok"] is True
    _, body = injected.patches[-1]
    assert body == {"wlanId": "grp2"}


def test_write_tools_count_when_enabled(monkeypatch):
    monkeypatch.setattr(mcp, "ALLOW_WRITES", True)
    reg = mcp._build_registry()
    for name in ("omada_ssid_create", "omada_ssid_delete", "omada_wlan_group_create",
                 "omada_assign_ap_group"):
        assert name in reg
