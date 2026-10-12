"""
Screenshot-Tool für FlightAware DLH722
Pro Lauf entstehen zwei Bilder im Ordner screenshots/:
  DLH722_<Zeit>.png        FlightAware-Seite (Status, Zeiten, Gesamtroute)
  DLH722_<Zeit>_karte.png  Detailkarte, zentriert auf die aktuelle Flugzeugposition
- Einmal-Lauf:      python screenshot.py
- Dauerschleife:    python screenshot.py --loop   (lokal, alle 15 Minuten)
"""
import json
import math
import os
import re
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

URL = "https://de.flightaware.com/live/flight/DLH722"
FLUG = "DLH722"
OUT_DIR = os.environ.get("OUT_DIR", "screenshots")
INTERVALL_MIN = 15
TZ = ZoneInfo("Europe/Berlin")

DETAIL_ZOOM = 5  # 4 = Großregion, 5 = Länder gut lesbar, 6 = Regionen/Städte

COOKIE_BUTTONS = [
    "#onetrust-accept-btn-handler",
    "button:has-text('Alle akzeptieren')",
    "button:has-text('Akzeptieren')",
    "button:has-text('Accept')",
]


# ---------- Flugdaten aus der FlightAware-Seite lesen ----------

def flugdaten_lesen(page):
    data = None
    try:
        data = page.evaluate("() => window.trackpollBootstrap || null")
    except Exception:
        pass
    if not data:
        m = re.search(r"trackpollBootstrap\s*=\s*(\{.*?\});\s*</script>", page.content(), re.S)
        if m:
            try:
                data = json.loads(m.group(1))
            except Exception:
                data = None
    if not data:
        return None

    kandidaten = []

    def suche(o):
        if isinstance(o, dict):
            t = o.get("track")
            if isinstance(t, list) and t and isinstance(t[0], dict) and "coord" in t[0]:
                kandidaten.append(o)
            for v in o.values():
                suche(v)
        elif isinstance(o, list):
            for v in o:
                suche(v)

    suche(data)
    if not kandidaten:
        return None
    flug = max(kandidaten, key=lambda f: len(f["track"]))

    punkte = []
    for p in flug["track"]:
        c = p.get("coord")
        if isinstance(c, list) and len(c) >= 2 and c[0] is not None and c[1] is not None:
            punkte.append([float(c[1]), float(c[0])])  # [lat, lon]
    if not punkte:
        return None

    def ort(key):
        c = (flug.get(key) or {}).get("coord")
        if isinstance(c, list) and len(c) >= 2:
            return [float(c[1]), float(c[0])]
        return None

    return {"track": punkte, "start": ort("origin"), "ziel": ort("destination")}


def kurs(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    x = math.sin(lon2 - lon1) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


# ---------- Eigene Detailkarte ----------

KARTE_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
 html,body,#map{margin:0;height:100%;width:100%;font-family:Arial,sans-serif}
 .info{position:absolute;top:16px;left:16px;z-index:1000;background:rgba(0,30,80,.88);color:#fff;
       padding:10px 16px;border-radius:6px;font-size:18px;font-weight:bold}
 .info span{display:block;font-size:13px;font-weight:normal;opacity:.85;margin-top:3px}
 .flieger{font-size:0}
</style></head><body>
<div id="map"></div>
<div class="info">__FLUG__<span>Position __ZEIT__</span></div>
<script>
 const D = __DATEN__;
 const pos = D.track[D.track.length - 1];
 const map = L.map('map', {zoomControl:false, attributionControl:true}).setView(pos, D.zoom);
 const tiles = L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
   {subdomains:'abcd', maxZoom:18, attribution:'© OpenStreetMap, © CARTO'}).addTo(map);
 tiles.on('load', () => { window.kartenFertig = true; });
 if (D.start && D.ziel) L.polyline([D.start, D.ziel], {color:'#666', weight:2, dashArray:'6 6'}).addTo(map);
 L.polyline(D.track, {color:'#d62828', weight:4}).addTo(map);
 [D.start, D.ziel].forEach(p => { if (p) L.circleMarker(p, {radius:6, color:'#003a8c', fillOpacity:1}).addTo(map); });
 const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="44" height="44" viewBox="0 0 24 24"
   style="transform:rotate(${D.kurs}deg);filter:drop-shadow(0 0 2px #fff)">
   <path fill="#003a8c" d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z"/></svg>`;
 L.marker(pos, {icon: L.divIcon({html:svg, className:'flieger', iconSize:[44,44], iconAnchor:[22,22]})}).addTo(map);
</script></body></html>"""


def karte_erstellen(browser, daten, pfad, zeit):
    tr = daten["track"]
    daten = dict(daten, zoom=DETAIL_ZOOM, kurs=kurs(tr[-2], tr[-1]) if len(tr) > 1 else 0)
    html = (KARTE_HTML.replace("__DATEN__", json.dumps(daten))
                      .replace("__FLUG__", FLUG).replace("__ZEIT__", zeit))
    page = browser.new_page(viewport={"width": 1200, "height": 900}, device_scale_factor=2)
    page.set_content(html, wait_until="load")
    try:
        page.wait_for_function("window.kartenFertig === true", timeout=20_000)
    except Exception:
        pass
    page.wait_for_timeout(1_500)
    page.screenshot(path=pfad)
    page.close()


# ---------- Hauptablauf ----------

def screenshot(versuche: int = 3) -> str | None:
    os.makedirs(OUT_DIR, exist_ok=True)
    jetzt = datetime.now(TZ)
    ts = jetzt.strftime("%Y-%m-%d_%H-%M")
    pfad = os.path.join(OUT_DIR, f"{FLUG}_{ts}.png")
    pfad_karte = os.path.join(OUT_DIR, f"{FLUG}_{ts}_karte.png")

    for versuch in range(1, versuche + 1):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(
                    viewport={"width": 1280, "height": 1600},
                    device_scale_factor=2,
                    locale="de-DE",
                    timezone_id="Europe/Berlin",
                )
                page.goto(URL, wait_until="domcontentloaded", timeout=60_000)

                for sel in COOKIE_BUTTONS:
                    try:
                        page.click(sel, timeout=2_500)
                        break
                    except Exception:
                        pass

                page.wait_for_timeout(8_000)
                page.evaluate("window.scrollTo(0, 130)")
                page.wait_for_timeout(1_000)
                page.screenshot(path=pfad, full_page=False)
                print(f"[{ts}] Gespeichert: {pfad}")

                daten = flugdaten_lesen(page)
                if daten:
                    karte_erstellen(browser, daten, pfad_karte, jetzt.strftime("%d.%m.%Y %H:%M"))
                    print(f"[{ts}] Gespeichert: {pfad_karte} (Position {daten['track'][-1]})")
                else:
                    print(f"[{ts}] Keine Positionsdaten (Flugzeug am Boden oder Seitenstruktur geändert)")

                browser.close()
            return pfad
        except Exception as e:
            print(f"[{ts}] Versuch {versuch}/{versuche} fehlgeschlagen: {e}")
            time.sleep(20)
    return None


if __name__ == "__main__":
    if "--loop" in sys.argv:
        while True:
            start = time.time()
            screenshot()
            time.sleep(max(0, INTERVALL_MIN * 60 - (time.time() - start)))
    else:
        sys.exit(0 if screenshot() else 1)
