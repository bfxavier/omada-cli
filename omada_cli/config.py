"""Configuration loading + password resolution.

Config lives in ~/.config/omada/config.json and is merged over the built-in
defaults. Nothing secret is stored in the repo. The controller password is
resolved (in order) from: the OMADA_PASS env var, the macOS Keychain, or — only
if you explicitly opt in — a "password" field in the config file.
"""
import json
import os
import subprocess
import sys

CONFIG_DIR = os.path.expanduser("~/.config/omada")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
KEYCHAIN_SERVICE = "omada-cli"

DEFAULTS = {
    "base_url": "https://192.168.1.1",
    "username": "admin",
    "controller_id": None,      # auto-discovered from /api/info when null
    "site": "Default",          # site name or 24-hex id
    "verify_tls": False,        # Omada ships a self-signed cert by default
    "password_source": "keychain",  # keychain | env | config
    "password": None,           # only read when password_source == "config"
    "aps": {},                  # optional friendly-name -> MAC map
}


class ConfigError(Exception):
    pass


def load_config(profile=None, overrides=None):
    """Return the merged config dict. Profiles let one file hold several
    controllers under a top-level "profiles" key."""
    cfg = dict(DEFAULTS)
    raw = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            raw = json.load(f)
    profiles = raw.get("profiles")
    if profiles:
        name = profile or raw.get("default_profile") or next(iter(profiles))
        if name not in profiles:
            raise ConfigError(f"profile '{name}' not found in {CONFIG_PATH}")
        cfg.update({k: v for k, v in raw.items()
                    if k not in ("profiles", "default_profile")})
        cfg.update(profiles[name])
        cfg["_profile"] = name
    else:
        cfg.update(raw)

    # environment overrides (handy for CI / scripts)
    env_map = {"OMADA_BASE_URL": "base_url", "OMADA_USER": "username",
               "OMADA_CONTROLLER_ID": "controller_id", "OMADA_SITE": "site"}
    for env, key in env_map.items():
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    if overrides:
        cfg.update({k: v for k, v in overrides.items() if v is not None})
    return cfg


def resolve_password(cfg):
    if os.environ.get("OMADA_PASS"):
        return os.environ["OMADA_PASS"]
    src = cfg.get("password_source", "keychain")
    if src == "config":
        if not cfg.get("password"):
            raise ConfigError("password_source=config but no 'password' set")
        return cfg["password"]
    if src == "env":
        raise ConfigError("password_source=env but OMADA_PASS is not set")
    # keychain (macOS)
    pw = keychain_get(cfg["username"])
    if pw is None:
        raise ConfigError(
            "no password in Keychain. Run 'omada setup-pass', or set OMADA_PASS, "
            "or set password_source in the config.")
    return pw


def keychain_get(account):
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
             "-a", account, "-w"],
            capture_output=True, text=True, check=True)
        return out.stdout.rstrip("\n")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def keychain_set(account, password):
    subprocess.run(
        ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE,
         "-a", account, "-w", password],
        check=True)


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    public = {k: v for k, v in cfg.items()
              if k in DEFAULTS and k != "password"}
    with open(CONFIG_PATH, "w") as f:
        json.dump(public, f, indent=2)
    os.chmod(CONFIG_PATH, 0o600)
    return CONFIG_PATH
