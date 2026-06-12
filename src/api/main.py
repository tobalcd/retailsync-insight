"""API HTTP del Motor INSIGHT (FastAPI).

POST /insight: detector de audiencia oculta + narrativa Claude, cacheado por
hash del input (SQLite local + Supabase insights_cache).

Arrancar en local:
    uvicorn src.api.main:app --reload
Docs interactivas: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.config import WINDOWS

app = FastAPI(title="Motor INSIGHT — RetailSync", version="0.2.0")


# ──────────────── Contratos (esquema de entrada/salida) ────────────────
class InsightRequest(BaseModel):
    city: str = Field(..., description="Slug de ciudad del catálogo, p.ej. 'madrid'.")
    sector: str = Field(..., description="Sector, p.ej. 'banca' o 'moda_lujo'.")
    profile: str = Field(..., description="Perfil de audiencia objetivo (texto libre).")
    window: Optional[str] = Field(
        None, description=f"Ventana temporal: {', '.join(WINDOWS)} o null (todas)."
    )


class HiddenAudienceHex(BaseModel):
    h3_index: str
    lat: float
    lon: float
    zona: str
    resident_score: float
    visitor_score: float
    gap: float
    description: str


class InsightResponse(BaseModel):
    hidden_audience: list[HiddenAudienceHex]
    next_wave: list[HiddenAudienceHex]
    narrative: str
    cached: bool


# ──────────────────────────── Endpoints ────────────────────────────
@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check para Fly.io / Railway."""
    return {"status": "ok"}


@app.post("/insight", response_model=InsightResponse)
def create_insight(req: InsightRequest) -> InsightResponse:
    """Análisis INSIGHT completo para (ciudad, sector, perfil, ventana)."""
    # Import perezoso: que el arranque del API no exija supabase/anthropic.
    from src.engine.insight_service import run_insight, sector_supported

    if req.window is not None and req.window not in WINDOWS:
        raise HTTPException(422, f"Ventana desconocida: '{req.window}'. Usa {sorted(WINDOWS)} o null.")
    if not sector_supported(req.sector):
        raise HTTPException(
            422,
            f"El sector '{req.sector}' es de perfil residencial: el detector de "
            "audiencia oculta no aplica (su insight será 'next_wave', en desarrollo).",
        )
    try:
        return InsightResponse(**run_insight(req.city, req.sector, req.profile, req.window))
    except ValueError as exc:  # ciudad sin datos, etc.
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:  # credenciales ausentes (Supabase / Anthropic)
        raise HTTPException(503, str(exc)) from exc
