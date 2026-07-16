#!/usr/bin/env python3
"""
DMG builder – PowerFlow
Output: dist/PowerFlow.dmg
"""

import os, shutil, subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "PowerFlow"
APP_PATH = os.path.join(SCRIPT_DIR, "dist", f"{APP_NAME}.app")
DMG_PATH = os.path.join(SCRIPT_DIR, "dist", f"{APP_NAME}.dmg")
TMP_DMG  = os.path.join(SCRIPT_DIR, "dist", f"{APP_NAME}_tmp.dmg")
STAGING  = os.path.join(SCRIPT_DIR, "dist", "dmg_staging")

# 1. Clean
# Detach any stale PowerFlow volume (e.g. the user left an old DMG mounted)
if os.path.ismount(f"/Volumes/{APP_NAME}"):
    subprocess.run(["diskutil", "unmount", "force", f"/Volumes/{APP_NAME}"],
                   capture_output=True)

for p in [DMG_PATH, TMP_DMG, STAGING]:
    if os.path.exists(p):
        if os.path.isdir(p): shutil.rmtree(p)
        else: os.remove(p)

if not os.path.exists(APP_PATH):
    print("ERROR: Run build_app.py first!")
    exit(1)

# 2. Staging
os.makedirs(STAGING)
shutil.copytree(APP_PATH, os.path.join(STAGING, f"{APP_NAME}.app"), symlinks=True)
os.symlink("/Applications", os.path.join(STAGING, "Applications"))
print("Staging ready")

# 3. Create DMG
subprocess.run([
    "hdiutil", "create", "-srcfolder", STAGING,
    "-volname", APP_NAME,
    "-fs", "HFS+",
    "-format", "UDRW",
    "-size", "150m",
    TMP_DMG
], check=True, capture_output=True)

# 4. Mount & style
mount = f"/Volumes/{APP_NAME}"
att = subprocess.run(["hdiutil", "attach", TMP_DMG, "-readwrite", "-noverify", "-noautoopen",
                      "-mountpoint", mount], check=True, capture_output=True, text=True)
dev = att.stdout.split()[0]  # /dev/diskN — device node used for detaching

# Finder window settings via AppleScript (no background image, clean look)
scpt = f'''
tell application "Finder"
    tell disk "{APP_NAME}"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set the bounds of container window to {{400, 200, 1040, 620}}
        set viewOptions to the icon view options of container window
        set arrangement of viewOptions to not arranged
        set icon size of viewOptions to 96
        set text size of viewOptions to 13
        set position of item "{APP_NAME}.app" of container window to {{220, 200}}
        set position of item "Applications" of container window to {{420, 200}}
        close
        open
        update without registering applications
        delay 1
    end tell
end tell
'''

sp = os.path.join(SCRIPT_DIR, "dist", "_dmg.scpt")
with open(sp, "w") as f: f.write(scpt)
subprocess.run(["osascript", sp], check=False, capture_output=True)
os.remove(sp)

# 5. Detach & convert (Finder can keep the disk busy for a while → retry)
import time
for attempt in range(10):
    r = subprocess.run(["hdiutil", "detach", dev], capture_output=True)
    if r.returncode == 0:
        break
    time.sleep(1)
else:
    subprocess.run(["diskutil", "eject", "force", dev], check=True, capture_output=True)

subprocess.run(["hdiutil", "convert", TMP_DMG, "-format", "UDZO",
                "-imagekey", "zlib-level=9", "-o", DMG_PATH], check=True, capture_output=True)

# 6. Cleanup
os.remove(TMP_DMG)
shutil.rmtree(STAGING)

size_mb = os.path.getsize(DMG_PATH) / (1024 * 1024)
print(f"Done: {DMG_PATH} ({size_mb:.1f} MB)")
