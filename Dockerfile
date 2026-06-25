FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:/root/.local/bin:${PATH}"

RUN pip install uv

WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src ./src
COPY scripts ./scripts
RUN uv sync --frozen --no-dev

ENTRYPOINT ["python3", "/app/scripts/run_analysis.py"]
