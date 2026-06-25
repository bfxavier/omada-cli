"""Shared fixtures: a fake controller that mimics the real API shapes.

Key fidelity detail: the /devices list does NOT carry rssiSetting (only the
per-EAP object does), so the fake mirrors that — otherwise the roaming
diagnostic would be tested against data the real controller never returns.
"""
import copy

import pytest


def _ap(name, mac, model, fw, ch5_idx, w5, ch5_act, ch2_act, **extra):
    """Build a /devices-style AP entry (note: no rssiSetting here)."""
    d = {
        "type": "ap", "name": name, "mac": mac, "model": model, "version": fw,
        "ip": "192.168.1.10", "status": 14, "clientNum": 3,
        "cpuUtil": 5, "memUtil": 40, "uptime": "1d 2h", "needUpgrade": False,
        "wirelessLinked": False, "hop": 0,
        "radioSetting5g": {"radioEnable": True, "channel": ch5_idx,
                           "channelWidth": w5, "channelRange": [],
                           "txPower": 20, "txPowerLevel": 1},
        "radioSetting2g": {"radioEnable": True, "channel": "0",
                           "channelWidth": "2", "txPower": 14, "txPowerLevel": 1},
        "wp5g": {"actualChannel": f"{ch5_act} / 5500MHz", "bandWidth": "80MHz",
                 "txUtil": 0, "rxUtil": 5, "interUtil": 1} if ch5_act else
                {"actualChannel": "N/A", "bandWidth": "80MHz",
                 "txUtil": 0, "rxUtil": 0, "interUtil": 0},
        "wp2g": {"actualChannel": f"{ch2_act} / 2437MHz", "bandWidth": "20MHz",
                 "txUtil": 3, "rxUtil": 30, "interUtil": 2},
    }
    d.update(extra)
    return d


class FakeClient:
    """Implements the subset of OmadaClient that commands/diagnostics/mcp use."""

    def __init__(self):
        self.site_ref = "Default"
        self.site_id = "0" * 24
        self.dry_run = False
        self.patches = []   # (target, body) for assertions
        self._devices = [
            _ap("Office", "AA-BB-CC-00-00-01", "EAP655-Wall", "1.6.2", "9", "5", 100, 6),
            _ap("Living", "AA-BB-CC-00-00-02", "EAP655-Wall", "1.4.3", "5", "5", 52, 6),
            _ap("Shed", "AA-BB-CC-00-00-03", "EAP620 HD", "1.0.3", "1", "3", 36, 1),
            _ap("Master", "AA-BB-CC-00-00-04", "EAP615-Wall", "1.5.4", "1", "3", 36, 11,
                needUpgrade=True),
            _ap("Basement", "AA-BB-CC-00-00-05", "EAP620 HD", "1.6.1", "5", "5", None, 11,
                radioSetting5g={"radioEnable": False, "channel": "5",
                                "channelWidth": "5", "txPower": 0, "txPowerLevel": 1}),
            {"type": "switch", "name": "Switch", "mac": "AA-BB-CC-00-00-99",
             "model": "SG2008P", "version": "3.20.19", "ip": "192.168.1.2",
             "clientNum": 7, "uptime": "300d"},
        ]
        # per-EAP detail carries rssiSetting; Office has an aggressive 5G kick
        self._rssi = {
            "AA-BB-CC-00-00-01": {"rssiSetting2g": {"rssiEnable": True, "threshold": -80},
                                  "rssiSetting5g": {"rssiEnable": True, "threshold": -65}},
        }
        self._setting = {
            "bandSteering": {"enable": True, "connectionThreshold": 30},
            "roaming": {"fastRoamingEnable": True, "forceDisassociationEnable": False},
            "mesh": {"meshEnable": False},
        }
        self._clients = [
            {"wireless": True, "radioId": 1, "rssi": -55, "channel": 100,
             "rxRate": 800000, "txRate": 900000, "name": "Phone", "mac": "11:11",
             "apName": "Office", "ip": "192.168.1.20", "healthScore": 9,
             "hostName": "phone"},
            {"wireless": True, "radioId": 0, "rssi": -82, "channel": 6,
             "rxRate": 50000, "txRate": 40000, "name": "Sensor", "mac": "22:22",
             "apName": "Living", "ip": "192.168.1.21", "healthScore": 3,
             "hostName": "sensor"},
            {"wireless": False, "name": "NAS", "mac": "33:33", "ip": "192.168.1.5"},
        ]

    # -- reads --
    def devices(self):
        return copy.deepcopy(self._devices)

    def eap(self, mac):
        d = next(x for x in self._devices if x["mac"] == mac)
        full = copy.deepcopy(d)
        full.update(copy.deepcopy(self._rssi.get(mac, {
            "rssiSetting2g": {"rssiEnable": True, "threshold": -82},
            "rssiSetting5g": {"rssiEnable": True, "threshold": -76}})))
        return full

    def clients(self, active=True):
        return copy.deepcopy(self._clients)

    def known_clients(self):
        return [{"name": "OldPhone", "mac": "99:99", "wireless": True,
                 "download": 5_000_000, "upload": 1_000_000, "lastSeen": 1_700_000_000_000,
                 "block": False}]

    def setting(self):
        return copy.deepcopy(self._setting)

    def wlan_groups(self):
        return [{"id": "grp1", "name": "Default", "primary": True},
                {"id": "grp2", "name": "Basement", "primary": False}]

    def ssids(self, wlan_id):
        if wlan_id == "grp2":
            return []
        return [{"id": "ssid1", "idInt": 1, "index": 1, "resource": 0,
                 "site": self.site_id, "wlanId": "grp1",
                 "name": "Home", "band": 7, "enable": True, "security": 3,
                 "pskSetting": {"securityKey": "old", "versionPsk": 4},
                 "guestNetEnable": False, "enable11r": True}]

    def lan_networks(self):
        return [{"name": "Default", "interface": "lan", "gatewaySubnet": "192.168.1.1/24",
                 "dhcpSettings": {"dhcpServerEnable": True}}]

    def alerts(self):
        return []

    def events(self):
        return [{"time": 1_700_000_000_000, "level": "info", "msg": "hello"}]

    def controller_status(self):
        return {"model": "OC200", "name": "Ctrl", "controllerVersion": "5.14",
                "firmwareVersion": "2.17", "upTime": 4_766_589_000}

    def overview(self):
        return {"connectedApNum": 5, "totalApNum": 5, "connectedSwitchNum": 1,
                "totalSwitchNum": 1, "totalClientNum": 29, "guestNum": 0,
                "powerConsumption": 20.0}

    def sites(self):
        return [{"name": "Default", "id": "0" * 24, "lanUserNum": 29,
                 "lanDeviceConnectedNum": 6, "lanDeviceDisconnectedNum": 0}]

    # -- writes (recorded) --
    def eap_patch(self, mac, body):
        self.patches.append((mac, body))
        return {"ok": True}

    def setting_patch(self, body):
        self.patches.append(("setting", body))
        return {"ok": True}

    def ssid_patch(self, wlan_id, ssid_id, body):
        self.patches.append((f"{wlan_id}/{ssid_id}", body))
        return {"ok": True}

    def patch(self, path, body):
        self.patches.append((path, body))
        return {"ok": True}

    def post(self, path, body=None):
        self.patches.append((path, body))
        return {"wlanId": "newgrp"}

    def delete(self, path):
        self.patches.append((path, "DELETE"))
        return {"ok": True}

    def get(self, path):
        return {"path": path}

    def _api(self, method, path, body=None):
        return {"method": method, "path": path}


@pytest.fixture
def fake_client():
    return FakeClient()


@pytest.fixture
def cfg():
    return {"base_url": "https://x", "username": "u", "site": "Default",
            "aps": {"office": "AA-BB-CC-00-00-01", "living": "AA-BB-CC-00-00-02"}}


class Args:
    """argparse.Namespace stand-in with attribute defaults."""
    def __init__(self, **kw):
        self.json = False
        self.__dict__.update(kw)


@pytest.fixture
def args():
    return Args
