# syntax=docker/dockerfile:1
# Image of the Picciuli REST API. Build from the repository root:
#   docker build -f apps/api/Dockerfile -t picciuli-api .
ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS build
WORKDIR /src
COPY packages/picciuli packages/picciuli
COPY apps/api apps/api
RUN pip wheel --no-cache-dir --wheel-dir /wheels ./packages/picciuli ./apps/api

FROM python:${PYTHON_VERSION}-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PICCIULI_DATA_DIR=/data \
    PICCIULI_HOST=0.0.0.0 \
    PICCIULI_PORT=8000
RUN useradd --system --uid 10001 --user-group --home-dir /data --no-create-home picciuli \
    && mkdir /data \
    && chown picciuli:picciuli /data
COPY --from=build /wheels /tmp/wheels
RUN pip install --no-cache-dir --no-index --find-links=/tmp/wheels picciuli-api \
    && rm -rf /tmp/wheels
USER picciuli
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"]
CMD ["picciuli-api"]
