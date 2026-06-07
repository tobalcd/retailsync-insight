"""Cache de análisis (SQLite local + Supabase remota).

ANDAMIAJE — sin lógica todavía.

Idea: cachear cada respuesta /insight por hash del input {city, sector, profile,
window}. Lectura/escritura en SQLite local (rápido, offline) y en la tabla
`insights_cache` de Supabase (compartida con el resto de RetailSync).
"""

from __future__ import annotations

import hashlib
import json


def input_hash(city: str, sector: str, profile: str, window: str) -> str:
    """Hash estable del input — clave de cache. (Esto sí es seguro fijarlo ya.)"""
    payload = json.dumps(
        {"city": city, "sector": sector, "profile": profile, "window": window},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_cached(key: str):
    """Pendiente de implementar (próximo turno)."""
    raise NotImplementedError


def set_cached(key: str, value: dict) -> None:
    """Pendiente de implementar (próximo turno)."""
    raise NotImplementedError
