"""Detector `next_wave`: la cara residencial del producto.

Espejo de `hidden_audience`. Mientras audiencia oculta busca "tu cliente PASA
aunque no viva aquí" (visitante ≫ residente), next_wave busca "tu cliente VIVE
aquí y la zona aún no está descubierta comercialmente":

  - alto `resident_score` para el sector (donde está tu base de clientes),
  - claramente más residencial que comercial (resident − visitor ≥ umbral), y
  - donde hay censo oficial (Madrid, Barcelona): POCOS competidores REALES del
    sector en el hex — la saturación deja de inferirse y se mide contra el
    registro municipal de locales. Sin censo, degrada al comportamiento previo.

Usa SOLO los scores ya validados + el conteo censal como filtro — no toca el
detector de audiencia oculta.
"""

from __future__ import annotations

from src.config import (
    NEXT_WAVE_SATURATION_PCT,
    NEXT_WAVE_SKEW_MIN,
    NEXT_WAVE_TOP_N,
)
from src.models import HiddenAudienceResult
from src.patterns.scoring import CityStats, resident_score, visitor_score


def _describe(resident: float, visitor: float, skew: float,
              competitors: int | None) -> str:
    base = (
        f"Encaje residente {round(resident)}, afluencia de paso {round(visitor)}. "
        f"Tu cliente vive aquí (+{round(skew)} sobre el paso comercial): "
        f"zona consolidada aún sin saturar."
    )
    if competitors is None:
        return base
    if competitors == 0:
        return base + " Sin competencia del sector en la zona (censo oficial)."
    return base + f" Solo {competitors} negocio(s) del sector en la zona (censo oficial)."


def saturation_threshold(hexes: list, density: dict[str, int]) -> int:
    """Corte de saturación: percentil NEXT_WAVE_SATURATION_PCT de los conteos
    del sector sobre los hexes poblados de la ciudad. Un hex por encima está
    entre los más saturados de la ciudad → no es 'próxima ola'."""
    counts = sorted(
        density.get(h.h3_index, 0) for h in hexes if h.poblacion > 0
    )
    if not counts:
        return 0
    idx = int(NEXT_WAVE_SATURATION_PCT * (len(counts) - 1))
    return counts[idx]


def detect_next_wave(
    hexes: list,
    sector: str,
    exclude: set[str] | None = None,
    stats: CityStats | None = None,
    density: dict[str, int] | None = None,
) -> list[HiddenAudienceResult]:
    """Top hexes residenciales de alto encaje aún no saturados.

    `exclude`: celdas a omitir (típicamente las ya marcadas como audiencia oculta).
    `stats`: reutilizable si ya se calculó.
    `density`: negocios reales del sector por hex (censo oficial). None = sin
    dato → sin filtro de saturación (comportamiento previo, ciudades sin censo).
    """
    if not hexes:
        return []
    stats = stats or CityStats.from_hexes(hexes, sector)
    exclude = exclude or set()
    sat_max = saturation_threshold(hexes, density) if density is not None else None

    results: list[HiddenAudienceResult] = []
    for hex in hexes:
        if hex.poblacion <= 0 or hex.h3_index in exclude:
            continue
        competitors = density.get(hex.h3_index, 0) if density is not None else None
        if sat_max is not None and competitors > sat_max:
            continue  # ya está entre lo más saturado de la ciudad para este sector
        rs = resident_score(hex, stats, sector)
        vs = visitor_score(hex, stats, sector)
        skew = round(rs - vs, 1)
        if skew < NEXT_WAVE_SKEW_MIN:
            continue  # no es claramente residencial → no es "ola sin descubrir"
        results.append(
            HiddenAudienceResult(
                h3_index=hex.h3_index, lat=hex.lat, lon=hex.lon,
                resident_score=rs, visitor_score=vs, gap=skew,
                description=_describe(rs, vs, skew, competitors),
            )
        )

    results.sort(key=lambda r: r.resident_score, reverse=True)
    return results[:NEXT_WAVE_TOP_N]
