"""Ingesta de hexágonos H3 desde Supabase a un parquet local.

Lee todos los hexágonos de una ciudad desde la tabla de hexes en Supabase y los
guarda en `data/hexes_{city}.parquet` para trabajar en local sin pegarle a la BD
en cada análisis.

Uso (desde la raíz del repo, con el venv activado):

    python -m src.ingestion.fetch_hexes --city madrid
    python -m src.ingestion.fetch_hexes --city "san sebastian" --table hexes --city-column city

Supuestos (ajustables por flags o en src/config.py):
  - Existe una tabla de hexágonos (por defecto `hexes`) con una columna de
    ciudad (por defecto `city`).
  - Se traen TODAS las columnas (`select *`). Más adelante podemos seleccionar
    solo las métricas que el motor necesite.

Si la tabla o la columna se llaman distinto en RetailSync, no edites el código:
pásalos con --table / --city-column, o fíjalos en el .env (HEXES_TABLE, CITY_COLUMN).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from src.config import settings
from src.db.supabase_client import get_client

# Supabase pagina las respuestas; pedimos en bloques de este tamaño.
PAGE_SIZE = 1000


def fetch_hexes(city: str, table: str, city_column: str) -> pd.DataFrame:
    """Trae todos los hexágonos de una ciudad, paginando hasta agotar resultados."""
    client = get_client()
    rows: list[dict] = []
    start = 0

    while True:
        end = start + PAGE_SIZE - 1
        response = (
            client.table(table)
            .select("*")
            .eq(city_column, city)
            .range(start, end)
            .execute()
        )
        batch = response.data or []
        rows.extend(batch)
        print(f"  …{len(rows)} hexágonos leídos", file=sys.stderr)

        # Si el lote viene incompleto, ya no quedan más páginas.
        if len(batch) < PAGE_SIZE:
            break
        start += PAGE_SIZE

    return pd.DataFrame(rows)


def save_parquet(df: pd.DataFrame, city: str, out_dir: Path) -> Path:
    """Guarda el DataFrame en data/hexes_{city}.parquet y devuelve la ruta."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Normaliza el nombre de fichero: minúsculas y espacios -> guion bajo.
    slug = city.strip().lower().replace(" ", "_")
    path = out_dir / f"hexes_{slug}.parquet"
    df.to_parquet(path, index=False)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingesta de hexágonos H3 desde Supabase.")
    parser.add_argument("--city", required=True, help="Ciudad a descargar, p.ej. 'madrid'.")
    parser.add_argument(
        "--table",
        default=settings.hexes_table,
        help=f"Tabla de hexes en Supabase (def: {settings.hexes_table}).",
    )
    parser.add_argument(
        "--city-column",
        default=settings.city_column,
        help=f"Columna de ciudad en esa tabla (def: {settings.city_column}).",
    )
    parser.add_argument(
        "--out-dir",
        default="data",
        help="Carpeta de salida del parquet (def: data).",
    )
    args = parser.parse_args()

    print(f"Descargando hexágonos de '{args.city}' desde la tabla '{args.table}'…", file=sys.stderr)
    df = fetch_hexes(args.city, args.table, args.city_column)

    if df.empty:
        print(
            f"⚠️  0 hexágonos para '{args.city}'. ¿Es correcto el nombre de la ciudad "
            f"y de la columna '{args.city_column}'?",
            file=sys.stderr,
        )
        sys.exit(1)

    path = save_parquet(df, args.city, Path(args.out_dir))
    print(f"✅ {len(df)} hexágonos · {df.shape[1]} columnas → {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
