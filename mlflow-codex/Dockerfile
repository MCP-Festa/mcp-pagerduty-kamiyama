FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/ ./src/

RUN uv sync --frozen --no-dev

RUN mkdir -p /data

EXPOSE 5000

ENTRYPOINT ["uv", "run"]
CMD ["mlflow", "ui", \
     "--backend-store-uri", "sqlite:////data/mlflow.db", \
     "--host", "0.0.0.0", \
     "--port", "5000"]
