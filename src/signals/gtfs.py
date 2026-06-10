"""Paradas de transporte público (GTFS) vía Mobility Database → POIs 'transporte'.

Flujo:
  1. Con MOBILITY_DB_REFRESH_TOKEN (.env) se pide un access token (válido 1h).
  2. Se listan los feeds GTFS de España filtrados por municipio.
  3. Se descarga el último dataset de cada feed (zip) y se extraen las paradas
     (stops.txt: stop_lat/stop_lon), deduplicadas por proximidad.
  4. Se guardan en data/transit_stops_{slug}.json — la agregación los recoge
     automáticamente como POIs de categoría 'transporte'.

Registro (gratuito): https://mobilitydatabase.org → cuenta → API → refresh token.

Uso:
    python -m src.signals.gtfs --city madrid
    python -m src.signals.gtfs            # las 10 Tier-1

NOTA: pendiente de primera ejecución real (requiere el refresh token del PO).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import h3

from src.signals.coverage_test import SPAIN_TIER1, get_json
from src.signals.venues import slug_of

API = "https://api.mobilitydatabase.org/v1"
OUT_DIR = Path(__file__).resolve().parents[2] / "data"

# nombre de municipio tal como suele figurar en el catálogo (es-ES oficial)
MUNICIPALITY_BY_SLUG = {
    "madrid": "Madrid", "barcelona": "Barcelona", "valencia": "Valencia",
    "sevilla": "Sevilla", "zaragoza": "Zaragoza", "malaga": "Málaga",
    "murcia": "Murcia", "bilbao": "Bilbao", "valladolid": "Valladolid",
    "alicante": "Alicante",
}


def load_refresh_token() -> str:
    import os
    tok = os.environ.get("MOBILITY_DB_REFRESH_TOKEN", "").strip()
    if tok:
        return tok
    env = Path(__file__).resolve().parents[2] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("MOBILITY_DB_REFRESH_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def get_access_token(refresh_token: str) -> str:
    req = urllib.request.Request(
        f"{API}/tokens",
        data=json.dumps({"refresh_token": refresh_token}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["access_token"]


def _get(url: str, token: str) -> dict | list:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def list_city_feeds(token: str, municipality: str) -> list[dict]:
    params = urllib.parse.urlencode({
        "country_code": "ES",
        "municipality": municipality,
        "limit": "50",
    })
    feeds = _get(f"{API}/gtfs_feeds?{params}", token)
    return feeds if isinstance(feeds, list) else []


def stops_from_feed(feed: dict) -> list[dict]:
    """Descarga el último dataset del feed y extrae stops.txt."""
    dataset = feed.get("latest_dataset") or {}
    url = dataset.get("hosted_url") or dataset.get("downloaded_at_url")
    if not url:
        return []
    with urllib.request.urlopen(url, timeout=120) as resp:
        blob = resp.read()
    stops = []
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        if "stops.txt" not in zf.namelist():
            return []
        with zf.open("stops.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                # location_type 1 = estación; 0/vacío = parada. Ambas valen.
                try:
                    lat, lon = float(row["stop_lat"]), float(row["stop_lon"])
                except (KeyError, TypeError, ValueError):
                    continue
                stops.append({
                    "name": (row.get("stop_name") or "").strip(),
                    "lat": lat,
                    "lng": lon,
                    "feed": feed.get("id"),
                })
    return stops


def dedupe_by_cell(stops: list[dict], res: int = 11) -> list[dict]:
    """Deduplica paradas casi idénticas (misma celda H3 res 11, ~25 m)."""
    seen, out = set(), []
    for s in stops:
        key = h3.latlng_to_cell(s["lat"], s["lng"], res)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Descarga paradas GTFS por ciudad.")
    parser.add_argument("--city", default=None, help="Slug (def: las 10 Tier-1).")
    args = parser.parse_args()

    refresh = load_refresh_token()
    if not refresh:
        print("❌ Falta MOBILITY_DB_REFRESH_TOKEN en .env.\n"
              "   Regístrate gratis en https://mobilitydatabase.org y copia el refresh token.",
              file=sys.stderr)
        return 1
    token = get_access_token(refresh)

    cities = SPAIN_TIER1 if not args.city else [c for c in SPAIN_TIER1 if slug_of(c) == args.city]
    if not cities:
        print(f"❌ Ciudad desconocida: {args.city}", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for city in cities:
        slug = slug_of(city)
        municipality = MUNICIPALITY_BY_SLUG.get(slug, city["name"])
        feeds = list_city_feeds(token, municipality)
        stops: list[dict] = []
        for feed in feeds:
            try:
                stops.extend(stops_from_feed(feed))
            except Exception as exc:  # noqa: BLE001 — un feed roto no tumba la ciudad
                print(f"  ⚠️ feed {feed.get('id')} falló: {exc}", file=sys.stderr)
            time.sleep(0.5)
        stops = dedupe_by_cell(stops)
        path = OUT_DIR / f"transit_stops_{slug}.json"
        path.write_text(json.dumps(stops, ensure_ascii=False))
        print(f"  {slug:<12} {len(feeds):>2} feeds · {len(stops):>5} paradas → {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
