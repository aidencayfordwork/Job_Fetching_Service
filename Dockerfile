# jobfetch-backend: API + scheduler (fetch, discovery, publish to BidFlow).
# On start it applies migrations and seeds sources, then serves on :8000.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/jobfetch

# Editable install: the code runs from here, where config/ sits next to app/.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir -e .

COPY alembic.ini ./
COPY alembic ./alembic
COPY config ./config

RUN useradd --system --no-create-home jobfetch
USER jobfetch

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=4)"

# Listens on $PORT (default 8000) over IPv4 and IPv6 (app/serve.py).
CMD ["sh", "-c", "alembic upgrade head && python -m app.db.seed && exec python -m app.serve"]
