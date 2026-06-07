# Motor INSIGHT — RetailSync

Servicio Python independiente que añade a RetailSync (location intelligence por
hexágonos H3 res 8) dos capacidades:

1. **Detector de audiencia oculta** — para un par `(ciudad, sector)`, hexágonos
   donde el perfil *residente* no es target pero el *visitante* (movilidad MITMA) sí.
2. **Motor narrativo** — ~200 palabras de insight accionable generadas con la API de Claude.

Se expone como una API HTTP (`POST /insight`) y cachea resultados por hash del input.

> **Estado actual: andamiaje.** La estructura, el contrato del API y el script de
> ingesta están listos. La lógica del motor (detector + narrativa + cache) aún
> **no** está implementada — es lo siguiente, una vez aprobado este esqueleto.

---

## Estructura

```
retailsync-insight/
├── pyproject.toml          # deps y metadatos del proyecto
├── .env.example            # plantilla de variables de entorno
├── Dockerfile              # imagen para Fly.io / Railway
├── data/                   # parquets y SQLite locales (no se commitean)
└── src/
    ├── config.py           # carga de configuración desde .env
    ├── db/
    │   └── supabase_client.py   # cliente Supabase compartido
    ├── ingestion/
    │   └── fetch_hexes.py       # ✅ descarga hexes de una ciudad a parquet
    ├── api/
    │   └── main.py              # FastAPI: POST /insight (stub 501) + /health
    ├── engine/
    │   ├── hidden_audience.py   # detector (stub)
    │   └── narrative.py         # motor narrativo Claude (stub)
    └── cache/
        └── store.py             # cache SQLite + Supabase (stub)
```

---

## Setup (macOS)

### 0. Python 3.11

El proyecto necesita **Python 3.11+**. Tu macOS trae el 3.9 del sistema, así que
instala el 3.11 con Homebrew (no toca al del sistema):

```bash
brew install python@3.11
```

### 1. Entorno virtual e instalación

Desde la raíz del repo:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .            # instala el proyecto y sus dependencias
# para herramientas de desarrollo (linter, tests):  pip install -e ".[dev]"
```

### 2. Variables de entorno

```bash
cp .env.example .env
```

Edita `.env` y rellena:

| Variable               | De dónde sale                                                        |
|------------------------|----------------------------------------------------------------------|
| `SUPABASE_URL`         | Supabase → Project Settings → API → *Project URL*                    |
| `SUPABASE_SERVICE_KEY` | Supabase → Project Settings → API → *service_role key* (¡secreta!)   |
| `ANTHROPIC_API_KEY`    | console.anthropic.com → API Keys (empieza por `sk-ant-…`)            |

El `.env` está en `.gitignore`: nunca se sube. La `service_role` salta RLS, trátala
como contraseña de admin.

---

## Uso

### Descargar los hexágonos de una ciudad

```bash
python -m src.ingestion.fetch_hexes --city madrid
# → data/hexes_madrid.parquet
```

Si la tabla o la columna de ciudad se llaman distinto en RetailSync:

```bash
python -m src.ingestion.fetch_hexes --city madrid --table hexes --city-column city
```

### Levantar el API en local

```bash
uvicorn src.api.main:app --reload
```

- Salud: http://127.0.0.1:8000/health
- Docs interactivas (Swagger): http://127.0.0.1:8000/docs
- `POST /insight` responde **501** por ahora (lógica pendiente).

---

## Despliegue (más adelante)

La imagen Docker está lista para Fly.io o Railway:

```bash
docker build -t retailsync-insight .
docker run -p 8000:8000 --env-file .env retailsync-insight
```

Ambas plataformas inyectan `$PORT` automáticamente; el `CMD` ya lo respeta.

---

## Roadmap inmediato (tras aprobar este andamiaje)

- [ ] `engine/hidden_audience.py` — detector residente-vs-visitante (top 10 hex).
- [ ] `engine/narrative.py` — generación de narrativa con Claude.
- [ ] `cache/store.py` — cache SQLite local + tabla `insights_cache` en Supabase.
- [ ] Conectar todo en `POST /insight` (mirar cache → detectar → narrar → guardar).
- [ ] Tests del detector con un parquet de ejemplo.
```
