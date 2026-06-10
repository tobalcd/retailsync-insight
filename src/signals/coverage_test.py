"""RetailSync — Test de cobertura de señales externas.

Dos capas con ROLES DISTINTOS en el motor (no se tratan igual):

  1. EVENTOS (Ticketmaster Discovery v2) — candidata a señal ESPACIAL: los
     venues tienen lat/lng → h3_index → gravedad de tráfico por hexágono,
     alimentando el visitor_score del detector. Este test solo mide cobertura
     (¿hay datos donde los necesitamos?); la extracción de venues vendrá después.

  2. CLIMA (Open-Meteo, sin key) — MODULADOR TEMPORAL: señal a nivel
     ciudad+semana para el motor narrativo y el timing de campaña (ventanas
     óptimas, next_wave). NO entra en el detector de audiencia oculta: no
     discrimina entre hexágonos de una misma ciudad.

Uso (la key se lee de TM_API_KEY en .env o del entorno):
    python -m src.signals.coverage_test                # grupo 'es' (Tier-1 España)
    python -m src.signals.coverage_test --group fase2  # ciudades Fase 2 (FR/IT)
    python -m src.signals.coverage_test --group all
    python -m src.signals.coverage_test --solo-clima   # sin key de Ticketmaster

Salida: resumen en consola + data/eventos_cobertura.csv + data/clima_resumen.csv

Robustez: las búsquedas de eventos/venues usan geoPoint (geohash) + radio en
lugar de nombre de ciudad — evita errores por exónimos ('Milano' vs 'Milan')
y formas bilingües ('A Coruña'), la clase de bug que ya nos mordió con el INE.
Solo stdlib + python-dotenv si está disponible.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

# Tier-1 España: las 10 ciudades con INE+MITMA migrados — donde el motor puede
# consumir la señal HOY. Coordenadas de centro urbano.
SPAIN_TIER1 = [
    {"name": "Madrid",     "country": "ES", "lat": 40.4168, "lon": -3.7038},
    {"name": "Barcelona",  "country": "ES", "lat": 41.3851, "lon": 2.1734},
    {"name": "Valencia",   "country": "ES", "lat": 39.4699, "lon": -0.3763},
    {"name": "Sevilla",    "country": "ES", "lat": 37.3891, "lon": -5.9845},
    {"name": "Zaragoza",   "country": "ES", "lat": 41.6488, "lon": -0.8891},
    {"name": "Málaga",     "country": "ES", "lat": 36.7213, "lon": -4.4214},
    {"name": "Murcia",     "country": "ES", "lat": 37.9922, "lon": -1.1307},
    {"name": "Bilbao",     "country": "ES", "lat": 43.2630, "lon": -2.9350},
    {"name": "Valladolid", "country": "ES", "lat": 41.6523, "lon": -4.7245},
    {"name": "Alicante",   "country": "ES", "lat": 38.3452, "lon": -0.4810},
]

# Fase 2 (expansión FR/IT + A Coruña): sin INE/MITMA aún — solo test de cobertura.
FASE2 = [
    {"name": "Lyon",       "country": "FR", "lat": 45.7640, "lon": 4.8357},
    {"name": "Strasbourg", "country": "FR", "lat": 48.5734, "lon": 7.7521},
    {"name": "Milano",     "country": "IT", "lat": 45.4642, "lon": 9.1900},
    {"name": "Torino",     "country": "IT", "lat": 45.0703, "lon": 7.6869},
    {"name": "Verona",     "country": "IT", "lat": 45.4384, "lon": 10.9916},
    {"name": "A Coruña",   "country": "ES", "lat": 43.3623, "lon": -8.4115},
]

GROUPS = {"es": SPAIN_TIER1, "fase2": FASE2, "all": SPAIN_TIER1 + FASE2}

SEGMENTS = ["Music", "Sports", "Arts & Theatre"]

EVENT_WINDOW_DAYS = 90
RADIUS_KM = 15            # radio de búsqueda alrededor del centro urbano
TM_BASE = "https://app.ticketmaster.com/discovery/v2"
RATE_DELAY = 0.35         # ~3 req/s, bajo el límite de 5 req/s

# Umbrales clima "día útil de campaña drive-to-store" (primera aproximación;
# si la señal entra al motor, deberán vivir POR SECTOR en config.py).
RAIN_MM_MAX = 5.0
TEMP_MIN_OK = 2.0
TEMP_MAX_OK = 36.0

OUT_DIR = Path(__file__).resolve().parents[2] / "data"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def load_env_key() -> str:
    """TM_API_KEY del entorno o del .env de la raíz del proyecto."""
    key = os.environ.get("TM_API_KEY", "").strip()
    if key:
        return key
    env = Path(__file__).resolve().parents[2] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("TM_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def get_json(url: str, retries: int = 3) -> dict:
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "RetailSync-coverage-test/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Fallo tras {retries} intentos: {url} → {last_err}")


def iso_z(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


_GH32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash(lat: float, lon: float, precision: int = 9) -> str:
    """Geohash base32 estándar (Ticketmaster acepta hasta 9 caracteres)."""
    lat_lo, lat_hi = -90.0, 90.0
    lon_lo, lon_hi = -180.0, 180.0
    bits, ch, even = 0, 0, True
    out = []
    while len(out) < precision:
        if even:
            mid = (lon_lo + lon_hi) / 2
            if lon >= mid:
                ch = (ch << 1) | 1
                lon_lo = mid
            else:
                ch <<= 1
                lon_hi = mid
        else:
            mid = (lat_lo + lat_hi) / 2
            if lat >= mid:
                ch = (ch << 1) | 1
                lat_lo = mid
            else:
                ch <<= 1
                lat_hi = mid
        even = not even
        bits += 1
        if bits == 5:
            out.append(_GH32[ch])
            bits, ch = 0, 0
    return "".join(out)


# ---------------------------------------------------------------------------
# Capa 1 — Ticketmaster Discovery (cobertura de EVENTOS, futura señal espacial)
# ---------------------------------------------------------------------------

def _tm_total(url: str) -> int:
    data = get_json(url)
    return int(data.get("page", {}).get("totalElements", 0))


def tm_count(apikey: str, city: dict, segment: str | None,
             start: datetime, end: datetime) -> int:
    params = {
        "apikey": apikey,
        "geoPoint": geohash(city["lat"], city["lon"]),
        "radius": str(RADIUS_KM),
        "unit": "km",
        "startDateTime": iso_z(start),
        "endDateTime": iso_z(end),
        "size": "1",
    }
    if segment:
        params["segmentName"] = segment
    return _tm_total(f"{TM_BASE}/events.json?{urllib.parse.urlencode(params)}")


def tm_venues(apikey: str, city: dict) -> int:
    params = {
        "apikey": apikey,
        "geoPoint": geohash(city["lat"], city["lon"]),
        "radius": str(RADIUS_KM),
        "unit": "km",
        "size": "1",
    }
    return _tm_total(f"{TM_BASE}/venues.json?{urllib.parse.urlencode(params)}")


def seg_key(segment: str) -> str:
    return "eventos_" + segment.lower().replace(" & ", "_").replace(" ", "_")


def run_events_layer(apikey: str, cities: list[dict]) -> list[dict]:
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=EVENT_WINDOW_DAYS)
    rows = []
    print(f"\n=== EVENTOS (Ticketmaster, próximos {EVENT_WINDOW_DAYS} días, radio {RADIUS_KM} km) ===")
    header = f"{'Ciudad':<12} {'País':<4} {'Total':>6} " + " ".join(f"{s[:8]:>8}" for s in SEGMENTS) + f" {'Venues':>7}"
    print(header)
    print("-" * len(header))
    for city in cities:
        row = {"ciudad": city["name"], "pais": city["country"]}
        row["total_eventos"] = tm_count(apikey, city, None, start, end)
        time.sleep(RATE_DELAY)
        for seg in SEGMENTS:
            row[seg_key(seg)] = tm_count(apikey, city, seg, start, end)
            time.sleep(RATE_DELAY)
        row["venues"] = tm_venues(apikey, city)
        time.sleep(RATE_DELAY)
        seg_cells = " ".join(f"{row[seg_key(s)]:>8}" for s in SEGMENTS)
        print(f"{city['name']:<12} {city['country']:<4} {row['total_eventos']:>6} {seg_cells} {row['venues']:>7}")
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Capa 2 — Open-Meteo (MODULADOR TEMPORAL: narrativa/timing, no detector)
# ---------------------------------------------------------------------------

def run_weather_layer(cities: list[dict]) -> list[dict]:
    end = date.today() - timedelta(days=7)
    start = end - timedelta(days=365)
    rows = []
    print("\n=== CLIMA (Open-Meteo, últimos 12 meses) — modulador temporal ===")
    print(f"Criterio 'día útil': lluvia < {RAIN_MM_MAX}mm, Tmin > {TEMP_MIN_OK}°C, Tmax < {TEMP_MAX_OK}°C")
    header = f"{'Ciudad':<12} {'Días útiles':>11} {'% útiles':>9} {'Días lluvia':>12} {'mm/año':>8}"
    print(header)
    print("-" * len(header))
    for city in cities:
        params = {
            "latitude": city["lat"],
            "longitude": city["lon"],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "precipitation_sum,temperature_2m_min,temperature_2m_max",
            "timezone": "auto",
        }
        url = "https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(params)
        data = get_json(url)
        daily = data.get("daily", {})
        precip = daily.get("precipitation_sum") or []
        tmin = daily.get("temperature_2m_min") or []
        tmax = daily.get("temperature_2m_max") or []
        n = len(precip)
        useful = sum(
            1 for i in range(n)
            if precip[i] is not None and tmin[i] is not None and tmax[i] is not None
            and precip[i] < RAIN_MM_MAX and tmin[i] > TEMP_MIN_OK and tmax[i] < TEMP_MAX_OK
        )
        rainy = sum(1 for p in precip if p is not None and p >= 1.0)
        total_mm = round(sum(p for p in precip if p is not None), 1)
        pct = round(100 * useful / n, 1) if n else 0.0
        rows.append({
            "ciudad": city["name"], "dias_analizados": n, "dias_utiles": useful,
            "pct_utiles": pct, "dias_lluvia_1mm": rainy, "precipitacion_anual_mm": total_mm,
        })
        print(f"{city['name']:<12} {useful:>11} {pct:>8}% {rainy:>12} {total_mm:>8}")
        time.sleep(0.5)
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"→ guardado {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Test de cobertura de señales externas.")
    parser.add_argument("--group", choices=sorted(GROUPS), default="es",
                        help="Grupo de ciudades (def: es = Tier-1 España).")
    parser.add_argument("--solo-clima", action="store_true", help="Saltar Ticketmaster.")
    args = parser.parse_args()
    cities = GROUPS[args.group]

    if not args.solo_clima:
        apikey = load_env_key()
        if not apikey:
            print("AVISO: falta TM_API_KEY (en .env o entorno). Capa de eventos saltada.")
        else:
            try:
                write_csv(OUT_DIR / "eventos_cobertura.csv", run_events_layer(apikey, cities))
            except Exception as e:  # noqa: BLE001
                print(f"\nERROR en capa de eventos: {e}")

    try:
        write_csv(OUT_DIR / "clima_resumen.csv", run_weather_layer(cities))
    except Exception as e:  # noqa: BLE001
        print(f"\nERROR en capa de clima: {e}")

    print("\nLectura de resultados:")
    print(" - Eventos: pocas decenas de eventos/90 días en una ciudad = cobertura TM")
    print("   insuficiente ahí (en IT domina TicketOne) → fuente alternativa antes de integrar.")
    print(" - Clima: si la dispersión del % de días útiles entre ciudades es <5 puntos,")
    print("   la señal solo aporta a nivel semana (timing), no comparando ciudades.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
