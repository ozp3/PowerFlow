#!/usr/bin/env python3
"""
PowerFlow – standalone desktop app (pywebview window).
Reuses server.py's data pipeline but opens its own window instead of a browser.
Usage: python3 app.py
"""

import http.server
import threading

import webview

import server


def main():
    # Data collectors (macmon + pmset/ioreg)
    threading.Thread(target=server.macmon_reader, daemon=True).start()
    threading.Thread(target=server.poll_loop, daemon=True).start()

    # HTTP server: port 0 → picks a free port, no conflicts
    httpd = http.server.HTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"PowerFlow: http://127.0.0.1:{port}", flush=True)

    webview.create_window(
        title="PowerFlow",
        url=f"http://127.0.0.1:{port}",
        width=760, height=560,
        resizable=True, min_size=(520, 400),
    )
    webview.start(gui="cocoa")


if __name__ == "__main__":
    main()
