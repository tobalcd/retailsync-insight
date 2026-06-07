# Motor INSIGHT — imagen para Fly.io / Railway
FROM python:3.11-slim

WORKDIR /app

# Instala dependencias primero (mejor cacheo de capas)
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

# Código
COPY src ./src

# Railway/Fly inyectan $PORT; por defecto 8000 en local
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT}"]
