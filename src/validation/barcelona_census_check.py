"""Validación Nivel 1 de Barcelona contra el Cens d'Activitats Comercials oficial.

Mismo método que src.validation.madrid_census_check, pero con el censo del
Ajuntament de Barcelona (68.024 locales, filtrados a los 12.083 activos de
nuestros 3 sectores) en vez de OSM. Ver src/signals/barcelona_census.py.

Uso:
    python -m src.validation.barcelona_census_check
"""

from __future__ import annotations

import sys

import h3

from src.config import H3_RES, SECTOR_DEFAULT_WINDOW
from src.patterns.aggregation import load_city_hexes
from src.patterns.hidden_audience import detect_from_hexes
from src.signals.barcelona_census import SECTOR_FILTERS, load_businesses

CITY = "barcelona"


def biz_cells(businesses: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for b in businesses:
        cell = h3.latlng_to_cell(b["lat"], b["lng"], H3_RES)
        counts[cell] = counts.get(cell, 0) + 1
    return counts


def evaluate(sector: str) -> dict:
    window = SECTOR_DEFAULT_WINDOW.get(sector)
    hexes = load_city_hexes(CITY, sector, window)
    universe = [hx for hx in hexes if hx.poblacion > 0 and hx.flujo_peatonal > 0]
    results = detect_from_hexes(hexes, sector)
    top_cells = [r.h3_index for r in results]

    counts = biz_cells(load_businesses(sector))
    n_universe = len(universe)
    base_hits = sum(1 for hx in universe if counts.get(hx.h3_index, 0) >= 1)
    baseline = base_hits / n_universe if n_universe else 0.0
    k = len(top_cells)
    hits = sum(1 for c in top_cells if counts.get(c, 0) >= 1)
    precision = hits / k if k else 0.0
    lift = (precision / baseline) if baseline > 0 else float("nan")

    return {
        "sector": sector, "k": k, "hits": hits, "precision": precision,
        "baseline": baseline, "lift": lift, "censo_total": sum(counts.values()),
    }


def main() -> int:
    print("Validación Barcelona vs Cens d'Activitats Comercials oficial (CC BY 4.0)")
    print(f"{'sector':<14}{'k':>3}{'hits':>5}{'prec@k':>8}{'base':>7}{'lift':>6}{'censo':>7}")
    print("-" * 50)
    for sector in SECTOR_FILTERS:
        r = evaluate(sector)
        print(f"{r['sector']:<14}{r['k']:>3}{r['hits']:>5}{r['precision']:>8.0%}"
              f"{r['baseline']:>7.0%}{r['lift']:>6.1f}{r['censo_total']:>7}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
