"""Detector `next_wave`: la cara residencial del producto.

Espejo de `hidden_audience`. Mientras audiencia oculta busca "tu cliente PASA
aunque no viva aquí" (visitante ≫ residente), next_wave busca "tu cliente VIVE
aquí y la zona aún no está descubierta comercialmente":

  - alto `resident_score` para el sector (donde está tu base de clientes), y
  - claramente más residencial que comercial (resident − visitor ≥ umbral),
    es decir, todavía no es un polo de paso saturado.

Usa SOLO los scores ya validados (resident_score, visitor_score) — no introduce
datos ni fórmulas nuevas, así que no puede degradar el detector de audiencia
oculta. Es el insight natural para sectores residenciales (alimentación, hogar,
deporte), donde "audiencia oculta" casi no existe (validación Nivel 1).
"""

from __future__ import annotations

from src.config import NEXT_WAVE_SKEW_MIN, NEXT_WAVE_TOP_N
from src.models import HiddenAudienceResult
from src.patterns.scoring import CityStats, resident_score, visitor_score


def _describe(resident: float, visitor: float, skew: float) -> str:
    return (
        f"Encaje residente {round(resident)}, afluencia de paso {round(visitor)}. "
        f"Tu cliente vive aquí (+{round(skew)} sobre el paso comercial): "
        f"zona consolidada aún sin saturar."
    )


def detect_next_wave(
    hexes: list,
    sector: str,
    exclude: set[str] | None = None,
    stats: CityStats | None = None,
) -> list[HiddenAudienceResult]:
    """Top hexes residenciales de alto encaje aún no saturados.

    `exclude`: celdas a omitir (típicamente las ya marcadas como audiencia oculta,
    para que ambos productos no se pisen). `stats`: reutilizable si ya se calculó.
    Ordena por encaje residente (dónde vive más tu cliente).
    """
    if not hexes:
        return []
    stats = stats or CityStats.from_hexes(hexes, sector)
    exclude = exclude or set()

    results: list[HiddenAudienceResult] = []
    for hex in hexes:
        if hex.poblacion <= 0 or hex.h3_index in exclude:
            continue
        rs = resident_score(hex, stats, sector)
        vs = visitor_score(hex, stats, sector)
        skew = round(rs - vs, 1)
        if skew < NEXT_WAVE_SKEW_MIN:
            continue  # no es claramente residencial → no es "ola sin descubrir"
        results.append(
            HiddenAudienceResult(
                h3_index=hex.h3_index, lat=hex.lat, lon=hex.lon,
                resident_score=rs, visitor_score=vs, gap=skew,
                description=_describe(rs, vs, skew),
            )
        )

    results.sort(key=lambda r: r.resident_score, reverse=True)
    return results[:NEXT_WAVE_TOP_N]
