#!/usr/bin/env python3
"""
Mac Power Sankey Widget – desktop panel.
Usage: python3 widget.py
"""

import os, sys, json, time, threading, subprocess, re, http.server
from datetime import datetime
import webview

PORT = 8766
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ═══════════════ DATA ═══════════════

_lock = threading.Lock()
_latest: dict = {}
_powermetrics_cache = {"data": {}, "ts": 0}
_pm_lock = threading.Lock()

def run(cmd, timeout=4):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except: return ""

def sudo(cmd, timeout=4):
    try:
        return subprocess.run(["sudo","-n"]+cmd, capture_output=True, text=True, timeout=timeout).stdout
    except: return ""

def poll_fast():
    """Fast metrics: pmset, ioreg (~200ms)"""
    result = {}
    ps = run(["pmset","-g","ps"])
    batt = run(["pmset","-g","batt"])

    result["power_source"] = "AC" if "AC Power" in ps else ("Battery" if "Battery Power" in ps else "unknown")
    if m := re.search(r'(\d+)%', batt): result["battery_pct"] = int(m.group(1))

    charging = False
    if re.search(r'\bcharging\b', batt) and 'not charging' not in batt: charging = True
    if re.search(r'\bdischarging\b', batt): charging = False
    if 'not charging' in batt: charging = False
    result["battery_charging"] = charging

    # ioreg
    io = run(["ioreg","-rn","AppleSmartBattery"])
    for line in io.splitlines():
        if m := re.search(r'"Voltage"\s*=\s*(\d+)', line): result["voltage_mv"] = int(m.group(1))
        if m := re.search(r'"InstantAmperage"\s*=\s*(\d+)', line):
            v = int(m.group(1)); result["current_ma"] = v - 2**64 if v > 2**63 else v
        if m := re.search(r'"AdapterVoltage"\s*=\s*(\d+)', line): result["adapter_voltage_mv"] = int(m.group(1))
        if m := re.search(r'"Watts"\s*=\s*(\d+)', line): result["adapter_watts"] = int(m.group(1))
        if m := re.search(r'"Current"\s*=\s*(\d+)', line): result["adapter_current_ma"] = int(m.group(1))

    return result

def poll_powermetrics():
    """Cached powermetrics data (updated by a background thread)"""
    with _pm_lock:
        return dict(_powermetrics_cache["data"])

_cached_system_power = 8.0
_last_source = "unknown"
_transition_at = 0.0
_TRANSITION_GRACE = 8.0  # 8s tolerance for SMC lag

def build_result(fast, pm):
    global _cached_system_power, _last_source, _transition_at
    r = {
        "ts": datetime.now().strftime("%H:%M:%S"),
        "power_source": fast.get("power_source","unknown"),
        "battery_pct": fast.get("battery_pct",0),
        "battery_charging": fast.get("battery_charging",False),
        "battery_voltage_mv": fast.get("voltage_mv",0),
        "battery_current_ma": fast.get("current_ma",0),
        "adapter_watts": fast.get("adapter_watts",0),
        "adapter_voltage_mv": fast.get("adapter_voltage_mv",0),
        "adapter_current_max_ma": fast.get("adapter_current_ma",0),
        "cpu_power_w": 0, "gpu_power_w": 0, "ane_power_w": 0,
        "display_power_w": 0, "other_power_w": 0, "heat_loss_w": 0,
        "total_power_w": 0, "has_detailed": False, "error": None,
    }
    bv = r["battery_voltage_mv"]/1000.0
    bi = r["battery_current_ma"]/1000.0
    bat_power = round(abs(bv*bi),2)
    r["battery_power_w"] = bat_power

    # Transition detection: SMC lags ~10s, react immediately
    src = r["power_source"]
    now = time.time()
    if src != _last_source and _last_source != "unknown":
        _transition_at = now
    _last_source = src

    in_transition = (now - _transition_at) < _TRANSITION_GRACE

    # Adapter just plugged in → assume the battery is charging
    if in_transition and src == "AC":
        r["battery_charging"] = True
    # Adapter just unplugged → battery is discharging
    if in_transition and src == "Battery":
        r["battery_charging"] = False

    # Cancel the transition once fresh SMC data arrives
    if r["battery_current_ma"] > 200 and src == "AC":
        _transition_at = 0  # real charge current observed, transition over
    if r["battery_current_ma"] < -200 and src == "Battery":
        _transition_at = 0  # real discharge current observed

    cpu_mw = pm.get("cpu_power_mw")
    if cpu_mw is not None:
        r["cpu_power_w"] = round(cpu_mw/1000,2)
        r["gpu_power_w"] = round(pm.get("gpu_power_mw",0)/1000,2)
        r["ane_power_w"] = round(pm.get("ane_power_mw",0)/1000,2)
        r["has_detailed"] = True

    # SoC power (powermetrics, updated every 2s)
    soc_measured = r["cpu_power_w"] + r["gpu_power_w"] + r["ane_power_w"]

    # Fixed base draw: display ~3W, SSD/fan/WiFi ~3W, heat ~1W
    fixed_overhead = 7.0

    if soc_measured > 0.5:
        # powermetrics is working → fast updates
        r["cpu_power_w"] = max(r["cpu_power_w"], 0.1)
        r["gpu_power_w"] = max(r["gpu_power_w"], 0.1)
        estimated_total = soc_measured + fixed_overhead
    else:
        # no powermetrics → fixed estimate
        r["cpu_power_w"] = round(fixed_overhead * 0.4, 2)
        r["gpu_power_w"] = round(fixed_overhead * 0.2, 2)
        estimated_total = fixed_overhead + r["cpu_power_w"] + r["gpu_power_w"]

    # Battery telemetry (SMC, ~10s) → calibration
    if r["power_source"] == "Battery" and bat_power > 1.0:
        # Battery discharge is the real total, converge toward it slowly
        _cached_system_power = _cached_system_power * 0.7 + bat_power * 0.3
    elif r["power_source"] == "AC" and r["battery_charging"] and bi > 0.1:
        _cached_system_power = _cached_system_power * 0.7 + (estimated_total + bat_power) * 0.3
    else:
        # On adapter, not charging → converge toward estimated_total slowly
        _cached_system_power = _cached_system_power * 0.7 + estimated_total * 0.3

    total = round(_cached_system_power, 2)
    r["total_power_w"] = total
    r["display_power_w"] = 0
    r["heat_loss_w"] = 0

    # Other = total - CPU/GPU (exact balance)
    real_soc = r["cpu_power_w"] + r["gpu_power_w"] + r["ane_power_w"]
    r["other_power_w"] = round(max(0.5, total - real_soc), 2)

    return r

def poll_fast_loop():
    """Fast metrics: every 500ms"""
    global _latest
    while True:
        try:
            fast = poll_fast()
            pm = poll_powermetrics()
            data = build_result(fast, pm)
            with _lock: _latest = data
        except Exception as e:
            with _lock: _latest["error"] = str(e)
        time.sleep(0.5)


def poll_slow_loop():
    """powermetrics in the background, without blocking poll_fast_loop"""
    while True:
        try:
            data = {}
            out = sudo(["powermetrics","--samplers","cpu_power,gpu_power,ane_power","-n","1","-i","50","-o","/dev/stdout"], timeout=4)
            for line in out.splitlines():
                for k in ["CPU Power","GPU Power","ANE Power"]:
                    if m := re.search(k+r':\s*(\d+)\s*mW', line):
                        data[k.lower().replace(" ","_")+"_mw"] = int(m.group(1))
            with _pm_lock:
                _powermetrics_cache["data"] = data
                _powermetrics_cache["ts"] = time.time()
        except:
            pass
        time.sleep(2)

# ═══════════════ WIDGET HTML ═══════════════

WIDGET_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<script src="/d3.v7.min.js"></script>
<script src="/d3-sankey.min.js"></script>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', sans-serif;
    background: #ffffff; color: #1d1d1f;
    padding: 4px 12px 2px; overflow: hidden;
    display: flex; flex-direction: column; height: 100vh;
    -webkit-user-select: none; user-select: none;
  }
  .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 3px; }
  .title { font-size: 13px; font-weight: 700; color: #1d1d1f; letter-spacing: -0.3px; }
  .status { display: flex; align-items: center; gap: 6px; font-size: 9px; font-weight: 600; color: #007a3d; text-transform: uppercase; letter-spacing: 0.5px; background: #e8f8ed; padding: 3px 8px; border-radius: 10px; }
  .live-dot { width:5px; height:5px; border-radius:50%; background:#34c759; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.25} }
  .live-dot { animation: pulse 2s ease-in-out infinite; }
  .info-row { display: flex; align-items: center; gap: 5px; font-size: 10px; color: #86868b; margin-bottom: 2px; padding: 2px 8px; background: #f5f5f7; border-radius: 5px; }
  .info-row .icon { font-size: 11px; }
  #chart { width:100%; flex: 1; min-height: 280px; background: #f2f2f7; border-radius: 10px; }
  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 5px; flex-shrink: 0; }
  .st { background: #f9f9fb; border: 1px solid #e8e8ed; border-radius: 8px; padding: 5px 6px; text-align: center; }
  .st .v { font-size: 14px; font-weight: 700; color: #1d1d1f; }
  .st .l { font-size: 7px; color: #86868b; text-transform: uppercase; letter-spacing: 0.6px; }
  .st:nth-child(1) .v { color: #f5a623; }
  .st:nth-child(2) .v { color: #4a90d9; }
  .st:nth-child(3) .v { color: #7ed321; }
  .st:nth-child(4) .v { color: #8e8e93; }
</style>
</head>
<body>

<div class="header">
  <span class="title">⚡ PowerFlow</span>
  <span class="status"><span class="live-dot"></span>Live</span>
</div>

<div class="info-row">
  <span class="icon" id="srcIcon">🔌</span>
  <span id="srcText"></span>
  <span style="margin-left:auto;font-family:monospace;font-size:9px;opacity:0.5" id="clock"></span>
</div>

<div id="chart"></div>

<div class="stats" id="stats"></div>

<script>
(function() {
  'use strict';
  if (typeof d3 === 'undefined' || typeof d3.sankey === 'undefined') return;

  function buildGraph(data) {
    var nodes = [], links = [];
    function N(id, icon, lbl) { nodes.push({id:id, icon:icon, label:lbl}); }
    function L(src, tgt, val) { if (val >= 0.05) links.push({source:src, target:tgt, value:+val.toFixed(2)}); }

    var onAC = data.power_source === 'AC';
    var chg = data.battery_charging && onAC;
    var cpu = data.cpu_power_w || 1.5;
    var gpu = data.gpu_power_w || 0.7;
    var ane = data.ane_power_w || 0.2;
    var socTotal = cpu+gpu+ane;
    // Other = remainder (exact balance guarantee, no rounding error)
    var sysPower = data.total_power_w;
    if (data.battery_charging && data.power_source === 'AC') {
      sysPower = data.total_power_w - data.battery_power_w;
    }
    var otherPower = Math.max(0.5, +(sysPower - socTotal).toFixed(2));

    if (onAC) {
      N('adapter', '🔌', 'Adapter');
      N('system',  '💻', 'System');
      if (chg) {
        N('battery', '🔋', 'Battery');
        L('adapter','system', Math.max(2, sysPower));
        L('adapter','battery', data.battery_power_w);
      } else {
        L('adapter','system', data.total_power_w);
      }
    } else {
      N('battery', '🔋', 'Battery');
      N('system',  '💻', 'System');
      L('battery','system', data.total_power_w);
    }
    N('soc',     '⚙',  'CPU/GPU');
    N('other',   '⋯',  'Other');
    L('system','soc', socTotal);
    L('system','other', otherPower);
    return {nodes:nodes, links:links};
  }

  function render(data) {
    document.getElementById('srcIcon').textContent = data.power_source === 'AC' ? '🔌' : '🔋';
    document.getElementById('srcText').textContent = data.power_source === 'AC'
      ? 'Adapter · '+data.adapter_watts+'W · Battery '+data.battery_pct+'%'
      : 'On battery · '+data.battery_pct+'%';
    document.getElementById('clock').textContent = data.ts;

    var g = buildGraph(data);
    if (g.nodes.length === 0) return;

    var el = document.getElementById('chart');
    var W = el.clientWidth || 630;
    var H = el.clientHeight || 340;
    var margin = {top:4, right:12, bottom:4, left:12};

    el.innerHTML = '';

    var svg = d3.select('#chart').append('svg')
      .attr('viewBox','0 0 '+W+' '+H)
      .attr('preserveAspectRatio','xMidYMid meet')
      .style('width','100%').style('height','100%');

    var defs = svg.append('defs');

    // Drop shadow for white nodes
    var sh = defs.append('filter').attr('id','sh').attr('x','-10%').attr('y','-10%').attr('width','130%').attr('height','130%');
    sh.append('feDropShadow').attr('dx',0).attr('dy',1).attr('stdDeviation',2).attr('flood-color','#000').attr('flood-opacity',0.08);

    // Links — white/transparent, no gradients needed

    // Sankey layout
    var sankey = d3.sankey()
      .nodeId(function(d){return d.id;})
      .nodeWidth(26).nodePadding(5)
      .extent([[margin.left,margin.top],[W-margin.right,H-margin.bottom]]);

    var sk = sankey(g);

    // ── Links (white/transparent) ──
    var linkG = svg.append('g').attr('fill','none');

    linkG.selectAll('path').data(sk.links).join('path')
      .attr('d', d3.sankeyLinkHorizontal())
      .attr('stroke', '#d5d5dd')
      .attr('stroke-width', function(d){return Math.max(2.5, d.width);})
      .attr('stroke-linecap','butt')
      .attr('stroke-opacity', 0.7);

    // Link value labels
    linkG.selectAll('text').data(sk.links).join('text')
      .attr('x', function(d){return (d.source.x1 + d.target.x0)/2;})
      .attr('y', function(d){return (d.y0 + d.y1)/2 - 4;})
      .attr('text-anchor','middle')
      .attr('fill','#888')
      .style('font-size','10px').style('font-weight','600')
      .style('font-family','"SF Mono", Monaco, monospace')
      .text(function(d){return d.value.toFixed(1)+'W';});

    // ── White rounded nodes ──
    var ng = svg.append('g').selectAll('g').data(sk.nodes).join('g');

    // White rounded rect with shadow
    ng.append('rect')
      .attr('x', function(d){return d.x0;})
      .attr('y', function(d){return d.y0;})
      .attr('width', function(d){return d.x1-d.x0;})
      .attr('height', function(d){return Math.max(1,d.y1-d.y0);})
      .attr('rx', 6)
      .attr('fill','#fff')
      .attr('stroke','#e5e5ea')
      .attr('stroke-width',0.5)
      .attr('filter','url(#sh)');

    // Emoji icon in center of node
    ng.append('text')
      .attr('x', function(d){return (d.x0+d.x1)/2;})
      .attr('y', function(d){return (d.y0+d.y1)/2;})
      .attr('dy','0.35em')
      .attr('text-anchor','middle')
      .style('font-size','13px')
      .text(function(d){return d.icon||'';});

    // Label outside node
    ng.append('text')
      .attr('x', function(d){return d.x0<W/2 ? d.x1+10 : d.x0-10;})
      .attr('y', function(d){return (d.y0+d.y1)/2;})
      .attr('dy','0.35em')
      .attr('text-anchor', function(d){return d.x0<W/2?'start':'end';})
      .attr('fill','#333')
      .style('font-size','12px').style('font-weight','600')
      .text(function(d){return d.label;});

    // Stats cards
    var totalIn = d3.sum(sk.links.filter(function(l){
      return !sk.links.some(function(ll){return ll.target.id===l.source.id;});
    }),function(l){return l.value;});

    document.getElementById('stats').innerHTML = [
      {v:totalIn.toFixed(1)+'W', l:'Input'},
      {v:data.total_power_w.toFixed(1)+'W', l:'System'},
      {v:data.battery_pct+'%', l:'Battery'},
      {v:(data.cpu_power_w+data.gpu_power_w+data.ane_power_w).toFixed(1)+'W', l:'CPU/GPU'}
    ].map(function(s){return'<div class="st"><div class="v">'+s.v+'</div><div class="l">'+s.l+'</div></div>';}).join('');
  }

  function fetchData() {
    fetch('/api/power')
      .then(function(r){return r.json();})
      .then(function(d){try{render(d);}catch(e){}})
      .catch(function(){});
  }

  fetchData();
  setInterval(fetchData, 500);

  var rt;
  window.addEventListener('resize',function(){
    clearTimeout(rt);
    rt=setTimeout(function(){fetchData();},200);
  });
})();
</script>
</body>
</html>"""



# ═══════════════ HTTP SERVER ═══════════════

STATIC = {
    "/d3.v7.min.js": os.path.join(SCRIPT_DIR, "d3.v7.min.js"),
    "/d3-sankey.min.js": os.path.join(SCRIPT_DIR, "d3-sankey.min.js"),
}

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in STATIC:
            try:
                with open(STATIC[self.path],"rb") as f: body=f.read()
                self.send_response(200)
                self.send_header("Content-Type","application/javascript")
                self.send_header("Content-Length",str(len(body)))
                self.end_headers(); self.wfile.write(body)
                return
            except: pass

        if self.path == "/api/power":
            with _lock: data = dict(_latest)
            body = json.dumps(data,ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin","*")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers(); self.wfile.write(body)
            return

        body = WIDGET_HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def log_message(self,f,*a): pass

# ═══════════════ MAIN ═══════════════

def main():
    print("⚡ Mac Power Sankey Widget")
    # Initial data
    fast = poll_fast()
    pm = poll_powermetrics()
    data = build_result(fast, pm)
    with _lock: _latest.update(data)
    print(f"  ✓ Adapter: {data['adapter_watts']}W | Battery: {data['battery_pct']}%")

    # Start pollers (fast + slow parallel)
    threading.Thread(target=poll_fast_loop, daemon=True).start()
    threading.Thread(target=poll_slow_loop, daemon=True).start()
    # Start server
    threading.Thread(target=lambda: http.server.HTTPServer(("127.0.0.1",PORT), Handler).serve_forever(), daemon=True).start()
    time.sleep(0.5)

    # Screen position
    from AppKit import NSScreen
    sf = NSScreen.mainScreen().visibleFrame()
    ww, wh = 660, 420
    x, y = int(sf.size.width - ww - 24), int(sf.size.height - wh - 24)

    webview.create_window(
        title="Mac Power Sankey",
        url=f"http://127.0.0.1:{PORT}",
        width=ww, height=wh, x=x, y=y,
        frameless=False, on_top=False,
        resizable=True, min_size=(500,340),
    )
    webview.start(gui="cocoa", debug=False)

if __name__ == "__main__":
    main()
