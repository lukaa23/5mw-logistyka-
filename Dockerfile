FROM node:24-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ASOLAR_HOST=0.0.0.0 PORT=8765
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY server.py desktop.py ./
COPY --from=frontend /build/frontend/dist ./frontend/dist
RUN mkdir -p /app/data/uploads
EXPOSE 8765
VOLUME ["/app/data"]
CMD ["python", "server.py"]
