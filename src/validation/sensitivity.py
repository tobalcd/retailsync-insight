"""Análisis de sensibilidad (Nivel 2): ¿cuánto depende el top-10 de cada peso?

Perturba cada peso del scoring ±20% y mide cuánto cambia el top-10 respecto al
baseline (solape). Solape alto = robusto (el resultado no depende de afinar ese
peso al milímetro); solape bajo = frágil (ese peso manda, hay que calibrarlo bien).

Es MEDICIÓN PURA: muta los pesos en memoria, recalcula y los restaura. No cambia
el algoritmo ni toca la BD más allá de leer cada ciudad una vez.

Uso:
    python -m src.validation.sensitivity
"""

from __future__ import annotations

import sys

import src.config as cfg
from src.patterns.aggregation import load_city_hexes
from src.patterns.hidden_audience import detect_from_hexes

DELTA = 0.20  # ±20%

# (grupo, dict de config, clave)
WEIGHTS = [
    ("visitor", cfg.VISITOR_WEIGHTS, "flujo"),
    ("visitor", cfg.VISITOR_WEIGHTS, "share"),
    ("visitor", cfg.VISITOR_WEIGHTS, "poi"),
    ("visitor", cfg.VISITOR_WEIGHTS, "perfil"),
    ("resident", cfg.RESIDENT_WEIGHTS, "renta"),
    ("resident", cfg.RESIDENT_WEIGHTS, "poblacion"),
    ("resident", cfg.RESIDENT_WEIGHTS, "perfil"),
]

SCENARIOS = [
    ("madrid", "banca", "laborable-manana"),
    ("madrid", "moda_lujo", "finde"),
    ("barcelona", "banca", "laborable-manana"),
    ("barcelona", "moda_lujo", "finde"),
]


def _top(hexes, sector) -> set[str]:
    return {r.h3_index for r in detect_from_hexes(hexes, sector)}


def _overlap(a: set[str], b: set[str]) -> float:
    """Fracción del baseline que sobrevive (|a∩b| / |a|)."""
    return len(a & b) / len(a) if a else 1.0


def main() -> int:
    print("Sensibilidad: solape del top-10 con el baseline al mover cada peso ±20%.")
    print("(1.00 = robusto · cuanto más bajo, más manda ese peso)\n")

    # Resultado acumulado por peso (peor caso entre escenarios y signos)
    worst_by_weight: dict[str, float] = {}

    for city, sector, window in SCENARIOS:
        hexes = load_city_hexes(city, sector, window)
        base = _top(hexes, sector)
        if not base:
            print(f"{city}·{sector}: sin top-10, saltado")
            continue
        print(f"### {city} · {sector} ({len(base)} en baseline)")
        for group, wdict, key in WEIGHTS:
            orig = dict(wdict)
            solapes = []
            for sign in (1 - DELTA, 1 + DELTA):
                wdict[key] = orig[key] * sign
                solapes.append(_overlap(base, _top(hexes, sector)))
                wdict.clear(); wdict.update(orig)  # restaurar en sitio
            worst = min(solapes)
            label = f"{group}.{key}"
            worst_by_weight[label] = min(worst_by_weight.get(label, 1.0), worst)
            barra = "█" * round(worst * 20)
            print(f"  {label:<18} solape {worst:.0%}  {barra}")
        print()

    print("=== PESO MÁS SENSIBLE (peor solape en cualquier escenario) ===")
    for label, w in sorted(worst_by_weight.items(), key=lambda kv: kv[1]):
        flag = "  ← el más frágil" if w == min(worst_by_weight.values()) else ""
        print(f"  {label:<18} {w:.0%}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
