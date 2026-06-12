"""Detector de patrones contraintuitivos: "audiencia oculta detectada".

Un hex es audiencia oculta cuando su afinidad sectorial es ALTA ponderando por
movilidad (quién pasa) pero BAJA ponderando por perfil residencial (quién vive).
Captura el insight "tu cliente está aquí aunque no viva aquí": ejes comerciales,
hoteles, oficinas, nodos de transporte.

Diseño: la lógica pura vive en `detect_from_hexes(hexes, sector)` — no toca red ni
Supabase, así que es 100% testeable con casos sintéticos. `detect_hidden_audience`
solo añade la carga de datos desde Supabase por encima.
"""

from __future__ import annotations

from src.config import settings, thresholds_for
from src.models import Hex, HiddenAudienceResult
from src.patterns.scoring import CityStats, resident_score, visitor_score

TOP_N = 10


def _describe(resident: float, visitor: float, gap: float) -> str:
    return (
        f"Score residente {round(resident)}, score visitante {round(visitor)}. "
        f"Diferencial +{round(gap)} puntos por movilidad."
    )


def detect_from_hexes(hexes: list[Hex], sector: str) -> list[HiddenAudienceResult]:
    """Núcleo del detector (puro, sin I/O).

    Devuelve el top 10 de hexes "audiencia oculta" ordenados por gap descendente.
    """
    if not hexes:
        return []

    stats = CityStats.from_hexes(hexes, sector)
    gap_thr, visitor_min = thresholds_for(sector)
    results: list[HiddenAudienceResult] = []

    for hex in hexes:
        # Filtra mar / zonas muertas: sin gente y sin paso no hay nada que decir.
        if hex.poblacion <= 0 or hex.flujo_peatonal <= 0:
            continue

        rs = resident_score(hex, stats, sector)
        vs = visitor_score(hex, stats, sector)
        gap = round(vs - rs, 1)

        if gap < gap_thr:
            continue
        if vs < visitor_min:
            continue

        results.append(
            HiddenAudienceResult(
                h3_index=hex.h3_index,
                lat=hex.lat,
                lon=hex.lon,
                resident_score=rs,
                visitor_score=vs,
                gap=gap,
                description=_describe(rs, vs, gap),
            )
        )

    results.sort(key=lambda r: r.gap, reverse=True)
    return results[:TOP_N]


# ─────────────────────────── Carga desde Supabase ───────────────────────────
def detect_hidden_audience(city: str, sector: str,
                           window: str | None = None) -> list[HiddenAudienceResult]:
    """Punto de entrada de alto nivel.

    No existe una tabla `hexes`: la malla H3 se DERIVA agregando ine_renta
    (residente) + mobility_zones (visitante, ponderada por sector y ventana)
    + screens/venues (POIs de paso). `city` es el slug del catálogo `cities`.
    """
    # Import perezoso: el detector puro no exige supabase/h3 instalados.
    from src.patterns.aggregation import load_city_hexes

    hexes = load_city_hexes(city, sector, window)
    return detect_from_hexes(hexes, sector)
