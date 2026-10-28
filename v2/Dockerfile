# ASOLAR v2 — obraz serwera (osobna usługa, niezależna od v1). Kontekst budowania: katalog v2/.
FROM node:24-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
# DejaVu zapewnia polskie znaki w raportach PDF.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ASOLAR_HOST=0.0.0.0 PORT=8770 ASOLAR_DATA_DIR=/app/data
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/asolar2 ./backend/asolar2
COPY backend/server.py ./backend/server.py
# asolar2/main.py szuka frontendu w ../../frontend/dist względem siebie — ten sam układ co w repozytorium.
COPY --from=frontend /build/frontend/dist ./frontend/dist
RUN mkdir -p /app/data && useradd --create-home --uid 10001 asolar && chown -R asolar /app/data
USER asolar
WORKDIR /app/backend
EXPOSE 8770
VOLUME ["/app/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8770\")}/api/health', timeout=4)"
CMD ["python", "server.py"]
