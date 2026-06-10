"""Descarga de venues de Ticketmaster → data/venues_{slug}.json.

Los venues (teatros, estadios, salas, recintos) son atractores de afluencia
visitante: engordan la capa de POIs del visitor_score. La cobertura está
verificada en las 10 ciudades Tier-1 (26–256 venues/ciudad, ver coverage_test).

Uso:
    python -m src.signals.venues                 # las 10 Tier-1
    python -m src.signals.venues --city madrid   # una sola

La key se lee de TM_API_KEY (.env o entorno).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from pathlib import Path

import h3

from src.signals.coverage_test import (
    RADIUS_KM,
    RATE_DELAY,
    SPAIN_TIER1,
    TM_BASE,
    geohash,
    get_json,
    load_env_key,
)

OUT_DIR = Path(__file__).resolve().parents[2] / "data"
PAGE_SIZE = 200


def slug_of(city: dict) -> str:
    import unicodedata
    n = unicodedata.normalize("NFKD", city["name"]).encode("ascii", "ignore").decode()
    return n.lower().replace(" ", "-")


def fetch_city_venues(apikey: str, city: dict) -> list[dict]:
    out, page = [], 0
    while True:
        params = {
            "apikey": apikey,
            "geoPoint": geohash(city["lat"], city["lon"]),
            "radius": str(RADIUS_KM),
            "unit": "km",
            "size": str(PAGE_SIZE),
            "page": str(page),
        }
        data = get_json(f"{TM_BASE}/venues.json?{urllib.parse.urlencode(params)}")
        venues = (data.get("_embedded") or {}).get("venues") or []
        for v in venues:
            loc = v.get("location") or {}
            try:
                lat, lng = float(loc["latitude"]), float(loc["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            out.append({
                "tm_id": v.get("id"),
                "name": v.get("name"),
                "lat": lat,
                "lng": lng,
                "h3_index": h3.latlng_to_cell(lat, lng, 8),
            })
        total_pages = int(data.get("page", {}).get("totalPages", 1))
        page += 1
        if page >= total_pages:
            return out
        time.sleep(RATE_DELAY)


def main() -> int:
    parser = argparse.ArgumentParser(description="Descarga venues TM por ciudad.")
    parser.add_argument("--city", default=None, help="Slug de una sola ciudad (def: todas).")
    args = parser.parse_args()

    apikey = load_env_key()
    if not apikey:
        print("❌ Falta TM_API_KEY en .env o entorno.", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cities = SPAIN_TIER1 if not args.city else [c for c in SPAIN_TIER1 if slug_of(c) == args.city]
    if not cities:
        print(f"❌ Ciudad desconocida: {args.city}", file=sys.stderr)
        return 1

    for city in cities:
        slug = slug_of(city)
        venues = fetch_city_venues(apikey, city)
        path = OUT_DIR / f"venues_{slug}.json"
        path.write_text(json.dumps(venues, ensure_ascii=False, indent=1))
        print(f"  {slug:<12} {len(venues):>4} venues → {path.name}")
        time.sleep(RATE_DELAY)
    return 0


if __name__ == "__main__":
    sys.exit(main())
