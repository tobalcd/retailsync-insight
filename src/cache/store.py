"""Cache de análisis: SQLite local (primaria) + Supabase `insights_cache` (compartida).

Estrategia:
  - Lectura: local primero (rápida, offline); si falla, remota — y si la remota
    acierta, se rehidrata la local.
  - Escritura: local siempre; remota best-effort (un fallo de red no rompe la
    respuesta al usuario, solo se pierde la compartición).

La clave incluye CACHE_VERSION: al cambiar la fórmula de scoring se incrementa
y toda la cache anterior queda invalidada de forma natural.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.config import settings

# Súbela cuando cambie el modelo de scoring o el formato de respuesta.
CACHE_VERSION = "2026-06-12.1"

REMOTE_TABLE = "insights_cache"


def input_hash(city: str, sector: str, profile: str, window: str | None) -> str:
    """Hash estable del input — clave de cache (incluye versión del modelo)."""
    payload = json.dumps(
        {"v": CACHE_VERSION, "city": city, "sector": sector,
         "profile": profile, "window": window},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ─────────────────────────── SQLite local ───────────────────────────
def _db() -> sqlite3.Connection:
    path = Path(settings.local_cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "create table if not exists insights_cache ("
        " key text primary key, payload text not null, created_at text not null)"
    )
    return conn


def _local_get(key: str) -> dict | None:
    with _db() as conn:
        row = conn.execute(
            "select payload from insights_cache where key = ?", (key,)
        ).fetchone()
    return json.loads(row[0]) if row else None


def _local_set(key: str, value: dict) -> None:
    with _db() as conn:
        conn.execute(
            "insert or replace into insights_cache (key, payload, created_at) values (?,?,?)",
            (key, json.dumps(value, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat()),
        )


# ─────────────────────────── Supabase remota ───────────────────────────
def _remote_get(key: str) -> dict | None:
    try:
        from src.db.supabase_client import get_client

        rows = (
            get_client().table(REMOTE_TABLE)
            .select("payload").eq("key", key).limit(1).execute()
        ).data
        return rows[0]["payload"] if rows else None
    except Exception:  # noqa: BLE001 — remota es opcional, nunca rompe
        return None


def _remote_set(key: str, value: dict) -> None:
    try:
        from src.db.supabase_client import get_client

        get_client().table(REMOTE_TABLE).upsert(
            {"key": key, "payload": value}, on_conflict="key"
        ).execute()
    except Exception:  # noqa: BLE001
        pass


# ─────────────────────────── API pública ───────────────────────────
def get_cached(key: str) -> dict | None:
    value = _local_get(key)
    if value is not None:
        return value
    value = _remote_get(key)
    if value is not None:
        _local_set(key, value)  # rehidrata la local
    return value


def set_cached(key: str, value: dict) -> None:
    _local_set(key, value)
    _remote_set(key, value)
