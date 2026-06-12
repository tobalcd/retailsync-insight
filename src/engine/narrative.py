"""Motor narrativo: ~200 palabras de insight accionable con la API de Claude.

Estructura pedida al modelo:
  1. Por qué funcionan las 3 mejores zonas (con nombres reales: distrito, metro)
  2. Una zona descartada y la razón
  3. Contexto comercial del sector (+ apunte de clima como modulador temporal)

`build_prompt` es puro (testeable sin red); `generate_narrative` llama a Claude.
La narrativa SOLO puede usar los datos que le pasamos — el prompt lo exige para
evitar que invente cifras o lugares.
"""

from __future__ import annotations

from src.config import settings
from src.models import HiddenAudienceResult

SYSTEM = (
    "Eres el analista de location intelligence de RetailSync. Escribes para "
    "directores de marketing y expansión en España. Estilo: directo, accionable, "
    "sin tecnicismos de GIS, sin inventar NADA que no esté en los datos que se "
    "te dan. Los scores son relativos a la ciudad (0-100). Español de España."
)

PROMPT_TEMPLATE = """Análisis de audiencia oculta — {city} · sector {sector} · perfil objetivo: {profile} · ventana: {window}.

"Audiencia oculta" = zonas donde quien VIVE no encaja con el target pero quien PASA sí (score visitante muy por encima del residente).

TOP ZONAS DETECTADAS:
{top_block}

ZONA DESCARTADA:
{discarded_block}

CONTEXTO ADICIONAL:
{context_block}

Escribe ~200 palabras (un único texto corrido, 2-3 párrafos, sin títulos ni listas):
1. Por qué funcionan las 3 primeras zonas para este sector y perfil (usa los nombres reales de zona/transporte dados).
2. La zona descartada y su razón, en una frase.
3. Cierra con contexto comercial del sector y, si hay dato de clima, un apunte de timing de campaña.
Usa SOLO la información proporcionada. No inventes calles, datos ni porcentajes."""


def _fmt_result(i: int, r: HiddenAudienceResult, zona: str, pois: list[str]) -> str:
    lugares = f" · referencias: {', '.join(pois)}" if pois else ""
    return (f"{i}. {zona} — residente {r.resident_score:.0f}, visitante {r.visitor_score:.0f}, "
            f"diferencial +{r.gap:.0f}{lugares}")


def build_prompt(
    city: str,
    sector: str,
    profile: str,
    window: str | None,
    results: list[HiddenAudienceResult],
    zonas: dict[str, str],
    pois: dict[str, list[str]],
    discarded: dict | None = None,
    clima: dict | None = None,
) -> str:
    """Arma el prompt con datos reales. Puro: sin red, testeable."""
    top_block = "\n".join(
        _fmt_result(i + 1, r, zonas.get(r.h3_index, city.title()), pois.get(r.h3_index, []))
        for i, r in enumerate(results[:3])
    ) or "(sin zonas que superen los umbrales de calidad)"

    if discarded:
        discarded_block = (
            f"{discarded['zona']} — visitante {discarded['visitor']:.0f} pero "
            f"residente {discarded['resident']:.0f} (diferencial +{discarded['gap']:.0f}, "
            f"bajo el umbral): {discarded['reason']}"
        )
    else:
        discarded_block = "(ninguna zona candidata cercana al corte)"

    ctx = []
    if clima:
        ctx.append(
            f"Clima ({city}): {clima['pct_utiles']}% de días útiles de campaña al año, "
            f"{clima['dias_lluvia']} días de lluvia."
        )
    if window:
        ctx.append(f"El análisis pondera el pulso de movilidad de la franja '{window}'.")
    context_block = "\n".join(ctx) or "(sin contexto adicional)"

    return PROMPT_TEMPLATE.format(
        city=city.title(), sector=sector, profile=profile,
        window=window or "todas las horas",
        top_block=top_block, discarded_block=discarded_block,
        context_block=context_block,
    )


def generate_narrative(prompt: str) -> str:
    """Llama a Claude y devuelve el texto. Lanza RuntimeError sin API key."""
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "Falta ANTHROPIC_API_KEY en .env — la narrativa requiere la API de Claude."
        )
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=600,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in msg.content if block.type == "text").strip()
