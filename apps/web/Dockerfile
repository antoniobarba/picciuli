# Image of the Picciuli web front-end: static files served by Caddy.
# Build from the repository root:
#   docker build -f apps/web/Dockerfile -t picciuli-web .
# The build stage runs on the build machine's own platform (the output is the
# same everywhere), so multi-platform builds only copy files for each target.
FROM --platform=$BUILDPLATFORM node:22-alpine AS build
WORKDIR /src/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
COPY apps/web/vendor ./vendor
RUN npm ci --no-audit --no-fund
COPY apps/api/openapi.json /src/apps/api/openapi.json
COPY apps/web ./
RUN npm run check-api-types && npm run build

FROM caddy:2-alpine
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
