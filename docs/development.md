# Development

## Repository layout

```
packages/picciuli/   core library (src layout, tests next to it)
apps/tui/            console user interface (Textual), with its tests
tools/               maintenance scripts, e.g. the v1 migration, with their tests
docs/, mkdocs.yml    this documentation
pyproject.toml       uv workspace root + shared ruff / mypy / pytest configuration
```

Future clients will live next to the library, all in this same repository:

```
apps/api/        FastAPI web backend (generates openapi.json, serves apps/web)
apps/web/        TypeScript web/PWA front-end with a client generated from openapi.json
apps/desktop/    optional desktop wrapper
```

Clients use only the public API of the library. For the console interface this
is enforced by a test (`apps/tui/tests/test_public_api.py`) that inspects its
imports.

## Commands

```bash
pip install -e "packages/picciuli[dev,docs]" -e apps/tui   # or: uv sync

pytest --cov             # tests with branch coverage (fails below 95 %)
ruff check . && ruff format --check .
mypy                     # strict type checking
mkdocs serve             # live documentation at http://127.0.0.1:8000
mkdocs build --strict    # what CI runs
picciuli-tui --demo demo.db && picciuli-tui demo.db   # try the console UI
```

The console interface keeps its logic in widget-free modules
(`formatting.py`, `calendar_model.py`, `forms.py`) tested directly against
`Book.in_memory()`. The screens are tested headless with Textual's `Pilot`
(see `apps/tui/tests/conftest.py`).

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
      test it.
2. **The future HTTP API.** Browsers and phones update on their own schedule.
    - Changes to the API should be additive.
    - Breaking changes go under a new path prefix (`/v2`), while `/v1` is kept
      for a deprecation window.
3. **Third-party users** of the published `picciuli` package rely on semver.
