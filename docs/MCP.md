# Using the MCP server

`omada-mcp` exposes the controller to any [MCP](https://modelcontextprotocol.io)
client (Claude Desktop, Claude Code, …) so you can inspect and tune the network
in plain language. It speaks newline-delimited JSON-RPC 2.0 over stdio and is
pure stdlib — no `mcp` SDK required.

## 1. Prerequisites

The MCP server authenticates **exactly like the CLI** — it reuses
`~/.config/omada/config.json` and the same password source. So set the CLI up
first and confirm it works:

```sh
omada setup        # writes config + stores the password in the Keychain
omada status       # confirm it connects
```

If `omada status` works, the MCP server will too. (The server runs as your user,
so it can read your config and Keychain entry.)

> Running headless / on Linux where the macOS Keychain isn't available? Provide
> the password via the `OMADA_PASS` environment variable in the MCP client's
> server config (see the `env` block below), or set `"password_source": "config"`.

## 2. Install

```sh
pip install .          # provides the `omada-mcp` command
# no install? use:  python -m omada_cli.mcp_server
```

## 3. Register it with a client

### Claude Code

```sh
claude mcp add omada -- omada-mcp                       # read-only
claude mcp add omada --env OMADA_MCP_ALLOW_WRITES=1 -- omada-mcp   # + tuning
claude mcp list                                         # verify it's registered
```

### Claude Desktop

Edit `claude_desktop_config.json` (Settings → Developer → Edit Config) and
restart the app:

```json
{
  "mcpServers": {
    "omada": {
      "command": "omada-mcp",
      "env": {
        "OMADA_MCP_ALLOW_WRITES": "0"
      }
    }
  }
}
```

If `omada-mcp` isn't on the app's PATH, use the module form instead:

```json
{
  "mcpServers": {
    "omada": {
      "command": "python3",
      "args": ["-m", "omada_cli.mcp_server"],
      "env": { "OMADA_PASS": "your-controller-password" }
    }
  }
}
```

### Any other MCP client

Point it at the command `omada-mcp` (stdio transport). That's the whole contract.

## 4. Enabling writes

Read tools are always available. The five **write** tools are only registered
when the server starts with `OMADA_MCP_ALLOW_WRITES=1` — set it in the `env`
block above. This is deliberate: it gates an LLM's ability to change live
infrastructure behind an explicit opt-in. Leave it off unless you want the
assistant to make changes.

## 5. Verify it's connected

In your client, ask the model to **list the omada tools** or just:

> Run omada_status and summarize the APs.

You should see a tool call to `omada_status` and a table of your APs back. If
writes are enabled, *"what omada tools can change settings?"* should list the
`omada_set_*` tools.

## 6. Example prompts

Read-only:

- *"Which of my APs are on the same channel?"* → `omada_doctor` / `omada_spectrum`
- *"Are any 5 GHz radios bouncing off their DFS channel?"* → `omada_dfs`
- *"List clients on 5 GHz sorted by signal."* → `omada_clients`
- *"How healthy is the network right now?"* → `omada_doctor`

With writes enabled:

- *"Move the office AP to channel 100 at 80 MHz."* → `omada_set_channel`
- *"Relax the roaming kick on all APs to -76 on 5 GHz and -82 on 2.4."* → `omada_set_roam`
- *"Turn the basement 5 GHz radio off."* → `omada_set_radio`
- *"Lower the living-room 5 GHz power to 17 dBm."* → `omada_set_power`

## 7. Tool reference

| Tool | Writes? | Arguments | Returns |
| --- | --- | --- | --- |
| `omada_controller` | no | — | controller info + network overview |
| `omada_status` | no | — | per-AP channel/width/airtime/clients |
| `omada_clients` | no | `band` (2.4/5/6), `ap` | active wireless clients |
| `omada_doctor` | no | — | health findings (severity/area/message) |
| `omada_dfs` | no | — | configured vs on-air 5 GHz + DFS state |
| `omada_spectrum` | no | — | channel occupancy + client histogram |
| `omada_aps` | no | — | AP inventory (model/fw/ip/load) |
| `omada_wlans` | no | — | WLAN groups + SSIDs |
| `omada_roam_get` | no | — | per-AP roaming-kick thresholds |
| `omada_set_channel` | **yes** | `ap`, `channel`, `width` | set 5 GHz channel/width |
| `omada_set_power` | **yes** | `ap`, `band`, `dbm` | set TX power |
| `omada_set_roam` | **yes** | `ap` (or `all`), `threshold2g`, `threshold5g`, `disable` | set/disable roaming kick |
| `omada_set_radio` | **yes** | `ap`, `band`, `state` | enable/disable a radio |
| `omada_toggle_feature` | **yes** | `feature` (steering/fastroam/forcedisassoc/mesh), `state` | toggle a site feature |

`ap` accepts a friendly name from your config's `aps` map or a MAC.

## 8. How it works / manual test

The server reads one JSON-RPC request per line on stdin and writes one response
per line on stdout. You can drive it by hand to confirm it runs:

```sh
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | omada-mcp
```

You should get an `initialize` result followed by the tool list.

## 9. Troubleshooting

- **No tools / server won't start** — confirm `omada status` works; the MCP
  server fails the same way the CLI does if config/credentials are missing.
- **Auth error at first tool call** — the password isn't reachable from the
  client's environment. Put `OMADA_PASS` in the server's `env` block, or ensure
  the client launches as the user whose Keychain holds the `omada-cli` entry.
- **Write tools missing** — set `OMADA_MCP_ALLOW_WRITES=1` in the `env` block and
  restart the client.
- **`omada-mcp: command not found`** — the client isn't using the Python env
  where you installed the package; use the `python3 -m omada_cli.mcp_server` form
  with an absolute interpreter path.
