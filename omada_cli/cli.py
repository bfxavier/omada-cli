"""Argument parsing and dispatch."""
import argparse
import sys

from . import __version__, commands
from .client import OmadaClient, OmadaError
from .config import ConfigError, load_config, resolve_password, save_config


def build_parser():
    # Global flags work in either position (`omada --json status` and
    # `omada status --json`). The main parser holds the real defaults; the
    # subparser copies use SUPPRESS so they only set a value when actually
    # passed after the subcommand — never clobbering a value given before it.
    def add_globals(parser, suppress):
        d = argparse.SUPPRESS if suppress else None
        parser.add_argument("--profile", default=d, help="config profile to use")
        for flag, help in [("--json", "machine-readable output"),
                           ("--dry-run", "print writes instead of sending them"),
                           ("--no-verify", "skip TLS verify"),
                           ("--verbose", "log requests")]:
            parser.add_argument(
                flag, *(["-v"] if flag == "--verbose" else []),
                action="store_true",
                default=(argparse.SUPPRESS if suppress else False), help=help)

    sub_common = argparse.ArgumentParser(add_help=False)
    add_globals(sub_common, suppress=True)

    p = argparse.ArgumentParser(
        prog="omada", description="tune a TP-Link Omada SDN wireless network")
    p.add_argument("--version", action="version", version=f"omada {__version__}")
    add_globals(p, suppress=False)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, help, fn, need_conn=True):
        sp = sub.add_parser(name, help=help, parents=[sub_common])
        sp.set_defaults(_fn=fn, _need_conn=need_conn)
        return sp

    # observability
    add("controller", "controller + network overview", commands.cmd_controller)
    add("sites", "list sites", commands.cmd_sites)
    add("status", "per-AP radio + airtime", commands.cmd_status)
    add("aps", "AP inventory (fw, ip, load)", commands.cmd_aps)
    add("devices", "all devices (AP/switch/gateway)", commands.cmd_devices)

    c = add("clients", "active wireless clients", commands.cmd_clients)
    c.add_argument("--band", choices=["2.4", "5", "6"])
    c.add_argument("--ap", help="filter by AP name substring")
    c.add_argument("--min-rssi", type=int, metavar="DBM")
    c.add_argument("--wired", action="store_true", help="include wired clients")
    c.add_argument("--sort", choices=["rssi", "rate", "name"], default="rssi")

    k = add("known", "known/historical clients", commands.cmd_known)
    k.add_argument("--limit", type=int, default=40)

    add("wlans", "WLAN groups + SSIDs", commands.cmd_wlans)
    add("networks", "LAN / VLAN networks", commands.cmd_networks)

    al = add("alerts", "controller alerts/events feed", commands.cmd_alerts)
    al.add_argument("--events", action="store_true", help="events instead of alerts")
    al.add_argument("--limit", type=int, default=40)

    add("doctor", "run health diagnostics", commands.cmd_doctor)
    add("dfs", "configured vs on-air 5G channel", commands.cmd_dfs)
    add("spectrum", "channel occupancy + client histogram", commands.cmd_spectrum)

    # radio writes
    ch = add("channel", "set 5GHz channel + width", commands.cmd_channel)
    ch.add_argument("ap")
    ch.add_argument("channel", type=int)
    ch.add_argument("width", type=int, choices=[20, 40, 80, 160], nargs="?", default=80)

    pw = add("power", "set TX power (dBm)", commands.cmd_power)
    pw.add_argument("ap")
    pw.add_argument("band", choices=["2.4", "5"])
    pw.add_argument("dbm", type=int)

    rd = add("radio", "enable/disable a band", commands.cmd_radio)
    rd.add_argument("ap")
    rd.add_argument("band", choices=["2.4", "5"])
    rd.add_argument("state", choices=["on", "off"])

    r = add("roam", "get/set/disable roaming kick", commands.cmd_roam)
    rs = r.add_subparsers(dest="action", required=True)
    rs.add_parser("get")
    st = rs.add_parser("set")
    st.add_argument("ap", help="AP name or 'all'")
    st.add_argument("--2.4", dest="g2", type=int, metavar="DBM")
    st.add_argument("--5", dest="g5", type=int, metavar="DBM")
    di = rs.add_parser("disable")
    di.add_argument("ap", help="AP name or 'all'")

    rn = add("rename", "rename an AP", commands.cmd_rename)
    rn.add_argument("ap")
    rn.add_argument("name")

    for name, fn, label in [
        ("steering", commands.cmd_steering, "band steering"),
        ("fastroam", commands.cmd_fastroam, "fast roaming"),
        ("forcedisassoc", commands.cmd_forcedisassoc, "forced disassociation"),
        ("mesh", commands.cmd_mesh, "mesh"),
    ]:
        sp = add(name, f"toggle {label} site-wide", fn)
        sp.add_argument("state", choices=["on", "off"])

    s = add("ssid", "list / enable / disable / set password", commands.cmd_ssid)
    ssub = s.add_subparsers(dest="action", required=True)
    ssub.add_parser("list")
    for act in ("enable", "disable"):
        a = ssub.add_parser(act)
        a.add_argument("name")
    sp = ssub.add_parser("passwd")
    sp.add_argument("name")
    sp.add_argument("password")

    # experimental
    lo = add("locate", "flash AP locate LED (experimental)", commands.cmd_locate)
    lo.add_argument("ap")
    lo.add_argument("state", choices=["on", "off"])
    bl = add("block", "block/unblock a client (experimental)", commands.cmd_block)
    bl.add_argument("action", choices=["block", "unblock"])
    bl.add_argument("mac")

    # snapshots
    bk = add("backup", "snapshot all AP radio config", commands.cmd_backup)
    bk.add_argument("file", nargs="?")
    df = add("diff", "diff a snapshot vs current", commands.cmd_diff)
    df.add_argument("file")
    re = add("restore", "re-apply a snapshot", commands.cmd_restore)
    re.add_argument("file")
    re.add_argument("--setting", action="store_true", help="also restore site features")

    # escape hatch + setup
    rw = add("raw", "raw API call", commands.cmd_raw)
    rw.add_argument("method", choices=["GET", "PATCH", "POST"])
    rw.add_argument("path")
    rw.add_argument("body", nargs="?")
    add("setup", "interactive config", cmd_setup, need_conn=False)
    add("setup-pass", "store password in Keychain", commands.cmd_setup_pass,
        need_conn=False)
    return p


def cmd_setup(client, cfg, args):
    """Interactive first-run config."""
    from . import config as cfgmod
    print("omada-cli setup (blank = keep default)")
    def ask(label, default):
        v = input(f"  {label} [{default}]: ").strip()
        return v or default
    cfg["base_url"] = ask("controller URL", cfg["base_url"])
    cfg["username"] = ask("username", cfg["username"])
    cfg["site"] = ask("site name", cfg["site"])
    cid = ask("controller_id (blank = auto-discover)", cfg.get("controller_id") or "")
    cfg["controller_id"] = cid or None
    path = save_config(cfg)
    print(f"wrote {path}")
    import getpass
    pw = getpass.getpass("controller password (stored in Keychain): ")
    if pw:
        cfgmod.keychain_set(cfg["username"], pw)
        print("password stored.")


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(profile=args.profile)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    if not getattr(args, "_need_conn", True):
        return args._fn(None, cfg, args) or 0

    try:
        password = resolve_password(cfg)
        client = OmadaClient(
            base_url=cfg["base_url"], username=cfg["username"], password=password,
            controller_id=cfg.get("controller_id"), site=cfg["site"],
            verify_tls=cfg.get("verify_tls", False) and not args.no_verify,
            dry_run=args.dry_run, verbose=args.verbose).connect()
        args._fn(client, cfg, args)
        return 0
    except (OmadaError, ConfigError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
