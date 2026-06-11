"""Tests del detector de audiencia oculta.

  1. Control sintético  : números fijos, gap y ordenamiento verificables a mano.
  4. Edge / datos pobres : no debe romper, degrada suavemente.
  2/3. Reales (Madrid, Barcelona): requieren Supabase → se SALTAN si no hay
        credenciales. La validación semántica (AZCA, Passeig de Gràcia) es manual
        vía la CLI; aquí solo comprobamos estructura cuando hay datos.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.models import Hex
from src.patterns.hidden_audience import detect_from_hexes, detect_hidden_audience

HAS_SUPABASE = bool(settings.supabase_url and settings.supabase_service_key)
skip_no_creds = pytest.mark.skipif(
    not HAS_SUPABASE, reason="Sin credenciales de Supabase en .env (test de datos reales)."
)


# ───────────────────────────── 1. Control sintético ─────────────────────────────
def test_control_sintetico_gap_y_orden():
    """3 hex con números fijos para sector 'banca' (resi 0.3 / visit 0.8).

    Esperado (pesos: flujo .25 + composición .25 + poi .3 + perfil .2):
      A: alto flujo/share/POI, baja renta/pob -> resi 9.0,  visit 96.0, gap 87.0 (oculto)
      B: flujo/share/POI medios               -> resi 19.9, visit 66.1, gap 46.2 (oculto)
      C: residente puro, sin paso             -> excluido (visitante bajo, gap negativo)
    """
    hexes = [
        Hex(h3_index="hexA", lat=40.0, lon=-3.0, renta=20, poblacion=5, flujo_peatonal=100,
            flujo_share=0.9, poi_counts={"oficinas": 10, "transporte": 10}),
        Hex(h3_index="hexB", lat=40.1, lon=-3.1, renta=40, poblacion=8, flujo_peatonal=90,
            flujo_share=0.7, poi_counts={"oficinas": 6}),
        Hex(h3_index="hexC", lat=40.2, lon=-3.2, renta=100, poblacion=100, flujo_peatonal=5,
            flujo_share=0.1, poi_counts={}),
    ]

    results = detect_from_hexes(hexes, sector="banca")

    # Solo A y B superan los umbrales; C queda fuera.
    ids = [r.h3_index for r in results]
    assert ids == ["hexA", "hexB"], ids
    assert "hexC" not in ids

    # Valores de control (tolerancia por redondeo).
    a, b = results
    assert a.resident_score == pytest.approx(9.0, abs=0.2)
    assert a.visitor_score == pytest.approx(96.0, abs=0.2)
    assert a.gap == pytest.approx(87.0, abs=0.2)
    assert b.gap == pytest.approx(46.2, abs=0.2)

    # Invariantes: gap == visitante - residente, y orden descendente por gap.
    for r in results:
        assert r.gap == pytest.approx(r.visitor_score - r.resident_score, abs=0.05)
    assert [r.gap for r in results] == sorted((r.gap for r in results), reverse=True)


def test_descripcion_template_no_llm():
    hexes = [
        Hex(h3_index="hexA", renta=20, poblacion=5, flujo_peatonal=100,
            poi_counts={"oficinas": 10, "transporte": 10}),
        Hex(h3_index="hexB", renta=40, poblacion=8, flujo_peatonal=90, poi_counts={"oficinas": 6}),
    ]
    r = detect_from_hexes(hexes, sector="banca")[0]
    assert "Score residente" in r.description
    assert "movilidad" in r.description


# ───────────────────────────── 4. Edge / datos pobres ─────────────────────────────
def test_edge_datos_pobres_no_rompe():
    """Ciudad con POIs vacíos, rentas iguales y algún hex sin flujo/población.

    Debe filtrar mar/zonas muertas, no dividir por cero y devolver una lista.
    """
    hexes = [
        Hex(h3_index="dead_flujo0", renta=50, poblacion=10, flujo_peatonal=0, poi_counts={}),
        Hex(h3_index="dead_pob0", renta=50, poblacion=0, flujo_peatonal=20, poi_counts={}),
        Hex(h3_index="vivo", renta=50, poblacion=10, flujo_peatonal=10, poi_counts={}),
    ]
    results = detect_from_hexes(hexes, sector="viajes_turismo")
    assert isinstance(results, list)
    # Los hex muertos nunca aparecen.
    assert all(r.h3_index not in {"dead_flujo0", "dead_pob0"} for r in results)


def test_edge_lista_vacia():
    assert detect_from_hexes([], sector="banca") == []


def test_edge_un_solo_hex_no_rompe():
    # min == max en todas las métricas → minmax_norm no debe explotar.
    hexes = [Hex(h3_index="solo", renta=50, poblacion=10, flujo_peatonal=10, poi_counts={})]
    assert isinstance(detect_from_hexes(hexes, sector="banca"), list)


# ───────────────────────────── 2/3. Datos reales (skip si no hay creds) ─────────────
@skip_no_creds
def test_real_madrid_banca():
    results = detect_hidden_audience("madrid", "banca")
    assert len(results) <= 10
    assert [r.gap for r in results] == sorted((r.gap for r in results), reverse=True)
    # Validación semántica (AZCA/Castellana, Plaza Castilla, Av. de América) -> manual vía CLI.
    print("\n[madrid/banca] top hexes:", [(r.h3_index, r.gap) for r in results])


@skip_no_creds
def test_real_barcelona_moda():
    results = detect_hidden_audience("barcelona", "moda_lujo")
    assert len(results) <= 10
    assert [r.gap for r in results] == sorted((r.gap for r in results), reverse=True)
    print("\n[barcelona/moda_lujo] top hexes:", [(r.h3_index, r.gap) for r in results])
