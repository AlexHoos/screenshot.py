"""
Screenshot-Tool für FlightAware DLH722
- Einmal-Lauf:      python screenshot.py           (für Cronjob / GitHub Actions / Aufgabenplanung)
- Dauerschleife:    python screenshot.py --loop    (läuft lokal, alle 15 Minuten)
"""
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

URL = "https://de.flightaware.com/live/flight/DLH722"
OUT_DIR = os.environ.get("OUT_DIR", "screenshots")
INTERVALL_MIN = 15
TZ = ZoneInfo("Europe/Berlin")

COOKIE_BUTTONS = [
    "#onetrust-accept-btn-handler",
    "button:has-text('Alle akzeptieren')",
    "button:has-text('Akzeptieren')",
    "button:has-text('Accept')",
]


def screenshot(versuche: int = 3) -> str | None:
    os.makedirs(OUT_DIR, exist_ok=True)
    ts = datetime.now(TZ).strftime("%Y-%m-%d_%H-%M")
    pfad = os.path.join(OUT_DIR, f"DLH722_{ts}.png")

    for versuch in range(1, versuche + 1):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(
                    viewport={"width": 1280, "height": 1450},
                    device_scale_factor=2,
                    locale="de-DE",
                    timezone_id="Europe/Berlin",
                )
                page.goto(URL, wait_until="domcontentloaded", timeout=60_000)

                # Cookie-Banner wegklicken, falls vorhanden
                for sel in COOKIE_BUTTONS:
                    try:
                        page.click(sel, timeout=2_500)
                        break
                    except Exception:
                        pass

                page.wait_for_timeout(8_000)  # Karte und Live-Daten laden lassen
                page.evaluate("window.scrollTo(0, 110)")  # Navigationsleiste ausblenden
                page.wait_for_timeout(1_000)
                page.screenshot(path=pfad, full_page=False)
                browser.close()
            print(f"[{ts}] Gespeichert: {pfad}")
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
