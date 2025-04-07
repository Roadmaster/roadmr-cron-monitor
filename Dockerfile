FROM ubuntu:24.04

# install build dependencies
RUN --mount=type=cache,target=/var/lib/apt,sharing=locked --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update -y && DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y \
    python3 locales curl \
    && apt-get clean && rm -f /var/lib/apt/lists/*_*

# Set the locale
RUN echo 'en_US.UTF-8 UTF-8' >>/etc/locale.gen && locale-gen

ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

WORKDIR /code
# Copy uv here because if uv changes it busts our base ubuntu image with packages
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_LINK_MODE=copy
ENV UV_CACHE_DIR=/opt/uv-cache/
COPY ./pyproject.toml /code/pyproject.toml
COPY ./uv.lock /code/uv.lock

RUN --mount=type=cache,target=/opt/uv-cache uv sync --no-group dev --frozen --compile-bytecode

COPY ./ /code/

CMD ["uv", "run", "--no-group", "dev","uvicorn",  "restarter:app", "--host", "0.0.0.0", "--port", "8000",  "--workers", "2"]
