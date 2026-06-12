"""API HTTP del Motor INSIGHT (FastAPI).

POST /insight: detector de audiencia oculta + narrativa Claude, cacheado por
hash del input (SQLite local + Supabase insights_cache).

Arrancar en local:
    uvicorn src.api.main:app --reload
Docs interactivas: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import hmac
from typing import Optional

from fastapi import FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from src.config import WINDOWS, settings

app = FastAPI(title="Motor INSIGHT — RetailSync", version="0.3.0")

# CORS: imprescindible para que el frontend (Lovable) pueda llamar desde el
# navegador. Orígenes configurables por entorno (ALLOWED_ORIGINS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.allowed_origins.split(",")],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(provided: Optional[str] = Security(_api_key_header)) -> None:
    """Si INSIGHT_API_KEY está definida, exige la cabecera X-API-Key.

    Vacía = sin auth (solo desarrollo local). Comparación en tiempo constante.
    """
    expected = settings.insight_api_key
    if not expected:
        return
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(401, "API key ausente o inválida (cabecera X-API-Key).")


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


@app.post("/insight", response_model=InsightResponse,
          dependencies=[Security(require_api_key)])
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
