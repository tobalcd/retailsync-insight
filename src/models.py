"""Modelos de dominio del Motor INSIGHT (Pydantic)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Hex(BaseModel):
    """Un hexágono H3 (res 8) con las métricas que usa el detector.

    Los nombres aquí son canónicos en snake_case. El mapeo desde las columnas
    reales de Supabase se hace en la carga (ver src.config.COLUMN_MAP), así que
    si en RetailSync se llaman distinto solo hay que tocar ese diccionario.
    """

    h3_index: str
    lat: float = 0.0
    lon: float = 0.0

    # Perfil residencial
    renta: float = 0.0
    poblacion: float = 0.0

    # Movilidad / paso
    flujo_peatonal: float = 0.0

    # Conteo de POIs por categoría dentro del hex, p.ej. {"oficinas": 12, "transporte": 3}
    poi_counts: dict[str, int] = Field(default_factory=dict)


class HiddenAudienceResult(BaseModel):
    """Un hexágono marcado como 'audiencia oculta detectada'."""

    h3_index: str
    lat: float
    lon: float
    resident_score: float
    visitor_score: float
    gap: float
    description: str
