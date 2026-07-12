"""Cens d'Activitats Comercials de l'Ajuntament de Barcelona (2024).

Fuente: https://opendata-ajuntament.barcelona.cat/data/es/dataset/cens-locals-planta-baixa-act-economica
(CC BY 4.0 — uso comercial permitido con atribución). Descarga manual (24 MB,
no versionado) a data/barcelona_census/censcomercial2024.csv.

A diferencia del censo de Madrid, este CSV trae Latitud/Longitud directas (no
hace falta convertir UTM) — verificado por punto de control contra
X_UTM_ETRS89/Y_UTM_ETRS89 (huso 31N, EPSG:25831; Barcelona cae en zona 31N, NO
30N como Madrid — longitud >0°E).

La taxonomía es limpia para moda/alimentación (Nom_Grup_Activitat +
Nom_Activitat aíslan bien la categoría), pero para banca el grupo "Finances i
assegurances" MEZCLA bancos con aseguradoras y cambio de divisa — se filtra
además por marca reconocida en Nom_Local (curado a mano, revisado contra los
918 registros reales del grupo).

Uso:
    python -m src.signals.barcelona_census
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CSV_PATH = DATA_DIR / "barcelona_census" / "censcomercial2024.csv"
SOURCE_URL = "https://opendata-ajuntament.barcelona.cat/data/es/dataset/cens-locals-planta-baixa-act-economica"

# Marcas bancarias reconocidas dentro del grupo "Finances i assegurances"
# (que también incluye aseguradoras: Mapfre, Axa, Catalana Occident...).
BANK_BRANDS = {
    "CAIXABANK", "BBVA", "SANTANDER", "SABADELL", "BANKINTER", "KUTXABANK",
    "IBERCAJA", "DEUTSCHE BANK", "ARQUIA", "ABANCA", "LIBERBANK", "LIBER BANK",
    "CAIXA D'ENGINYERS", "ING", "OPENBANK", "UNICAJA", "CAJAMAR", "WIZINK",
    "EVO BANCO", "MEDIOLANUM", "TARGOBANK", "MYINVESTOR", "BNP PARIBAS",
    "BARCLAYS", "TRIODOS", "COINC", "PICHINCHA", "BANCA MARCH", "CECABANK",
    "ANDBANK", "BANCA PUEYO", "RENAULT BANK",
}

# (Nom_Grup_Activitat, {Nom_Activitat válidos}) por sector. None = todo el grupo.
SECTOR_FILTERS: dict[str, tuple[str, set[str] | None]] = {
    "banca": ("Finances i assegurances", None),  # filtrado aparte por marca
    "moda_lujo": ("Equipament personal", {
        "Vestir", "Joieria, rellotgeria i bijuteria", "Calçat i pell",
    }),
    "alimentacion": ("Quotidià alimentari", {
        "Autoservei / Supermercat", "Pa, pastisseria i làctics", "Carn i Porc",
        "Fruites i verdures", "Peix i marisc", "Ous i aus", "Begudes",
        "Plats preparats (no degustació)",
    }),
    # Sectores residenciales (saturación de next_wave). Explorado 2026-07:
    # fuera Floristeries y Segells/monedes (no son interiorismo) y
    # "Joguines i esports" (contaminado de jugueterías).
    "interiorismo_hogar": ("Parament de la llar", {
        "Material equipament llar", "Mobles i articles fusta i metall",
        "Parament ferreteria", "Aparells domèstics",
    }),
    "deportes_fitness": ("Altres", {
        "Gimnàs /fitnes", "Altres equipaments esportius", "Esports",
    }),
    "tecnologia": ("Oci i cultura", {"Informàtica"}),
}


def _is_bank(nom_local: str) -> bool:
    name = nom_local.strip().upper()
    return any(brand in name for brand in BANK_BRANDS)


def load_businesses(sector: str, csv_path: Path = CSV_PATH) -> list[dict]:
    """Locales ACTIUS del sector, con lat/lng. Cachea en JSON por sector."""
    cache = DATA_DIR / f"barcelona_census_{sector}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Falta {csv_path}. Descarga manual (24MB, CC BY 4.0):\n  {SOURCE_URL}"
        )
    if sector not in SECTOR_FILTERS:
        raise ValueError(f"Sector sin mapeo: {sector}")

    grupo, activitats = SECTOR_FILTERS[sector]
    out = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["Nom_Principal_Activitat"].strip() != "Actiu":
                continue
            if row["Nom_Grup_Activitat"].strip() != grupo:
                continue
            if activitats is not None and row["Nom_Activitat"].strip() not in activitats:
                continue
            nom_local = row["Nom_Local"].strip()
            if sector == "banca" and not _is_bank(nom_local):
                continue
            try:
                lat = float(row["Latitud"])
                lon = float(row["Longitud"])
            except ValueError:
                continue
            out.append({
                "id_local": row["ID_Global"],
                "name": nom_local,
                "lat": lat, "lng": lon,
                "distrito": row["Nom_Districte"].strip(),
                "actividad": row["Nom_Activitat"].strip(),
            })

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False))
    return out


def main() -> int:
    if not CSV_PATH.exists():
        print(f"❌ Falta {CSV_PATH}. Descárgalo de {SOURCE_URL} (CSV 2024).", file=sys.stderr)
        return 1
    for sector in SECTOR_FILTERS:
        biz = load_businesses(sector)
        print(f"  {sector:<14} {len(biz):>6} locales activos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
