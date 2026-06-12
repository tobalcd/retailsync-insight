"""Funciones de scoring para el detector de audiencia oculta.

Dos scores ORTOGONALES por hex, ambos en escala 0..100 tras normalizar por ciudad:

  - resident_score : afinidad si solo miramos quién VIVE (renta, población, perfil).
  - visitor_score  : afinidad si solo miramos quién PASA (volumen de flujo,
                     composición sectorial del flujo, POIs ponderados por sector,
                     perfil visitante).

La normalización es min-max RELATIVA A LA CIUDAD — y, donde la señal depende del
sector (composición, POIs), también relativa al sector pedido.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config import (
    DEFAULT_AFFINITY,
    DEFAULT_POI_WEIGHTS,
    RESIDENT_WEIGHTS,
    SECTOR_AFFINITY,
    SECTOR_POI_WEIGHTS,
    VISIT_POI_CATEGORIES,
    VISITOR_WEIGHTS,
)
from src.models import Hex


def weighted_poi(hex: Hex, sector: str | None) -> float:
    """Densidad de POIs de paso ponderada por lo que importa al sector.

    Para banca pesan las oficinas; para moda, el turismo. Sector desconocido o
    None → pesos planos (comportamiento neutro).
    """
    weights = SECTOR_POI_WEIGHTS.get(sector or "", DEFAULT_POI_WEIGHTS)
    return sum(hex.poi_counts.get(cat, 0) * w for cat, w in weights.items())


def count_poi(hex: Hex, categories: list[str]) -> int:
    """Suma simple de POIs por categorías (sin ponderar). Uso auxiliar."""
    return sum(hex.poi_counts.get(cat, 0) for cat in categories)


@dataclass
class CityStats:
    """Mínimos y máximos por métrica en una ciudad, para normalizar (min-max).

    `poi_*` depende del sector (ponderación): construir con el MISMO sector
    que luego se pasa a visitor_score.
    """

    renta_min: float
    renta_max: float
    poblacion_min: float
    poblacion_max: float
    flujo_min: float
    flujo_max: float
    share_min: float
    share_max: float
    poi_visit_min: float
    poi_visit_max: float

    @classmethod
    def from_hexes(cls, hexes: list[Hex], sector: str | None = None) -> "CityStats":
        rentas = [h.renta for h in hexes]
        pobs = [h.poblacion for h in hexes]
        flujos = [h.flujo_peatonal for h in hexes]
        shares = [h.flujo_share for h in hexes]
        pois = [weighted_poi(h, sector) for h in hexes]
        return cls(
            renta_min=min(rentas), renta_max=max(rentas),
            poblacion_min=min(pobs), poblacion_max=max(pobs),
            flujo_min=min(flujos), flujo_max=max(flujos),
            share_min=min(shares), share_max=max(shares),
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
    """Score 0..100 basado SOLO en el perfil visitante.

    Volumen (cuánta gente pasa) + composición (qué parte es target del sector)
    + POIs ponderados por sector + afinidad del sector.
    """
    nf = minmax_norm(hex.flujo_peatonal, stats.flujo_min, stats.flujo_max)
    ns = minmax_norm(hex.flujo_share, stats.share_min, stats.share_max)
    npoi = minmax_norm(weighted_poi(hex, sector), stats.poi_visit_min, stats.poi_visit_max)
    aff = sector_affinity(sector, "visitante")
    raw = (
        VISITOR_WEIGHTS["flujo"] * nf
        + VISITOR_WEIGHTS["share"] * ns
        + VISITOR_WEIGHTS["poi"] * npoi
        + VISITOR_WEIGHTS["perfil"] * aff
    )
    return round(raw * 100, 1)