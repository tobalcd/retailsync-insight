# Validación Nivel 1 — detector de audiencia oculta vs. presencia comercial real

**Fecha:** 2026-06-10 · **Método:** top-k del detector contrastado con negocios
reales del sector (OpenStreetMap/Overpass) en las 10 ciudades Tier-1.
**Métrica:** precision@k (% del top con ≥1 negocio del sector en el hex) y
lift sobre la base de la ciudad. **Reproducir:** `python -m src.validation.level1`.

## Resultado agregado

| Sector | precision@k | baseline media | lift | hexes evaluados |
|---|--:|--:|--:|--:|
| moda_lujo | **61%** | 22% | **2,7×** | 97 (10 ciudades) |
| banca | **53%** | 27% | **2,0×** | 88 (10 ciudades) |
| alimentacion | 86% | 51% | 1,7× | 28 (solo 7 ciudades) |

**Lectura:** los hexes que el detector marca como "audiencia oculta" tienen
2–2,7 veces más probabilidad de albergar negocios reales del sector que un hex
cualquiera de la ciudad. El lift es ≥1,3 en TODAS las combinaciones
ciudad-sector con detección — la señal no es una anécdota de Madrid/Barcelona.
(Claim honesto para deck: *"lift 2,0–2,7× contra presencia comercial real en
10 ciudades"*.)

Cautela inherente al método: precision <100% no siempre es fallo — un hex con
señal y sin negocios puede ser exactamente la oportunidad oculta que se busca.
El lift agregado es la métrica defendible, no la precisión de un hex concreto.

## Lo que la prueba destapó (problemas reales)

### 1. Sesgo de centro — el control negativo FALLA en 5 de 7 ciudades

El top de `alimentacion` (sector residencial) comparte la mayoría de sus hexes
con el de `banca` (Madrid 3/4, Barcelona 4/5, Valencia 3/3, Alicante 5/6).
El detector premia "visitante ≫ residente", y eso es estructuralmente el
centro de la ciudad **sea cual sea el sector**: la afinidad sector×tipo de zona
modula el flujo, pero el min-max por ciudad re-estira la escala y el centro
vuelve a ganar. La diferenciación sectorial actual es insuficiente.

### 2. El concepto no aplica simétrico a sectores residenciales

`alimentacion` detecta 0 hexes en Sevilla, Bilbao y Valladolid, y ≤7 en el
resto. Tiene lógica de producto: la audiencia de un supermercado SON los
residentes — su "audiencia oculta" apenas existe. Conclusión de producto, no
de código: **el detector de audiencia oculta es un producto para sectores de
visitante** (moda, banca, viajes, restauración). Para sectores residenciales
el insight útil es otro (p. ej. zonas residenciales infraservidas — encaja con
el concepto `next_wave` del contrato del API).

### 3. Calidad desigual de la verdad externa

Murcia tiene ~101 bancos mapeados en OSM (vs. 953 en Madrid): parte del lift
bajo de Murcia (1,6×) puede ser cobertura OSM pobre, no fallo del detector.
OSM es suficiente para el agregado, pero no para juzgar ciudades pequeñas
una a una. (Catastro daría una base más uniforme — pendiente.)

## Recomendaciones derivadas

1. **Producto:** limitar "audiencia oculta" a sectores con afinidad visitante
   ≥ ~0,6 y diseñar `next_wave` como el insight para sectores residenciales.
2. **Modelo:** atacar el sesgo de centro — candidato: rankear por lift
   sectorial del flujo (flujo ponderado por sector ÷ flujo neutro) en vez de
   por gap absoluto, para que "centro porque sí" no puntúe en todos los sectores.
3. **Datos:** mantener OSM como verdad externa del agregado; evaluar Catastro
   para uniformidad. Nivel 2 (sensibilidad de pesos) sigue pendiente.

## Detalle por ciudad

Ver `data/validation_level1.csv` (generado por el script). Resumen banca:
lift por ciudad entre 1,5× (Barcelona) y 2,4× (Valencia); moda entre 1,3×
(Valladolid) y 4,3× (Sevilla).
