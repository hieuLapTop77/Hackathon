# Airline Revenue Optimizer -- Dockerfile
#
# Targets (use --target when building):
#   backend  -> Python FastAPI app
#   frontend -> nginx serving React static build
#
# Build examples:
#   docker build -t airline-backend .              # backend only
#   docker build -t airline-frontend --target frontend .
#   docker build -t airline .                     # all stages

# ── Shared base for backend ─────────────────────────────────────────────────
FROM python:3.11-slim AS backend-base

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libgomp1 curl gnupg2 \
    && curl https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Backend stage ────────────────────────────────────────────────────────────
FROM backend-base AS backend

COPY backend/ ./backend/

RUN mkdir -p /app/outputs /app/data/raw /app/data/processed

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["uvicorn", "backend.src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]


# ── Frontend build stage ─────────────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ ./

ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build


# ── Frontend nginx stage ─────────────────────────────────────────────────────
FROM nginx:alpine AS frontend

# Remove default nginx site
RUN rm -rf /usr/share/nginx/html/*

# Copy React build output
COPY --from=frontend-builder /app/dist /usr/share/nginx/html

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
