# ⚡ PowerFlow

Real-time power flow visualization for Mac. Shows adapter → battery → system → CPU/GPU power distribution as a Sankey diagram. No `sudo` required.

![PowerFlow](PowerFlow.png)

## Installation

Download `PowerFlow.dmg` from the [Releases](https://github.com/ozp3/PowerFlow/releases) page, open it, and drag the app into your **Applications** folder.

> Requirements: macOS 12+, [Python 3](https://www.python.org/downloads/) and `pip3 install pywebview`

## Running from source

```bash
# Standalone windowed app
python3 app.py

# or in the browser (http://localhost:8765)
python3 server.py
```

## Data sources

- **[macmon](https://github.com/vladkens/macmon)** – real-time SMC system power, CPU usage and temperature (no sudo)
- **pmset** – power source (AC/battery), charging state
- **ioreg** – battery voltage/current, adapter wattage

## Building

```bash
python3 build_app.py   # dist/PowerFlow.app
python3 build_dmg.py   # dist/PowerFlow.dmg
```
