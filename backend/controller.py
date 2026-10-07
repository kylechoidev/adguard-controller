#!/usr/bin/env python3
"""
AdGuard Controller Backend
Provides a lightweight, non-blocking ThreadingHTTPServer on 127.0.0.1:5350
with an autonomous background watchdog thread and REST API.
"""

import sys
import os
import json
import time
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import urllib.parse
import subprocess

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config, save_config, get_public_config
from network_guard import (
    get_dns_status,
    enable_vps_dns,
    reset_to_default,
    probe_vps_dns
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")

# Initial configuration load
cfg = load_config()
PORT = cfg.get("port", 5350)
HOST = cfg.get("host", "127.0.0.1")

# In-memory event log
recent_events = []


def log_event(msg: str, level: str = "info") -> None:
    entry = {
        "time": time.strftime("%H:%M:%S"),
        "msg": msg,
        "level": level
    }
    recent_events.insert(0, entry)
    if len(recent_events) > 35:
        recent_events.pop()
    print(f"[{entry['time']}] [{level.upper()}] {msg}")


log_event("AdGuard Controller backend starting up.")


# Autonomous Watchdog Thread
def watchdog_loop() -> None:
    fail_count = 0
    while True:
        try:
            current_cfg = load_config()
            interval = current_cfg.get("watchdog_interval_sec", 10)
            threshold = current_cfg.get("watchdog_fail_threshold", 2)
            time.sleep(interval)

            status = get_dns_status()

            # If VPN became active while VPS DNS was on, auto-revert to avoid routing collisions
            if status["is_vpn_active"] and status["is_vps_active"]:
                log_event("VPN activation detected while VPS DNS was active. Safely reverting.", "warning")
                reset_to_default()
                fail_count = 0
                continue

            # If VPS DNS is active, verify health
            if status["is_vps_active"]:
                ok, latency, msg = probe_vps_dns(domain="google.com", timeout=4.0)
                if not ok:
                    fail_count += 1
                    log_event(f"Watchdog probe failure ({fail_count}/{threshold}): {msg}", "warning")
                    if fail_count >= threshold:
                        log_event(f"Watchdog: {threshold} consecutive failures. Triggering automatic rollback!", "error")
                        reset_to_default()
                        subprocess.run([
                            "notify-send", "-a", "AdGuard Controller",
                            "AdGuard Watchdog ⚠️",
                            "VPS DNS was unresponsive. Automatically restored default network."
                        ], check=False)
                        fail_count = 0
                else:
                    if fail_count > 0:
                        log_event("Watchdog probe recovered.", "info")
                    fail_count = 0
            else:
                fail_count = 0
        except Exception as e:
            log_event(f"Watchdog exception: {e}", "error")


watchdog_thread = threading.Thread(target=watchdog_loop, daemon=True)
watchdog_thread.start()


class ControllerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def send_json(self, data, status_code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", f"http://{HOST}:{PORT}")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/status":
            st = get_dns_status()
            st["events"] = recent_events
            st["port"] = PORT
            self.send_json(st)
        elif parsed.path == "/api/config":
            self.send_json(get_public_config())
        elif parsed.path == "/" or not parsed.path.startswith("/api/"):
            super().do_GET()
        else:
            self.send_error(404, "Endpoint not found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else ""

        try:
            payload = json.loads(post_data) if post_data else {}
        except Exception:
            payload = {}

        if parsed.path == "/api/toggle":
            action = payload.get("action")
            status = get_dns_status()

            if status["is_vpn_active"]:
                self.send_json({"ok": False, "message": "Cannot toggle while VPN is active."}, 400)
                return

            if action == "enable" or (action is None and not status["is_vps_active"]):
                ok, msg = enable_vps_dns()
                log_event(msg, "info" if ok else "error")
                self.send_json({"ok": ok, "message": msg}, 200 if ok else 500)
            else:
                ok, msg = reset_to_default()
                log_event(msg, "info")
                self.send_json({"ok": ok, "message": msg}, 200)

        elif parsed.path == "/api/config":
            # Update configuration from UI
            doh_url = payload.get("doh_url")
            updates = {}
            if doh_url is not None:
                updates["doh_url"] = doh_url.strip()
            if updates:
                ok = save_config(updates)
                msg = "Configuration saved successfully." if ok else "Failed to save configuration."
                log_event(msg, "info" if ok else "error")
                self.send_json({"ok": ok, "message": msg, "config": get_public_config()})
            else:
                self.send_json({"ok": False, "message": "No valid configuration fields provided."}, 400)

        elif parsed.path == "/api/test":
            ok, latency, msg = probe_vps_dns(domain="google.com", timeout=4.0)
            log_event(f"Manual probe test: {msg}", "info" if ok else "warning")
            self.send_json({"ok": ok, "latency_ms": latency, "message": msg})

        elif parsed.path == "/api/reset":
            ok, msg = reset_to_default()
            log_event(f"Emergency reset invoked: {msg}", "warning")
            self.send_json({"ok": ok, "message": msg})

        else:
            self.send_error(404, "Endpoint not found")

    def log_message(self, format, *args):
        # Suppress routine static asset access logging from stdout
        if len(args) > 0 and "/api/" in args[0]:
            pass


def main():
    server = ThreadingHTTPServer((HOST, PORT), ControllerHandler)
    print(f"AdGuard Controller running at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down AdGuard Controller.")
        server.server_close()


if __name__ == "__main__":
    main()
