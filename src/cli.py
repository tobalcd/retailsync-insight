"""CLI temporal de validación humana del Motor INSIGHT.

Uso:
    python -m src.cli detect-hidden --city madrid --sector banca

Imprime una tabla con el top 10 de hexes "audiencia oculta". Sin JSON aún:
esto es solo para mirar los números con ojos humanos mientras calibramos.
"""

from __future__ import annotations

import argparse
import sys

from src.models import HiddenAudienceResult


def _print_table(results: list[HiddenAudienceResult], city: str, sector: str) -> None:
    print(f"\nAudiencia oculta — {city} · {sector}")
    print("=" * 78)
    if not results:
        print("(sin hexes que superen los umbrales)")
        return
    header = f"{'#':>2}  {'h3_index':<16} {'lat':>8} {'lon':>8} {'resi':>6} {'visit':>6} {'gap':>6}"
    print(header)
    print("-" * 78)
    for i, r in enumerate(results, 1):
        print(
            f"{i:>2}  {r.h3_index:<16} {r.lat:>8.4f} {r.lon:>8.4f} "
            f"{r.resident_score:>6.1f} {r.visitor_score:>6.1f} {r.gap:>6.1f}"
        )
    print("-" * 78)
    print(f"{len(results)} hexes detectados.\n")


def _cmd_detect_hidden(args: argparse.Namespace) -> int:
    # Import perezoso para que `--help` funcione sin credenciales.
    from src.patterns.hidden_audience import detect_hidden_audience

    try:
        results = detect_hidden_audience(args.city, args.sector, args.window)
    except RuntimeError as exc:
        # Típico: faltan credenciales de Supabase.
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    _print_table(results, args.city, args.sector)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insight", description="CLI del Motor INSIGHT.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_detect = sub.add_parser("detect-hidden", help="Detecta hexes de audiencia oculta.")
    p_detect.add_argument("--city", required=True, help="Ciudad, p.ej. 'madrid'.")
    p_detect.add_argument("--sector", required=True, help="Sector, p.ej. 'banca'.")
    p_detect.add_argument("--window", default=None,
                          choices=["laborable-manana", "laborable-tarde", "finde", "noche"],
                          help="Ventana temporal (def: todas las horas).")
    p_detect.set_defaults(func=_cmd_detect_hidden)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
