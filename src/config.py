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
