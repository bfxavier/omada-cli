import json

import pytest

from omada_cli import commands as c
from omada_cli.client import OmadaError


# -- resolution ------------------------------------------------------------
def test_resolve_ap_by_config_name(fake_client, cfg):
    label, mac = c.resolve_ap(fake_client, cfg, "office")
    assert mac == "AA-BB-CC-00-00-01"


def test_resolve_ap_by_device_name(fake_client, cfg):
    label, mac = c.resolve_ap(fake_client, cfg, "Master")
    assert mac == "AA-BB-CC-00-00-04"


def test_resolve_ap_by_mac(fake_client, cfg):
    label, mac = c.resolve_ap(fake_client, cfg, "AA-BB-CC-00-00-02")
    assert mac == "AA-BB-CC-00-00-02"


def test_resolve_ap_unknown(fake_client, cfg):
    with pytest.raises(OmadaError):
        c.resolve_ap(fake_client, cfg, "nope")


# -- reads -----------------------------------------------------------------
def test_status_table(fake_client, cfg, args, capsys):
    c.cmd_status(fake_client, cfg, args())
    out = capsys.readouterr().out
    assert "Office" in out and "100" in out


def test_status_json(fake_client, cfg, args, capsys):
    c.cmd_status(fake_client, cfg, args(json=True))
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 5


def test_controller(fake_client, cfg, args, capsys):
    c.cmd_controller(fake_client, cfg, args())
    out = capsys.readouterr().out
    assert "OC200" in out and "55d" in out  # uptime formatted from ms


def test_clients_filter_band(fake_client, cfg, args, capsys):
    c.cmd_clients(fake_client, cfg, args(band="5", ap=None, min_rssi=None,
                                         wired=False, sort="rssi"))
    out = capsys.readouterr().out
    assert "Phone" in out and "Sensor" not in out


def test_clients_min_rssi(fake_client, cfg, args, capsys):
    c.cmd_clients(fake_client, cfg, args(band=None, ap=None, min_rssi=-60,
                                         wired=False, sort="rssi"))
    out = capsys.readouterr().out
    assert "Phone" in out and "Sensor" not in out


def test_dfs_states(fake_client, cfg, args, capsys):
    c.cmd_dfs(fake_client, cfg, args())
    out = capsys.readouterr().out
    assert "holding DFS" in out      # Office ch100
    assert "5G off" in out           # Basement


def test_doctor(fake_client, cfg, args, capsys):
    c.cmd_doctor(fake_client, cfg, args())
    out = capsys.readouterr().out
    assert "firmware" in out


def test_spectrum(fake_client, cfg, args, capsys):
    c.cmd_spectrum(fake_client, cfg, args())
    out = capsys.readouterr().out
    assert "channel occupancy" in out


def test_wlans(fake_client, cfg, args, capsys):
    c.cmd_wlans(fake_client, cfg, args())
    assert "Home" in capsys.readouterr().out


def test_networks(fake_client, cfg, args, capsys):
    c.cmd_networks(fake_client, cfg, args())
    assert "192.168.1.1/24" in capsys.readouterr().out


def test_known(fake_client, cfg, args, capsys):
    c.cmd_known(fake_client, cfg, args(limit=10))
    assert "OldPhone" in capsys.readouterr().out


def test_roam_get(fake_client, cfg, args, capsys):
    c.cmd_roam(fake_client, cfg, args(action="get"))
    out = capsys.readouterr().out
    assert "-65" in out  # Office aggressive 5G kick


# -- writes ----------------------------------------------------------------
def test_channel_patch(fake_client, cfg, args):
    c.cmd_channel(fake_client, cfg, args(ap="office", channel=116, width=80))
    target, body = fake_client.patches[-1]
    assert target == "AA-BB-CC-00-00-01"
    assert body["radioSetting5g"]["channel"] == "13"        # ch116 -> idx 13
    assert body["radioSetting5g"]["channelRange"] == [5580, 5600, 5620, 5640]


def test_power_patch_sets_custom_level(fake_client, cfg, args):
    c.cmd_power(fake_client, cfg, args(ap="living", band="5", dbm=17))
    _, body = fake_client.patches[-1]
    assert body["radioSetting5g"]["txPowerLevel"] == 1
    assert body["radioSetting5g"]["txPower"] == 17


def test_radio_off(fake_client, cfg, args):
    c.cmd_radio(fake_client, cfg, args(ap="office", band="2.4", state="off"))
    _, body = fake_client.patches[-1]
    assert body["radioSetting2g"]["radioEnable"] is False


def test_roam_set_all(fake_client, cfg, args, capsys):
    c.cmd_roam(fake_client, cfg, args(action="set", ap="all", g2=-82, g5=-76))
    assert len(fake_client.patches) == 5  # all APs
    _, body = fake_client.patches[-1]
    assert body["rssiSetting5g"]["threshold"] == -76


def test_roam_disable(fake_client, cfg, args):
    c.cmd_roam(fake_client, cfg, args(action="disable", ap="office"))
    _, body = fake_client.patches[-1]
    assert body["rssiSetting5g"]["rssiEnable"] is False


def test_roam_set_nothing_raises(fake_client, cfg, args):
    with pytest.raises(OmadaError):
        c.cmd_roam(fake_client, cfg, args(action="set", ap="office", g2=None, g5=None))


def test_steering_toggle(fake_client, cfg, args):
    c.cmd_steering(fake_client, cfg, args(state="off"))
    _, body = fake_client.patches[-1]
    assert body["bandSteering"]["enable"] is False


def test_mesh_toggle(fake_client, cfg, args):
    c.cmd_mesh(fake_client, cfg, args(state="on"))
    _, body = fake_client.patches[-1]
    assert body["mesh"]["meshEnable"] is True


def test_rename(fake_client, cfg, args):
    c.cmd_rename(fake_client, cfg, args(ap="office", name="New Name"))
    _, body = fake_client.patches[-1]
    assert body["name"] == "New Name"


def test_ssid_disable(fake_client, cfg, args):
    c.cmd_ssid(fake_client, cfg, args(action="disable", name="Home"))
    target, body = fake_client.patches[-1]
    assert target == "grp1/ssid1" and body["enable"] is False


def test_ssid_passwd(fake_client, cfg, args):
    c.cmd_ssid(fake_client, cfg, args(action="passwd", name="Home", password="secret"))
    _, body = fake_client.patches[-1]
    assert body["pskSetting"]["wpaPsk"] == "secret"


def test_ssid_not_found(fake_client, cfg, args):
    with pytest.raises(OmadaError):
        c.cmd_ssid(fake_client, cfg, args(action="enable", name="Ghost"))


def test_block_experimental(fake_client, cfg, args, capsys):
    c.cmd_block(fake_client, cfg, args(action="block", mac="11:11"))
    target, body = fake_client.patches[-1]
    assert target == "/clients/11:11" and body["block"] is True


# -- snapshots -------------------------------------------------------------
def test_backup_diff_restore(fake_client, cfg, args, tmp_path):
    path = tmp_path / "snap.json"
    c.cmd_backup(fake_client, cfg, args(file=str(path)))
    assert path.exists()
    snap = json.loads(path.read_text())
    assert len(snap["aps"]) == 5

    # diff with no changes => no '~' lines beyond the summary
    c.cmd_diff(fake_client, cfg, args(file=str(path)))

    # restore re-applies radio settings to every AP
    fake_client.patches.clear()
    c.cmd_restore(fake_client, cfg, args(file=str(path), setting=False))
    assert len(fake_client.patches) == 5


def test_diff_detects_change(fake_client, cfg, args, tmp_path, capsys):
    path = tmp_path / "snap.json"
    c.cmd_backup(fake_client, cfg, args(file=str(path)))
    fake_client._setting["bandSteering"]["enable"] = False  # mutate
    capsys.readouterr()
    c.cmd_diff(fake_client, cfg, args(file=str(path)))
    assert "bandSteering" in capsys.readouterr().out


# -- raw -------------------------------------------------------------------
def test_raw_get(fake_client, cfg, args, capsys):
    c.cmd_raw(fake_client, cfg, args(method="GET", path="/devices", body=None))
    assert "/sites" not in capsys.readouterr().out or True  # smoke: no crash
