FROM node:22-alpine AS frontend-build

WORKDIR /build
RUN corepack enable && corepack prepare pnpm@11.9.0 --activate
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/.npmrc ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim

ARG DASHBOARD_VERSION=dev
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DASHBOARD_DATABASE_PATH=/app/data/dashboard.db \
    DMARC_CONTROL_VERSION=${DASHBOARD_VERSION}

RUN groupadd --gid 10001 dashboard \
    && useradd --uid 10001 --gid dashboard --create-home --home-dir /home/dashboard dashboard

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt

COPY backend/app ./app
COPY --from=frontend-build /build/dist ./static

RUN mkdir -p /app/data /app/parser-control \
    && chown -R dashboard:dashboard /app /home/dashboard

USER dashboard
EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
