"""Tests del detector next_wave (cara residencial, puro y sin red)."""

from __future__ import annotations

import pytest

from src.models import Hex
from src.patterns.next_wave import detect_next_wave

# R: residencial puro (alta renta/pob, poco paso) → debe salir
# V: visitante puro (poco residente, mucho paso) → NO debe salir
# M: mixto residencial → sale, por debajo de R
HEXES = [
    Hex(h3_index="R", lat=40.0, lon=-3.0, renta=90, poblacion=90, flujo_peatonal=10,
        flujo_share=0.1, poi_counts={}),
    Hex(h3_index="V", lat=40.1, lon=-3.1, renta=20, poblacion=10, flujo_peatonal=100,
        flujo_share=0.9, poi_counts={"turismo": 10}),
    Hex(h3_index="M", lat=40.2, lon=-3.2, renta=50, poblacion=50, flujo_peatonal=50,
        flujo_share=0.5, poi_counts={}),
]


def test_next_wave_prioriza_residencial_y_excluye_visitante():
    res = detect_next_wave(HEXES, sector="alimentacion")
    ids = [r.h3_index for r in res]
    assert ids == ["R", "M"], ids          # ordenado por encaje residente
    assert "V" not in ids                  # el hex de paso queda fuera
    # gap aquí = sesgo residencial (resident - visitor), positivo
    assert res[0].gap > res[1].gap > 0
    assert res[0].gap == pytest.approx(res[0].resident_score - res[0].visitor_score, abs=0.05)


def test_next_wave_respeta_exclude():
    # excluir R (p.ej. ya está en hidden_audience) → solo queda M
    res = detect_next_wave(HEXES, sector="alimentacion", exclude={"R"})
    assert [r.h3_index for r in res] == ["M"]


def test_next_wave_descripcion_residencial():
    r = detect_next_wave(HEXES, sector="alimentacion")[0]
    assert "vive aquí" in r.description
    assert "sin saturar" in r.description


def test_next_wave_lista_vacia():
    assert detect_next_wave([], sector="alimentacion") == []


def test_next_wave_applies_solo_residenciales():
    # Gate de producto: residenciales sí, visitantes no.
    from src.engine.insight_service import next_wave_applies
    assert next_wave_applies("alimentacion")
    assert next_wave_applies("interiorismo_hogar")
    assert not next_wave_applies("banca")
    assert not next_wave_applies("moda_lujo")
