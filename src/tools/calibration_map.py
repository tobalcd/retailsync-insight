"""Mapa HTML de calibración del detector de audiencia oculta.

Pinta todos los hexes de una ciudad coloreados por gap (visitante − residente),
con popups de métricas, las zonas de control marcadas y sliders en vivo para
los dos umbrales (gap y visitante). Pensado para sesiones de calibración con
el PO: mueve los sliders, mira qué hexes pasan, y fijamos los umbrales.

Uso:
    python -m src.tools.calibration_map --city madrid --sector banca --window laborable-manana
    python -m src.tools.calibration_map --city barcelona --sector moda_lujo

Salida: data/calibration_{city}_{sector}.html (autocontenido, Leaflet por CDN).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import h3

from src.config import settings
from src.patterns.aggregation import load_city_hexes
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
    width:270px; font-size:13px;
  }
  #panel h3 { margin:0 0 6px; font-size:14px; }
  #panel .sub { color:#666; margin-bottom:10px; }
  .sliderrow { margin:8px 0 2px; }
  .sliderrow label { display:flex; justify-content:space-between; font-weight:600; }
  input[type=range] { width:100%; }
  #count { margin-top:10px; font-size:15px; font-weight:700; }
  .legend { margin-top:10px; line-height:1.5; color:#444; }
  .sw { display:inline-block; width:14px; height:14px; border-radius:3px; vertical-align:-2px; margin-right:4px; }
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
  <div class="legend">
    <span class="sw" style="background:#b2182b"></span> gap alto (audiencia oculta)<br>
    <span class="sw" style="background:#f7f7f7;border:1px solid #ccc"></span> gap ≈ 0<br>
    <span class="sw" style="background:#2166ac"></span> gap negativo (residente domina)<br>
    Borde negro grueso = pasa umbrales. ⭐ = zona de control.
  </div>
</div>
<script>
const HEXES = __HEXES__;
const CONTROLS = __CONTROLS__;

const map = L.map('map').setView([__CLAT__, __CLON__], 13);
L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
  { attribution:'© OpenStreetMap, © CARTO', maxZoom: 18 }).addTo(map);

function gapColor(g) {
  // diverging azul (−40) → blanco (0) → rojo (+60)
  const t = Math.max(-40, Math.min(60, g));
  if (t >= 0) {
    const k = t / 60;
    return `rgb(${Math.round(247-(247-178)*k)},${Math.round(247-(247-24)*k)},${Math.round(247-(247-43)*k)})`;
  }
  const k = -t / 40;
  return `rgb(${Math.round(247-(247-33)*k)},${Math.round(247-(247-102)*k)},${Math.round(247-(247-172)*k)})`;
}

const layers = [];
HEXES.forEach(h => {
  const poly = L.polygon(h.b, { weight:1, color:'#999', fillColor: gapColor(h.gap), fillOpacity:0.65 });
  poly.bindPopup(
    `<b>${h.cell}</b><br>` +
    `residente <b>${h.resi}</b> · visitante <b>${h.visit}</b> · gap <b>${h.gap}</b><br>` +
    `población ${h.pob.toLocaleString('es')} · renta ${Math.round(h.renta).toLocaleString('es')} €<br>` +
    `flujo ${Math.round(h.flujo).toLocaleString('es')} · POIs ${h.pois}`
  );
  poly.addTo(map);
  layers.push([h, poly]);
});

CONTROLS.forEach(c => {
  L.marker([c[1], c[2]]).addTo(map)
    .bindTooltip('⭐ ' + c[0], { permanent:true, direction:'top', offset:[-14,-8] });
});

const gapthr = document.getElementById('gapthr');
const visthr = document.getElementById('visthr');
function restyle() {
  const g = +gapthr.value, v = +visthr.value;
  document.getElementById('gapv').textContent = '≥ ' + g;
  document.getElementById('visv').textContent = '≥ ' + v;
  let n = 0;
  layers.forEach(([h, poly]) => {
    const pass = h.gap >= g && h.visit >= v;
    if (pass) n++;
    poly.setStyle({
      weight: pass ? 2.5 : 0.7,
      color: pass ? '#000' : '#bbb',
      fillOpacity: pass ? 0.85 : 0.35,
    });
  });
  document.getElementById('count').textContent = n + ' hexes pasan los umbrales';
}
gapthr.addEventListener('input', restyle);
visthr.addEventListener('input', restyle);
restyle();
</script>
</body>
</html>
"""


def build_map(city: str, sector: str, window: str | None) -> Path:
    hexes = load_city_hexes(city, sector, window)
    if not hexes:
        raise RuntimeError(f"Sin hexes para '{city}' — ¿slug correcto?")
    stats = CityStats.from_hexes(hexes)

    rows = []
    for hx in hexes:
        if hx.poblacion <= 0 or hx.flujo_peatonal <= 0:
            continue  # mismos filtros que el detector
        rs = resident_score(hx, stats, sector)
        vs = visitor_score(hx, stats, sector)
        boundary = [[round(la, 5), round(lo, 5)] for la, lo in h3.cell_to_boundary(hx.h3_index)]
        rows.append({
            "cell": hx.h3_index, "b": boundary,
            "resi": rs, "visit": vs, "gap": round(vs - rs, 1),
            "pob": hx.poblacion, "renta": hx.renta, "flujo": hx.flujo_peatonal,
            "pois": sum(hx.poi_counts.values()),
        })

    clat = sum(r["b"][0][0] for r in rows) / len(rows)
    clon = sum(r["b"][0][1] for r in rows) / len(rows)
    html = (
        TEMPLATE
        .replace("__TITLE__", f"{city} · {sector}")
        .replace("__SUBTITLE__", f"ventana: {window or 'todas'} · {len(rows)} hexes (res 9)")
        .replace("__GAP_THR__", str(int(settings.hidden_audience_gap_threshold)))
        .replace("__VIS_THR__", str(int(settings.hidden_audience_visitor_min)))
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
