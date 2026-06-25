# omada-cli

Command-line **radio tuning** for TP-Link Omada SDN networks — set channels,
channel width, transmit power, and roaming/RSSI thresholds per access point,
plus a full read-only view of devices, clients, and network health.

```console
$ omada doctor
WARN  channels   5G co-channel: Shed AP, Master Bedroom AP all on ch36
info  firmware   Shed AP: firmware update available (1.0.3)
  OK  overall    no warnings — network looks healthy

$ omada channel office 100 80
Bruno's Office AP: ch44/40MHz -> ch100/80MHz
patched. on-air channel resyncs in ~30-60s (omada status / omada dfs).
```

## Why this exists

TP-Link ships an official **Omada Open API** (the Northbound API). It's great
for monitoring and bulk *template* provisioning — but it **cannot configure a
single AP's radio**: no channel, no channel width, no transmit power, no
roaming/RSSI threshold. The popular
[`tplink-omada-client`](https://pypi.org/project/tplink-omada-client/) library
has the same limitation (it's read-only on radios).

Those radio knobs only exist in the controller's **internal web API** — the one
the GUI uses. `omada-cli` speaks that API, so you can script the tuning you'd
otherwise have to click through the web UI for. That's the whole point of the
tool.

> **Heads up:** because it uses the internal API, a controller upgrade *could*
> change an endpoint. Tested against **OC200 / controller 5.14.x**. The encoding
> quirks it relies on are documented below.

## Features

- **Observability** — `controller`, `status`, `aps`, `devices`, `clients`
  (filter by band/AP/RSSI), `known` (historical clients), `wlans`, `networks`
  (VLANs), `alerts`, `spectrum` (channel occupancy + client histogram)
- **Diagnostics** — `doctor` flags co-channel overlap, airtime congestion,
  aggressive roaming kicks, firmware mismatches, mesh-on-wired, weak clients
- **`dfs`** — shows configured vs on-air 5 GHz channel and flags radar bounces
- **Radio config** — `channel`, `power`, `radio` (band on/off), `roam`
  (get/set/disable RSSI kick), `rename`
- **Site features** — `steering`, `fastroam`, `forcedisassoc`, `mesh`
- **SSID** — `ssid list|enable|disable|passwd`
- **Snapshots** — `backup`, `diff`, `restore` your radio config
- **Safety** — `--dry-run` prints the exact PATCH instead of sending it
- **`--json`** on every read command; `raw` escape hatch for anything else
- **MCP server** — drive it from Claude Desktop / Claude Code (see below)
- **Zero dependencies** — Python standard library only

## Install

### pip (recommended)

```sh
pip install --user .          # from a clone
# or, once published:  pip install omada-cli
omada --version
```

### Zero-install launcher

No pip needed — symlink the bundled launcher onto your PATH:

```sh
git clone https://github.com/brunoxavier/omada-cli && cd omada-cli
ln -s "$PWD/bin/omada" ~/.local/bin/omada
```

## Setup

```sh
omada setup        # interactive: controller URL, user, site -> ~/.config/omada/config.json
```

This also stashes your password in the **macOS Keychain**. Prefer not to use the
Keychain? Set `OMADA_PASS` in your environment, or `"password_source": "config"`
(see [`config.example.json`](config.example.json)).

`controller_id` and `site` are **auto-discovered** if you leave them at their
defaults — you can usually just give the URL, username, and password.

Optionally map friendly AP names so you never type a MAC:

```json
{ "aps": { "office": "A8-42-A1-FD-8E-B0", "living": "20-E1-5D-A4-A2-38" } }
```

Multiple controllers? Put them under a `profiles` object and select with
`--profile <name>`.

## Usage

```sh
# look around
omada controller                 # controller + overview
omada status                     # per-AP channels + airtime utilization
omada clients --band 5 --sort rssi
omada doctor                     # health checks
omada dfs                        # DFS hold / radar-bounce check
omada spectrum                   # channel occupancy

# tune radios  (add --dry-run to preview the PATCH)
omada channel office 100 80      # 5GHz channel + width (20/40/80)
omada power living 5 20          # TX power in dBm
omada radio basement 5 off       # turn a band off
omada roam set all --5 -76 --2.4 -82
omada roam disable all           # rely on 802.11k/v instead

# site-wide wireless features
omada steering on
omada forcedisassoc off

# SSIDs
omada ssid list
omada ssid passwd XavIoT 'new-pre-shared-key'

# snapshot / restore
omada backup before-changes.json
omada diff before-changes.json
omada restore before-changes.json

# anything not wrapped yet
omada raw GET /eaps/A8-42-A1-FD-8E-B0
```

Every read command accepts `--json`. Global flags (`--json`, `--dry-run`,
`--profile`, `--no-verify`, `-v`) work before *or* after the subcommand.

## Encoding notes (reverse-engineered)

The internal API doesn't take channel numbers or human units. Verified
empirically:

| setting | encoding |
| --- | --- |
| 5 GHz `channel` | **1-based index** into the region channel list (36→`"1"`, 52→`"5"`, 100→`"9"`, 116→`"13"`, 132→`"17"`) |
| `channelWidth` | `"2"`=20 MHz, `"3"`=40, `"5"`=80, `"6"`=160 |
| `channelRange` | list of 20 MHz center freqs; **must match the width** or the AP widens on its own |
| TX power | set `txPowerLevel=1` (Custom) for a dBm value to be honored — presets `3`/`4` ignore it and force max |
| 2.4 GHz `channel` | literal number string (`"1"`/`"6"`/`"11"`, `"0"`=auto) |

`omada-cli` handles all of this for you; the table is here so the `raw` command
and future contributors aren't flying blind.

**DFS is per-AP-model.** Some models hold DFS channels (52/100/116…), others
silently revert to non-DFS. `omada dfs` shows you which APs are actually holding
their configured channel.

## MCP server

The package ships an [MCP](https://modelcontextprotocol.io) server so an MCP
client (Claude Desktop, Claude Code, …) can inspect and tune the network
conversationally — *"which APs are co-channel?"*, *"move the office AP to channel
100"*. It's pure stdlib (no `mcp` SDK needed) and speaks JSON-RPC over stdio.

```sh
omada-mcp            # provided after `pip install`; or: python -m omada_cli.mcp_server
```

**Read-only by default.** Write tools (channel/power/roaming/radio/features) are
only registered when `OMADA_MCP_ALLOW_WRITES=1` — because this hands an LLM a
wire to live infrastructure.

Register it with **Claude Code**:

```sh
claude mcp add omada -- omada-mcp
# allow tuning too:
claude mcp add omada --env OMADA_MCP_ALLOW_WRITES=1 -- omada-mcp
```

…or in **Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "omada": {
      "command": "omada-mcp",
      "env": { "OMADA_MCP_ALLOW_WRITES": "0" }
    }
  }
}
```

Tools: `omada_controller`, `omada_status`, `omada_clients`, `omada_doctor`,
`omada_dfs`, `omada_spectrum`, `omada_aps`, `omada_wlans`, `omada_roam_get`
(read) and — when writes are enabled — `omada_set_channel`, `omada_set_power`,
`omada_set_roam`, `omada_set_radio`, `omada_toggle_feature`.

## Safety & scope

- Writes are explicit subcommands; `--dry-run` shows the exact PATCH first.
- `locate` and `block` are marked **experimental** — the controller exposes the
  fields but the action endpoints aren't officially documented; field-test them.
- This is an unofficial tool. It is not affiliated with or endorsed by TP-Link.

## License

[MIT](LICENSE)
