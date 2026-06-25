"""Command handlers. Each takes (client, cfg, args)."""
import json
import time
from collections import Counter

from . import diagnostics, encoding
from .client import OmadaError
from .output import color, emit_json, table

BANDS = {0: "2.4", 1: "5G", 2: "6G"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _devices_cache(client):
    if not hasattr(client, "_dev_cache"):
        client._dev_cache = client.devices()
    return client._dev_cache


def resolve_ap(client, cfg, name):
    """Return (label, mac). Accepts a friendly name from config, a raw MAC,
    or a (partial) device name match."""
    key = name.lower()
    aps = {k.lower(): v for k, v in cfg.get("aps", {}).items()}
    if key in aps:
        return key, aps[key]
    if len(name) == 17 and name.count("-") == 5:
        return name, name.upper()
    matches = [d for d in _devices_cache(client)
               if d.get("type") == "ap" and key in (d.get("name") or "").lower()]
    if len(matches) == 1:
        return matches[0]["name"], matches[0]["mac"]
    if len(matches) > 1:
        raise OmadaError(f"'{name}' matches several APs: "
                         + ", ".join(m["name"] for m in matches))
    known = list(cfg.get("aps", {})) + \
        [d.get("name") for d in _devices_cache(client) if d.get("type") == "ap"]
    raise OmadaError(f"unknown AP '{name}'. known: {', '.join(known)}")


def _ap_list(client, cfg, target):
    if target == "all":
        return [(d.get("name"), d["mac"]) for d in _devices_cache(client)
                if d.get("type") == "ap"]
    return [resolve_ap(client, cfg, target)]


def _ch(wp):
    return str(wp.get("actualChannel", "")).split("/")[0].strip() if wp else ""


def _util(wp):
    if not wp or wp.get("txUtil") is None:
        return ""
    return f"{wp.get('txUtil')}/{wp.get('rxUtil')}/{wp.get('interUtil')}"


# --------------------------------------------------------------------------
# observability
# --------------------------------------------------------------------------
def _fmt_uptime(val):
    """Controller upTime is milliseconds; render as 'Nd Nh Nm'."""
    try:
        secs = int(val) // 1000
    except (TypeError, ValueError):
        return val
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    return f"{d}d {h}h {rem // 60}m"


def cmd_controller(client, cfg, args):
    s = client.controller_status()
    ov = client.overview()
    if args.json:
        return emit_json({"controller": s, "overview": ov})
    table(["field", "value"], [
        ("model", s.get("model")), ("name", s.get("name")),
        ("version", s.get("controllerVersion")),
        ("firmware", s.get("firmwareVersion")), ("uptime", _fmt_uptime(s.get("upTime"))),
        ("APs", f"{ov.get('connectedApNum')}/{ov.get('totalApNum')} up"),
        ("switches", f"{ov.get('connectedSwitchNum')}/{ov.get('totalSwitchNum')} up"),
        ("clients", ov.get("totalClientNum")),
        ("guests", ov.get("guestNum")),
        ("PoE draw (W)", ov.get("powerConsumption")),
    ], aligns=["<", "<"])


def cmd_sites(client, cfg, args):
    sites = client.sites()
    if args.json:
        return emit_json(sites)
    table(["site", "id", "clients", "APs up/down"],
          [(s.get("name"), s.get("id"), s.get("lanUserNum"),
            f"{s.get('lanDeviceConnectedNum')}/{s.get('lanDeviceDisconnectedNum')}")
           for s in sites])


def cmd_status(client, cfg, args):
    aps = [d for d in _devices_cache(client) if d.get("type") == "ap"]
    if args.json:
        return emit_json(aps)
    rows = []
    for a in sorted(aps, key=lambda x: x.get("name") or ""):
        w5, w2 = a.get("wp5g") or {}, a.get("wp2g") or {}
        rows.append((a.get("name"), a.get("model"),
                     f"{_ch(w5)}/{w5.get('bandWidth','')}", _util(w5),
                     f"{_ch(w2)}/{w2.get('bandWidth','')}", _util(w2),
                     a.get("clientNum"), a.get("uptime", "")))
    table(["AP", "model", "5G ch/bw", "5G t/r/i", "2.4 ch/bw", "2.4 t/r/i",
           "cli", "uptime"], rows)


def cmd_aps(client, cfg, args):
    aps = [d for d in _devices_cache(client) if d.get("type") == "ap"]
    if args.json:
        return emit_json(aps)
    rows = [(a.get("name"), a.get("model"), a.get("version"), a.get("ip"),
             a.get("clientNum"),
             f"{a.get('cpuUtil')}/{a.get('memUtil')}",
             "yes" if a.get("needUpgrade") else "", a.get("uptime", ""))
            for a in sorted(aps, key=lambda x: x.get("name") or "")]
    table(["AP", "model", "fw", "ip", "cli", "cpu/mem%", "upd?", "uptime"], rows)


def cmd_devices(client, cfg, args):
    devs = _devices_cache(client)
    if args.json:
        return emit_json(devs)
    rows = [(d.get("type"), d.get("name"), d.get("model"), d.get("version"),
             d.get("ip"), d.get("mac"), d.get("clientNum"), d.get("uptime", ""))
            for d in devs]
    table(["type", "name", "model", "fw", "ip", "mac", "cli", "uptime"], rows)


def cmd_clients(client, cfg, args):
    cl = client.clients(active=True)
    if not args.wired:
        cl = [c for c in cl if c.get("wireless")]
    if args.band:
        want = {"2.4": 0, "5": 1, "5G": 1, "6": 2}.get(args.band, None)
        cl = [c for c in cl if c.get("radioId") == want]
    if args.ap:
        cl = [c for c in cl if args.ap.lower() in (c.get("apName") or "").lower()]
    if args.min_rssi is not None:
        cl = [c for c in cl if (c.get("rssi") or 0) >= args.min_rssi]
    keys = {"rssi": lambda c: c.get("rssi") or 0,
            "rate": lambda c: -(c.get("rxRate") or 0),
            "name": lambda c: (c.get("name") or c.get("mac") or "").lower()}
    cl.sort(key=keys.get(args.sort, keys["rssi"]))
    if args.json:
        return emit_json(cl)
    rows = []
    for c in cl:
        rows.append(((c.get("name") or c.get("hostName") or c.get("mac"))[:26],
                     BANDS.get(c.get("radioId"), "wired" if not c.get("wireless") else "?"),
                     c.get("rssi"), c.get("channel"),
                     f"{c.get('rxRate')}/{c.get('txRate')}",
                     c.get("healthScore"), (c.get("apName") or "")[:14], c.get("ip")))
    table(["client", "band", "rssi", "ch", "down/up kbps", "health", "ap", "ip"],
          rows, aligns=["<", "<", ">", ">", ">", ">", "<", "<"])


def cmd_known(client, cfg, args):
    kc = client.known_clients()
    kc.sort(key=lambda c: c.get("lastSeen") or 0, reverse=True)
    if args.json:
        return emit_json(kc)
    rows = [((c.get("name") or c.get("mac"))[:28],
             "wifi" if c.get("wireless") else "wired",
             f"{round((c.get('download') or 0)/1e6,1)}MB",
             f"{round((c.get('upload') or 0)/1e6,1)}MB",
             "blocked" if c.get("block") else "",
             time.strftime("%Y-%m-%d %H:%M", time.localtime((c.get("lastSeen") or 0)/1000)))
            for c in kc[:args.limit]]
    table(["client", "type", "down", "up", "", "last seen"], rows)


def cmd_wlans(client, cfg, args):
    groups = client.wlan_groups()
    out = []
    for g in groups:
        ssids = client.ssids(g["id"])
        out.append({"group": g["name"], "id": g["id"], "ssids": ssids})
    if args.json:
        return emit_json(out)
    rows = []
    for grp in out:
        for s in grp["ssids"]:
            band = {1: "2.4", 2: "5G", 3: "2.4+5", 7: "all"}.get(s.get("band"), s.get("band"))
            rows.append((grp["group"], s.get("name"), band,
                         "on" if s.get("enable") is not False else "off",
                         "yes" if s.get("guestNetEnable") else "",
                         "yes" if s.get("enable11r") else ""))
    table(["wlan group", "ssid", "band", "state", "guest", "11r"], rows)


def cmd_networks(client, cfg, args):
    nets = client.lan_networks()
    if args.json:
        return emit_json(nets)
    rows = [(n.get("name"), n.get("purpose", n.get("interface")),
             n.get("vlan", (n.get("interface") or {}) if isinstance(n.get("interface"), dict) else ""),
             n.get("gatewaySubnet"),
             "on" if (n.get("dhcpSettings") or {}).get("dhcpServerEnable") else "off")
            for n in nets]
    table(["network", "purpose", "vlan", "subnet", "dhcp"], rows)


def cmd_alerts(client, cfg, args):
    feed = client.events() if args.events else client.alerts()
    if args.json:
        return emit_json(feed)
    if not feed:
        print(color("(no entries)", "dim"))
        return
    rows = [(time.strftime("%Y-%m-%d %H:%M", time.localtime((e.get("time") or 0)/1000)),
             e.get("level", e.get("type")), (e.get("msg") or e.get("content") or "")[:80])
            for e in feed[:args.limit]]
    table(["time", "level", "message"], rows)


def cmd_doctor(client, cfg, args):
    findings = diagnostics.run(client)
    if args.json:
        return emit_json([{"severity": s, "area": a, "message": m}
                          for s, a, m in findings])
    icon = {"warn": color("WARN", "yellow"), "info": color("info", "cyan"),
            "ok": color("OK", "green")}
    for sev, area, msg in findings:
        print(f"{icon.get(sev, sev):>4}  {area:10} {msg}")


def cmd_dfs(client, cfg, args):
    aps = [d for d in _devices_cache(client) if d.get("type") == "ap"]
    if args.json:
        return emit_json(aps)
    rows = []
    for a in sorted(aps, key=lambda x: x.get("name") or ""):
        rs = a.get("radioSetting5g") or {}
        cfg_ch = encoding.index_to_channel(rs.get("channel"))
        act = _ch(a.get("wp5g"))
        if not rs.get("radioEnable"):
            state = color("5G off", "dim")
        elif act and cfg_ch and str(cfg_ch) != act:
            state = color(f"BOUNCED (cfg {cfg_ch} -> on {act})", "yellow")
        elif cfg_ch and encoding.is_dfs(cfg_ch):
            state = color("holding DFS", "green")
        else:
            state = "non-DFS"
        rows.append((a.get("name"), a.get("model"), cfg_ch or "?", act or "-", state))
    table(["AP", "model", "cfg 5G", "on-air", "dfs state"], rows)


def cmd_spectrum(client, cfg, args):
    aps = [d for d in _devices_cache(client) if d.get("type") == "ap"]
    clients = [c for c in client.clients(active=True) if c.get("wireless")]
    print(color("AP channel occupancy", "cyan"))
    rows = []
    for a in sorted(aps, key=lambda x: x.get("name") or ""):
        for band, key in (("2.4", "wp2g"), ("5G", "wp5g")):
            wp = a.get(key) or {}
            if _ch(wp):
                rows.append((a.get("name"), band, _ch(wp),
                             wp.get("bandWidth", ""), _util(wp)))
    table(["AP", "band", "ch", "bw", "t/r/i %"], rows)
    hist = Counter(c.get("channel") for c in clients if c.get("channel"))
    print("\n" + color("clients per channel", "cyan"))
    table(["channel", "clients"],
          [(ch, n) for ch, n in sorted(hist.items())], aligns=[">", ">"])


# --------------------------------------------------------------------------
# radio config (writes)
# --------------------------------------------------------------------------
def cmd_channel(client, cfg, args):
    label, mac = resolve_ap(client, cfg, args.ap)
    cur = client.eap(mac)["radioSetting5g"]
    idx = encoding.channel_index(args.channel)
    body = {"radioSetting5g": {**cur, "channel": idx,
                               "channelWidth": encoding.width_code(args.width),
                               "channelRange": encoding.channel_range(args.channel, args.width)}}
    print(f"{label}: {encoding.describe_5g(cur)} -> ch{args.channel}/{args.width}MHz")
    client.eap_patch(mac, body)
    print("patched. on-air channel resyncs in ~30-60s (omada status / omada dfs).")


def cmd_power(client, cfg, args):
    label, mac = resolve_ap(client, cfg, args.ap)
    key = "radioSetting2g" if args.band == "2.4" else "radioSetting5g"
    cur = client.eap(mac)[key]
    body = {key: {**cur, "txPowerLevel": 1, "txPower": args.dbm}}
    print(f"{label}: {args.band}G txPower {cur.get('txPower')} -> {args.dbm}dBm (custom)")
    client.eap_patch(mac, body)


def cmd_radio(client, cfg, args):
    label, mac = resolve_ap(client, cfg, args.ap)
    key = "radioSetting2g" if args.band == "2.4" else "radioSetting5g"
    cur = client.eap(mac)[key]
    on = args.state == "on"
    print(f"{label}: {args.band}G radio -> {'ON' if on else 'OFF'}")
    client.eap_patch(mac, {key: {**cur, "radioEnable": on}})


def cmd_roam(client, cfg, args):
    if args.action == "get":
        # rssiSetting lives only on the per-EAP object, not the /devices list.
        aps = [d for d in _devices_cache(client) if d.get("type") == "ap"]
        rows = []
        for a in sorted(aps, key=lambda x: x.get("name") or ""):
            full = client.eap(a["mac"])
            r2, r5 = full.get("rssiSetting2g") or {}, full.get("rssiSetting5g") or {}
            rows.append((a.get("name"),
                         r2.get("threshold") if r2.get("rssiEnable") else "off",
                         r5.get("threshold") if r5.get("rssiEnable") else "off"))
        if args.json:
            return emit_json(rows)
        return table(["AP", "2.4 kick", "5G kick"], rows, aligns=["<", ">", ">"])

    body = {}
    if args.action == "disable":
        body = {"rssiSetting2g": {"rssiEnable": False, "threshold": -95},
                "rssiSetting5g": {"rssiEnable": False, "threshold": -95}}
    else:  # set
        if args.g2 is not None:
            body["rssiSetting2g"] = {"rssiEnable": True, "threshold": args.g2}
        if args.g5 is not None:
            body["rssiSetting5g"] = {"rssiEnable": True, "threshold": args.g5}
        if not body:
            raise OmadaError("nothing to set: pass --2.4 and/or --5")
    for label, mac in _ap_list(client, cfg, args.ap):
        client.eap_patch(mac, body)
        print(f"{label}: roaming kick -> {json.dumps(body)}")


def cmd_rename(client, cfg, args):
    label, mac = resolve_ap(client, cfg, args.ap)
    print(f"{label} -> '{args.name}'")
    client.eap_patch(mac, {"name": args.name})


# --------------------------------------------------------------------------
# site-wide wireless features
# --------------------------------------------------------------------------
def _toggle_feature(client, path_key, sub_key, on, label):
    cur = client.setting().get(path_key, {})
    print(f"{label} -> {'ON' if on else 'OFF'}")
    client.setting_patch({path_key: {**cur, sub_key: on}})


def cmd_steering(client, cfg, args):
    _toggle_feature(client, "bandSteering", "enable", args.state == "on", "band steering")


def cmd_fastroam(client, cfg, args):
    _toggle_feature(client, "roaming", "fastRoamingEnable", args.state == "on", "fast roaming (802.11r/k)")


def cmd_forcedisassoc(client, cfg, args):
    _toggle_feature(client, "roaming", "forceDisassociationEnable", args.state == "on", "forced disassociation")


def cmd_mesh(client, cfg, args):
    _toggle_feature(client, "mesh", "meshEnable", args.state == "on", "mesh")


# --------------------------------------------------------------------------
# SSID
# --------------------------------------------------------------------------
def _find_ssid(client, name):
    for g in client.wlan_groups():
        for s in client.ssids(g["id"]):
            if s.get("name", "").lower() == name.lower():
                return g["id"], s
    raise OmadaError(f"SSID '{name}' not found")


def cmd_ssid(client, cfg, args):
    if args.action == "list":
        return cmd_wlans(client, cfg, args)
    wlan_id, ssid = _find_ssid(client, args.name)
    if args.action in ("enable", "disable"):
        on = args.action == "enable"
        print(f"SSID '{ssid['name']}' -> {'enabled' if on else 'disabled'}")
        client.ssid_patch(wlan_id, ssid["id"], {**ssid, "enable": on})
    elif args.action == "passwd":
        psk = dict(ssid.get("pskSetting") or {})
        psk["wpaPsk"] = args.password
        print(f"SSID '{ssid['name']}': password updated")
        client.ssid_patch(wlan_id, ssid["id"], {**ssid, "pskSetting": psk})


# --------------------------------------------------------------------------
# experimental device/client actions (field-test before relying)
# --------------------------------------------------------------------------
def cmd_locate(client, cfg, args):
    label, mac = resolve_ap(client, cfg, args.ap)
    on = args.state == "on"
    print(color(f"[experimental] {label}: locate LED -> {'ON' if on else 'OFF'}", "yellow"))
    client.eap_patch(mac, {"locateEnable": on})


def cmd_block(client, cfg, args):
    on = args.action == "block"
    print(color(f"[experimental] client {args.mac} -> {'BLOCK' if on else 'unblock'}", "yellow"))
    client.patch(f"/clients/{args.mac}", {"block": on})


# --------------------------------------------------------------------------
# snapshots
# --------------------------------------------------------------------------
_RADIO_KEYS = ["radioSetting2g", "radioSetting5g", "rssiSetting2g", "rssiSetting5g"]


def cmd_backup(client, cfg, args):
    aps = [d for d in _devices_cache(client) if d.get("type") == "ap"]
    snap = {"taken": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "site": client.site_ref, "setting": client.setting(), "aps": {}}
    for a in aps:
        full = client.eap(a["mac"])
        snap["aps"][a["mac"]] = {"name": a.get("name"),
                                 **{k: full.get(k) for k in _RADIO_KEYS}}
    path = args.file or f"omada-backup-{time.strftime('%Y%m%d-%H%M%S')}.json"
    with open(path, "w") as f:
        json.dump(snap, f, indent=2)
    print(f"wrote {path} ({len(snap['aps'])} APs)")


def cmd_diff(client, cfg, args):
    with open(args.file) as f:
        snap = json.load(f)
    cur_setting = client.setting()
    for feat in ("bandSteering", "roaming", "mesh"):
        if snap.get("setting", {}).get(feat) != cur_setting.get(feat):
            print(color(f"~ setting.{feat} differs", "yellow"))
            print(f"    snapshot: {json.dumps(snap.get('setting',{}).get(feat))}")
            print(f"    current : {json.dumps(cur_setting.get(feat))}")
    for mac, saved in snap.get("aps", {}).items():
        cur = client.eap(mac)
        for k in _RADIO_KEYS:
            if saved.get(k) != cur.get(k):
                print(color(f"~ {saved.get('name')} {k} differs", "yellow"))
                print(f"    snapshot: {json.dumps(saved.get(k))}")
                print(f"    current : {json.dumps(cur.get(k))}")
    print(color("diff complete", "dim"))


def cmd_restore(client, cfg, args):
    with open(args.file) as f:
        snap = json.load(f)
    for mac, saved in snap.get("aps", {}).items():
        body = {k: saved[k] for k in _RADIO_KEYS if saved.get(k) is not None}
        print(f"restore {saved.get('name')} ({mac})")
        client.eap_patch(mac, body)
    if args.setting:
        s = snap.get("setting", {})
        client.setting_patch({k: s[k] for k in ("bandSteering", "roaming", "mesh")
                              if k in s})
        print("restored site features")


# --------------------------------------------------------------------------
# escape hatch + setup
# --------------------------------------------------------------------------
def cmd_raw(client, cfg, args):
    body = json.loads(args.body) if args.body else None
    if args.path.startswith("/sites/") or not args.path.startswith("/"):
        path = args.path if args.path.startswith("/") else "/" + args.path
        if args.method == "GET":
            out = client.get(path)
        elif args.method == "PATCH":
            out = client.patch(path, body or {})
        else:
            out = client.post(path, body)
    else:
        out = client._api(args.method, args.path, body)
    emit_json(out)


def cmd_setup_pass(client, cfg, args):
    import getpass

    from . import config as cfgmod
    pw = getpass.getpass(f"controller password for {cfg['username']}: ")
    cfgmod.keychain_set(cfg["username"], pw)
    print("stored in macOS Keychain (service 'omada-cli').")
