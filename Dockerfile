# Dalili backend + website, production image.
#   docker build -t dalili .
#   docker run -p 8000:8000 --env-file .env dalili
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TRAVEL_AGENT_HTTP_CACHE=/app/.cache/http_cache.sqlite \
    TRAVEL_AGENT_DB=/app/data/travel_agent.db

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY travel_agent ./travel_agent
COPY frontend ./frontend
COPY seo ./seo
COPY ml/models ./ml/models

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 dalili && mkdir -p /app/.cache /app/data && chown -R dalili /app
USER dalili

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
# --proxy-headers: behind Azure's HTTPS ingress the app must see https (secure cookies, canonical URLs).
CMD ["uvicorn", "travel_agent.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
