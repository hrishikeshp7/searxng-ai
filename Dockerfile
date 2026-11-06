# syntax=docker/dockerfile:1.7
FROM docker.io/searxng/base:searxng-builder AS builder

WORKDIR /usr/local/searxng

COPY ./requirements.txt ./requirements-server.txt ./

ENV UV_NO_MANAGED_PYTHON="true"

RUN --mount=type=cache,id=uv,target=/root/.cache/uv set -eux -o pipefail; \
    uv venv; \
    uv pip install --requirements ./requirements.txt --requirements ./requirements-server.txt; \
    uv cache prune --ci; \
    find ./.venv/lib/ -type f -exec strip --strip-unneeded {} + || true; \
    find ./.venv/lib/ -type d -name "__pycache__" -exec rm -rf {} +; \
    find ./.venv/lib/ -type f -name "*.pyc" -delete; \
    python -m compileall -q -f -j 0 --invalidation-mode=unchecked-hash ./.venv/lib/

COPY ./searx/ ./searx/

RUN set -eux -o pipefail; \
    python -m compileall -q -f -j 0 --invalidation-mode=unchecked-hash ./searx/; \
    find ./searx/static/ -type f \
    \( -name "*.html" -o -name "*.css" -o -name "*.js" -o -name "*.svg" \) \
    -exec gzip -9 -k {} + \
    -exec brotli -9 -k {} + \
    -exec gzip --test {}.gz + \
    -exec brotli --test {}.br +

FROM docker.io/searxng/base:searxng AS dist

WORKDIR /usr/local/searxng

COPY --chown=977:977 --from=builder /usr/local/searxng/.venv/ ./.venv/
COPY --chown=977:977 --from=builder /usr/local/searxng/searx/ ./searx/
COPY --chown=977:977 ./container/entrypoint.sh ./entrypoint.sh
COPY --chown=977:977 ./container/settings.template.yml ./settings.template.yml
COPY --chown=977:977 ./searx/version_frozen.py ./searx/

RUN chmod +x /usr/local/searxng/entrypoint.sh

ARG CREATED="0001-01-01T00:00:00Z"
ARG VERSION="custom-ai"
ARG VCS_URL="https://github.com/hrishikeshp7/searxng-ai-23"
ARG VCS_REVISION="unknown"

LABEL org.opencontainers.image.created="$CREATED" \
    org.opencontainers.image.description="SearXNG AI custom container" \
    org.opencontainers.image.title="SearXNG AI" \
    org.opencontainers.image.version="$VERSION"

ENV __SEARXNG_VERSION="$VERSION" \
    __SEARXNG_SETTINGS_PATH="$__SEARXNG_CONFIG_PATH/settings.yml" \
    GRANIAN_PROCESS_NAME="searxng" \
    GRANIAN_INTERFACE="wsgi" \
    GRANIAN_HOST="::" \
    GRANIAN_PORT="8080" \
    GRANIAN_WEBSOCKETS="false" \
    GRANIAN_BLOCKING_THREADS="4" \
    GRANIAN_WORKERS_KILL_TIMEOUT="30s" \
    GRANIAN_BLOCKING_THREADS_IDLE_TIMEOUT="5m"

VOLUME $__SEARXNG_CONFIG_PATH
VOLUME $__SEARXNG_DATA_PATH

EXPOSE 8080

ENTRYPOINT ["/usr/local/searxng/entrypoint.sh"]
