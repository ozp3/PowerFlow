# ⚡ PowerFlow

Mac için gerçek zamanlı güç akışı görselleştirmesi. Adaptör → batarya → sistem → CPU/GPU güç dağılımını Sankey diyagramı olarak gösterir. `sudo` gerektirmez.

![PowerFlow](PowerFlow.png)

## Kurulum

[Releases](https://github.com/ozp3/PowerFlow/releases) sayfasından `PowerFlow.dmg` dosyasını indir, aç ve uygulamayı **Applications** klasörüne sürükle.

> Gereksinimler: macOS 12+, [Python 3](https://www.python.org/downloads/) ve `pip3 install pywebview`

## Kaynaktan çalıştırma

```bash
# Bağımsız pencereli uygulama
python3 app.py

# veya tarayıcıda (http://localhost:8765)
python3 server.py
```

## Veri kaynakları

- **[macmon](https://github.com/vladkens/macmon)** – gerçek zamanlı SMC sistem gücü, CPU kullanımı ve sıcaklık (sudo'suz)
- **pmset** – güç kaynağı (AC/batarya), şarj durumu
- **ioreg** – batarya voltajı/akımı, adaptör gücü

## Derleme

```bash
python3 build_app.py   # dist/PowerFlow.app
python3 build_dmg.py   # dist/PowerFlow.dmg
```
