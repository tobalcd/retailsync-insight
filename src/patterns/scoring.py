"""Funciones de scoring para el detector de audiencia oculta.

Dos scores ORTOGONALES por hex, ambos en escala 0..100 tras normalizar por ciudad:

  - resident_score : afinidad si solo miramos quién VIVE (renta, población, perfil).
  - visitor_score  : afinidad si solo miramos quién PASA (flujo MITMA, POIs, perfil).

La normalización es min-max RELATIVA A LA CIUDAD: por eso necesitamos las
estadísticas de toda la ciudad (`CityStats`) además del hex individual.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config import (
    DEFAULT_AFFINITY,
    RESIDENT_WEIGHTS,
    SECTOR_AFFINITY,
    VISIT_POI_CATEGORIES,
    VISITOR_WEIGHTS,
)
from src.models import Hex


@dataclass
class CityStats:
    """Mínimos y máximos por métrica en una ciudad, para normalizar (min-max)."""

    renta_min: float
    renta_max: float
    poblacion_min: float
    poblacion_max: float
    flujo_min: float
    flujo_max: float
    poi_visit_min: float
    poi_visit_max: float

    @classmethod
    def from_hexes(cls, hexes: list[Hex]) -> "CityStats":
        rentas = [h.renta for h in hexes]
        pobs = [h.poblacion for h in hexes]
        flujos = [h.flujo_peatonal for h in hexes]
        pois = [count_poi(h, VISIT_POI_CATEGORIES) for h in hexes]
        return cls(
            renta_min=min(rentas), renta_max=max(rentas),
            poblacion_min=min(pobs), poblacion_max=max(pobs),
            flujo_min=min(flujos), flujo_max=max(flujos),
            poi_visit_min=min(pois), poi_visit_max=max(pois),
        )


def minmax_norm(value: float, lo: float, hi: float) -> float:
    """Normaliza a 0..1. Si no hay rango (hi<=lo) devuelve 0.0 (sin señal)."""
    if hi <= lo:
        return 0.0
    return (value - lo) / (hi - lo)


def sector_affinity(sector: str, profile_type: str) -> float:
    """Afinidad 0..1 de un sector con un perfil ('residente' | 'visitante').

    Sector desconocido → neutro (0.5), para degradar suavemente.
    """
    return SECTOR_AFFINITY.get(sector, DEFAULT_AFFINITY)[profile_type]


def count_poi(hex: Hex, categories: list[str]) -> int:
    """Suma de POIs del hex que caen en las categorías indicadas."""
    return sum(hex.poi_counts.get(cat, 0) for cat in categories)


def resident_score(hex: Hex, stats: CityStats, sector: str) -> float:
    """Score 0..100 basado SOLO en el perfil residente."""
    nr = minmax_norm(hex.renta, stats.renta_min, stats.renta_max)
    npob = minmax_norm(hex.poblacion, stats.poblacion_min, stats.poblacion_max)
    aff = sector_affinity(sector, "residente")
    raw = (
        RESIDENT_WEIGHTS["renta"] * nr
        + RESIDENT_WEIGHTS["poblacion"] * npob
        + RESIDENT_WEIGHTS["perfil"] * aff
    )
    return round(raw * 100, 1)


def visitor_score(hex: Hex, stats: CityStats, sector: str) -> float:
    """Score 0..100 basado SOLO en el perfil visitante (movilidad + POIs de paso)."""
    nf = minmax_norm(hex.flujo_peatonal, stats.flujo_min, stats.flujo_max)
    npoi = minmax_norm(
        count_poi(hex, VISIT_POI_CATEGORIES), stats.poi_visit_min, stats.poi_visit_max
    )
    aff = sector_affinity(sector, "visitante")
    raw = (
        VISITOR_WEIGHTS["flujo"] * nf
        + VISITOR_WEIGHTS["poi"] * npoi
        + VISITOR_WEIGHTS["perfil"] * aff
    )
    return round(raw * 100, 1)
