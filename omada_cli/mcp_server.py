"""A Model Context Protocol (MCP) server exposing omada-cli over stdio.

Lets an MCP client (Claude Desktop, Claude Code, etc.) read network state and —
when explicitly enabled — tune radios through natural language.

Implemented in pure stdlib (newline-delimited JSON-RPC 2.0 over stdio) so the
package stays dependency-free. No `mcp` SDK required.

Safety: write tools (channel/power/roaming/...) are only registered when the
environment variable OMADA_MCP_ALLOW_WRITES=1 is set. By default the server is
read-only, because it hands an LLM a wire to live infrastructure.
"""
import json
import os
import sys

from . import __version__, commands, diagnostics, encoding
from .client import OmadaClient, OmadaError
from .commands import resolve_ap
from .config import ConfigError, load_config, resolve_password

PROTOCOL_VERSION = "2024-11-05"
ALLOW_WRITES = os.environ.get("OMADA_MCP_ALLOW_WRITES") == "1"

_state = {"client": None, "cfg": None}


def _client():
    if _state["client"] is None:
        cfg = load_config(profile=os.environ.get("OMADA_PROFILE"))
        client = OmadaClient(
            base_url=cfg["base_url"], username=cfg["username"],
            password=resolve_password(cfg),
            controller_id=cfg.get("controller_id"), site=cfg["site"],
            verify_tls=cfg.get("verify_tls", False)).connect()
        _state["client"], _state["cfg"] = client, cfg
    return _state["client"], _state["cfg"]


def _aps(c):
    return [d for d in c.devices() if d.get("type") == "ap"]


def _ch(wp):
    return str((wp or {}).get("actualChannel", "")).split("/")[0].strip()


# --------------------------------------------------------------------------
# tool handlers — each returns a JSON-serializable object
# --------------------------------------------------------------------------
def t_controller(args):
    c, _ = _client()
    return {"controller": c.controller_status(), "overview": c.overview()}


def t_status(args):
    c, _ = _client()
    out = []
    for a in _aps(c):
        w5, w2 = a.get("wp5g") or {}, a.get("wp2g") or {}
        out.append({"name": a.get("name"), "model": a.get("model"),
                    "clients": a.get("clientNum"), "uptime": a.get("uptime"),
                    "ch5g": _ch(w5), "bw5g": w5.get("bandWidth"),
                    "util5g": {"tx": w5.get("txUtil"), "rx": w5.get("rxUtil"), "inter": w5.get("interUtil")},
                    "ch2g": _ch(w2), "bw2g": w2.get("bandWidth"),
                    "util2g": {"tx": w2.get("txUtil"), "rx": w2.get("rxUtil"), "inter": w2.get("interUtil")}})
    return out


def t_clients(args):
    c, _ = _client()
    cl = [x for x in c.clients(active=True) if x.get("wireless")]
    band = {"2.4": 0, "5": 1, "6": 2}.get(args.get("band"))
    if band is not None:
        cl = [x for x in cl if x.get("radioId") == band]
    if args.get("ap"):
        cl = [x for x in cl if args["ap"].lower() in (x.get("apName") or "").lower()]
    cl.sort(key=lambda x: x.get("rssi") or 0)
    return [{"name": x.get("name") or x.get("hostName") or x.get("mac"),
             "band": {0: "2.4", 1: "5G", 2: "6G"}.get(x.get("radioId")),
             "rssi": x.get("rssi"), "channel": x.get("channel"),
             "rxRate": x.get("rxRate"), "txRate": x.get("txRate"),
             "ap": x.get("apName"), "ip": x.get("ip")} for x in cl]


def t_doctor(args):
    c, _ = _client()
    return [{"severity": s, "area": a, "message": m} for s, a, m in diagnostics.run(c)]


def t_dfs(args):
    c, _ = _client()
    out = []
    for a in _aps(c):
        rs = a.get("radioSetting5g") or {}
        cfg_ch = encoding.index_to_channel(rs.get("channel"))
        act = _ch(a.get("wp5g"))
        if not rs.get("radioEnable"):
            state = "5g-off"
        elif act and cfg_ch and str(cfg_ch) != act:
            state = "bounced"
        elif cfg_ch and encoding.is_dfs(cfg_ch):
            state = "holding-dfs"
        else:
            state = "non-dfs"
        out.append({"name": a.get("name"), "configured": cfg_ch,
                    "onAir": act, "state": state})
    return out


def t_spectrum(args):
    c, _ = _client()
    aps, hist = [], {}
    for a in _aps(c):
        for band, key in (("2.4", "wp2g"), ("5G", "wp5g")):
            wp = a.get(key) or {}
            if _ch(wp):
                aps.append({"ap": a.get("name"), "band": band, "channel": _ch(wp),
                            "width": wp.get("bandWidth"),
                            "util": {"tx": wp.get("txUtil"), "rx": wp.get("rxUtil"), "inter": wp.get("interUtil")}})
    for x in c.clients(active=True):
        if x.get("wireless") and x.get("channel"):
            hist[x["channel"]] = hist.get(x["channel"], 0) + 1
    return {"apChannels": aps, "clientsPerChannel": hist}


def t_aps(args):
    c, _ = _client()
    return [{"name": a.get("name"), "model": a.get("model"), "firmware": a.get("version"),
             "ip": a.get("ip"), "mac": a.get("mac"), "clients": a.get("clientNum"),
             "needUpgrade": a.get("needUpgrade"), "uptime": a.get("uptime")}
            for a in _aps(c)]


def t_wlans(args):
    c, _ = _client()
    out = []
    for g in c.wlan_groups():
        for s in c.ssids(g["id"]):
            out.append({"group": g["name"], "ssid": s.get("name"),
                        "band": s.get("band"), "enabled": s.get("enable") is not False})
    return out


def t_roam_get(args):
    c, _ = _client()
    out = []
    for a in _aps(c):
        full = c.eap(a["mac"])
        r2, r5 = full.get("rssiSetting2g") or {}, full.get("rssiSetting5g") or {}
        out.append({"name": a.get("name"),
                    "kick2g": r2.get("threshold") if r2.get("rssiEnable") else None,
                    "kick5g": r5.get("threshold") if r5.get("rssiEnable") else None})
    return out


# --- write handlers (only registered when ALLOW_WRITES) -------------------
def t_set_channel(args):
    c, cfg = _client()
    label, mac = resolve_ap(c, cfg, args["ap"])
    ch = int(args["channel"])
    if encoding.band_of_channel(ch) == "2.4":
        width = int(args.get("width") or 20)
        if ch != 0:
            encoding.validate_2g(ch, width)
        cur = c.eap(mac)["radioSetting2g"]
        c.eap_patch(mac, {"radioSetting2g": {**cur, "channel": str(ch),
                          "channelWidth": encoding.TWO_G_WIDTHS[width]}})
    else:
        width = int(args.get("width") or 80)
        cur = c.eap(mac)["radioSetting5g"]
        c.eap_patch(mac, {"radioSetting5g": {**cur,
                    "channel": encoding.channel_index(ch),
                    "channelWidth": encoding.width_code(width),
                    "channelRange": encoding.channel_range(ch, width)}})
    return {"ok": True, "ap": label, "channel": ch, "width": width}


def t_ssid_create(args):
    c, cfg = _client()
    gid = commands._group_id(c, args.get("group") or "Default")
    tmpl = {k: v for k, v in commands._ssid_template(c).items()
            if k not in commands._SSID_STRIP}
    tmpl["name"] = args["name"]
    tmpl["band"] = commands.BAND_NAME_TO_CODE.get(args.get("band", "all"), 7)
    if args.get("password"):
        psk = dict(tmpl.get("pskSetting") or {})
        psk["securityKey"] = args["password"]
        tmpl["pskSetting"], tmpl["security"] = psk, 3
    else:
        tmpl["security"] = 0
    c.post(f"/setting/wlans/{gid}/ssids", tmpl)
    return {"ok": True, "ssid": args["name"], "group": args.get("group") or "Default"}


def t_ssid_delete(args):
    c, _ = _client()
    wlan_id, ssid = commands._find_ssid(c, args["name"])
    c.delete(f"/setting/wlans/{wlan_id}/ssids/{ssid['id']}")
    return {"ok": True, "deleted": ssid["name"]}


def t_wlan_group_create(args):
    c, _ = _client()
    c.post("/setting/wlans", {"name": args["name"], "clone": False})
    return {"ok": True, "group": args["name"]}


def t_assign_ap_group(args):
    c, cfg = _client()
    label, mac = resolve_ap(c, cfg, args["ap"])
    gid = commands._group_id(c, args["group"])
    c.eap_patch(mac, {"wlanId": gid})
    return {"ok": True, "ap": label, "group": args["group"]}


def t_set_power(args):
    c, cfg = _client()
    label, mac = resolve_ap(c, cfg, args["ap"])
    key = "radioSetting2g" if args["band"] == "2.4" else "radioSetting5g"
    cur = c.eap(mac)[key]
    c.eap_patch(mac, {key: {**cur, "txPowerLevel": 1, "txPower": int(args["dbm"])}})
    return {"ok": True, "ap": label, "band": args["band"], "dbm": int(args["dbm"])}


def t_set_roam(args):
    c, cfg = _client()
    targets = (_aps(c) if args["ap"] == "all"
               else [{"name": resolve_ap(c, cfg, args["ap"])[0], "mac": resolve_ap(c, cfg, args["ap"])[1]}])
    if args.get("disable"):
        body = {"rssiSetting2g": {"rssiEnable": False, "threshold": -95},
                "rssiSetting5g": {"rssiEnable": False, "threshold": -95}}
    else:
        body = {}
        if args.get("threshold2g") is not None:
            body["rssiSetting2g"] = {"rssiEnable": True, "threshold": int(args["threshold2g"])}
        if args.get("threshold5g") is not None:
            body["rssiSetting5g"] = {"rssiEnable": True, "threshold": int(args["threshold5g"])}
    for a in targets:
        c.eap_patch(a["mac"], body)
    return {"ok": True, "applied": body, "aps": [a["name"] for a in targets]}


def t_set_radio(args):
    c, cfg = _client()
    label, mac = resolve_ap(c, cfg, args["ap"])
    key = "radioSetting2g" if args["band"] == "2.4" else "radioSetting5g"
    cur = c.eap(mac)[key]
    c.eap_patch(mac, {key: {**cur, "radioEnable": args["state"] == "on"}})
    return {"ok": True, "ap": label, "band": args["band"], "state": args["state"]}


def t_toggle_feature(args):
    c, _ = _client()
    feat = args["feature"]
    path_key, sub = {"steering": ("bandSteering", "enable"),
                     "fastroam": ("roaming", "fastRoamingEnable"),
                     "forcedisassoc": ("roaming", "forceDisassociationEnable"),
                     "mesh": ("mesh", "meshEnable")}[feat]
    cur = c.setting().get(path_key, {})
    c.setting_patch({path_key: {**cur, sub: args["state"] == "on"}})
    return {"ok": True, "feature": feat, "state": args["state"]}


# --------------------------------------------------------------------------
# tool registry
# --------------------------------------------------------------------------
def _ap_arg():
    return {"ap": {"type": "string", "description": "AP friendly name or MAC"}}


READ_TOOLS = [
    ("omada_controller", "Controller info + network overview (counts, clients).", {}, t_controller),
    ("omada_status", "Per-AP radio state: channel, width, airtime utilization, client count.", {}, t_status),
    ("omada_clients", "Active wireless clients with RSSI, channel, rate, AP.",
     {"band": {"type": "string", "enum": ["2.4", "5", "6"]}, "ap": {"type": "string"}}, t_clients),
    ("omada_doctor", "Run health diagnostics (co-channel, congestion, roaming, firmware).", {}, t_doctor),
    ("omada_dfs", "Configured vs on-air 5GHz channel; flags DFS radar bounces.", {}, t_dfs),
    ("omada_spectrum", "Per-AP channel occupancy and clients-per-channel histogram.", {}, t_spectrum),
    ("omada_aps", "AP inventory: model, firmware, IP, load, upgrade status.", {}, t_aps),
    ("omada_wlans", "WLAN groups and their SSIDs.", {}, t_wlans),
    ("omada_roam_get", "Current per-AP roaming-kick (RSSI) thresholds.", {}, t_roam_get),
]

WRITE_TOOLS = [
    ("omada_set_channel", "Set an AP's channel + width. 1-13 = 2.4GHz, 36+ = 5GHz, 0 = auto.",
     {**_ap_arg(), "channel": {"type": "integer"}, "width": {"type": "integer", "enum": [20, 40, 80, 160]}},
     t_set_channel, ["ap", "channel"]),
    ("omada_set_power", "Set an AP's transmit power in dBm for a band.",
     {**_ap_arg(), "band": {"type": "string", "enum": ["2.4", "5"]}, "dbm": {"type": "integer"}},
     t_set_power, ["ap", "band", "dbm"]),
    ("omada_set_roam", "Set or disable roaming-kick RSSI thresholds. ap may be 'all'.",
     {**_ap_arg(), "threshold2g": {"type": "integer"}, "threshold5g": {"type": "integer"},
      "disable": {"type": "boolean"}}, t_set_roam, ["ap"]),
    ("omada_set_radio", "Enable/disable an AP's 2.4 or 5 GHz radio.",
     {**_ap_arg(), "band": {"type": "string", "enum": ["2.4", "5"]}, "state": {"type": "string", "enum": ["on", "off"]}},
     t_set_radio, ["ap", "band", "state"]),
    ("omada_toggle_feature", "Toggle a site-wide feature on/off.",
     {"feature": {"type": "string", "enum": ["steering", "fastroam", "forcedisassoc", "mesh"]},
      "state": {"type": "string", "enum": ["on", "off"]}}, t_toggle_feature, ["feature", "state"]),
    ("omada_ssid_create", "Create an SSID in a WLAN group (clones an existing SSID's schema).",
     {"name": {"type": "string"}, "band": {"type": "string", "enum": ["2.4", "5", "6", "2.4+5", "all"]},
      "group": {"type": "string"}, "password": {"type": "string"}}, t_ssid_create, ["name"]),
    ("omada_ssid_delete", "Delete an SSID by name.",
     {"name": {"type": "string"}}, t_ssid_delete, ["name"]),
    ("omada_wlan_group_create", "Create an empty WLAN group.",
     {"name": {"type": "string"}}, t_wlan_group_create, ["name"]),
    ("omada_assign_ap_group", "Assign an AP to a WLAN group (resyncs its radios).",
     {**_ap_arg(), "group": {"type": "string"}}, t_assign_ap_group, ["ap", "group"]),
]


def _build_registry():
    reg = {}
    for name, desc, props, fn in READ_TOOLS:
        reg[name] = {"description": desc, "handler": fn,
                     "inputSchema": {"type": "object", "properties": props}}
    if ALLOW_WRITES:
        for name, desc, props, fn, required in WRITE_TOOLS:
            reg[name] = {"description": "[WRITE] " + desc, "handler": fn,
                         "inputSchema": {"type": "object", "properties": props, "required": required}}
    return reg


REGISTRY = _build_registry()


# --------------------------------------------------------------------------
# JSON-RPC plumbing
# --------------------------------------------------------------------------
def _result(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _error(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        ver = params.get("protocolVersion") or PROTOCOL_VERSION
        return _result(mid, {
            "protocolVersion": ver,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "omada-cli", "version": __version__},
            "instructions": ("Tools to inspect and tune a TP-Link Omada wifi network. "
                             + ("Write tools are ENABLED." if ALLOW_WRITES
                                else "Read-only mode (set OMADA_MCP_ALLOW_WRITES=1 to enable tuning).")),
        })
    if method == "ping":
        return _result(mid, {})
    if method and method.startswith("notifications/"):
        return None  # notifications get no response
    if method == "tools/list":
        tools = [{"name": n, "description": t["description"], "inputSchema": t["inputSchema"]}
                 for n, t in REGISTRY.items()]
        return _result(mid, {"tools": tools})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = REGISTRY.get(name)
        if not tool:
            return _result(mid, {"isError": True,
                                 "content": [{"type": "text", "text": f"unknown tool: {name}"}]})
        try:
            data = tool["handler"](args)
            text = json.dumps(data, indent=2, default=str)
            return _result(mid, {"content": [{"type": "text", "text": text}]})
        except (OmadaError, ConfigError, encoding.EncodingError, KeyError, ValueError) as e:
            return _result(mid, {"isError": True,
                                 "content": [{"type": "text", "text": f"error: {e}"}]})
    if mid is not None:
        return _error(mid, -32601, f"method not found: {method}")
    return None


def main(argv=None):
    # newline-delimited JSON-RPC over stdio
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
