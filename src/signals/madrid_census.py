"""Censo de Locales y Actividades del Ayuntamiento de Madrid.

Fuente: https://datos.madrid.es/dataset/200085-0-censo-locales (fichero
"Actividades", CC BY 4.0 — uso comercial permitido con atribución).
Descarga manual (119 MB, no versionado) a data/madrid_census/actividades.csv.

Censo oficial, no crowdsourcing: mucho más denso y fiable que OSM como verdad
externa para el Nivel 1 en Madrid (1.351 sucursales bancarias reales frente a
las 953 detectadas por Overpass, p.ej.), y candidato a señal de POI nueva.

Coordenadas en ETRS89 UTM huso 30N (EPSG:25830) — verificado por punto de
control contra una dirección real. Se convierten a lat/lng con pyproj.

Uso:
    python -m src.signals.madrid_census                # resumen de conteos
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pyproj

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CSV_PATH = DATA_DIR / "madrid_census" / "actividades.csv"
SOURCE_URL = "https://datos.madrid.es/dataset/200085-0-censo-locales"

_UTM30N_TO_WGS84 = pyproj.Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)

# epígrafe (CNAE, texto tal cual en el censo) → sector del motor. Solo retail/
# servicio real de cara al público (excluye manufactura/mayorista con el mismo
# nombre de sector, p.ej. "INDUSTRIA TEXTIL" no es moda_lujo).
SECTOR_EPIGRAFES: dict[str, set[str]] = {
    "banca": {
        "INTERMEDIACION MONETARIA: BANCOS, CAJAS DE AHORRO",
    },
    "moda_lujo": {
        "COMERCIO AL POR MENOR DE PRENDAS DE VESTIR EN ESTABLECIMIENTOS ESPECIALIZADOS",
        "COMERCIO AL POR MENOR DE JOYAS, RELOJERIA Y BISUTERIA",
        "COMERCIO AL POR MENOR DE CALZADO Y ARTICULOS DE CUERO EN ESTABLECIMIENTOS ESPECIALIZADOS",
    },
    "alimentacion": {
        "OTRO COMERCIO AL POR MENOR DE PRODUCTOS ALIMENTICIOS (PERECEDEROS Y NO PERECEDEROS) CON VENDEDOR N.C.O.P.",
        "COMERCIO AL POR MENOR EN ESTABLECIMIENTOS NO ESPECIALIZADOS, CON PREDOMINIO EN PRODUCTOS ALIMENTICIOS, BEBIDAS Y TABACO (AUTOSERVICIO)",
        "COMERCIO AL POR MENOR DE FRUTAS Y HORTALIZAS SIN OBRADOR",
        "COMERCIO AL POR MENOR DE PRODUCTOS ALIMENTICIOS NO PERECEDEROS ENVASADOS",
        "COMERCIO AL POR MENOR DE PAN Y PRODUCTOS DE PANADERIA Y BOLLERIA CON OBRADOR",
        "COMERCIO AL POR MENOR DE PAN Y PRODUCTOS DE PANADERIA Y BOLLERIA SIN OBRADOR",
        "COMERCIO AL POR MENOR DE CHARCUTERIA",
        "COMERCIO AL POR MENOR DE CARNICERIA",
        "COMERCIO AL POR MENOR DE CARNICERIA-SALCHICHERIA",
        "COMERCIO AL POR MENOR DE PESCADOS Y MARISCOS SIN OBRADOR",
        "COMERCIO AL POR MENOR DE AVES, HUEVOS Y CAZA SIN OBRADOR",
    },
    # Sectores residenciales (para saturación de next_wave). Epígrafes
    # explorados contra el CSV real 2026-07 — solo categorías inequívocas
    # (fuera clubes/instalaciones deportivas: a menudo no son competencia
    # de consumo directa).
    "interiorismo_hogar": {
        "COMERCIO AL POR MENOR DE MUEBLES",
        "COMERCIO AL POR MENOR DE TEXTILES PARA EL HOGAR",
        "COMERCIO AL POR MENOR DE ARTICULOS DE FERRETERIA",
        "COMERCIO AL POR MENOR DE ARTICULOS DE USO DOMESTICO EN ESTABLECIMIENTO ESPECIALIZADO",
        "COMERCIO AL POR MENOR DE MUEBLES DE COCINA",
        "COMERCIO AL POR MENOR DE APARATOS DE ILUMINACION",
    },
    "deportes_fitness": {
        "ACTIVIDADES DE LOS GIMNASIOS",
        "COMERCIO AL POR MENOR DE ARTICULOS DEPORTIVOS",
    },
    "tecnologia": {
        "COMERCIO AL POR MENOR DE PRODUCTOS DE TELEFONIA Y TELECOMUNICACIONES",
        "COMERCIO AL POR MENOR DE PRODUCTOS INFORMATICOS (ORDENADORES, PROGRAMAS, EQUIPOS PERIFERICOS Y CONSUMIBLES)",
        "COMERCIO AL POR MENOR DE ELECTRODOMESTICOS",
    },
}


def utm_to_latlng(x: float, y: float) -> tuple[float, float]:
    lon, lat = _UTM30N_TO_WGS84.transform(x, y)
    return lat, lon


def load_businesses(sector: str, csv_path: Path = CSV_PATH) -> list[dict]:
    """Locales ABIERTOS del sector, con lat/lng. Cachea en JSON por sector."""
    cache = DATA_DIR / f"madrid_census_{sector}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Falta {csv_path}. Descarga manual (119MB, CC BY 4.0):\n"
            f"  {SOURCE_URL} -> fichero 'Actividades' (CSV)"
        )

    epigrafes = SECTOR_EPIGRAFES.get(sector)
    if not epigrafes:
        raise ValueError(f"Sector sin mapeo de epígrafes: {sector}")

    out = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter=";"):
            if row["desc_situacion_local"].strip() != "Abierto":
                continue
            if row["desc_epigrafe"].strip() not in epigrafes:
                continue
            try:
                x = float(row["coordenada_x_local"])
                y = float(row["coordenada_y_local"])
            except ValueError:
                continue
            lat, lon = utm_to_latlng(x, y)
            out.append({
                "id_local": row["id_local"],
                "name": row["rotulo"].strip(),
                "lat": lat, "lng": lon,
                "distrito": row["desc_distrito_local"].strip(),
                "epigrafe": row["desc_epigrafe"].strip(),
            })

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False))
    return out


def main() -> int:
    if not CSV_PATH.exists():
        print(f"❌ Falta {CSV_PATH}. Descárgalo de {SOURCE_URL} (fichero 'Actividades' CSV).",
              file=sys.stderr)
        return 1
    for sector in SECTOR_EPIGRAFES:
        biz = load_businesses(sector)
        print(f"  {sector:<14} {len(biz):>6} locales abiertos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
