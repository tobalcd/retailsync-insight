"""Configuración centralizada del Motor INSIGHT.

Lee las variables del entorno (o del fichero `.env` en local) y las expone
como un objeto `settings` tipado. Importar desde cualquier módulo con:

    from src.config import settings
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Supabase ---
    supabase_url: str = ""
    supabase_service_key: str = ""

    # --- Anthropic / Claude ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # --- Datos / dominio ---
    # Nombre de la tabla de hexágonos H3 en Supabase y la columna de ciudad.
    # Ajústalos si en RetailSync se llaman distinto.
    hexes_table: str = "hexes"
    city_column: str = "city"

    # --- Cache local ---
    local_cache_path: str = "data/insight_cache.db"

    # --- Detector de audiencia oculta (umbrales, sobreescribibles por entorno) ---
    # Un hex se marca "audiencia oculta" si el diferencial visitante-residente
    # supera este umbral...
    hidden_audience_gap_threshold: float = 25.0
    # ...y además el score de visitante es alto (no queremos zonas mediocres).
    hidden_audience_visitor_min: float = 65.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia cacheada de Settings (se lee el .env una sola vez)."""
    return Settings()


settings = get_settings()


# ─────────────────────────────────────────────────────────────────────
# Constantes del detector de audiencia oculta
# (pesos y afinidades; se ajustan a mano mientras calibramos el modelo)
# ─────────────────────────────────────────────────────────────────────

# Pesos del score RESIDENTE. Suman 1.0 → score normalizado en 0..1 (luego ×100).
RESIDENT_WEIGHTS = {
    "renta": 0.4,
    "poblacion": 0.3,
    "perfil": 0.3,  # afinidad sectorial del perfil residente
}

# Pesos del score VISITANTE. Suman 1.0.
VISITOR_WEIGHTS = {
    "flujo": 0.5,  # flujo peatonal (movilidad MITMA)
    "poi": 0.3,    # densidad de POIs de paso
    "perfil": 0.2,  # afinidad sectorial del perfil visitante
}

# Categorías de POI que cuentan como "de paso" (público visitante, no residente).
VISIT_POI_CATEGORIES = ["turismo", "transporte", "oficinas"]

# Afinidad de cada sector con el perfil residente vs. visitante (0..1).
# Hardcodeado por ahora; se refinará con datos. Sector desconocido → neutro 0.5.
SECTOR_AFFINITY = {
    "moda_lujo": {"residente": 0.4, "visitante": 0.9},      # turista premium predomina
    "alimentacion": {"residente": 0.8, "visitante": 0.3},    # consumo local
    "banca": {"residente": 0.3, "visitante": 0.8},           # ejecutivo en tránsito
    "restauracion": {"residente": 0.5, "visitante": 0.7},
    "tecnologia": {"residente": 0.5, "visitante": 0.5},
    "viajes_turismo": {"residente": 0.2, "visitante": 0.95},
    "deportes_fitness": {"residente": 0.7, "visitante": 0.4},
    "interiorismo_hogar": {"residente": 0.85, "visitante": 0.2},
}
DEFAULT_AFFINITY = {"residente": 0.5, "visitante": 0.5}

# ─────────────────────────────────────────────────────────────────────
# Agregación espacial → hex H3 res 8
# ─────────────────────────────────────────────────────────────────────

H3_RES = 8

# Decaimiento del flujo de una zona MITMA sobre los hexes vecinos:
# flujo(hex) = Σ_zonas visitantes × exp(-distancia_km / FLUJO_DECAY_KM)
FLUJO_DECAY_KM = 1.5

# Más allá de este radio una zona ya no aporta flujo (corte de cómputo).
FLUJO_MAX_KM = 8.0

# Cómo se traducen las pantallas (screens) a categorías de POI "de paso".
# tipo exacto → categoría; tags → categoría.
SCREEN_TIPO_TO_POI = {"dooh_transporte": "transporte"}
SCREEN_TAG_TO_POI = {"turistico": "turismo", "business": "oficinas"}

# Los venues de Ticketmaster (teatros, estadios, salas) cuentan como POIs de
# esta categoría: son atractores de afluencia visitante.
VENUE_POI_CATEGORY = "turismo"

# ─────────────────────────────────────────────────────────────────────
# Afinidad sector × tipo de zona MITMA (0..1)
# El flujo de una zona se pondera por esto: mide QUIÉN pasa, no solo cuánta
# gente. Para banca, 1M de turistas en Sol vale menos que 300k oficinistas.
# ─────────────────────────────────────────────────────────────────────
ZONE_TYPE_AFFINITY = {
    "banca": {
        "business": 1.0, "comercial_premium": 0.85, "residencial_premium": 0.5,
        "comercial_turistico": 0.3, "periferia": 0.3, "ocio_nocturno": 0.15,
    },
    "moda_lujo": {
        "comercial_premium": 1.0, "comercial_turistico": 0.85, "business": 0.5,
        "residencial_premium": 0.45, "ocio_nocturno": 0.35, "periferia": 0.1,
    },
    "alimentacion": {
        "residencial_premium": 0.9, "periferia": 0.8, "comercial_premium": 0.5,
        "business": 0.35, "comercial_turistico": 0.3, "ocio_nocturno": 0.2,
    },
    "restauracion": {
        "comercial_turistico": 0.9, "ocio_nocturno": 0.85, "comercial_premium": 0.7,
        "business": 0.6, "residencial_premium": 0.5, "periferia": 0.3,
    },
    "tecnologia": {
        "business": 0.7, "comercial_premium": 0.6, "comercial_turistico": 0.5,
        "residencial_premium": 0.5, "ocio_nocturno": 0.4, "periferia": 0.4,
    },
    "viajes_turismo": {
        "comercial_turistico": 1.0, "ocio_nocturno": 0.7, "comercial_premium": 0.6,
        "business": 0.4, "residencial_premium": 0.3, "periferia": 0.15,
    },
    "deportes_fitness": {
        "residencial_premium": 0.8, "periferia": 0.7, "comercial_premium": 0.45,
        "business": 0.4, "comercial_turistico": 0.3, "ocio_nocturno": 0.25,
    },
    "interiorismo_hogar": {
        "residencial_premium": 0.9, "periferia": 0.6, "comercial_premium": 0.55,
        "business": 0.3, "comercial_turistico": 0.2, "ocio_nocturno": 0.1,
    },
}
DEFAULT_ZONE_TYPE_AFFINITY = 0.5  # sector o tipo desconocido → neutro

# ─────────────────────────────────────────────────────────────────────
# Ventanas temporales (parámetro `window` del API)
# Días según las claves del traffic_profile MITMA; horas en formato 0-23.
# El flujo de una zona se modula por su pulso horario DENTRO de la ventana
# relativo a su media (un eje oficinista puntúa alto en laborable-mañana).
# ─────────────────────────────────────────────────────────────────────
WINDOWS = {
    "laborable-manana": {
        "days": ["lunes", "martes", "miercoles", "jueves", "viernes"],
        "hours": list(range(7, 14)),
    },
    "laborable-tarde": {
        "days": ["lunes", "martes", "miercoles", "jueves", "viernes"],
        "hours": list(range(14, 21)),
    },
    "finde": {
        "days": ["sabado", "domingo"],
        "hours": list(range(11, 21)),
    },
    "noche": {
        "days": ["jueves", "viernes", "sabado"],
        "hours": [21, 22, 23, 0, 1],
    },
}
