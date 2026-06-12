"""Tests del bloque narrativa + cache + endpoint."""

from __future__ import annotations

import pytest

from src.models import HiddenAudienceResult


# ─────────────────────────── cache ───────────────────────────
def test_cache_roundtrip_local(tmp_path, monkeypatch):
    from src.config import settings
    from src.cache import store
    monkeypatch.setattr(settings, "local_cache_path", str(tmp_path / "cache.db"))
    # La remota NUNCA se toca desde tests (escribiría en producción).
    monkeypatch.setattr(store, "_remote_get", lambda key: None)
    monkeypatch.setattr(store, "_remote_set", lambda key, value: None)
    key = store.input_hash("madrid", "banca", "ejecutivo", "laborable-manana")
    assert store.get_cached(key) is None
    store.set_cached(key, {"narrative": "hola", "hidden_audience": []})
    assert store.get_cached(key)["narrative"] == "hola"


def test_input_hash_estable_y_sensible():
    from src.cache.store import input_hash
    a = input_hash("madrid", "banca", "ejecutivo", None)
    assert a == input_hash("madrid", "banca", "ejecutivo", None)  # estable
    assert a != input_hash("madrid", "banca", "ejecutivo", "finde")  # sensible
    assert a != input_hash("madrid", "moda_lujo", "ejecutivo", None)


# ─────────────────────────── narrativa (prompt puro) ───────────────────────────
def _result(cell="89390cb0a4bffff", gap=34.7):
    return HiddenAudienceResult(
        h3_index=cell, lat=40.45, lon=-3.69, resident_score=40.6,
        visitor_score=75.3, gap=gap, description="…",
    )


def test_build_prompt_usa_nombres_reales():
    from src.engine.narrative import build_prompt
    prompt = build_prompt(
        "madrid", "banca", "ejecutivo en tránsito", "laborable-manana",
        [_result()], zonas={"89390cb0a4bffff": "Tetuán"},
        pois={"89390cb0a4bffff": ["🚇 Nuevos Ministerios"]},
        discarded={"zona": "Salamanca", "visitor": 60.0, "resident": 50.0,
                   "gap": 10.0, "reason": "el residente ya encaja"},
        clima={"pct_utiles": "72.4", "dias_lluvia": "78"},
    )
    for needle in ["Tetuán", "Nuevos Ministerios", "Salamanca", "72.4",
                   "laborable-manana", "ejecutivo en tránsito", "No inventes"]:
        assert needle in prompt, needle


def test_generate_narrative_sin_key_falla_claro(monkeypatch):
    from src.config import settings
    from src.engine.narrative import generate_narrative
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        generate_narrative("hola")


# ─────────────────────────── endpoint ───────────────────────────
@pytest.fixture
def client(monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "insight_api_key", "")  # sin auth por defecto
    from fastapi.testclient import TestClient
    from src.api.main import app
    return TestClient(app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_insight_rechaza_sector_residencial(client):
    r = client.post("/insight", json={"city": "madrid", "sector": "alimentacion",
                                      "profile": "familias", "window": None})
    assert r.status_code == 422
    assert "next_wave" in r.json()["detail"]


def test_insight_rechaza_ventana_invalida(client):
    r = client.post("/insight", json={"city": "madrid", "sector": "banca",
                                      "profile": "x", "window": "madrugada"})
    assert r.status_code == 422


def test_api_key_exigida_cuando_configurada(client, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "insight_api_key", "secreta-123")
    body = {"city": "madrid", "sector": "banca", "profile": "x", "window": None}

    assert client.post("/insight", json=body).status_code == 401  # sin cabecera
    assert client.post("/insight", json=body,
                       headers={"X-API-Key": "mala"}).status_code == 401

    import src.engine.insight_service as svc
    monkeypatch.setattr(svc, "run_insight", lambda *a: {
        "hidden_audience": [], "next_wave": [], "narrative": "ok", "cached": False})
    r = client.post("/insight", json=body, headers={"X-API-Key": "secreta-123"})
    assert r.status_code == 200


def test_health_abierto_incluso_con_api_key(client, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "insight_api_key", "secreta-123")
    assert client.get("/health").status_code == 200


def test_insight_happy_path_con_mocks(client, monkeypatch):
    import src.engine.insight_service as svc

    def fake_run(city, sector, profile, window):
        return {
            "hidden_audience": [{
                "h3_index": "89390cb0a4bffff", "lat": 40.45, "lon": -3.69,
                "zona": "Tetuán", "resident_score": 40.6, "visitor_score": 75.3,
                "gap": 34.7, "description": "…",
            }],
            "next_wave": [], "narrative": "Texto de prueba.", "cached": False,
        }

    monkeypatch.setattr(svc, "run_insight", fake_run)
    r = client.post("/insight", json={"city": "madrid", "sector": "banca",
                                      "profile": "ejecutivo", "window": "laborable-manana"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hidden_audience"][0]["zona"] == "Tetuán"
    assert body["narrative"] == "Texto de prueba."
    assert body["cached"] is False
