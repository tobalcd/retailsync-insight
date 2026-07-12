"""Densidad de negocios por hex desde los censos comerciales oficiales.

Precomputa, para cada ciudad con censo oficial (Madrid, Barcelona), cuántos
negocios REALES de cada sector hay en cada hex H3 → data/census_density_{city}.json.
Es la señal de SATURACIÓN de next_wave: "tu cliente vive aquí y el sector aún
no ha llegado" deja de inferirse y pasa a medirse.

Los ficheros de densidad son pequeños y SÍ se versionan (los CSV fuente de
119/24 MB no). El fichero guarda la resolución H3 usada: si H3_RES cambia,
el loader lo detecta y degrada a {} (hay que reconstruir con --build).

Uso:
    python -m src.signals.census_density --build   # regenera desde los censos
    python -m src.signals.census_density           # resumen de lo existente
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import h3

from src.config import H3_RES

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# ciudad → módulo de censo (import perezoso para no exigir pyproj en producción)
CITIES = ["madrid", "barcelona"]


def _load_census_module(city: str):
    if city == "madrid":
        from src.signals import madrid_census
        return madrid_census, list(madrid_census.SECTOR_EPIGRAFES)
    if city == "barcelona":
        from src.signals import barcelona_census
        return barcelona_census, list(barcelona_census.SECTOR_FILTERS)
    raise ValueError(f"Ciudad sin censo oficial: {city}")


def _density_path(city: str) -> Path:
    return DATA_DIR / f"census_density_{city}.json"


def build_density(city: str) -> Path:
    """Reconstruye el fichero de densidad de una ciudad desde su censo."""
    module, sectors = _load_census_module(city)
    payload = {"h3_res": H3_RES, "city": city, "sectors": {}}
    for sector in sectors:
        counts: dict[str, int] = {}
        for b in module.load_businesses(sector):
            cell = h3.latlng_to_cell(b["lat"], b["lng"], H3_RES)
            counts[cell] = counts.get(cell, 0) + 1
        payload["sectors"][sector] = counts
    path = _density_path(city)
    path.write_text(json.dumps(payload, ensure_ascii=False))
    return path


def load_density(city: str, sector: str) -> dict[str, int] | None:
    """Conteo de negocios del sector por hex, o None si no hay dato utilizable.

    None (no {}) cuando falta el fichero, la resolución no coincide con H3_RES
    o el sector no está mapeado — así el llamador distingue "sin dato" de
    "dato: cero negocios en todas partes".
    """
    path = _density_path(city)
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    if payload.get("h3_res") != H3_RES:
        return None  # resolución cambiada: reconstruir con --build
    return payload.get("sectors", {}).get(sector)


def main() -> int:
    parser = argparse.ArgumentParser(description="Densidad de negocios por hex (censos oficiales).")
    parser.add_argument("--build", action="store_true", help="Regenerar desde los censos.")
    args = parser.parse_args()

    for city in CITIES:
        if args.build:
            path = build_density(city)
            print(f"✅ {path.name}")
        payload_path = _density_path(city)
        if not payload_path.exists():
            print(f"  {city}: sin fichero (usa --build)")
            continue
        payload = json.loads(payload_path.read_text())
        for sector, counts in payload["sectors"].items():
            print(f"  {city:<10} {sector:<20} {sum(counts.values()):>6} negocios en {len(counts):>4} hexes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
