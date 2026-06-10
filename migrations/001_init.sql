-- ============================================================================
-- RetailSync — Esquema inicial Supabase (Motor INSIGHT, turno 4)
-- 9 tablas · columnas h3_index precomputadas · RLS dual.
--
-- CÓMO EJECUTAR: pega este fichero entero en el SQL Editor de Supabase
-- (Dashboard → SQL Editor → New query → Run), o aplícalo vía psql con la
-- connection string del proyecto. supabase-py (PostgREST) NO ejecuta DDL.
--
-- Nota RLS: en Supabase, la `service_role` SALTA RLS por diseño. Por eso solo
-- definimos políticas de SELECT para anon/authenticated; al no haber políticas
-- de INSERT/UPDATE/DELETE, esas operaciones quedan bloqueadas para todos salvo
-- service_role → "escritura solo service_role" se cumple automáticamente.
--
-- h3_index: se rellena en la ingesta (h3-py, res 8) desde lat/lng. Aquí solo
-- se crean la columna y el índice; la migración hace el UPDATE/INSERT del valor.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. cities
-- ----------------------------------------------------------------------------
create table if not exists cities (
  slug          text primary key,
  name          text not null,
  country       text not null,
  lat           double precision,
  lng           double precision,
  zoom          int,
  currency      text,
  tier          smallint not null default 1,
  neighborhoods jsonb default '[]'::jsonb
);

-- ----------------------------------------------------------------------------
-- 2. ine_renta   (tabla única; ~6.846 filas)
-- ----------------------------------------------------------------------------
create table if not exists ine_renta (
  seccion_censal            text primary key,
  city_slug                 text references cities(slug),
  h3_index                  text,                 -- res 8, precomputado en ingesta
  municipio                 text,
  municipio_codigo          text,
  distrito                  text,
  barrio                    text,
  lat                       double precision,
  lng                       double precision,
  coords_pendientes         boolean default false,
  coords_source             text,
  renta_neta_hogar          numeric,
  renta_neta_persona        numeric,
  renta_uc_media            numeric,
  renta_uc_mediana          numeric,
  poblacion                 numeric,
  edad_media                numeric,
  pct_menor_18              numeric,
  pct_65_plus               numeric,
  pct_espanola              numeric,
  tamano_medio_hogar        numeric,
  pct_hogares_unipersonales numeric,
  indice_gini               numeric,
  ratio_p80_p20             numeric,
  pct_ingresos_salario      numeric,
  pct_ingresos_pensiones    numeric,
  pct_ingresos_desempleo    numeric,
  pct_ingresos_otras_prestaciones numeric,
  pct_ingresos_otros        numeric,
  fuente                    text,
  ano_dato                  smallint
);
create index if not exists ine_renta_city_idx      on ine_renta (city_slug);
create index if not exists ine_renta_municipio_idx on ine_renta (municipio_codigo, distrito);
create index if not exists ine_renta_h3_idx        on ine_renta (h3_index);   -- agregación por hex

-- ----------------------------------------------------------------------------
-- 3. mobility_zones   (MITMA; ~120 filas)
-- ----------------------------------------------------------------------------
create table if not exists mobility_zones (
  id                 bigint generated always as identity primary key,
  city_slug          text references cities(slug),
  zona_mitma         text not null,
  h3_index           text,                          -- res 8, desde el centroide
  tipo               text,
  lat                double precision,
  lng                double precision,
  avg_daily_visitors integer,
  traffic_profile    jsonb,
  peak_hours         jsonb,
  source             text,
  unique (city_slug, zona_mitma)
);
create index if not exists mobility_zones_city_idx on mobility_zones (city_slug);
create index if not exists mobility_zones_h3_idx   on mobility_zones (h3_index);

-- ----------------------------------------------------------------------------
-- 4. screens   (~90 filas)
-- ----------------------------------------------------------------------------
create table if not exists screens (
  id                  text primary key,
  city_slug           text references cities(slug),
  h3_index            text,                          -- res 8, desde lat/lng
  tipo                text,
  nombre              text,
  direccion           text,
  lat                 double precision,
  lng                 double precision,
  formato             text,
  dimensiones         text,
  orientacion         text,
  caras               smallint,
  impresiones_diarias integer,
  horario             text,
  cpm_estimado        numeric,
  proveedor           text,
  estado              text,
  entorno             text,
  tags                text[]
);
create index if not exists screens_city_idx on screens (city_slug);
create index if not exists screens_h3_idx   on screens (h3_index);

-- ----------------------------------------------------------------------------
-- 5. temporal_profiles   (5 filas; por tipo de zona)
-- ----------------------------------------------------------------------------
create table if not exists temporal_profiles (
  zone_type text primary key,
  weekday   jsonb,
  saturday  jsonb,
  sunday    jsonb
);

-- ----------------------------------------------------------------------------
-- 6. city_benchmarks   (89 filas)
-- ----------------------------------------------------------------------------
create table if not exists city_benchmarks (
  city_name        text primary key,
  income_benchmark numeric,
  ine_data_year    smallint default 2023
);

-- ----------------------------------------------------------------------------
-- 7. acquisition_models   (~10 filas)
-- ----------------------------------------------------------------------------
create table if not exists acquisition_models (
  sector                  text primary key,
  addressable_market_pct  numeric,
  weekly_visit_propensity numeric,
  acquisition_radius_km   numeric,
  ticket_medio            numeric,
  frecuencia_anual        numeric,
  ltv_1y                  numeric,
  ltv_3y                  numeric,
  retention_factor        numeric,
  saturation_index        numeric,
  fuente                  text
);

-- ----------------------------------------------------------------------------
-- 8. tier2_cities   (17 filas; semillas del generador sintético)
-- ----------------------------------------------------------------------------
create table if not exists tier2_cities (
  name         text primary key,
  lat          double precision,
  lng          double precision,
  pob          integer,
  base_renta   integer,
  mun_code     text,
  top_visitors integer
);

-- ----------------------------------------------------------------------------
-- 9. projects   (1 fila)
-- ----------------------------------------------------------------------------
create table if not exists projects (
  id                       text primary key,
  label                    text,
  client                   text,
  city_slug                text references cities(slug),
  sector                   text,
  default_profile          text,
  pin                      jsonb,
  context_card             text,
  feeders_nacionales       text[],
  mercados_internacionales text[],
  profile_rename           jsonb,
  auto_enable_jcdecaux     boolean default false
);

-- ============================================================================
-- RLS dual
-- ============================================================================
alter table cities             enable row level security;
alter table ine_renta          enable row level security;
alter table mobility_zones     enable row level security;
alter table city_benchmarks    enable row level security;
alter table temporal_profiles  enable row level security;
alter table tier2_cities       enable row level security;
alter table screens            enable row level security;
alter table projects           enable row level security;
alter table acquisition_models enable row level security;

-- Grupo A — SELECT público (anon + authenticated): datos INE/MITMA públicos.
create policy "cities_select_public"            on cities            for select to anon, authenticated using (true);
create policy "ine_renta_select_public"         on ine_renta         for select to anon, authenticated using (true);
create policy "mobility_zones_select_public"    on mobility_zones    for select to anon, authenticated using (true);
create policy "city_benchmarks_select_public"   on city_benchmarks   for select to anon, authenticated using (true);
create policy "temporal_profiles_select_public" on temporal_profiles for select to anon, authenticated using (true);
create policy "tier2_cities_select_public"      on tier2_cities      for select to anon, authenticated using (true);

-- Grupo B — SELECT solo authenticated: posible dato comercial sensible.
-- NOTA: acquisition_models lo incluyo aquí por criterio de seguridad
-- (LTV/ticket medio); confírmame si prefieres que sea público.
create policy "screens_select_auth"            on screens            for select to authenticated using (true);
create policy "projects_select_auth"           on projects           for select to authenticated using (true);
create policy "acquisition_models_select_auth" on acquisition_models for select to authenticated using (true);

-- INSERT/UPDATE/DELETE: sin políticas → solo service_role (que salta RLS).
