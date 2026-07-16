#!/usr/bin/env python3
"""
Mac Power Sankey – real-time power flow visualization.

Usage:
    python3 power_server.py
    then open in a browser: http://localhost:8765

    or open index.html directly in a browser:
    open index.html   (but it won't work without the API)

Data sources:
    pmset           – power source (AC/battery), charge percentage
    system_profiler – adapter wattage
    ioreg           – battery voltage, current, adapter details
    powermetrics    – CPU/GPU/ANE power breakdown (requires sudo)
"""

import http.server
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime

PORT = 8765

# ─── Global state ─────────────────────────────────────────────────
_lock = threading.Lock()
_latest: dict = {}


def run(cmd: list[str], timeout: float = 5) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""


def sudo_run(cmd: list[str], timeout: float = 6) -> str:
    try:
        r = subprocess.run(["sudo", "-n"] + cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""


def parse_battery_ioreg() -> dict:
    out = run(["ioreg", "-rn", "AppleSmartBattery"], timeout=4)
    data = {}
    for line in out.splitlines():
        if m := re.search(r'"Voltage"\s*=\s*(\d+)', line):
            data["voltage_mv"] = int(m.group(1))
        if m := re.search(r'"InstantAmperage"\s*=\s*(\d+)', line):
            raw = int(m.group(1))
            if raw > 2**63:
                raw -= 2**64
            data["current_ma"] = raw
        elif m := re.search(r'"Amperage"\s*=\s*(\d+)', line):
            raw = int(m.group(1))
            if raw > 2**63:
                raw -= 2**64
            if "current_ma" not in data:
                data["current_ma"] = raw
        if m := re.search(r'"AdapterVoltage"\s*=\s*(\d+)', line):
            data["adapter_voltage_mv"] = int(m.group(1))
        if m := re.search(r'"Current"\s*=\s*(\d+)', line):
            data["adapter_current_ma"] = int(m.group(1))
        if m := re.search(r'"Watts"\s*=\s*(\d+)', line):
            data["adapter_watts"] = int(m.group(1))
    return data


def parse_powermetrics() -> dict:
    out = sudo_run(
        ["powermetrics", "--samplers", "cpu_power,gpu_power,ane_power",
         "-n", "1", "-i", "200", "-o", "/dev/stdout"],
        timeout=8
    )
    data = {}
    for line in out.splitlines():
        for key in ["CPU Power", "GPU Power", "ANE Power"]:
            if m := re.search(key + r':\s*(\d+)\s*mW', line):
                data[key.lower().replace(" ", "_") + "_mw"] = int(m.group(1))
    return data


def poll() -> dict:
    result = {
        "ts": datetime.now().strftime("%H:%M:%S"),
        "power_source": "unknown",
        "battery_pct": 0,
        "battery_charging": False,
        "battery_voltage_mv": 0,
        "battery_current_ma": 0,
        "battery_power_w": 0.0,
        "adapter_watts": 0,
        "adapter_voltage_mv": 0,
        "adapter_current_max_ma": 0,
        "cpu_power_w": 0.0,
        "gpu_power_w": 0.0,
        "ane_power_w": 0.0,
        "display_power_w": 0.0,
        "other_power_w": 0.0,
        "heat_loss_w": 0.0,
        "total_power_w": 0.0,
        "has_detailed": False,
        "error": None,
    }

    # 1. pmset
    ps_out = run(["pmset", "-g", "ps"], timeout=3)
    batt_out = run(["pmset", "-g", "batt"], timeout=3)

    if "AC Power" in ps_out:
        result["power_source"] = "AC"
    elif "Battery Power" in ps_out:
        result["power_source"] = "Battery"

    if m := re.search(r'(\d+)%', batt_out):
        result["battery_pct"] = int(m.group(1))

    # Charging: "not charging" != charging
    if re.search(r'\bcharging\b', batt_out) and 'not charging' not in batt_out:
        result["battery_charging"] = True
    if re.search(r'\bdischarging\b', batt_out):
        result["battery_charging"] = False
    if 'not charging' in batt_out:
        result["battery_charging"] = False

    # 2. system_profiler
    sp_out = run(["system_profiler", "SPPowerDataType"], timeout=5)
    if m := re.search(r'Wattage \(W\):\s*(\d+)', sp_out):
        result["adapter_watts"] = int(m.group(1))
    if "Charging: Yes" in sp_out:
        result["battery_charging"] = True

    # 3. ioreg
    io = parse_battery_ioreg()
    if v := io.get("voltage_mv"):
        result["battery_voltage_mv"] = v
    if c := io.get("current_ma"):
        result["battery_current_ma"] = c
    if v := io.get("adapter_voltage_mv"):
        result["adapter_voltage_mv"] = v
    if c := io.get("adapter_current_ma"):
        result["adapter_current_max_ma"] = c
    if w := io.get("adapter_watts"):
        result["adapter_watts"] = w

    # Battery power: V * I
    bv = result["battery_voltage_mv"] / 1000.0
    bi = result["battery_current_ma"] / 1000.0
    result["battery_power_w"] = round(abs(bv * bi), 2)

    # 4. powermetrics (optional, needs sudo)
    pm = parse_powermetrics()
    cpu_mw = pm.get("cpu_power_mw", None)
    if cpu_mw is not None:
        result["cpu_power_w"] = round(cpu_mw / 1000.0, 2)
        result["gpu_power_w"] = round(pm.get("gpu_power_mw", 0) / 1000.0, 2)
        result["ane_power_w"] = round(pm.get("ane_power_mw", 0) / 1000.0, 2)
        result["has_detailed"] = True

    # 5. Estimate total system power
    soc = result["cpu_power_w"] + result["gpu_power_w"] + result["ane_power_w"]
    if soc < 0.1:
        soc = 2.5  # minimum SoC idle draw

    display_est = 3.5
    other_est = 1.8
    heat_est = 0.5

    if result["power_source"] == "Battery":
        est_total = result["battery_power_w"] if result["battery_power_w"] > 1.0 else soc + display_est + other_est + heat_est
    else:
        est_total = soc + display_est + other_est + heat_est
        if result["battery_charging"] and result["battery_current_ma"] > 100:
            est_total += result["battery_power_w"]

    result["total_power_w"] = round(est_total, 2)
    result["display_power_w"] = round(display_est, 2)
    result["other_power_w"] = round(other_est, 2)
    result["heat_loss_w"] = round(heat_est, 2)

    # Refine SoC values
    if result["has_detailed"]:
        if result["cpu_power_w"] < 0.01:
            result["cpu_power_w"] = round(soc * 0.55, 2)
        if result["gpu_power_w"] < 0.01:
            result["gpu_power_w"] = round(soc * 0.35, 2)
        if result["ane_power_w"] < 0.01:
            result["ane_power_w"] = round(soc * 0.10, 2)

    return result


def poll_loop():
    global _latest
    while True:
        try:
            data = poll()
            with _lock:
                _latest = data
        except Exception as e:
            with _lock:
                _latest["error"] = str(e)
        time.sleep(2)


# ─── HTTP Server ──────────────────────────────────────────────────
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/power":
            with _lock:
                data = dict(_latest)
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/" or self.path == "/index.html":
            try:
                with open(HTML_PATH, "rb") as f:
                    body = f.read()
            except FileNotFoundError:
                body = b"<h1>index.html not found</h1>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress logs


def main():
    print("=" * 56)
    print("  ⚡  Mac Power Sankey – Real-Time")
    print("=" * 56)
    print(f"  →  Browser:  http://localhost:{PORT}")
    print(f"  →  API:      http://localhost:{PORT}/api/power")
    print(f"  →  Quit:     Ctrl+C")
    print()

    # Initial poll
    print("  Taking first measurement...")
    try:
        initial = poll()
        with _lock:
            _latest.update(initial)
        print(f"  ✓ Adapter: {initial['adapter_watts']}W | "
              f"Battery: {initial['battery_pct']}% | "
              f"Source: {initial['power_source']} | "
              f"Charging: {'Yes' if initial['battery_charging'] else 'No'}")
        if initial["has_detailed"]:
            print(f"  ✓ CPU: {initial['cpu_power_w']}W | "
                  f"GPU: {initial['gpu_power_w']}W | "
                  f"ANE: {initial['ane_power_w']}W")
        else:
            print(f"  ⚠ No CPU/GPU breakdown (sudo powermetrics unavailable)")
            print(f"    For passwordless sudo:")
            print(f"    echo '$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/powermetrics' | sudo tee /etc/sudoers.d/powermetrics")
        print(f"  ✓ Estimated system power: {initial['total_power_w']}W")
    except Exception as e:
        print(f"  ⚠ First measurement failed: {e}")

    # Background poller
    threading.Thread(target=poll_loop, daemon=True).start()

    # HTTP server
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"\n  🌐 http://localhost:{PORT}")
    print("  (Press Ctrl+C to quit)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  👋 Stopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
