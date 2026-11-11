# shortcut: one Python image for api, dagster and mock-sources; split when image size or dependency conflicts hurt.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/venv PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
# The download cache survives between builds, so a dependency change fetches only what changed.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
COPY apps/api apps/api
COPY apps/__init__.py apps/__init__.py
COPY data data
COPY services services
