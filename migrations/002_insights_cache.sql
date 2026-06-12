-- ============================================================================
-- Motor INSIGHT — cache remota de análisis (tabla insights_cache)
-- EJECUTAR EN: Supabase Dashboard → SQL Editor → New query → Run
-- (igual que 001_init.sql; supabase-py no ejecuta DDL)
--
-- Clave = sha256 del input {city, sector, profile, window} + versión del
-- modelo de scoring (para invalidar cuando cambie la fórmula).
-- ============================================================================

create table if not exists insights_cache (
  key        text primary key,
  payload    jsonb not null,
  created_at timestamptz not null default now()
);

alter table insights_cache enable row level security;

-- Lectura solo authenticated (el insight puede tener valor comercial).
create policy "insights_cache_select_auth"
  on insights_cache for select to authenticated using (true);

-- Escritura: sin políticas → solo service_role (el motor).
