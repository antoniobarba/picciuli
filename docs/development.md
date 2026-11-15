# Development

## Repository layout

```
packages/picciuli/   core library (src layout, tests next to it)
apps/tui/            console user interface (Textual), with its tests
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

Clients use only the public API of the library. For the console interface this
is enforced by a test (`apps/tui/tests/test_public_api.py`) that inspects its
imports.

## Commands

```bash
pip install -e "packages/picciuli[dev,docs]" -e apps/tui   # or: uv sync
pip install -e "apps/api[dev]"                             # API server, Python 3.11+

pytest --cov             # tests with branch coverage (fails below 95 %)
ruff check . && ruff format --check .
mypy                     # strict type checking
mkdocs serve             # live documentation at http://127.0.0.1:8000
mkdocs build --strict    # what CI runs
picciuli-tui --demo demo.db && picciuli-tui demo.db   # try the console UI
picciuli-api openapi --output apps/api/openapi.json   # after changing the API
cd apps/web && npm run api-types                      # ...then update the web client
```

The web front-end has its own Node.js tooling (Node 20.19+ or 22):
`npm ci`, `npm test`, `npm run lint`, `npm run typecheck` and `npm run build`
in `apps/web`; see [Web and mobile app](web.md#development).

The console interface keeps its logic in widget-free modules
(`formatting.py`, `calendar_model.py`, `forms.py`) tested directly against
`Book.in_memory()`. The screens are tested headless with Textual's `Pilot`
(see `apps/tui/tests/conftest.py`).

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
2. **The HTTP API.** Browsers and phones update on their own schedule.
    - Changes to the API should be additive.
    - Breaking changes go under a new path prefix (`/v2`), while `/v1` is kept
      for a deprecation window.
3. **Third-party users** of the published `picciuli` package rely on semver.
