# Hospital Copilot - plateforme (FastAPI + agents + simulateur embarque + jumeau 3D)
#   docker build -t hospital-copilot .
#   docker run --rm -p 8000:8000 --env-file .env -v hackcure-data:/data hospital-copilot
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATABASE_URL=sqlite:////data/clinic.db \
    PORT=8000

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Code : uniquement ce dont le serveur a besoin (pas les modeles de vision ni les donnees d'entrainement)
COPY contracts/ ./contracts/
COPY simulator/ ./simulator/
COPY n8n/ ./n8n/
COPY scripts/ ./scripts/
COPY dashboard/ ./dashboard/

# Utilisateur non-root ; /data (base SQLite, certificats) est le seul dossier inscriptible
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin hackcure \
    && mkdir -p /data \
    && chown -R hackcure:hackcure /data
USER hackcure
VOLUME ["/data"]

WORKDIR /app/dashboard
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=40s --retries=3 CMD ["python", "healthcheck.py"]
CMD ["sh", "-c", "python serve.py --port ${PORT:-8000}"]
