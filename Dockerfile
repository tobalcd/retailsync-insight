# Motor INSIGHT — imagen para Fly.io / Railway
FROM python:3.11-slim

WORKDIR /app

# El pyproject declara packages=["src"], así que src/ debe existir al instalar.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

# Datos locales que el motor lee en runtime (venues TM, paradas GTFS, clima)
COPY data ./data

# Railway/Fly inyectan $PORT; por defecto 8000 en local
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT}"]
