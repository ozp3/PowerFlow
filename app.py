#!/usr/bin/env python3
"""
PowerFlow – bağımsız masaüstü uygulaması (pywebview penceresi).
server.py'nin veri altyapısını kullanır, tarayıcı yerine kendi penceresini açar.
Kullanım: python3 app.py
"""

import http.server
import threading

import webview

import server


def main():
    # Veri toplayıcılar (macmon + pmset/ioreg)
    threading.Thread(target=server.macmon_reader, daemon=True).start()
    threading.Thread(target=server.poll_loop, daemon=True).start()

    # HTTP sunucusu: port 0 → boş bir port seçilir, çakışma olmaz
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
