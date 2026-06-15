# Stage 1: build venv with production deps
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy dependency manifests first — changes to source don't bust this layer
COPY pyproject.toml uv.lock ./

# Install deps without the project itself to maximise cache reuse
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install the project package as a wheel into site-packages
COPY email_triage/ ./email_triage/
RUN uv sync --frozen --no-dev --no-editable

# Stage 2: lean runtime image
FROM python:3.14-slim AS runtime

WORKDIR /app

# Bring in the built venv from builder — email_triage is in site-packages
COPY --from=builder /app/.venv /app/.venv

COPY gunicorn.conf.py ./

# Put the venv on PATH so gunicorn/uvicorn are found without activation
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["gunicorn", "-c", "gunicorn.conf.py", "email_triage.main:app"]
