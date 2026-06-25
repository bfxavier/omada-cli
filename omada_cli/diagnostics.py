"""Heuristic health checks ('omada doctor').

Each rule reads already-fetched controller data and yields findings as
(severity, area, message). Severity is one of: 'warn', 'info', 'ok'.
"""
from collections import defaultdict


def _actual_channel(wp):
    """'100 / 5500MHz' -> 100 (int) or None."""
    if not wp:
        return None
    raw = str(wp.get("actualChannel", "")).split("/")[0].strip()
    try:
        return int(raw)
    except ValueError:
        return None


def run(client):
    findings = []
    devices = client.devices()
    aps = [d for d in devices if d.get("type") == "ap"]
    setting = client.setting()
    clients = client.clients(active=True)

    findings += _firmware(aps)
    findings += _co_channel(aps)
    findings += _congestion(aps)
    findings += _roaming(client, aps, setting)
    findings += _site_features(setting, aps)
    findings += _weak_clients(clients)
    findings += _offline(devices)

    if not any(s == "warn" for s, _, _ in findings):
        findings.append(("ok", "overall", "no warnings — network looks healthy"))
    return findings


def _firmware(aps):
    out = []
    by_model = defaultdict(set)
    for a in aps:
        by_model[a.get("model")].add(a.get("version"))
    for model, vers in by_model.items():
        if len(vers) > 1:
            out.append(("warn", "firmware",
                        f"{model}: mixed firmware {sorted(vers)} — update the laggard"))
    for a in aps:
        if a.get("needUpgrade"):
            out.append(("info", "firmware",
                        f"{a.get('name')}: firmware update available ({a.get('version')})"))
    return out


def _co_channel(aps):
    # 5G co-channel is a real problem (plenty of channels to spread over).
    # 2.4 co-channel is largely unavoidable past 3 APs (only 1/6/11), so it's
    # informational unless one of the cells is also congested.
    out = []
    for band, wp_key, sev in (("5G", "wp5g", "warn"), ("2.4", "wp2g", "info")):
        seen = defaultdict(list)
        for a in aps:
            ch = _actual_channel(a.get(wp_key))
            if ch:
                seen[ch].append(a.get("name"))
        for ch, names in seen.items():
            if len(names) > 1:
                out.append((sev, "channels",
                            f"{band} co-channel: {', '.join(names)} all on ch{ch}"))
    return out


def _congestion(aps):
    out = []
    for a in aps:
        for band, wp_key in (("5G", "wp5g"), ("2.4", "wp2g")):
            wp = a.get(wp_key) or {}
            rx, inter = wp.get("rxUtil"), wp.get("interUtil")
            if rx is not None and rx >= 50:
                out.append(("warn", "airtime",
                            f"{a.get('name')} {band}: rx airtime {rx}% (congested)"))
            if inter is not None and inter >= 20:
                out.append(("warn", "airtime",
                            f"{a.get('name')} {band}: interference {inter}% (neighbors)"))
    return out


def _roaming(client, aps, setting):
    out = []
    roaming = setting.get("roaming", {})
    if roaming.get("forceDisassociationEnable"):
        out.append(("info", "roaming",
                    "forced-disassociation is ON site-wide — can make iPhones "
                    "stick/require a wifi toggle if thresholds are aggressive"))
    # The /devices list omits rssiSetting; fetch the per-EAP object for it.
    for a in aps:
        full = client.eap(a["mac"])
        for band, key, floor in (("5G", "rssiSetting5g", -72), ("2.4", "rssiSetting2g", -78)):
            rs = full.get(key) or {}
            if rs.get("rssiEnable") and rs.get("threshold", -99) > floor:
                out.append(("warn", "roaming",
                            f"{a.get('name')} {band}: roaming kick at "
                            f"{rs.get('threshold')}dBm is aggressive (>{floor}) — "
                            f"may boot healthy clients"))
    return out


def _site_features(setting, aps):
    out = []
    if not setting.get("bandSteering", {}).get("enable"):
        out.append(("info", "steering", "band steering is OFF"))
    if setting.get("mesh", {}).get("meshEnable"):
        wired = all(a.get("wirelessLinked") is False or a.get("hop", 0) == 0
                    for a in aps)
        if wired:
            out.append(("warn", "mesh",
                        "mesh is ON but all APs are wired — turn it off"))
    return out


def _weak_clients(clients):
    out = []
    weak = [c for c in clients
            if c.get("wireless") and (c.get("rssi") or 0) <= -78]
    for c in weak[:8]:
        nm = c.get("name") or c.get("hostName") or c.get("mac")
        out.append(("info", "clients",
                    f"weak signal: {nm} at {c.get('rssi')}dBm on {c.get('apName')}"))
    return out


def _offline(devices):
    out = []
    # status 14 = connected on this controller build; anything else is suspect.
    for d in devices:
        if d.get("status") not in (14, 11, 7) and d.get("type") == "ap":
            out.append(("warn", "device",
                        f"{d.get('name')} status={d.get('status')} (not fully connected)"))
    return out
