#!/usr/bin/env bash
# Start or update the stack. Run on the server from /opt/picciuli:
#   ./deploy.sh            deploy the latest images
#   ./deploy.sh <sha>      deploy (or roll back to) the images of a commit
set -euo pipefail
cd "$(dirname "$0")"

tag=${1:-latest}
if [[ ! $tag =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "invalid image tag: $tag" >&2
    exit 2
fi
if [[ ! -f .env ]]; then
    echo "missing .env: copy .env.example and fill it in" >&2
    exit 1
fi

# The API and the web front-end are built from the same commit.
for name in API_TAG WEB_TAG; do
    if grep -q "^$name=" .env; then
        sed -i "s/^$name=.*/$name=$tag/" .env
    else
        echo "$name=$tag" >>.env
    fi
done

mkdir -p data/picciuli
docker compose pull --quiet
docker compose up --detach --remove-orphans --wait --wait-timeout 300
docker image prune --force >/dev/null
echo "deployed picciuli-api and picciuli-web:$tag"
