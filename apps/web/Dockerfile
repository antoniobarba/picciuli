# Image of the Picciuli web front-end: static files served by Caddy.
# Build from the repository root:
#   docker build -f apps/web/Dockerfile -t picciuli-web .
# The build stage runs on the build machine's own platform (the output is the
# same everywhere), so multi-platform builds only copy files for each target.
# Base images are pinned by the digest of their multi-platform index;
# Dependabot keeps them current.
FROM --platform=$BUILDPLATFORM node:22-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a AS build
WORKDIR /src/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
COPY apps/web/vendor ./vendor
RUN npm ci --no-audit --no-fund
COPY apps/api/openapi.json /src/apps/api/openapi.json
COPY apps/web ./
RUN npm run check-api-types && npm run build

FROM caddy:2-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0
# Settings read by the browser from /config.json (see apps/web/Caddyfile).
ENV PICCIULI_API_URL="" \
    PICCIULI_OIDC_ISSUER="" \
    PICCIULI_OIDC_CLIENT_ID="" \
    PICCIULI_OIDC_PROJECT_ID="" \
    XDG_CONFIG_HOME=/tmp/caddy-config \
    XDG_DATA_HOME=/tmp/caddy-data
COPY apps/web/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/apps/web/dist /srv
USER 10002:10002
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"]
