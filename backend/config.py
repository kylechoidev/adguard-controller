#!/usr/bin/env python3
"""
AdGuard Controller: Configuration Manager
Handles hierarchical loading from:
1. Environment variables
2. User directory: ~/.config/adguard-controller/config.json
3. Local repo file: config.json
4. Hardcoded safe defaults
"""

import os
import json
import re
from pathlib import Path
from typing import Dict, Any

DEFAULT_CONFIG: Dict[str, Any] = {
    "doh_url": "",
    "local_stub": "127.0.2.1",
    "fallback_dns": "1.1.1.1",
    "port": 5350,
    "host": "127.0.0.1",
    "watchdog_interval_sec": 10,
    "watchdog_fail_threshold": 2
}

USER_CONFIG_DIR = Path.home() / ".config" / "adguard-controller"
USER_CONFIG_FILE = USER_CONFIG_DIR / "config.json"
LOCAL_CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"


def get_config_path() -> Path:
    """Return the active configuration file path."""
    if USER_CONFIG_FILE.exists():
        return USER_CONFIG_FILE
    if LOCAL_CONFIG_FILE.exists():
        return LOCAL_CONFIG_FILE
    return USER_CONFIG_FILE


def load_config() -> Dict[str, Any]:
    """Load configuration with fallback hierarchy."""
    cfg = DEFAULT_CONFIG.copy()

    # 1. Load from file
    path = get_config_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    cfg.update(data)
        except Exception as e:
            print(f"[CONFIG] Warning: Could not parse {path}: {e}")

    # 2. Environment variables override file
    if os.environ.get("ADGUARD_DOH_URL"):
        cfg["doh_url"] = os.environ["ADGUARD_DOH_URL"]
    if os.environ.get("ADGUARD_LOCAL_STUB"):
        cfg["local_stub"] = os.environ["ADGUARD_LOCAL_STUB"]
    if os.environ.get("ADGUARD_FALLBACK_DNS"):
        cfg["fallback_dns"] = os.environ["ADGUARD_FALLBACK_DNS"]
    if os.environ.get("ADGUARD_PORT"):
        try:
            cfg["port"] = int(os.environ["ADGUARD_PORT"])
        except ValueError:
            pass

    return cfg


def save_config(updates: Dict[str, Any]) -> bool:
    """Save updated configuration to ~/.config/adguard-controller/config.json."""
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    cfg.update(updates)

    try:
        with open(USER_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        print(f"[CONFIG] Error saving to {USER_CONFIG_FILE}: {e}")
        return False


def mask_doh_url(url: str) -> str:
    """Mask sensitive tokens in the DoH URL for safe display."""
    if not url:
        return "Not Configured"
    # Mask path token after last slash: e.g. /mk-sec-1234 -> /mk-sec-***
    match = re.search(r"(/dns-query/)([^/?#]+)", url)
    if match:
        prefix, token = match.group(1), match.group(2)
        if len(token) > 8:
            masked = token[:6] + "..." + token[-2:]
        else:
            masked = "***"
        return url.replace(match.group(0), f"{prefix}{masked}")
    return url


def get_public_config() -> Dict[str, Any]:
    """Return sanitized configuration safe for public API responses."""
    cfg = load_config()
    return {
        "doh_url_masked": mask_doh_url(cfg.get("doh_url", "")),
        "is_configured": bool(cfg.get("doh_url", "").strip()),
        "local_stub": cfg.get("local_stub", "127.0.2.1"),
        "fallback_dns": cfg.get("fallback_dns", "1.1.1.1"),
        "port": cfg.get("port", 5350),
        "host": cfg.get("host", "127.0.0.1"),
    }
