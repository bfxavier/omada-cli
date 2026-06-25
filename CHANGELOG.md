# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] — 2026-06-25

First public release.

### Added
- CLI with ~31 commands: observability (`controller`, `status`, `aps`,
  `devices`, `clients`, `known`, `wlans`, `networks`, `alerts`, `spectrum`),
  diagnostics (`doctor`, `dfs`), radio writes (`channel`, `power`, `radio`,
  `roam`, `rename`), site features (`steering`, `fastroam`, `forcedisassoc`,
  `mesh`), `ssid`, snapshots (`backup`/`diff`/`restore`), and a `raw` escape hatch.
- `--dry-run`, `--json`, and `--profile` global flags (usable before or after
  the subcommand); multi-controller profiles; auto-discovery of controller id
  and site.
- MCP server (`omada-mcp`) — pure-stdlib stdio JSON-RPC; read-only by default,
  write tools gated behind `OMADA_MCP_ALLOW_WRITES=1`.
- Test suite (pytest) with ~94% coverage; ruff lint config.
- GitHub Actions CI (lint + test matrix, Python 3.9–3.13) and tag-driven release.

### Notes
- Uses the controller's internal web API; tested on OC200 / controller 5.14.x.
- `locate` and `block` are experimental (fields exposed, action endpoints
  undocumented).

[Unreleased]: https://github.com/bfxavier/omada-cli/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/bfxavier/omada-cli/releases/tag/v0.2.0
