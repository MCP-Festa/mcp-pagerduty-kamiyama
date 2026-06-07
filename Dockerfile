FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock* ./

RUN uv sync --frozen --no-dev

COPY server.py ./

EXPOSE 8007

CMD ["uv", "run", "python", "server.py"]
