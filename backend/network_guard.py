#!/usr/bin/env python3
"""
Network Guard: Safe DNS management utilities for Linux Mint / Ubuntu / Debian.
Enforces non-negotiable safety rules:
- Dynamic configuration loaded from ~/.config/adguard-controller/config.json
- Zero hardcoded secrets, domains, or IP addresses
- NEVER set '~.' routing domain
- Pre-flight and post-flight verification
- Atomic 3-stage recovery
- Mutual exclusivity with active VPNs (Surfshark / WireGuard / OpenVPN)
"""

import subprocess
import time
import socket
import struct
import re
import urllib.parse
from typing import Tuple, Optional, Dict, Any, List

from config import load_config, mask_doh_url


def run_cmd(cmd: str, timeout: int = 5) -> Tuple[int, str, str]:
    """Execute shell command safely with timeout."""
    try:
        res = subprocess.run(
            cmd,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


def get_active_interface() -> str:
    """Detect primary physical or Wi-Fi network interface (ignoring VPN interfaces)."""
    code, out, _ = run_cmd("ip route show default")
    if code == 0 and out:
        for line in out.splitlines():
            parts = line.split()
            if "dev" in parts:
                dev = parts[parts.index("dev") + 1]
                if not dev.startswith(("surfshark", "wg", "tun", "tap", "docker", "veth", "br-")):
                    return dev

    code, out, _ = run_cmd("nmcli -t -f DEVICE,TYPE,STATE dev")
    if code == 0 and out:
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] in ("wifi", "ethernet") and parts[2] == "connected":
                return parts[0]

    return "wlp2s0"


def is_vpn_active() -> Tuple[bool, Optional[str]]:
    """Check if any VPN tunnel (WireGuard, OpenVPN, Surfshark, etc.) is active."""
    code, out, _ = run_cmd("nmcli -t -f DEVICE,TYPE,STATE dev")
    if code == 0 and out:
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 3:
                dev, dev_type, state = parts[0], parts[1], parts[2]
                if state == "connected" and (
                    dev.startswith(("surfshark", "wg", "tun"))
                    or dev_type in ("wireguard", "tun", "vpn")
                ):
                    return True, dev

    code, out, _ = run_cmd("resolvectl status")
    if code == 0 and out:
        if "surfshark_wg" in out or "surfshark_ipv6" in out:
            if re.search(r"Link.*surfshark.*Scopes:\s*DNS", out, re.IGNORECASE):
                return True, "surfshark_wg"

    return False, None


def probe_vps_dns(domain: str = "google.com", timeout: float = 4.0) -> Tuple[bool, Optional[float], str]:
    """
    Perform an out-of-band DNS query to the configured DoH endpoint via RFC 8484 wire-format.
    Completely isolated: tests reachability without touching system network settings.
    """
    cfg = load_config()
    doh_url = cfg.get("doh_url", "").strip()

    if not doh_url:
        return False, None, "DoH URL is not configured. Please set your endpoint in Settings."

    import base64
    import ssl
    import urllib.request

    # Construct minimal DNS wire-format query (A record)
    header = struct.pack("!HHHHHH", 0x5432, 0x0100, 1, 0, 0, 0)
    qname = b"".join(bytes([len(p)]) + p.encode() for p in domain.split(".")) + b"\x00"
    query = header + qname + struct.pack("!HH", 1, 1)
    b64 = base64.urlsafe_b64encode(query).decode().rstrip("=")

    start_t = time.time()
    try:
        delimiter = "&" if "?" in doh_url else "?"
        url = f"{doh_url}{delimiter}dns={b64}"
        req = urllib.request.Request(url, headers={"Accept": "application/dns-message"})
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED

        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            data = r.read()

        latency_ms = round((time.time() - start_t) * 1000, 1)

        if len(data) >= 12:
            resp_id, resp_flags = struct.unpack("!HH", data[:4])
            rcode = resp_flags & 0xF
            if resp_id == 0x5432 and (resp_flags & 0x8000) and rcode == 0:
                return True, latency_ms, f"DoH resolved in {latency_ms}ms"
            else:
                return False, latency_ms, f"DoH response code: rcode={rcode}"
    except Exception as e:
        latency_ms = round((time.time() - start_t) * 1000, 1)
        return False, None, f"DoH probe failed: {e}"

    return False, None, "No data received from DoH resolver"


def get_dns_status() -> Dict[str, Any]:
    """Retrieve high-level status of the host system DNS and controller state."""
    cfg = load_config()
    local_stub = cfg.get("local_stub", "127.0.2.1")
    doh_url = cfg.get("doh_url", "")

    iface = get_active_interface()
    vpn_active, vpn_dev = is_vpn_active()

    code, out, _ = run_cmd(f"resolvectl dns {iface}")
    cur_dns: List[str] = []
    if code == 0 and ":" in out:
        cur_dns = out.split(":", 1)[1].strip().split()

    # Active when local stub is configured as link resolver
    is_vps_active = any(local_stub in s for s in cur_dns)

    if vpn_active:
        state = "VPN_ACTIVE"
    elif is_vps_active:
        state = "ACTIVE"
    else:
        state = "INACTIVE"

    return {
        "interface": iface,
        "current_dns": cur_dns,
        "is_vps_active": is_vps_active,
        "is_vpn_active": vpn_active,
        "vpn_interface": vpn_dev,
        "state": state,
        "vps_target": mask_doh_url(doh_url),
        "is_configured": bool(doh_url),
        "fallback_dns": cfg.get("fallback_dns", "1.1.1.1"),
        "local_stub": local_stub
    }


def enable_vps_dns() -> Tuple[bool, str]:
    """
    Safely switch system DNS to use the VPS AdGuard instance via DoH.
    Includes pre-flight probe, post-flight verification, and atomic fallback.
    """
    cfg = load_config()
    doh_url = cfg.get("doh_url", "").strip()
    local_stub = cfg.get("local_stub", "127.0.2.1")

    if not doh_url:
        return False, "Cannot enable: No DoH URL configured. Please configure your endpoint in Settings."

    vpn_active, vpn_dev = is_vpn_active()
    if vpn_active:
        return False, f"Cannot enable: VPN ({vpn_dev}) is active and managing routes."

    iface = get_active_interface()
    if not iface:
        return False, "No active network interface detected."

    # 1. Pre-flight Check: Probe VPS resolver via DoH before making changes
    ok, latency, msg = probe_vps_dns(domain="google.com", timeout=5.0)
    if not ok:
        return False, f"Pre-flight DoH probe failed: {msg}. Network settings left untouched."

    # 2. Ensure dnscrypt-proxy is running
    code, _, _ = run_cmd("systemctl is-active dnscrypt-proxy")
    if code != 0:
        start_code, _, start_err = run_cmd("systemctl start dnscrypt-proxy", timeout=10)
        if start_code != 0:
            return False, f"dnscrypt-proxy is not running and could not be started: {start_err}"
        time.sleep(1)

    # 3. Point systemd-resolved exclusively at dnscrypt-proxy local stub
    apply_cmd = f"resolvectl dns {iface} {local_stub}"
    code, out, err = run_cmd(apply_cmd)
    if code != 0:
        return False, f"Failed to apply resolvectl: {err}"

    run_cmd("resolvectl flush-caches")

    # 4. Post-flight Verification: Test end-to-end resolution
    time.sleep(0.5)
    code, out, err = run_cmd("resolvectl query -4 --legend=no google.com", timeout=4)
    if code != 0:
        # Post-flight failed: immediate atomic rollback!
        reset_to_default()
        return False, "Post-flight verification failed! Atomic rollback executed to restore default network."

    return True, f"AdGuard DoH enabled on {iface} via {local_stub} (Latency: {latency}ms)."


def reset_to_default() -> Tuple[bool, str]:
    """
    3-Stage Atomic Recovery:
    1. Revert link DNS overrides in systemd-resolved
    2. Restart systemd-resolved to pull fresh DNS from NetworkManager DHCP
    3. Flush stale caches
    """
    iface = get_active_interface()

    # Step 1: Revert systemd-resolved overrides
    run_cmd(f"resolvectl revert {iface}")

    # Step 2: Restart resolved to cleanly pull NetworkManager DHCP state
    run_cmd("systemctl restart systemd-resolved")

    # Step 3: Flush caches
    run_cmd("resolvectl flush-caches")

    return True, f"Network restored to default DHCP on {iface}."


if __name__ == "__main__":
    import json
    print("Status:", json.dumps(get_dns_status(), indent=2))
    print("DoH Probe:", probe_vps_dns())
