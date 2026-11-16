# Development

## Repository layout

```
packages/picciuli/   core library (src layout, tests next to it)
apps/api/            multi-user REST API (FastAPI), tests in apps/api/api_tests,
                     committed OpenAPI schema in apps/api/openapi.json
apps/web/            web and mobile front-end (React, TypeScript, PWA) with a
                     client generated from apps/api/openapi.json
deploy/              production stack (Docker Compose, Caddy, Zitadel) and scripts
docs/, mkdocs.yml    this documentation
pyproject.toml       uv workspace root + shared ruff / mypy / pytest configuration
```

Native wrappers (for example Capacitor for the app stores or Tauri for a
desktop installer) can be added next to it later; the web app is already
installable everywhere.

Clients use only the public API of the library.

## Commands

```bash
pip install -e "packages/picciuli[dev,docs]"   # or: uv sync
pip install -e "apps/api[dev]"                 # API server, Python 3.11+

pytest --cov             # tests with branch coverage (fails below 95 %)
ruff check . && ruff format --check .
mypy                     # strict type checking
mkdocs serve             # live documentation at http://127.0.0.1:8000
mkdocs build --strict    # what CI runs
picciuli-api openapi --output apps/api/openapi.json   # after changing the API
cd apps/web && npm run api-types                      # ...then update the web client
```

The web front-end has its own Node.js tooling (Node 20.19+ or 22):
`npm ci`, `npm test`, `npm run lint`, `npm run typecheck` and `npm run build`
in `apps/web`; see [Web and mobile app](web.md#development).

## Pinned dependencies

The API image installs third-party packages only from
`apps/api/requirements.lock` (and its build backend from
`apps/api/requirements-build.lock`), checking every file's hash; the two
local packages are installed from source without dependencies, and
`pip check` fails the image build if the lock no longer satisfies their
`pyproject.toml`. After changing a dependency of `packages/picciuli` or
`apps/api` (or to pick up updates), regenerate the locks with uv, from the
repository root:

```bash
uv pip compile apps/api/pyproject.toml packages/picciuli/pyproject.toml \
  --override apps/api/lock-overrides.txt --universal --python-version 3.13 \
  --generate-hashes --no-emit-package picciuli -o apps/api/requirements.lock
uv pip compile apps/api/requirements-build.in --universal --python-version 3.13 \
  --generate-hashes -o apps/api/requirements-build.lock
```

GitHub Actions are pinned to commit SHAs (with the version in a comment) and
base images to the digest of their multi-platform index (arm64 for production,
amd64 for CI). Dependabot (`.github/dependabot.yml`) opens weekly pull
requests for actions, Python and npm packages, Dockerfiles and the images in
`deploy/compose.yml`.

## Publishing documentation

The CI workflow publishes the documentation to
[GitHub Pages](https://antoniobarba.github.io/picciuli/) on pushes to `master`,
after the lint, test, web and documentation jobs pass. Pull requests build the
documentation for validation but do not publish it.

One-time repository setup: under **Settings > Pages > Build and deployment**,
set **Source** to **GitHub Actions** before pushing the workflow changes.
CI uploads the generated `site/` directory and deploys it using the built-in
`GITHUB_TOKEN`; no VM or additional deployment secrets are needed.

## Design rules

- **Public API.** Whatever `picciuli/__init__.py` exports, plus the service
  methods reachable from `Book`, is public and follows semantic versioning.
  Modules whose name starts with `_` are private.
- **Snapshots, not live objects.** Services return frozen dataclasses. SQLAlchemy
  rows never leave the library.
- **No I/O or presentation** in the library: no printing, no prompting and no
  locale handling. The only exception is the helpers in `picciuli.money`.
- **Errors.** Every expected failure raises a `PicciuliError` subclass, and
  database integrity errors are translated into `ConflictError`.
- **Documentation.** Every public object has a Google-style docstring. The API
  reference is generated from them.

## Versioning and compatibility

All packages in the repository are released together with one version number.
A breaking change in the library is fixed in its in-repo clients in the same
commit. Three boundaries still need explicit compatibility handling:

1. **Database files** outlive every release, and several clients may open the
   same file at different versions.
    - The schema version is stored in the `meta` table.
    - `Book.open` upgrades older files automatically, running the steps
      registered in `picciuli/_db/schema.py`.
    - It refuses files written by a newer version.
    - To change the schema, bump `SCHEMA_VERSION`, add a migration step and
      test it. Write the step's DDL out in full instead of reusing the ORM
      tables, so that it keeps producing the same schema when the tables change
      later (see the version 1 → 2 step). The test in `tests/test_book.py`
      checks that an upgraded file has the same structure as a new one.
    - The version 2 ? 3 step adds the `trades` table and back-fills it only
      for buys and sales whose splits it can rebuild exactly from the inferred
      trade; any other transaction keeps no trade and is edited as splits.
2. **The HTTP API.** Browsers and phones update on their own schedule.
    - Changes to the API should be additive.
    - Breaking changes go under a new path prefix (`/v2`), while `/v1` is kept
      for a deprecation window.
3. **Third-party users** of the published `picciuli` package rely on semver.
