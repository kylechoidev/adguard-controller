# 🛡️ AdGuard DNS Controller for Linux

> **Gentle, autonomous laptop DNS switcher for remote AdGuard Home & Pi-hole instances.**  
> Features encrypted DoH, automatic health watchdog with atomic rollback, and mutual exclusivity with active VPN tunnels.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux%20(Mint%20%7C%20Ubuntu%20%7C%20Debian)-orange.svg)](#)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9%2B-brightgreen.svg)](#)

---

## 💡 The Problem It Solves

Self-hosting an **AdGuard Home** or **Pi-hole** resolver on a cloud VPS (e.g. Hetzner, DigitalOcean) is great for centralized ad and tracker blocking, but roaming on a laptop presents major operational headaches:

1. **Captive Portal Lockouts:** Hardcoding remote DNS breaks airport, hotel, and coffee shop Wi-Fi logins.
2. **DDoS Amplification Threat:** Exposing raw UDP port 53 to WAN invites abuse scans from national CERTs and server suspensions.
3. **Unauthenticated Open Resolvers:** Publicly reachable DNS allows anyone on the internet to freely piggyback on your bandwidth.
4. **VPN Route Collisions:** Turning on WireGuard, OpenVPN, or commercial VPNs (e.g. Surfshark) causes routing conflicts and DNS leaks.
5. **No Failover:** If the VPS drops or internet glitches, laptop DNS silently hangs indefinitely.

**AdGuard DNS Controller** solves this with a non-destructive, single-click toggle and an autonomous background watchdog.

---

## ✨ Features

- 🔒 **Encrypted DNS-over-HTTPS (DoH):** Uses tokenized endpoints (`https://adguard.example.com/dns-query/YOUR_TOKEN`) behind Nginx. Zero exposed UDP/53 or DoT/853 ports on WAN.
- 🐶 **Autonomous Safety Watchdog:** Probes resolver health every 10 seconds. If 2 consecutive failures occur, it triggers an atomic 3-stage rollback to standard DHCP and notifies via desktop alerts.
- 🔀 **VPN-Aware Mutual Exclusivity:** Detects active WireGuard, OpenVPN, or commercial VPN tunnels and automatically yields DNS control to prevent routing conflicts.
- 🖥️ **Dual Interface (GUI + CLI):**
  - **Modern Dark UI:** Frameless app-window mode via Chromium or standard browser on `http://127.0.0.1:5350`.
  - **CLI Tool:** Fast `adguard-dns {status|toggle|enable|disable|test}` commands suitable for keyboard shortcuts.
- ⚡ **Zero-Privilege Daemon:** The controller runs entirely as a user-level `systemd --user` service. System DNS modifications use native `resolvectl` policies without running web servers as root.

---

## 🏛️ Architecture

```mermaid
flowchart TD
    subgraph Laptop ["User Laptop (Linux Mint / Ubuntu / Debian)"]
        Apps["Browsers & Applications"]
        SR["systemd-resolved"]
        DP["dnscrypt-proxy (Local Stub: 127.0.2.1:53)"]
        Daemon["AdGuard Controller Daemon (127.0.0.1:5350)"]
        UI["Web GUI & CLI"]
        Watchdog["Autonomous Watchdog Thread"]

        UI -->|REST API| Daemon
        Watchdog -->|Health Probes| Daemon
        Apps --> SR
        SR -->|When Active| DP
        SR -->|When Inactive| DHCP["Standard Network DHCP"]
        Daemon -.->|resolvectl| SR
    end

    subgraph VPS ["Remote Cloud VPS"]
        Nginx["Nginx Reverse Proxy (:443 TLS 1.3)"]
        AGH["AdGuard Home (:8443)"]
        
        DP -->|RFC 8484 DoH / HTTPS| Nginx
        Nginx -->|Token Validated| AGH
        Nginx -->|Invalid / Scanner Probe| Reject["404 Not Found"]
```

---

## 🌐 Universal Resolver Compatibility

While designed with **AdGuard Home** in mind, the controller speaks standard **RFC 8484 DNS-over-HTTPS (DoH)**. Ad-blocking and tracking filters are evaluated server-side by whichever resolver you configure:

| Resolver Backend | Filtering Mechanism | Supported |
|---|---|:---:|
| **AdGuard Home** (Self-Hosted VPS) | Official **AdGuard DNS Filter** (178,000+ rules), parental controls, custom regex rules | ✅ Native |
| **Pi-hole** (Self-Hosted + DoH) | Gravity blocklists (StevenBlack, Firebog, etc.) | ✅ Yes |
| **NextDNS** (Cloud) | Cloud profiles with customizable blocklists & analytics | ✅ Yes |
| **Control D** | Multi-profile ad, tracker, & malware blocking | ✅ Yes |
| **Mullvad DNS** | Public ad-blocking & tracker-blocking DoH | ✅ Yes |
| **Quad9 / Cloudflare** | Threat intelligence & privacy-focused upstream | ✅ Yes |

---

## 🚀 Quick Start

### 1. Prerequisites
On Ubuntu, Debian, or Linux Mint:
```bash
sudo apt update
sudo apt install -y python3 curl dnscrypt-proxy
```

### 2. Installation
Clone the repository and run the installer:
```bash
git clone https://github.com/kylechoidev/adguard-controller.git
cd adguard-controller
./install.sh
```

The installer:
- Configures `~/.config/adguard-controller/config.json`
- Registers and starts the user systemd service (`adguard-controller.service`)
- Installs the CLI tool to `~/.local/bin/adguard-dns`
- Creates a desktop application launcher

---

## ⚙️ Configuration

Configuration is stored in `~/.config/adguard-controller/config.json`:

```json
{
  "doh_url": "https://adguard.example.com/dns-query/YOUR_SECRET_TOKEN",
  "local_stub": "127.0.2.1",
  "fallback_dns": "1.1.1.1",
  "port": 5350,
  "host": "127.0.0.1",
  "watchdog_interval_sec": 10,
  "watchdog_fail_threshold": 2
}
```

You can update the endpoint anytime:
- **Via GUI:** Click the **⚙️ Settings** icon in the top header.
- **Via CLI:** `adguard-dns config https://adguard.example.com/dns-query/YOUR_TOKEN`
- **Via JSON:** Edit `~/.config/adguard-controller/config.json` and restart with `systemctl --user restart adguard-controller`.

---

## 💻 CLI Usage

```bash
# Check current protection status and active network interface
adguard-dns status

# Toggle between VPS AdGuard and standard DHCP
adguard-dns toggle

# Explicitly enable or disable
adguard-dns enable
adguard-dns disable

# Run an isolated out-of-band DoH probe test
adguard-dns test

# Force emergency recovery to standard network settings
adguard-dns reset
```

---

## 🔒 Server-Side Hardening (Nginx + AdGuard Home)

To achieve the scanner-proof token routing on your VPS, configure Nginx to reject unauthenticated requests and proxy valid tokens to internal AdGuard Home:

```nginx
server {
    listen 443 ssl http2;
    server_name adguard.example.com;

    ssl_certificate     /etc/letsencrypt/live/adguard.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/adguard.example.com/privkey.pem;

    # 1. Block bare probe attempts from scanners
    location = /dns-query {
        return 404;
    }

    # 2. Allow only authorized secret client token(s)
    location ~ ^/dns-query/(mk-sec-[a-zA-Z0-9_-]+)$ {
        proxy_pass https://127.0.0.1:8443;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_ssl_verify off;
        proxy_http_version 1.1;
    }

    # 3. Block any other subpath
    location /dns-query/ {
        return 404;
    }
}
```

Ensure port 53 UDP/TCP is blocked in UFW on WAN (`eth0`).

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for details.
