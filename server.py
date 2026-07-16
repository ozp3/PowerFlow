#!/usr/bin/env python3
"""
PowerFlow — Mac power monitoring (macmon + pmset + ioreg, no sudo)
Usage: python3 server.py  →  http://localhost:8765
"""

import http.server, json, os, re, subprocess, threading, time
from datetime import datetime

PORT = 8765
DIR  = os.path.dirname(os.path.abspath(__file__))

# ═══════════════════════════════════════════════════════════════
# MACMON — real-time SMC power (IOReport, no sudo)
# ═══════════════════════════════════════════════════════════════

_macmon = {"sys_power": 7.0, "cpu_usage": 20.0, "cpu_temp": 40.0}
_mm_lock = threading.Lock()


def _macmon_bin():
    """Find macmon binary: bundled > homebrew > PATH"""
    bundled = os.path.join(DIR, "macmon")
    if os.path.exists(bundled): return bundled
    return "macmon"  # fallback to PATH


def macmon_reader():
    """Read JSON from the macmon pipe (continuous, no sudo)"""
    global _macmon
    while True:
        try:
            proc = subprocess.Popen(
                [_macmon_bin(), "pipe", "-i", "200"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            )
        except OSError:
            time.sleep(10)  # macmon missing, keep using estimated values
            continue
        for line in proc.stdout:
            try:
                d = json.loads(line.strip())
                temp = d.get("temp") or {}
                with _mm_lock:
                    _macmon = {
                        "sys_power": d.get("sys_power", 7.0),
                        # macmon reports cpu_usage_pct as a 0-1 ratio → convert to percent
                        "cpu_usage": d.get("cpu_usage_pct", 0.2) * 100.0,
                        "cpu_temp": temp.get("cpu_temp_avg", 40.0),
                    }
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        time.sleep(2)  # macmon exited, restart it


def get_macmon():
    with _mm_lock:
        return dict(_macmon)


# ═══════════════════════════════════════════════════════════════
# BATTERY POLLING (pmset + ioreg)
# ═══════════════════════════════════════════════════════════════

def cmd(args, timeout=4):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except: return ""


def poll_battery():
    """pmset + ioreg → battery state"""
    d = {}
    ps   = cmd(["pmset","-g","ps"])
    batt = cmd(["pmset","-g","batt"])

    d["power_source"] = "AC" if "AC Power" in ps else ("Battery" if "Battery Power" in ps else "unknown")
    if m := re.search(r'(\d+)%', batt): d["battery_pct"] = int(m.group(1))

    chg = False
    if re.search(r'\bcharging\b', batt) and 'not charging' not in batt: chg = True
    if 'discharging' in batt: chg = False
    if 'not charging' in batt: chg = False
    d["battery_charging"] = chg

    io = cmd(["ioreg","-rn","AppleSmartBattery"])
    if m := re.search(r'"Voltage"\s*=\s*(\d+)', io):
        d["voltage_mv"] = int(m.group(1))
    if m := re.search(r'"InstantAmperage"\s*=\s*(\d+)', io):
        v = int(m.group(1)); d["current_ma"] = v - 2**64 if v > 2**63 else v
    if m := re.search(r'"Watts"\s*=\s*(\d+)', io):
        d["adapter_watts"] = int(m.group(1))

    return d


# ═══════════════════════════════════════════════════════════════
# MAIN POLL LOOP
# ═══════════════════════════════════════════════════════════════

_state = {}
_lock = threading.Lock()
_cached_system = 8.0
_last_src = "unknown"


def poll_loop():
    global _state, _cached_system, _last_src

    while True:
        try:
            bat = poll_battery()
            mm  = get_macmon()

            src   = bat.get("power_source", "unknown")
            pct   = bat.get("battery_pct", 0)
            chg   = bat.get("battery_charging", False)
            adapt = bat.get("adapter_watts", 0)
            v_mv  = bat.get("voltage_mv", 0)
            i_ma  = bat.get("current_ma", 0)

            # Battery power (SMC lags by ~10s)
            bat_w = round(abs((v_mv/1000) * (i_ma/1000)), 2) if v_mv else 0

            # Real-time system power from macmon (SMC PSTR key, instant)
            sys_raw = mm["sys_power"]
            cpu_pct = mm["cpu_usage"]

            # System power
            OVERHEAD = 5.0  # display+ssd+fan baseline
            if src == "Battery":
                if bat_w > 1.0:
                    _cached_system = bat_w
                system_power = _cached_system
                charge_power = 0.0
            else:
                # AC: macmon sys_power is the real value
                system_power = sys_raw

                # Transition: Battery→AC → SMC doesn't report charging yet, assume it
                if src != _last_src and _last_src == "Battery":
                    chg = True  # adapter just plugged in, assume charging

                if chg and i_ma > 100:
                    charge_power = bat_w
                elif chg:
                    charge_power = bat_w if bat_w > 0.5 else system_power * 0.3
                else:
                    charge_power = 0.0
                _cached_system = system_power

            adapter_total = system_power + charge_power
            if adapt > 0 and adapter_total > adapt:
                ratio = adapt / adapter_total
                system_power *= ratio
                charge_power *= ratio
                adapter_total = adapt

            # CPU/GPU split (proportional to cpu_usage %)
            total_w = system_power
            dynamic = max(0.5, total_w - OVERHEAD)
            if cpu_pct > 1:
                cpu_w = round(dynamic * min(0.85, cpu_pct / 100), 2)
                gpu_w = round(dynamic * 0.15, 2)
            else:
                cpu_w = round(dynamic * 0.5, 2)
                gpu_w = round(dynamic * 0.15, 2)
            other_w = round(max(0.3, total_w - cpu_w - gpu_w), 2)

            _last_src = src

            with _lock:
                _state = {
                    "ts": datetime.now().strftime("%H:%M:%S"),
                    "power_source": src,
                    "battery_pct": pct,
                    "battery_charging": chg,
                    "adapter_watts": adapt,
                    "total_w": round(adapter_total, 2),
                    "system_power_w": round(system_power, 2),
                    "battery_power_w": round(charge_power, 2),
                    "cpu_w": cpu_w,
                    "gpu_w": gpu_w,
                    "other_w": other_w,
                    "cpu_usage_pct": round(cpu_pct, 1),
                    "cpu_temp": round(mm["cpu_temp"], 1),
                    "stale": False,
                }

        except Exception:
            pass  # retry next cycle

        time.sleep(3)


# ═══════════════════════════════════════════════════════════════
# HTTP SERVER
# ═══════════════════════════════════════════════════════════════

STATIC = {
    "/d3.v7.min.js":      os.path.join(DIR, "d3.v7.min.js"),
    "/d3-sankey.min.js":  os.path.join(DIR, "d3-sankey.min.js"),
}
HTML_PATH = os.path.join(DIR, "index.html")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in STATIC:
            try:
                with open(STATIC[self.path], "rb") as f: body = f.read()
                self._ok("application/javascript", body)
                return
            except: pass

        if self.path == "/api/power":
            with _lock: data = dict(_state)
            body = json.dumps(data, ensure_ascii=False).encode()
            self._ok("application/json", body, cors=True)
            return

        try:
            with open(HTML_PATH, "rb") as f: body = f.read()
            self._ok("text/html; charset=utf-8", body)
        except:
            self.send_response(404); self.end_headers()

    def _ok(self, ct, body, cors=False):
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        if cors: self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a): pass


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print("⚡ PowerFlow Server (macmon + pmset + ioreg)")
    print(f"   http://localhost:{PORT}")

    # Start macmon reader
    threading.Thread(target=macmon_reader, daemon=True).start()
    time.sleep(0.5)  # wait for first reading

    # Start poller
    threading.Thread(target=poll_loop, daemon=True).start()
    time.sleep(1)

    mm = get_macmon()
    print(f"   macmon sys_power: {mm['sys_power']:.1f}W | cpu: {mm['cpu_usage']:.0f}% | temp: {mm['cpu_temp']:.0f}°C")

    httpd = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    print("   Press Ctrl+C to quit\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Stopped")


if __name__ == "__main__":
    main()
