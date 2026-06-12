"""Mapa HTML de calibración del detector de audiencia oculta.

Pinta los hexes de una ciudad coloreados por gap (visitante − residente) con:
  - nombre humano por hex (distrito INE + parada de metro/venue más relevante)
  - ranking 1-10 sobre el mapa (lo que devolvería el producto)
  - sliders en vivo para los umbrales y check para ocultar el ruido
  - zonas de control del brief marcadas con ⭐

Uso:
    python -m src.tools.calibration_map --city madrid --sector banca --window laborable-manana
    python -m src.tools.calibration_map --city barcelona --sector moda_lujo

Salida: data/calibration_{city}_{sector}.html (autocontenido, Leaflet por CDN).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import h3

from src.config import thresholds_for
from src.patterns.aggregation import (
    cell_of,
    load_city_hexes,
    load_transit_stops,
    load_venues,
)
from src.patterns.scoring import CityStats, resident_score, visitor_score

OUT_DIR = Path(__file__).resolve().parents[2] / "data"

# Zonas de control por ciudad (las del brief de validación).
CONTROLS = {
    "madrid": [
        ("AZCA", 40.4500, -3.6920),
        ("Plaza Castilla", 40.4666, -3.6892),
        ("Av. América", 40.4382, -3.6766),
        ("Sol / Gran Vía", 40.4170, -3.7035),
    ],
    "barcelona": [
        ("Passeig de Gràcia", 41.3920, 2.1650),
        ("Born", 41.3853, 2.1818),
        ("Gòtic", 41.3838, 2.1763),
    ],
}

# Nombres de distrito (códigos INE) — mismos que usa el frontend (ineHelpers.ts).
DISTRICT_NAMES = {
    "madrid": {
        "01": "Centro", "02": "Arganzuela", "03": "Retiro", "04": "Salamanca",
        "05": "Chamartín", "06": "Tetuán", "07": "Chamberí", "08": "Fuencarral-El Pardo",
        "09": "Moncloa-Aravaca", "10": "Latina", "11": "Carabanchel", "12": "Usera",
        "13": "Puente de Vallecas", "14": "Moratalaz", "15": "Ciudad Lineal",
        "16": "Hortaleza", "17": "Villaverde", "18": "Villa de Vallecas",
        "19": "Vicálvaro", "20": "San Blas-Canillejas", "21": "Barajas",
    },
    "barcelona": {
        "01": "Ciutat Vella", "02": "Eixample", "03": "Sants-Montjuïc", "04": "Les Corts",
        "05": "Sarrià-Sant Gervasi", "06": "Gràcia", "07": "Horta-Guinardó",
        "08": "Nou Barris", "09": "Sant Andreu", "10": "Sant Martí",
    },
}


def _fetch_districts(city_slug: str) -> dict[str, str]:
    """h3 (res del detector) → nombre del distrito dominante entre sus secciones."""
    from src.db.supabase_client import get_client

    client = get_client()
    rows, start = [], 0
    while True:
        batch = (
            client.table("ine_renta")
            .select("lat,lng,coords_pendientes,distrito")
            .eq("city_slug", city_slug)
            .range(start, start + 999)
            .execute()
        ).data or []
        rows.extend(batch)
        if len(batch) < 1000:
            break
        start += 1000

    names = DISTRICT_NAMES.get(city_slug, {})
    by_cell: dict[str, Counter] = {}
    for r in rows:
        cell = cell_of(r)
        if not cell:
            continue
        code = (r.get("distrito") or "").strip().zfill(2)
        by_cell.setdefault(cell, Counter())[code] += 1

    return {
        cell: names.get(counts.most_common(1)[0][0], f"Distrito {counts.most_common(1)[0][0]}")
        for cell, counts in by_cell.items()
    }


def _poi_names_by_cell(city_slug: str) -> dict[str, list[str]]:
    """h3 → hasta 3 nombres de POI (paradas primero — son los más reconocibles)."""
    out: dict[str, list[str]] = {}

    def add(row: dict, prefix: str) -> None:
        cell = cell_of(row)
        name = (row.get("name") or "").strip().title()
        if not cell or not name:
            return
        bucket = out.setdefault(cell, [])
        label = f"{prefix} {name}"
        if label not in bucket and len(bucket) < 3:
            bucket.append(label)

    for s in load_transit_stops(city_slug):
        add(s, "🚇")
    for v in load_venues(city_slug):
        add(v, "🎭")
    return out


TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Calibración INSIGHT — __TITLE__</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html,body { margin:0; height:100%; font-family: -apple-system, system-ui, sans-serif; }
  #map { height:100%; }
  #panel {
    position:absolute; top:12px; right:12px; z-index:1000; background:#fff;
    padding:14px 16px; border-radius:10px; box-shadow:0 2px 12px rgba(0,0,0,.25);
    width:280px; font-size:13px;
  }
  #panel h3 { margin:0 0 4px; font-size:15px; }
  #panel .sub { color:#666; margin-bottom:10px; }
  .sliderrow { margin:8px 0 2px; }
  .sliderrow label { display:flex; justify-content:space-between; font-weight:600; }
  input[type=range] { width:100%; }
  #count { margin-top:8px; font-size:14px; font-weight:700; }
  .hint { color:#888; font-size:12px; margin-top:2px; }
  .legend { margin-top:10px; line-height:1.5; color:#444; font-size:12px; }
  .sw { display:inline-block; width:13px; height:13px; border-radius:3px; vertical-align:-2px; margin-right:4px; }
  .checkrow { margin-top:8px; font-weight:600; }
  .rank-badge {
    background:#111; color:#fff; border-radius:50%; width:22px; height:22px;
    line-height:22px; text-align:center; font-weight:700; font-size:12px;
    box-shadow:0 1px 4px rgba(0,0,0,.4); border:2px solid #fff;
  }
  .leaflet-popup-content { font-size:13px; line-height:1.45; }
  .pop-zona { font-size:15px; font-weight:700; margin-bottom:2px; }
  .pop-pois { color:#555; margin:4px 0; }
  .pop-code { color:#aaa; font-size:10px; margin-top:6px; }
  .bar { height:7px; border-radius:4px; background:#eee; margin:2px 0 6px; }
  .bar > div { height:100%; border-radius:4px; }
</style>
</head>
<body>
<div id="map"></div>
<div id="panel">
  <h3>__TITLE__</h3>
  <div class="sub">__SUBTITLE__</div>
  <div class="sliderrow">
    <label>Umbral gap <span id="gapv"></span></label>
    <input type="range" id="gapthr" min="0" max="60" step="1" value="__GAP_THR__">
  </div>
  <div class="sliderrow">
    <label>Umbral visitante <span id="visv"></span></label>
    <input type="range" id="visthr" min="0" max="100" step="1" value="__VIS_THR__">
  </div>
  <div id="count"></div>
  <div class="hint">El producto entrega los 10 mejores (numerados en el mapa).</div>
  <div class="checkrow"><label><input type="checkbox" id="onlypass"> Ocultar los que no pasan</label></div>
  <div class="legend">
    <span class="sw" style="background:#b2182b"></span> visitante ≫ residente (audiencia oculta)<br>
    <span class="sw" style="background:#f7f7f7;border:1px solid #ccc"></span> equilibrado ·
    <span class="sw" style="background:#2166ac"></span> domina residente<br>
    ⭐ zonas de control del caso de prueba
  </div>
</div>
<script>
const HEXES = __HEXES__;
const CONTROLS = __CONTROLS__;

const map = L.map('map').setView([__CLAT__, __CLON__], 13);
L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
  { attribution:'© OpenStreetMap, © CARTO', maxZoom: 18 }).addTo(map);

function gapColor(g) {
  const t = Math.max(-40, Math.min(60, g));
  if (t >= 0) {
    const k = t / 60;
    return `rgb(${Math.round(247-(247-178)*k)},${Math.round(247-(247-24)*k)},${Math.round(247-(247-43)*k)})`;
  }
  const k = -t / 40;
  return `rgb(${Math.round(247-(247-33)*k)},${Math.round(247-(247-102)*k)},${Math.round(247-(247-172)*k)})`;
}

function bar(v, color) {
  return `<div class="bar"><div style="width:${Math.min(100,v)}%;background:${color}"></div></div>`;
}

const layers = [];
HEXES.forEach(h => {
  const poly = L.polygon(h.b, { weight:1, color:'#999', fillColor: gapColor(h.gap), fillOpacity:0.65 });
  const pois = h.names.length ? `<div class="pop-pois">${h.names.join('<br>')}</div>` : '';
  poly.bindPopup(
    `<div class="pop-zona">${h.zona}</div>` + pois +
    `Residente <b>${h.resi}</b>` + bar(h.resi, '#2166ac') +
    `Visitante <b>${h.visit}</b>` + bar(h.visit, '#b2182b') +
    `Diferencial (gap): <b>+${h.gap}</b><br>` +
    `${h.pob.toLocaleString('es')} hab · renta ${Math.round(h.renta).toLocaleString('es')} €` +
    `<div class="pop-code">${h.cell}</div>`
  );
  poly.addTo(map);
  layers.push([h, poly]);
});

CONTROLS.forEach(c => {
  L.marker([c[1], c[2]]).addTo(map)
    .bindTooltip('⭐ ' + c[0], { permanent:true, direction:'top', offset:[-14,-8] });
});

let badges = [];
const gapthr = document.getElementById('gapthr');
const visthr = document.getElementById('visthr');
const onlypass = document.getElementById('onlypass');

function restyle() {
  const g = +gapthr.value, v = +visthr.value, hide = onlypass.checked;
  document.getElementById('gapv').textContent = '≥ ' + g;
  document.getElementById('visv').textContent = '≥ ' + v;
  const passing = [];
  layers.forEach(([h, poly]) => {
    const pass = h.gap >= g && h.visit >= v;
    if (pass) passing.push(h);
    poly.setStyle({
      weight: pass ? 2.5 : 0.7,
      color: pass ? '#000' : '#bbb',
      fillOpacity: pass ? 0.85 : (hide ? 0.04 : 0.35),
      opacity: (!pass && hide) ? 0.05 : 1,
    });
  });
  document.getElementById('count').textContent = passing.length + ' hexes pasan los umbrales';
  badges.forEach(b => map.removeLayer(b));
  badges = passing
    .sort((a, b) => b.gap - a.gap)
    .slice(0, 10)
    .map((h, i) => L.marker(h.c, {
      icon: L.divIcon({ className:'', html:`<div class="rank-badge">${i+1}</div>`, iconSize:[22,22], iconAnchor:[11,11] }),
      interactive: false,
    }).addTo(map));
}
gapthr.addEventListener('input', restyle);
visthr.addEventListener('input', restyle);
onlypass.addEventListener('change', restyle);
restyle();
</script>
</body>
</html>
"""


def build_map(city: str, sector: str, window: str | None) -> Path:
    hexes = load_city_hexes(city, sector, window)
    if not hexes:
        raise RuntimeError(f"Sin hexes para '{city}' — ¿slug correcto?")
    stats = CityStats.from_hexes(hexes, sector)
    districts = _fetch_districts(city)
    poi_names = _poi_names_by_cell(city)

    rows = []
    for hx in hexes:
        if hx.poblacion <= 0 or hx.flujo_peatonal <= 0:
            continue  # mismos filtros que el detector
        rs = resident_score(hx, stats, sector)
        vs = visitor_score(hx, stats, sector)
        boundary = [[round(la, 5), round(lo, 5)] for la, lo in h3.cell_to_boundary(hx.h3_index)]
        rows.append({
            "cell": hx.h3_index, "b": boundary,
            "c": [round(hx.lat, 5), round(hx.lon, 5)],
            "zona": districts.get(hx.h3_index, city.title()),
            "names": poi_names.get(hx.h3_index, []),
            "resi": rs, "visit": vs, "gap": round(vs - rs, 1),
            "pob": hx.poblacion, "renta": hx.renta,
        })

    clat = sum(r["c"][0] for r in rows) / len(rows)
    clon = sum(r["c"][1] for r in rows) / len(rows)
    html = (
        TEMPLATE
        .replace("__TITLE__", f"{city} · {sector}")
        .replace("__SUBTITLE__", f"ventana: {window or 'todas'} · {len(rows)} hexes (res 9)")
        .replace("__GAP_THR__", str(int(thresholds_for(sector)[0])))
        .replace("__VIS_THR__", str(int(thresholds_for(sector)[1])))
        .replace("__HEXES__", json.dumps(rows, ensure_ascii=False))
        .replace("__CONTROLS__", json.dumps(CONTROLS.get(city, []), ensure_ascii=False))
        .replace("__CLAT__", f"{clat:.5f}")
        .replace("__CLON__", f"{clon:.5f}")
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"calibration_{city}_{sector}.html"
    out.write_text(html, encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera el mapa HTML de calibración.")
    parser.add_argument("--city", required=True)
    parser.add_argument("--sector", required=True)
    parser.add_argument("--window", default=None,
                        choices=["laborable-manana", "laborable-tarde", "finde", "noche"])
    args = parser.parse_args()
    out = build_map(args.city, args.sector, args.window)
    print(f"✅ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
