# syntax=docker/dockerfile:1
# Image of the Picciuli REST API. Build from the repository root:
#   docker build -f apps/api/Dockerfile -t picciuli-api .
#
# The base image is pinned by the digest of its multi-platform index (arm64 in
# production, amd64 in CI); Dependabot keeps it current. Third-party Python
# packages come only from the lock files, verified by hash; regenerate them
# after changing a dependency (see docs/development.md).

FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS build
WORKDIR /src
COPY apps/api/requirements.lock apps/api/requirements-build.lock apps/api/
RUN pip install --no-cache-dir --require-hashes -r apps/api/requirements-build.lock \
    && pip wheel --no-cache-dir --require-hashes --wheel-dir /wheels \
        -r apps/api/requirements.lock
COPY packages/picciuli packages/picciuli
COPY apps/api apps/api
RUN pip wheel --no-cache-dir --no-deps --no-build-isolation --wheel-dir /wheels \
    ./packages/picciuli ./apps/api

FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PICCIULI_DATA_DIR=/data \
    PICCIULI_HOST=0.0.0.0 \
    PICCIULI_PORT=8000
RUN useradd --system --uid 10001 --user-group --home-dir /data --no-create-home picciuli \
    && mkdir /data \
    && chown picciuli:picciuli /data
# The wheels were verified against the lock files in the build stage; pip check
# fails the build if the lock no longer satisfies the packages' requirements.
COPY --from=build /wheels /tmp/wheels
RUN pip install --no-cache-dir --no-index --no-deps /tmp/wheels/*.whl \
    && pip check \
    && rm -rf /tmp/wheels
USER picciuli
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"]
# umask 077: the user databases (and any other file the server creates) are 0600.
CMD ["/bin/sh", "-c", "umask 077 && exec picciuli-api"]
