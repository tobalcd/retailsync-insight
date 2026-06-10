"""API HTTP del Motor INSIGHT (FastAPI).

ANDAMIAJE: define los contratos (request/response) y el endpoint POST /insight,
pero la lógica del motor todavía NO está implementada. El endpoint devuelve 501
hasta que conectemos el detector de audiencia oculta y el motor narrativo.

Arrancar en local:
    uvicorn src.api.main:app --reload
Docs interactivas: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Motor INSIGHT — RetailSync", version="0.1.0")


# ──────────────── Contratos (esquema de entrada/salida) ────────────────
class InsightRequest(BaseModel):
    city: str = Field(..., description="Ciudad del análisis, p.ej. 'madrid'.")
    sector: str = Field(..., description="Sector comercial, p.ej. 'restauración'.")
    profile: str = Field(..., description="Perfil de audiencia objetivo.")
    window: str = Field(..., description="Ventana temporal de movilidad, p.ej. 'laborable-tarde'.")


class HiddenAudienceHex(BaseModel):
    h3_index: str
    score: float
    description: str


class InsightResponse(BaseModel):
    hidden_audience: list[HiddenAudienceHex]
    next_wave: list[HiddenAudienceHex]
    narrative: str


# ──────────────────────────── Endpoints ────────────────────────────
@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check para Fly.io / Railway."""
    return {"status": "ok"}


@app.post("/insight", response_model=InsightResponse)
def create_insight(req: InsightRequest) -> InsightResponse:
    """Genera el análisis INSIGHT para un (ciudad, sector, perfil, ventana).

    TODO (siguientes turnos):
      1. Mirar la cache (hash del input) en SQLite local + Supabase insights_cache.
      2. Detector de audiencia oculta  -> src/patterns/hidden_audience.py
      3. Motor narrativo (Claude API)  -> src/engine/narrative.py
      4. Guardar en cache y devolver.
    """
    raise HTTPException(status_code=501, detail="Motor INSIGHT aún no implementado.")
