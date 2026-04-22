# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# System dependencies required for certain Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy dependency manifest first for layer caching
COPY pyproject.toml ./

# Install all production dependencies into a local prefix
RUN pip install --upgrade pip setuptools wheel \
    && pip install --prefix=/install --no-cache-dir \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.30" \
        "gunicorn>=22.0" \
        "sqlalchemy>=2.0" \
        "alembic>=1.13" \
        "asyncpg>=0.29" \
        "pydantic>=2.0" \
        "pydantic-settings>=2.0" \
        "redis>=5.0" \
        "arq>=0.26" \
        "python-jose[cryptography]>=3.3" \
        "passlib[bcrypt]>=1.7" \
        "python-dotenv>=1.0" \
        "structlog>=24.0" \
        "ccxt>=4.0" \
        "pandas>=2.0" \
        "numpy>=1.26" \
        "lightgbm>=4.0" \
        "xgboost>=2.0" \
        "scikit-learn>=1.4" \
        "torch>=2.2" \
        "gymnasium>=0.29" \
        "stable-baselines3>=2.2" \
        "optuna>=3.5" \
        "shap>=0.44" \
        "fracdiff>=0.1" \
        "httpx>=0.27" \
        "orjson>=3.9" \
        "slowapi>=0.1.9" \
        "sentry-sdk[fastapi]>=2.0"

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Runtime system libs
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

WORKDIR /app

# Create directories that may be volume-mounted
RUN mkdir -p /app/models /app/logs && chown -R appuser:appgroup /app

# Copy application source
COPY --chown=appuser:appgroup . .

USER appuser

EXPOSE 8000

# Default command; overridden by docker-compose for worker/trader
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
