"""Migración de los datasets .ts del frontend → Supabase.

Lee los datasets TypeScript del frontend Lovable, calcula `h3_index` (res 8) donde
aplica, y los inserta por batches en Supabase (upsert idempotente). Verifica el
count tras cada tabla. Si una tabla falla, PARA y reporta.

Uso:
    python -m src.ingestion.migrate --frontend ~/proyectos/retailsync-frontend

Requiere: SUPABASE_URL + SUPABASE_SERVICE_KEY en .env, y el esquema ya creado
(migrations/001_init.sql ejecutado en el SQL Editor).
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

import h3
import json5

from src.db.supabase_client import get_client

BATCH = 1000
INE_CITY_NAMES = [
    "Madrid", "Barcelona", "Valencia", "Sevilla", "Zaragoza",
    "Málaga", "Murcia", "Bilbao", "Valladolid", "Alicante",
]


# ─────────────────────────── helpers de parseo ───────────────────────────
def slugify(name: str) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", n.lower()).strip("-")


def _strip_underscores(text: str) -> str:
    return re.sub(r"(?<=\d)_(?=\d)", "", text)


def extract_block(text: str, marker: str, open_char: str) -> str:
    """Extrae el literal ([] o {}) que sigue al primer `marker` y su `=`."""
    close_char = "]" if open_char == "[" else "}"
    idx = text.index(marker)
    eq = text.index("=", idx)
    start = text.index(open_char, eq)
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise ValueError(f"bloque no cerrado para {marker}")


def load_ts(path: Path, marker: str, open_char: str):
    raw = _strip_underscores(path.read_text()).replace(" as const", "")
    return json5.loads(extract_block(raw, marker, open_char))


def h3_or_none(lat, lng) -> str | None:
    try:
        if lat in (None, 0) and lng in (None, 0):
            return None
        return h3.latlng_to_cell(float(lat), float(lng), 8)
    except Exception:
        return None


# ─────────────────────────── loaders por tabla ───────────────────────────
def load_cities(data: Path) -> list[dict]:
    obj = load_ts(data / "cities.ts", "export const CITIES", "{")
    ine_slugs = {slugify(n) for n in INE_CITY_NAMES}
    rows, seen = [], set()
    for _country, lst in obj.items():
        for c in lst:
            slug = slugify(c["name"])
            if slug in seen:
                continue
            seen.add(slug)
            rows.append({
                "slug": slug, "name": c["name"], "country": c.get("country", ""),
                "lat": c.get("lat"), "lng": c.get("lng"), "zoom": c.get("zoom"),
                "currency": c.get("currency"),
                "tier": 1 if slug in ine_slugs else 2,
                "neighborhoods": c.get("neighborhoods", []),
            })
    return rows


def load_city_benchmarks(data: Path) -> list[dict]:
    obj = load_ts(data / "cityBenchmarks.ts", "export const CITY_INCOME_BENCHMARKS", "{")
    return [{"city_name": k, "income_benchmark": v, "ine_data_year": 2023} for k, v in obj.items()]


def load_temporal_profiles(data: Path) -> list[dict]:
    raw = _strip_underscores((data / "temporalProfiles.ts").read_text())
    block = extract_block(raw, "export const ACTIVITY_PROFILES", "{")
    block = re.sub(r"([\{,]\s*)(\d+)(\s*:)", r'\1"\2"\3', block)  # comillas a claves numéricas
    obj = json5.loads(block)
    return [{"zone_type": k, "weekday": v.get("weekday"),
             "saturday": v.get("saturday"), "sunday": v.get("sunday")} for k, v in obj.items()]


def load_acquisition_models(data: Path) -> list[dict]:
    obj = load_ts(data / "acquisitionModel.ts", "export const ACQUISITION_PROFILES", "{")
    return list(obj.values())  # cada valor ya trae 'sector' + las métricas


def load_tier2(data: Path) -> list[dict]:
    arr = load_ts(data / "tier2CitiesMeta.ts", "export const TIER2_META", "[")
    return [{"name": z["name"], "lat": z["lat"], "lng": z["lng"], "pob": z["pob"],
             "base_renta": z["baseRenta"], "mun_code": z["munCode"],
             "top_visitors": z.get("topVisitors")} for z in arr]


INE_COLS = [
    "seccion_censal", "municipio", "municipio_codigo", "distrito", "barrio",
    "lat", "lng", "coords_pendientes", "coords_source",
    "renta_neta_hogar", "renta_neta_persona", "renta_uc_media", "renta_uc_mediana",
    "poblacion", "edad_media", "pct_menor_18", "pct_65_plus", "pct_espanola",
    "tamano_medio_hogar", "pct_hogares_unipersonales", "indice_gini", "ratio_p80_p20",
    "pct_ingresos_salario", "pct_ingresos_pensiones", "pct_ingresos_desempleo",
    "pct_ingresos_otras_prestaciones", "pct_ingresos_otros", "fuente", "ano_dato",
]


# Alias bilingües del INE → nombre canónico presente en el catálogo `cities`
# (réplica de normalizeCity en ineIndex.ts del frontend).
CITY_NORMALIZE = {
    "Valencia/València": "Valencia", "València": "Valencia",
    "Alacant/Alicante": "Alicante", "Alicante/Alacant": "Alicante", "Alacant": "Alicante",
    "Bilbo": "Bilbao", "Malaga": "Málaga",
}


def load_ine(data: Path) -> list[dict]:
    rows = []
    for f in sorted((data / "ine").glob("ineRenta*.ts")):
        arr = load_ts(f, "export const INE_", "[")
        for r in arr:
            row = {c: r.get(c) for c in INE_COLS}
            muni = (r.get("municipio") or "").strip()
            row["city_slug"] = slugify(CITY_NORMALIZE.get(muni, muni))
            row["h3_index"] = None if r.get("coords_pendientes") else h3_or_none(r.get("lat"), r.get("lng"))
            rows.append(row)
    return rows


def _peak_hours(tipo: str) -> dict:
    weekday = "8:00-10:00" if tipo == "business" else ("21:00-01:00" if tipo == "ocio_nocturno" else "12:00-14:00")
    weekend = "22:00-02:00" if tipo == "ocio_nocturno" else "12:00-15:00"
    return {"weekday": weekday, "weekend": weekend}


def load_mobility_zones(data: Path) -> list[dict]:
    rows = []
    for f in sorted(data.glob("footTraffic*.ts")):
        city = f.stem.replace("footTraffic", "")
        slug = slugify(city)
        raw = _strip_underscores(f.read_text())
        profiles = json5.loads(extract_block(raw, "const P", "{"))
        zones = json5.loads(extract_block(raw, "const ZONES", "["))
        for z in zones:
            zona, tipo, lat, lng, _pob, visitors = z[0], z[1], z[2], z[3], z[4], z[5]
            rows.append({
                "city_slug": slug, "zona_mitma": str(zona), "tipo": tipo,
                "lat": lat, "lng": lng, "h3_index": h3_or_none(lat, lng),
                "avg_daily_visitors": visitors,
                "traffic_profile": profiles.get(tipo, profiles.get("periferia")),
                "peak_hours": _peak_hours(tipo),
                "source": "MITMA Open Data Movilidad",
            })
    return rows


# SCREENS_* no son literales (usan Array.from), así que NO se parsean con json5.
# Se vuelcan ejecutando el TS real con tsx (.tooling/emit/emit.ts) → screens.json.
SCREENS_JSON = Path(__file__).resolve().parents[2] / "screens.json"


def load_screens(data: Path) -> list[dict]:
    if not SCREENS_JSON.exists():
        raise FileNotFoundError(
            f"Falta {SCREENS_JSON}. Genéralo con: "
            ".tooling/emit/node_modules/.bin/tsx .tooling/emit/emit.ts > screens.json"
        )
    import json
    data_json = json.loads(SCREENS_JSON.read_text())
    rows = []
    for slug, arr in [("madrid", data_json["madrid"]), ("barcelona", data_json["barcelona"])]:
        for s in arr:
            s = dict(s)
            s["city_slug"] = slug
            s["h3_index"] = h3_or_none(s.get("lat"), s.get("lng"))
            rows.append(s)
    return rows


def load_projects(data: Path) -> list[dict]:
    arr = load_ts(data / "projects.ts", "export const PROJECTS", "[")
    return [{
        "id": p["id"], "label": p.get("label"), "client": p.get("client"),
        "city_slug": slugify(p.get("city", "")), "sector": p.get("sector"),
        "default_profile": p.get("defaultProfile"), "pin": p.get("pin"),
        "context_card": p.get("contextCard"),
        "feeders_nacionales": p.get("feedersNacionales"),
        "mercados_internacionales": p.get("mercadosInternacionales"),
        "profile_rename": p.get("profileRename"),
        "auto_enable_jcdecaux": p.get("autoEnableJCDecaux", False),
    } for p in arr]


# ─────────────────────────── ejecución ───────────────────────────
# (tabla, loader, on_conflict para upsert idempotente)
PLAN = [
    ("cities", load_cities, "slug"),
    ("city_benchmarks", load_city_benchmarks, "city_name"),
    ("temporal_profiles", load_temporal_profiles, "zone_type"),
    ("acquisition_models", load_acquisition_models, "sector"),
    ("tier2_cities", load_tier2, "name"),
    ("ine_renta", load_ine, "seccion_censal"),
    ("mobility_zones", load_mobility_zones, "city_slug,zona_mitma"),
    ("projects", load_projects, "id"),
    # screens al final: SCREENS_* incluye filas generadas por Array.from (no
    # es literal) → parser pendiente. Ver nota al usuario.
    ("screens", load_screens, "id"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Migra los datasets .ts a Supabase.")
    parser.add_argument("--frontend", default="~/proyectos/retailsync-frontend",
                        help="Raíz del repo frontend.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo parsea y cuenta, NO inserta.")
    args = parser.parse_args()
    data = Path(args.frontend).expanduser() / "src" / "data"

    client = get_client()
    report = []
    for table, loader, on_conflict in PLAN:
        try:
            rows = loader(data)
            expected = len(rows)
            if not args.dry_run:
                for i in range(0, len(rows), BATCH):
                    client.table(table).upsert(rows[i : i + BATCH], on_conflict=on_conflict).execute()
                got = client.table(table).select("*", count="exact").limit(0).execute().count
            else:
                got = "—(dry)"
            status = "OK" if (args.dry_run or got == expected) else f"MISMATCH ({got})"
            report.append((table, expected, got, status))
            print(f"  {table:<20} esperadas={expected:<6} insertadas={got:<8} [{status}]")
            if status.startswith("MISMATCH"):
                print(f"\n❌ PARO en '{table}': el count no coincide.")
                break
        except Exception as exc:
            report.append((table, "?", "—", "ERROR"))
            print(f"\n❌ PARO en '{table}': {exc}")
            break

    print("\n=== TABLA DE CONTROL ===")
    print(f"{'tabla':<20}{'esperadas':>10}{'insertadas':>12}  status")
    for t, e, g, s in report:
        print(f"{t:<20}{str(e):>10}{str(g):>12}  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
