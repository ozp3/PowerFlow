#!/usr/bin/env python3
"""
.app bundle builder – PowerFlow
Run:    python3 build_app.py
Output: dist/PowerFlow.app
"""

import os, shutil, stat

APP_NAME = "PowerFlow"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(SCRIPT_DIR, "dist", f"{APP_NAME}.app")
CONTENTS = os.path.join(APP_PATH, "Contents")
MACOS   = os.path.join(CONTENTS, "MacOS")
RESOURCES = os.path.join(CONTENTS, "Resources")

# 1. Clean and create directories
if os.path.exists(APP_PATH):
    shutil.rmtree(APP_PATH)

for d in [MACOS, RESOURCES]:
    os.makedirs(d)
    print(f"  ✓ {d}")

# 2. Copy resource files
# Bundle the macmon binary as well
macmon_src = "/opt/homebrew/bin/macmon"
macmon_dst = os.path.join(RESOURCES, "macmon")
if os.path.exists(macmon_src):
    shutil.copy2(macmon_src, macmon_dst)
    os.chmod(macmon_dst, 0o755)
    print(f"  ✓ macmon → Resources/")

for fname in ["app.py", "server.py", "index.html", "d3.v7.min.js", "d3-sankey.min.js"]:
    src = os.path.join(SCRIPT_DIR, fname)
    dst = os.path.join(RESOURCES, fname)
    shutil.copy2(src, dst)
    print(f"  ✓ {fname} → Resources/")

# 3. Create launcher script
LAUNCHER = os.path.join(MACOS, APP_NAME)
PYTHON = "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"

with open(LAUNCHER, "w") as f:
    f.write(f'''#!/bin/bash
# PowerFlow – standalone windowed app launcher

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RESOURCES="$APP_DIR/Resources"
cd "$RESOURCES"

# Find Python: framework install > PATH > system
PY="{PYTHON}"
if [ ! -x "$PY" ]; then PY="$(command -v python3 || echo /usr/bin/python3)"; fi

# exec: keep the same PID so macOS associates the window with this bundle
LOG="$HOME/Library/Logs/PowerFlow.log"
exec "$PY" "$RESOURCES/app.py" >>"$LOG" 2>&1
''')

os.chmod(LAUNCHER, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
print(f"  ✓ launcher → MacOS/")

# 4. Info.plist
PLIST = os.path.join(CONTENTS, "Info.plist")
with open(PLIST, "w") as f:
    f.write(f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>{APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>{APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>com.powerflow.app</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleExecutable</key>
    <string>{APP_NAME}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>LSBackgroundOnly</key>
    <false/>
    <key>LSUIElement</key>
    <false/>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>CFBundleIconFile</key>
    <string>icon.icns</string>
</dict>
</plist>''')
print(f"  ✓ Info.plist")

# 5. Copy icon (PowerFlow.icns)
icon_src = os.path.join(SCRIPT_DIR, "PowerFlow.icns")
if os.path.exists(icon_src):
    shutil.copy2(icon_src, os.path.join(RESOURCES, "icon.icns"))
    print(f"  ✓ icon.icns → Resources/")
else:
    print(f"  ⚠ PowerFlow.icns not found, skipping icon")

print(f"\n✅ {APP_PATH}")
print(f"   Double-click in Finder, drag to the Dock, or run")
print(f"   open '{APP_PATH}'")
