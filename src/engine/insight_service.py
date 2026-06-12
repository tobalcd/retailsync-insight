"""Orquestador del análisis INSIGHT: cache → detector → narrativa → cache.

Es la pieza que une todo para POST /insight. El endpoint queda fino y esta
lógica es invocable también desde CLI o tests.
"""

from __future__ import annotations

import csv
import unicodedata
from pathlib import Path

from src.cache.store import get_cached, input_hash, set_cached
from src.config import SECTOR_AFFINITY, thresholds_for
from src.engine.narrative import build_prompt, generate_narrative
from src.patterns.aggregation import load_city_hexes
from src.patterns.hidden_audience import detect_from_hexes
from src.patterns.scoring import CityStats, resident_score, visitor_score
from src.tools.calibration_map import _fetch_districts, _poi_names_by_cell

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# Puerta de producto: audiencia oculta solo para sectores de visitante
# (validación Nivel 1: en sectores residenciales el concepto apenas existe).
MIN_VISITOR_AFFINITY = 0.6


def sector_supported(sector: str) -> bool:
    return SECTOR_AFFINITY.get(sector, {}).get("visitante", 0.0) >= MIN_VISITOR_AFFINITY


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _load_clima(city_slug: str) -> dict | None:
    """Días útiles de campaña (Open-Meteo, src.signals.coverage_test)."""
    path = DATA_DIR / "clima_resumen.csv"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if _norm(row["ciudad"]) == _norm(city_slug):
                return {"pct_utiles": row["pct_utiles"],
                        "dias_lluvia": row["dias_lluvia_1mm"]}
    return None


def _find_discarded(hexes, stats, sector, top_cells, zonas) -> dict | None:
    """La mejor zona que se quedó FUERA, con la razón (para la narrativa)."""
    gap_thr, visitor_min = thresholds_for(sector)
    best = None
    for hx in hexes:
        if hx.poblacion <= 0 or hx.flujo_peatonal <= 0 or hx.h3_index in top_cells:
            continue
        vs = visitor_score(hx, stats, sector)
        rs = resident_score(hx, stats, sector)
        if best is None or vs > best[0]:
            best = (vs, rs, hx)
    if best is None:
        return None
    vs, rs, hx = best
    gap = vs - rs
    if gap < gap_thr and rs >= 35:
        reason = "el perfil residente ya encaja con el target — no hay diferencial oculto que explotar"
    elif gap < gap_thr:
        reason = "el diferencial visitante-residente no alcanza el umbral de calidad"
    else:
        reason = "el volumen de visitante no alcanza el mínimo exigido"
    return {"zona": zonas.get(hx.h3_index, "otra zona"), "visitor": vs,
            "resident": rs, "gap": gap, "reason": reason}


def run_insight(city: str, sector: str, profile: str, window: str | None) -> dict:
    """Análisis completo (con cache). Devuelve el payload del API."""
    key = input_hash(city, sector, profile, window)
    cached = get_cached(key)
    if cached is not None:
        return {**cached, "cached": True}

    hexes = load_city_hexes(city, sector, window)
    if not hexes:
        raise ValueError(f"Sin datos para la ciudad '{city}' — ¿slug correcto?")
    stats = CityStats.from_hexes(hexes)
    results = detect_from_hexes(hexes, sector)

    zonas = _fetch_districts(city)
    pois = _poi_names_by_cell(city)
    top_cells = {r.h3_index for r in results}
    discarded = _find_discarded(hexes, stats, sector, top_cells, zonas)
    clima = _load_clima(city)

    prompt = build_prompt(city, sector, profile, window, results, zonas, pois,
                          discarded, clima)
    narrative = generate_narrative(prompt)

    payload = {
        "hidden_audience": [
            {
                "h3_index": r.h3_index, "lat": r.lat, "lon": r.lon,
                "zona": zonas.get(r.h3_index, city.title()),
                "resident_score": r.resident_score, "visitor_score": r.visitor_score,
                "gap": r.gap, "description": r.description,
            }
            for r in results
        ],
        "next_wave": [],  # producto para sectores residenciales — pendiente de diseño
        "narrative": narrative,
    }
    set_cached(key, payload)
    return {**payload, "cached": False}
