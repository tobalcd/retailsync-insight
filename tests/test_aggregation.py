"""Tests de la capa de agregación espacial (pura, sin Supabase)."""

from __future__ import annotations

import h3
import pytest

from src.patterns.aggregation import (
    aggregate_ine,
    build_hexes,
    flujo_for_hex,
    poi_counts_by_hex,
    window_ratio,
    zone_affinity,
)

# Dos celdas reales vecinas en Madrid centro (res 8) para los sintéticos.
CELL_A = h3.latlng_to_cell(40.4178, -3.7144, 8)
CELL_B = h3.latlng_to_cell(40.4500, -3.6920, 8)  # zona AZCA


def test_aggregate_ine_pondera_por_poblacion():
    rows = [
        {"h3_index": CELL_A, "renta_neta_hogar": 30000, "poblacion": 1000},
        {"h3_index": CELL_A, "renta_neta_hogar": 60000, "poblacion": 3000},
    ]
    agg = aggregate_ine(rows)
    assert agg[CELL_A]["poblacion"] == 4000
    # media ponderada: (30k*1k + 60k*3k) / 4k = 52.5k  (no la simple 45k)
    assert agg[CELL_A]["renta"] == pytest.approx(52500)


def test_aggregate_ine_sin_poblacion_usa_media_simple():
    rows = [
        {"h3_index": CELL_A, "renta_neta_hogar": 30000, "poblacion": 0},
        {"h3_index": CELL_A, "renta_neta_hogar": 50000, "poblacion": None},
    ]
    agg = aggregate_ine(rows)
    assert agg[CELL_A]["renta"] == pytest.approx(40000)


def test_aggregate_ine_ignora_secciones_sin_h3():
    rows = [{"h3_index": None, "renta_neta_hogar": 30000, "poblacion": 100}]
    assert aggregate_ine(rows) == {}


def test_flujo_decae_con_distancia():
    zona = [{"lat": 40.4500, "lng": -3.6920, "avg_daily_visitors": 100000}]
    cerca = flujo_for_hex(40.4510, -3.6925, zona)     # ~120 m
    lejos = flujo_for_hex(40.4178, -3.7144, zona)     # ~4 km
    fuera = flujo_for_hex(40.9000, -3.6920, zona)     # ~50 km → corte
    assert cerca > lejos > 0
    assert fuera == 0.0
    assert cerca == pytest.approx(100000, rel=0.1)    # casi encima de la zona


def test_poi_counts_mapea_tipo_y_tags():
    screens = [
        {"h3_index": CELL_A, "tipo": "dooh_transporte", "tags": []},
        {"h3_index": CELL_A, "tipo": "dooh_urbano", "tags": ["turistico", "premium"]},
        {"h3_index": CELL_B, "tipo": "dooh_urbano", "tags": ["business"]},
        {"h3_index": CELL_B, "tipo": "ooh_valla", "tags": ["vehicular"]},  # sin categoría
    ]
    pois = poi_counts_by_hex(screens)
    assert pois[CELL_A] == {"transporte": 1, "turismo": 1}
    assert pois[CELL_B] == {"oficinas": 1}


def test_zone_affinity_pondera_quien_pasa():
    # banca: una zona business vale mucho más que una turística
    assert zone_affinity("banca", "business") > zone_affinity("banca", "comercial_turistico")
    # sin sector → flujo bruto (peso 1.0, retrocompatible)
    assert zone_affinity(None, "business") == 1.0
    # sector o tipo desconocido → neutro
    assert zone_affinity("sector_inventado", "business") == 0.5
    assert zone_affinity("banca", "tipo_inventado") == 0.5


def test_window_ratio_distingue_pulso_horario():
    # Perfil oficinista: pico de mañana laborable, muerto el finde.
    perfil_business = {
        d: [3, 3, 3, 3, 5, 15, 45, 78, 90, 85, 75, 68, 62, 65, 72, 78, 82, 70, 42, 22, 12, 8, 5, 3]
        for d in ["lunes", "martes", "miercoles", "jueves", "viernes"]
    }
    perfil_business["sabado"] = [3] * 24
    perfil_business["domingo"] = [3] * 24

    manana = window_ratio(perfil_business, "laborable-manana")
    finde = window_ratio(perfil_business, "finde")
    assert manana > 1.0 > finde
    # sin ventana o sin perfil → neutro
    assert window_ratio(perfil_business, None) == 1.0
    assert window_ratio(None, "finde") == 1.0
    assert window_ratio(perfil_business, "ventana_inventada") == 1.0


def test_flujo_ponderado_por_sector():
    # Misma distancia y visitantes: para banca, la zona business pesa ~3.3x la turística.
    zona_turistica = [{"lat": 40.45, "lng": -3.692, "avg_daily_visitors": 100000,
                       "tipo": "comercial_turistico"}]
    zona_business = [{"lat": 40.45, "lng": -3.692, "avg_daily_visitors": 100000,
                      "tipo": "business"}]
    f_tur = flujo_for_hex(40.451, -3.692, zona_turistica, sector="banca")
    f_bus = flujo_for_hex(40.451, -3.692, zona_business, sector="banca")
    assert f_bus > f_tur
    assert f_bus / f_tur == pytest.approx(1.0 / 0.3, rel=0.01)


def test_poi_counts_incluye_venues():
    venues = [{"h3_index": CELL_A, "name": "Teatro X"},
              {"h3_index": CELL_A, "name": "Sala Y"}]
    pois = poi_counts_by_hex([], venues)
    assert pois[CELL_A] == {"turismo": 2}


def test_build_hexes_integra_las_tres_fuentes():
    ine = [
        {"h3_index": CELL_A, "renta_neta_hogar": 60000, "poblacion": 1200},
        {"h3_index": CELL_B, "renta_neta_hogar": 35000, "poblacion": 800},
    ]
    zones = [{"lat": 40.4500, "lng": -3.6920, "avg_daily_visitors": 500000}]
    screens = [{"h3_index": CELL_B, "tipo": "dooh_urbano", "tags": ["business"]}]

    hexes = {hx.h3_index: hx for hx in build_hexes(ine, zones, screens)}
    assert set(hexes) == {CELL_A, CELL_B}
    # B está pegado a la zona → más flujo que A
    assert hexes[CELL_B].flujo_peatonal > hexes[CELL_A].flujo_peatonal
    assert hexes[CELL_B].poi_counts == {"oficinas": 1}
    assert hexes[CELL_A].poi_counts == {}
    # lat/lon del hex = centroide de la celda
    lat, lon = h3.cell_to_latlng(CELL_A)
    assert hexes[CELL_A].lat == pytest.approx(lat)
    assert hexes[CELL_A].lon == pytest.approx(lon)
