"""Cliente Supabase compartido.

Crea un único cliente supabase-py usando la SERVICE KEY (acceso de servidor,
se salta RLS). Pensado para uso de backend, nunca para exponer al navegador.
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from src.config import settings


@lru_cache
def get_client() -> Client:
    """Devuelve un cliente Supabase cacheado.

    Lanza un error claro si faltan las credenciales, para no fallar más tarde
    con un mensaje críptico de red.
    """
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError(
            "Faltan credenciales de Supabase. Define SUPABASE_URL y "
            "SUPABASE_SERVICE_KEY en tu .env (copia .env.example)."
        )
    return create_client(settings.supabase_url, settings.supabase_service_key)
