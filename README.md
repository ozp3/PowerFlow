<div align="center">

<img src="https://github.com/ozp3/PowerFlow/releases/download/v1.0.0/logo.png" width="140" alt="PowerFlow logo">

# PowerFlow

**See where every watt goes — live.**

Real-time power flow visualization for Apple Silicon Macs.<br>
Adapter → Battery → System → CPU/GPU, rendered as an animated Sankey diagram. No `sudo` required.

[![Release](https://img.shields.io/github/v/release/ozp3/PowerFlow?color=0071e3&label=release)](https://github.com/ozp3/PowerFlow/releases/latest)
[![Platform](https://img.shields.io/badge/platform-macOS%2012%2B-1d1d1f?logo=apple&logoColor=white)](https://github.com/ozp3/PowerFlow/releases/latest)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)

</div>

---

## ✨ Features

- ⚡ **Live Sankey diagram** — watch power flow from the adapter into the battery and system in real time
- 🔋 **Charging aware** — the layout adapts to AC, AC + charging, and on-battery states automatically
- 🧠 **Smart CPU/GPU split** — combines SMC system power with CPU usage to estimate the SoC's share
- 🔓 **No sudo, no kernel extensions** — reads everything through public interfaces
- 🪶 **Tiny** — a single Python file for data, a single HTML file for the UI

## 📦 Installation

1. Download **`PowerFlow.dmg`** from the [latest release](https://github.com/ozp3/PowerFlow/releases/latest)
2. Open it and drag **PowerFlow** into your **Applications** folder
3. Launch it — a standalone window opens with the live diagram

> **Requirements:** macOS 12+, [Python 3](https://www.python.org/downloads/) and `pip3 install pywebview`

## 🚀 Running from source

```bash
git clone https://github.com/ozp3/PowerFlow.git
cd PowerFlow

# Standalone windowed app
python3 app.py

# … or serve it to your browser at http://localhost:8765
python3 server.py
```

## 🔍 How it works

PowerFlow polls three no-sudo data sources every 3 seconds and merges them into a single power model:

| Source | Provides |
|---|---|
| [**macmon**](https://github.com/vladkens/macmon) | Real-time SMC system power, CPU usage, temperature |
| **pmset** | Power source (AC / battery), charge percentage, charging state |
| **ioreg** | Battery voltage & current, adapter wattage |

The battery's own telemetry (V × I) calibrates the total, while CPU usage proportionally splits the dynamic power between the SoC and everything else.

## 🛠 Building

```bash
python3 build_app.py   # → dist/PowerFlow.app
python3 build_dmg.py   # → dist/PowerFlow.dmg
```

## 🙏 Credits

Built with [d3-sankey](https://github.com/d3/d3-sankey) and [macmon](https://github.com/vladkens/macmon).
