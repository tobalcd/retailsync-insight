"""Agregación espacial: secciones INE + zonas MITMA + screens + venues → hexes H3 res 8.

Construye la malla de `Hex` que consume el detector (`detect_from_hexes`):

  - renta / poblacion  ← ine_renta agrupada por h3_index (renta ponderada por población)
  - flujo_peatonal     ← mobility_zones con decaimiento por distancia, PONDERADO por
                         (a) afinidad sector×tipo de zona (quién pasa, no solo cuánto) y
                         (b) pulso horario de la zona dentro de la ventana pedida
  - poi_counts         ← screens (turismo/transporte/oficinas) + venues TM (turismo)

La parte pura (build_hexes y auxiliares) no toca red — testeable con sintéticos.
load_city_inputs trae las tablas de Supabase; los venues se leen de
data/venues_{slug}.json si existe (generado por src.signals.venues).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import h3

from src.config import (
    DEFAULT_ZONE_TYPE_AFFINITY,
    FLUJO_DECAY_KM,
    FLUJO_MAX_KM,
    H3_RES,
    SCREEN_TAG_TO_POI,
    SCREEN_TIPO_TO_POI,
    TRANSIT_POI_CATEGORY,
    VENUE_POI_CATEGORY,
    WINDOWS,
    ZONE_TYPE_AFFINITY,
)
from src.models import Hex

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def cell_of(row: dict) -> str | None:
    """Celda H3 a la resolución del detector, desde lat/lng de la fila.

    No usa el h3_index almacenado (que es res 8 fijo): así H3_RES es la única
    fuente de verdad de la resolución. Sin coordenadas fiables → None.
    """
    lat, lng = row.get("lat"), row.get("lng")
    if lat is None or lng is None or row.get("coords_pendientes"):
        return None
    return h3.latlng_to_cell(float(lat), float(lng), H3_RES)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ─────────────────────────── parte pura ───────────────────────────
def aggregate_ine(ine_rows: list[dict]) -> dict[str, dict]:
    """Agrupa secciones censales por h3_index.

    poblacion = suma; renta = media de renta_neta_hogar ponderada por población
    (si ninguna sección del hex tiene población, media simple).
    """
    grouped: dict[str, dict] = {}
    for r in ine_rows:
        cell = r.get("h3_index")
        if not cell:
            continue  # sección sin coordenadas fiables
        g = grouped.setdefault(cell, {"pob": 0.0, "renta_pond": 0.0, "rentas": []})
        pob = float(r.get("poblacion") or 0)
        renta = r.get("renta_neta_hogar")
        g["pob"] += pob
        if renta is not None:
            g["rentas"].append(float(renta))
            g["renta_pond"] += float(renta) * pob

    out: dict[str, dict] = {}
    for cell, g in grouped.items():
        if g["pob"] > 0 and g["renta_pond"] > 0:
            renta = g["renta_pond"] / g["pob"]
        elif g["rentas"]:
            renta = sum(g["rentas"]) / len(g["rentas"])
        else:
            renta = 0.0
        out[cell] = {"renta": renta, "poblacion": g["pob"]}
    return out


def zone_affinity(sector: str | None, tipo: str | None) -> float:
    """Peso 0..1 del tipo de zona para el sector. Desconocidos → neutro."""
    if not sector:
        return 1.0  # sin sector: flujo bruto (retrocompatible)
    table = ZONE_TYPE_AFFINITY.get(sector)
    if not table:
        return DEFAULT_ZONE_TYPE_AFFINITY
    return table.get(tipo or "", DEFAULT_ZONE_TYPE_AFFINITY)


def window_ratio(traffic_profile: dict | None, window: str | None) -> float:
    """Pulso de la zona en la ventana relativo a su media global (clamp 0..2).

    >1: la zona late MÁS de lo normal en esa ventana (eje oficinista en
    laborable-mañana); <1: late menos (el mismo eje en finde). Sin perfil → 1.
    """
    if not window or not traffic_profile:
        return 1.0
    spec = WINDOWS.get(window)
    if not spec:
        return 1.0
    all_vals = [v for day_vals in traffic_profile.values() for v in day_vals if v is not None]
    win_vals = [
        traffic_profile[day][hh]
        for day in spec["days"]
        if day in traffic_profile and len(traffic_profile[day]) == 24
        for hh in spec["hours"]
    ]
    if not all_vals or not win_vals:
        return 1.0
    overall = sum(all_vals) / len(all_vals)
    if overall <= 0:
        return 1.0
    return min(2.0, max(0.0, (sum(win_vals) / len(win_vals)) / overall))


def flujo_for_hex(lat: float, lon: float, zones: list[dict],
                  sector: str | None = None, window: str | None = None) -> float:
    """Flujo gravitacional ponderado:

    Σ visitantes × exp(-d_km/DECAY) × afinidad(sector, tipo_zona) × pulso(ventana)
    """
    total = 0.0
    for z in zones:
        zlat, zlon = z.get("lat"), z.get("lng")
        visitors = z.get("avg_daily_visitors") or 0
        if zlat is None or zlon is None or not visitors:
            continue
        d = _haversine_km(lat, lon, float(zlat), float(zlon))
        if d > FLUJO_MAX_KM:
            continue
        weight = zone_affinity(sector, z.get("tipo")) * window_ratio(z.get("traffic_profile"), window)
        total += float(visitors) * math.exp(-d / FLUJO_DECAY_KM) * weight
    return total


def poi_counts_by_hex(screens: list[dict], venues: list[dict] | None = None,
                      transit_stops: list[dict] | None = None) -> dict[str, dict[str, int]]:
    """Cuenta categorías de POI de paso por h3_index.

    Fuentes: pantallas (tipo/tags), venues TM (turismo) y paradas GTFS (transporte).
    """
    out: dict[str, dict[str, int]] = {}

    def bump(cell: str, cat: str) -> None:
        counts = out.setdefault(cell, {})
        counts[cat] = counts.get(cat, 0) + 1

    for s in screens:
        cell = s.get("h3_index")
        if not cell:
            continue
        cats = set()
        tipo_cat = SCREEN_TIPO_TO_POI.get(s.get("tipo") or "")
        if tipo_cat:
            cats.add(tipo_cat)
        for tag in s.get("tags") or []:
            tag_cat = SCREEN_TAG_TO_POI.get(tag)
            if tag_cat:
                cats.add(tag_cat)
        for c in cats:
            bump(cell, c)

    for v in venues or []:
        cell = v.get("h3_index")
        if cell:
            bump(cell, VENUE_POI_CATEGORY)

    for t in transit_stops or []:
        cell = t.get("h3_index")
        if cell:
            bump(cell, TRANSIT_POI_CATEGORY)

    return out


def build_hexes(ine_rows: list[dict], zones: list[dict], screens: list[dict],
                venues: list[dict] | None = None,
                sector: str | None = None, window: str | None = None,
                transit_stops: list[dict] | None = None) -> list[Hex]:
    """Malla de Hex de una ciudad. Universo = hexes con al menos una sección INE."""
    ine_by_hex = aggregate_ine(ine_rows)
    pois = poi_counts_by_hex(screens, venues, transit_stops)

    hexes: list[Hex] = []
    for cell, agg in ine_by_hex.items():
        lat, lon = h3.cell_to_latlng(cell)
        flujo = flujo_for_hex(lat, lon, zones, sector, window)
        # Composición: proporción del flujo BRUTO (sin sector ni ventana) que
        # es relevante para el sector. Anti sesgo-de-centro.
        neutro = flujo_for_hex(lat, lon, zones) if sector else flujo
        share = (flujo / neutro) if neutro > 0 else 0.0
        hexes.append(
            Hex(
                h3_index=cell,
                lat=lat,
                lon=lon,
                renta=agg["renta"],
                poblacion=agg["poblacion"],
                flujo_peatonal=flujo,
                flujo_share=min(1.0, share),
                poi_counts=pois.get(cell, {}),
            )
        )
    return hexes


# ─────────────────────────── carga de datos ───────────────────────────
def _fetch_all(client, table: str, columns: str, city_slug: str) -> list[dict]:
    page, start, rows = 1000, 0, []
    while True:
        batch = (
            client.table(table)
            .select(columns)
            .eq("city_slug", city_slug)
            .range(start, start + page - 1)
            .execute()
        ).data or []
        rows.extend(batch)
        if len(batch) < page:
            return rows
        start += page


def _load_json_cache(name: str) -> list[dict]:
    path = DATA_DIR / name
    if not path.exists():
        return []
    return json.loads(path.read_text())


def load_venues(city_slug: str) -> list[dict]:
    """Venues TM cacheados en local (data/venues_{slug}.json). Sin fichero → []"""
    return _load_json_cache(f"venues_{city_slug}.json")


def load_transit_stops(city_slug: str) -> list[dict]:
    """Paradas GTFS cacheadas (data/transit_stops_{slug}.json). Sin fichero → []"""
    return _load_json_cache(f"transit_stops_{city_slug}.json")


def load_city_inputs(city_slug: str) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """Trae (ine_rows, zones, screens, venues, transit_stops) de una ciudad."""
    from src.db.supabase_client import get_client

    client = get_client()
    ine = _fetch_all(client, "ine_renta",
                     "lat,lng,coords_pendientes,renta_neta_hogar,poblacion", city_slug)
    zones = _fetch_all(client, "mobility_zones",
                       "lat,lng,avg_daily_visitors,tipo,traffic_profile", city_slug)
    screens = _fetch_all(client, "screens", "lat,lng,tipo,tags", city_slug)
    venues = load_venues(city_slug)
    transit = load_transit_stops(city_slug)
    # La celda se recalcula a H3_RES desde lat/lng (los h3_index de BD son res 8).
    for row in (*ine, *screens, *venues, *transit):
        row["h3_index"] = cell_of(row)
    return ine, zones, screens, venues, transit


def load_city_hexes(city_slug: str, sector: str | None = None,
                    window: str | None = None) -> list[Hex]:
    """Punto de entrada: malla de Hex lista para el detector."""
    ine, zones, screens, venues, transit = load_city_inputs(city_slug)
    return build_hexes(ine, zones, screens, venues, sector, window, transit)
