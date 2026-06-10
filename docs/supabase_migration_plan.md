# RetailSync — Inventario de datasets + propuesta de esquema Supabase

> Análisis read-only del frontend Lovable clonado en `~/proyectos/retailsync-frontend/src/data/`.
> **No se ha tocado Supabase. No hay CREATE TABLE ni inserts.** Solo propuesta para aprobar.
> Fecha: 2026-06-07.

---

## Hallazgos que cambian el plan original

1. **Los INE no son 247k filas, son ~6.846 registros.** El fichero tiene ~247k
   *líneas* pero cada registro ocupa ~36 líneas. Madrid = **2.493** secciones
   censales. Es el dato oficial a nivel de sección (~1.500 hab.), pero la
   volumetría real es pequeña → la migración es trivial, no necesita ingeniería pesada.
2. **`foot_traffic` no es una tabla horaria plana.** Cada ciudad tiene zonas de
   movilidad MITMA (8–21 por ciudad, **120 en total**) y cada zona lleva un
   `traffic_profile` (7 días × 24h) + `avg_daily_visitors` + `tipo`. Aplanarlo a
   (city, hour, day) daría ~35k filas y perdería estructura → mejor `jsonb` por zona.
3. **`syntheticCityData.ts` es un GENERADOR, no datos.** Produce Tier-2 al vuelo
   desde semillas (`tier2CitiesMeta.ts`, 17 ciudades). No se migra output generado;
   se migran las **semillas**.
4. **No existen hexágonos H3 en los datos.** El `hexes` (H3 res 8) que asume el
   Motor INSIGHT **no está en el dataset**: hay secciones censales (INE) + zonas
   MITMA + pantallas. Los hexes son una agregación de *runtime* que habrá que
   **derivar**. → Implicación directa para el detector (ver final).

---

## Paso 1 · Inventario completo

### `src/data/` (datasets de dominio)

| Fichero | Export principal | Tipo | Nº elem. | Contenido |
|---|---|---|---|---|
| `cities.ts` | `CITIES` | `Record<país, City[]>` | 12 países | Catálogo de ciudades (name, country, lat/lng, zoom, currency, neighborhoods). Incluye además `INTERESTS`, `ZONE_TYPES`, `COUNTRY_CODES`, `EXCHANGE_RATES`, `CPM_BENCHMARKS`, `CITY_WEIGHTS`, `REGIONS`, `PPP_INDEX` (config/referencia). |
| `tier2CitiesMeta.ts` | `TIER2_META` | `SyntheticCityMeta[]` | 17 | Semillas Tier-2 (name, lat, lng, pob, baseRenta, munCode). |
| `footTraffic{Ciudad}.ts` ×10 | `FOOT_TRAFFIC_{CIUDAD}` | `FootTrafficZone[]` | 120 total | Zonas MITMA: zona, tipo, lat/lng, `traffic_profile` (7×24), peak_hours, avg_daily_visitors, source. |
| `screensMadrid.ts` | `SCREENS_MADRID` + iface `Screen` | `Screen[]` | 54 | Pantallas OOH/DOOH con 18 atributos (tipo, lat/lng, formato, impresiones, cpm, proveedor, estado, tags…). |
| `screensBarcelona.ts` | `SCREENS_BARCELONA` | `Screen[]` | 36 | Igual estructura. |
| `acquisitionModel.ts` | `ACQUISITION_PROFILES` | `Record<sector, AcquisitionProfile>` | ~10 | Modelo de adquisición por sector (LTV, ticket, frecuencia, radio, saturación). |
| `cityBenchmarks.ts` | `CITY_INCOME_BENCHMARKS`, `ZONE_INCOME_MULTIPLIERS` | `Record<string,number>` | 89 ciudades | Renta media por ciudad (fallback) + multiplicadores por zona + `INE_DATA_YEAR=2023`, `MITMA_DATA_YEAR=2024`. |
| `temporalProfiles.ts` | `ACTIVITY_PROFILES` | `Record<tipo_zona, DayProfiles>` | 5 | Multiplicadores horarios por **tipo de zona** (weekday/saturday/sunday). |
| `syntheticCityData.ts` | `generateSynthetic*` (funcs) + iface `SyntheticCityMeta` | generador | — | Genera INE+footTraffic plausibles para Tier-2. No es dato persistido. |
| `projects.ts` | `PROJECTS` | `ProjectDef[]` | 1 | "Modo proyecto" (config de campaña: pin, feeders, mercados, rename perfiles). |

### `src/data/ine/` (renta por sección censal)

| Fichero | Export | Nº registros | Notas |
|---|---|---|---|
| `ineTypes.ts` | `interface INERecord` | — | Define la fila: 5 IDs + geo + 4 rentas + 7 demografía + 2 desigualdad + 5 composición ingresos + 2 metadatos (~30 campos). |
| `ineIndex.ts` | `getINEForCity()`, `INE_CITIES` | — | Re-export + normalización de aliases (València→Valencia, etc.). |
| `ineHelpers.ts` | helpers | — | Nombres de distrito, conversiones 0-100→0-1, derivación de tramos de edad. |
| `ineRentaMadrid.ts` | `INE_MADRID` | **2.493** | |
| `ineRentaBarcelona.ts` | `INE_BARCELONA` | 1.068 | |
| `ineRentaValencia.ts` | `INE_VALENCIA` | 602 | |
| `ineRentaSevilla.ts` | `INE_SEVILLA` | 541 | |
| `ineRentaZaragoza.ts` | `INE_ZARAGOZA` | 509 | |
| `ineRentaMalaga.ts` | `INE_MALAGA` | 447 | |
| `ineRentaMurcia.ts` | `INE_MURCIA` | 389 | |
| `ineRentaBilbao.ts` | `INE_BILBAO` | 278 | |
| `ineRentaValladolid.ts` | `INE_VALLADOLID` | 266 | |
| `ineRentaAlicante.ts` | `INE_ALICANTE` | 253 | |
| **TOTAL** | | **6.846** | |

**Muestra de un `INERecord` (Madrid, sección 2807901001):** renta_neta_hogar 59.502 €,
renta_neta_persona 27.408 €, poblacion 1.135, edad_media 47.1, gini 43.6, lat 40.4178 / lng -3.7144.

---

## Paso 2 · Esquema Supabase propuesto (SQL PREVIEW — no ejecutar)

Convenciones: snake_case, claves naturales donde existen, `jsonb` para estructuras
anidadas (perfiles horarios), `text[]` para listas, RLS activada con lectura pública
y escritura solo `service_role` (es backend; el motor usa la service key).

```sql
-- 1. cities ---------------------------------------------------------------
create table cities (
  slug        text primary key,            -- 'madrid' (normalizado)
  name        text not null,               -- 'Madrid'
  country     text not null,
  lat         double precision,
  lng         double precision,
  zoom        int,
  currency    text,
  tier        smallint not null default 1, -- 1 = INE+MITMA real; 2 = sintético
  neighborhoods jsonb default '[]'         -- [{name, scoreBonus}]
);

-- 2. ine_renta  (tabla ÚNICA para todas las ciudades) ---------------------
create table ine_renta (
  seccion_censal  text primary key,        -- '2807901001' (único nacional)
  city_slug       text references cities(slug),
  municipio       text,
  municipio_codigo text,
  distrito        text,
  barrio          text,
  lat             double precision,
  lng             double precision,
  coords_pendientes boolean default false,
  coords_source   text,
  -- renta (€/año)
  renta_neta_hogar    numeric,
  renta_neta_persona  numeric,
  renta_uc_media      numeric,
  renta_uc_mediana    numeric,
  -- demografía
  poblacion           numeric,
  edad_media          numeric,
  pct_menor_18        numeric,
  pct_65_plus         numeric,
  pct_espanola        numeric,
  tamano_medio_hogar  numeric,
  pct_hogares_unipersonales numeric,
  -- desigualdad
  indice_gini         numeric,
  ratio_p80_p20       numeric,
  -- composición ingresos (%)
  pct_ingresos_salario        numeric,
  pct_ingresos_pensiones      numeric,
  pct_ingresos_desempleo      numeric,
  pct_ingresos_otras_prestaciones numeric,
  pct_ingresos_otros          numeric,
  -- metadatos
  fuente   text,
  ano_dato smallint
);
create index ine_renta_city_idx        on ine_renta (city_slug);
create index ine_renta_municipio_idx   on ine_renta (municipio_codigo, distrito);
-- índice geográfico para el futuro mapeo a hex H3:
create index ine_renta_geo_idx         on ine_renta (lat, lng);

-- 3. mobility_zones  (MITMA — reemplaza el foot_traffic plano) ------------
create table mobility_zones (
  id            bigint generated always as identity primary key,
  city_slug     text references cities(slug),
  zona_mitma    text not null,             -- '2807901'
  tipo          text,                       -- comercial_turistico, business...
  lat           double precision,
  lng           double precision,
  avg_daily_visitors integer,
  traffic_profile jsonb,                    -- {lunes:[24], ..., domingo:[24]}
  peak_hours    jsonb,                      -- {weekday, weekend}
  source        text,
  unique (city_slug, zona_mitma)
);
create index mobility_zones_city_idx on mobility_zones (city_slug);

-- 4. screens  (extiende screens_demo -> catálogo completo) ----------------
create table screens (
  id            text primary key,           -- 'MAD-DOOH-001'
  city_slug     text references cities(slug),
  tipo          text,                        -- dooh_urbano, ooh_valla...
  nombre        text,
  direccion     text,
  lat           double precision,
  lng           double precision,
  formato       text,
  dimensiones   text,
  orientacion   text,
  caras         smallint,
  impresiones_diarias integer,
  horario       text,
  cpm_estimado  numeric,
  proveedor     text,
  estado        text,                        -- disponible/reservado/mantenimiento
  entorno       text,
  tags          text[]
);
create index screens_city_idx on screens (city_slug);

-- 5. temporal_profiles  (por TIPO de zona, no por city/sector) ------------
create table temporal_profiles (
  zone_type   text primary key,             -- 'Comercial premium'...
  weekday     jsonb,                          -- {hora: multiplicador}
  saturday    jsonb,
  sunday      jsonb
);

-- 6. city_benchmarks ------------------------------------------------------
create table city_benchmarks (
  city_name        text primary key,         -- nombre tal cual ('Madrid', 'París')
  income_benchmark numeric,                   -- renta media fallback
  ine_data_year    smallint default 2023
);

-- 7. acquisition_models  (por sector) ------------------------------------
create table acquisition_models (
  sector                 text primary key,
  addressable_market_pct numeric,
  weekly_visit_propensity numeric,
  acquisition_radius_km  numeric,
  ticket_medio           numeric,
  frecuencia_anual       numeric,
  ltv_1y                 numeric,
  ltv_3y                 numeric,
  retention_factor       numeric,
  saturation_index       numeric,
  fuente                 text
);

-- 8. tier2_cities  (semillas del generador sintético) --------------------
create table tier2_cities (
  name        text primary key,
  lat         double precision,
  lng         double precision,
  pob         integer,
  base_renta  integer,
  mun_code    text,
  top_visitors integer
);

-- 9. projects  ('Modo proyecto') -----------------------------------------
create table projects (
  id            text primary key,
  label         text,
  client        text,
  city_slug     text references cities(slug),
  sector        text,
  default_profile text,
  pin           jsonb,
  context_card  text,
  feeders_nacionales       text[],
  mercados_internacionales text[],
  profile_rename jsonb,
  auto_enable_jcdecaux boolean default false
);
```

**RLS sugerida (todas las tablas):** lectura pública (`select` para `anon`),
escritura restringida a `service_role`. Son datos de referencia, no PII de usuarios.

---

## Paso 3 · Plan de migración (orden + volumetría)

| Orden | Tabla | Filas | Estrategia |
|---|---|---|---|
| 1 | `cities` | ~catálogo (12 países) | Insert directo. Referenciada por todas → primero. |
| 2 | `city_benchmarks` | 89 | Insert directo. |
| 3 | `temporal_profiles` | 5 | Insert directo. |
| 4 | `acquisition_models` | ~10 | Insert directo. |
| 5 | `tier2_cities` | 17 | Insert directo. |
| 6 | `ine_renta` | **6.846** | Batches de 1.000 (≈7 lotes). Es la crítica, pero pequeña. |
| 7 | `mobility_zones` | 120 | Insert directo (jsonb por zona). |
| 8 | `screens` | 90 | Insert directo. |
| 9 | `projects` | 1 | Insert directo. |

**Volumen total: ~7.300 filas.** No necesita ingeniería de batch sofisticada;
solo `ine_renta` conviene trocearla en lotes de 1.000 por límites de payload de
PostgREST. El parser leerá los `.ts` (extrayendo los arrays `export const ...`).

---

## Implicación para el Motor INSIGHT (importante)

El detector del turno 2 asume una tabla `hexes` con `renta`, `poblacion`,
`flujoPeatonal` y POIs por hex H3. **Ese hex no existe en estos datos.** Habrá que
construir una capa de derivación H3 res 8 que agregue:

- **resident_score** ← `ine_renta` (renta + población por sección censal → hex)
- **visitor_score** ← `mobility_zones` (avg_daily_visitors / traffic_profile → hex)
- **POIs de paso** ← `screens` u otra fuente de POIs (a definir)

Es decir: tras la migración, el siguiente bloque del motor será un paso de
**agregación espacial sección/zona → hex H3**, no un simple `select` de `hexes`.
Lo dejo anotado para planificarlo; no forma parte de esta migración.

---

## ¿Aprobamos?

¿Apruebas el esquema y el plan? Si sí, en el siguiente turno ejecuto
`CREATE TABLE` + migración por batches (con credenciales en `.env`).
