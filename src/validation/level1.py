"""Validación Nivel 1 del detector de audiencia oculta.

Contrasta el top-10 del detector con la PRESENCIA COMERCIAL REAL del sector
(OpenStreetMap vía Overpass), en las 10 ciudades Tier-1:

  - precision@k : % del top-k con ≥1 negocio real del sector en el hex
  - baseline    : % de TODOS los hexes de la ciudad con ≥1 negocio del sector
  - lift        : precision / baseline  (>1 = el detector enriquece; ~1 = azar)
  - control negativo : el top de `alimentacion` (sector residencial) no debe
    solaparse con el de `banca` (sector visitante)

Lectura honesta: una precision baja puede significar fallo del detector O
oportunidad genuinamente oculta (el sector aún no llegó). El lift agregado en
10 ciudades separa señal de ruido mejor que cualquier anécdota.

Uso:
    python -m src.validation.level1                 # todas las ciudades
    python -m src.validation.level1 --city madrid   # una

Los POIs de OSM se cachean en data/osm_{sector}_{city}.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import h3

from src.config import H3_RES
from src.patterns.aggregation import load_city_hexes
from src.patterns.hidden_audience import detect_from_hexes
from src.signals.coverage_test import SPAIN_TIER1
from src.signals.venues import slug_of

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OVERPASS = "https://overpass-api.de/api/interpreter"
RADIUS_M = 8000

# Sector del motor → selector OSM de negocios de ese sector.
OSM_SELECTORS = {
    "banca": '["amenity"="bank"]',
    "moda_lujo": '["shop"~"^(clothes|boutique|jewelry|bag|shoes|watches|fashion_accessories)$"]',
    "alimentacion": '["shop"~"^(supermarket|convenience|greengrocer|bakery|butcher|seafood|deli)$"]',
}

# Ventana usada por sector en la validación (la natural de cada uno).
SECTOR_WINDOW = {"banca": "laborable-manana", "moda_lujo": None, "alimentacion": None}


def fetch_osm_businesses(city: dict, sector: str) -> list[dict]:
    """Negocios del sector en la ciudad (cacheado en data/)."""
    slug = slug_of(city)
    cache = DATA_DIR / f"osm_{sector}_{slug}.json"
    if cache.exists():
        return json.loads(cache.read_text())

    sel = OSM_SELECTORS[sector]
    around = f"(around:{RADIUS_M},{city['lat']},{city['lon']})"
    query = f"""[out:json][timeout:90];
(node{sel}{around}; way{sel}{around};);
out center 4000;"""
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                OVERPASS,
                data=urllib.parse.urlencode({"data": query}).encode(),
                headers={"User-Agent": "RetailSync-validation/1.0"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                elements = json.loads(resp.read()).get("elements", [])
            break
        except Exception:  # noqa: BLE001 — throttling de Overpass: backoff y reintento
            if attempt == 3:
                raise
            time.sleep(15 * (attempt + 1))

    out = []
    for e in elements:
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        out.append({"lat": lat, "lng": lon,
                    "name": (e.get("tags") or {}).get("name", "")})
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False))
    time.sleep(3)  # cortesía con el endpoint público
    return out


def biz_cells(businesses: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for b in businesses:
        cell = h3.latlng_to_cell(b["lat"], b["lng"], H3_RES)
        counts[cell] = counts.get(cell, 0) + 1
    return counts


def evaluate_city_sector(city: dict, sector: str) -> dict:
    slug = slug_of(city)
    window = SECTOR_WINDOW.get(sector)
    hexes = load_city_hexes(slug, sector, window)
    universe = [hx for hx in hexes if hx.poblacion > 0 and hx.flujo_peatonal > 0]
    results = detect_from_hexes(hexes, sector)
    top_cells = [r.h3_index for r in results]

    counts = biz_cells(fetch_osm_businesses(city, sector))
    n_universe = len(universe)
    base_hits = sum(1 for hx in universe if counts.get(hx.h3_index, 0) >= 1)
    baseline = base_hits / n_universe if n_universe else 0.0
    k = len(top_cells)
    hits = sum(1 for c in top_cells if counts.get(c, 0) >= 1)
    precision = hits / k if k else 0.0
    lift = (precision / baseline) if baseline > 0 else float("nan")

    return {
        "city": slug, "sector": sector, "k": k, "hits": hits,
        "precision": precision, "baseline": baseline, "lift": lift,
        "osm_total": sum(counts.values()), "top_cells": top_cells,
    }


def overlap(a: list[str], b: list[str]) -> int:
    return len(set(a) & set(b))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validación Nivel 1 (OSM).")
    parser.add_argument("--city", default=None, help="Slug de una sola ciudad.")
    args = parser.parse_args()

    cities = SPAIN_TIER1 if not args.city else [c for c in SPAIN_TIER1 if slug_of(c) == args.city]
    if not cities:
        print(f"❌ Ciudad desconocida: {args.city}", file=sys.stderr)
        return 1

    rows = []
    tops: dict[tuple[str, str], list[str]] = {}
    print(f"{'ciudad':<12}{'sector':<14}{'k':>3}{'hits':>5}{'prec@k':>8}{'base':>7}{'lift':>6}{'OSM':>6}")
    print("-" * 64)
    for city in cities:
        for sector in ["banca", "moda_lujo", "alimentacion"]:
            try:
                r = evaluate_city_sector(city, sector)
            except Exception as exc:  # noqa: BLE001
                print(f"{slug_of(city):<12}{sector:<14}  ERROR: {str(exc)[:40]}")
                continue
            rows.append(r)
            tops[(r["city"], sector)] = r["top_cells"]
            print(f"{r['city']:<12}{sector:<14}{r['k']:>3}{r['hits']:>5}"
                  f"{r['precision']:>8.0%}{r['baseline']:>7.0%}{r['lift']:>6.1f}{r['osm_total']:>6}")

    # Agregados por sector
    print("\n=== AGREGADO POR SECTOR (todas las ciudades) ===")
    for sector in ["banca", "moda_lujo", "alimentacion"]:
        rs = [r for r in rows if r["sector"] == sector and r["k"] > 0]
        if not rs:
            continue
        tot_k = sum(r["k"] for r in rs)
        tot_hits = sum(r["hits"] for r in rs)
        mean_base = sum(r["baseline"] for r in rs) / len(rs)
        prec = tot_hits / tot_k
        print(f"  {sector:<14} precision@k {prec:.0%}  (baseline media {mean_base:.0%}, "
              f"lift {prec/mean_base:.1f}x, {tot_k} hexes en {len(rs)} ciudades)")

    # Control negativo: solape banca vs alimentacion por ciudad
    print("\n=== CONTROL NEGATIVO (solape top banca ∩ top alimentacion) ===")
    for city in cities:
        slug = slug_of(city)
        a, b = tops.get((slug, "banca")), tops.get((slug, "alimentacion"))
        if a is None or b is None or not a or not b:
            continue
        ov = overlap(a, b)
        verdict = "OK" if ov <= 2 else "⚠️ ALTO"
        print(f"  {slug:<12} {ov}/{min(len(a), len(b))} hexes compartidos  [{verdict}]")

    # CSV
    out = DATA_DIR / "validation_level1.csv"
    import csv as _csv
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=["city", "sector", "k", "hits", "precision",
                                           "baseline", "lift", "osm_total"])
        w.writeheader()
        for r in rows:
            w.writerow({key: r[key] for key in w.fieldnames})
    print(f"\n→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
