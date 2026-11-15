# API server

`apps/api` is a multi-user REST server built with [FastAPI](https://fastapi.tiangolo.com/)
on top of the library. It is meant to be used by a web or mobile front-end.

## How it works

```
Front-end ──login (OIDC, PKCE)──▶ Zitadel (auth.example.com)
    │ Authorization: Bearer <access token (JWT)>
    ▼
Caddy (HTTPS) ──▶ picciuli-api ──▶ data/users/<user id>.db   (one Book per user)
                       └──▶ Yahoo Finance, through a shared 15-minute cache
```

- **Zitadel owns identities.** The optional [native login backend](web.md#enabling-native-login)
  forwards registration, passwords, recovery and MFA checks to Zitadel through
  narrowly scoped `/api/auth/*` endpoints. Credentials are not stored by Picciuli.
  The book API still checks the signature, issuer, audience and expiry of the
  OIDC JWT access token in each request.
- **Every user has a private SQLite book**, created on the first request. The
  file name is a SHA-256 digest of the token's issuer and subject, so it never
  contains personal data. Users cannot reach each other's data: there is no
  request parameter that selects a book.
- Open books are kept in a bounded cache (`PICCIULI_MAX_OPEN_BOOKS`) and closed
  when idle and least recently used.
- **Prices and exchange rates** are only downloaded when a user asks for a
  refresh. Quotes are public, so one cache serves everybody: a symbol is
  downloaded at most once every `PICCIULI_PRICE_CACHE_SECONDS` (15 minutes).
  The cache keeps the 1024 most recently used symbols and currency pairs.

## Interactive documentation

| URL             | Content                                                   |
|-----------------|-----------------------------------------------------------|
| `/docs`         | Swagger UI: read and try every endpoint                    |
| `/redoc`        | ReDoc: the same reference, easier to read                  |
| `/openapi.json` | the OpenAPI 3 schema, also committed as `apps/api/openapi.json` |

Click **Authorize** in Swagger UI and paste an access token, or, when
`PICCIULI_OIDC_SWAGGER_CLIENT_ID` is set, log in through Zitadel directly.

The committed schema lets the front-end generate a typed client, for example
`npx openapi-typescript apps/api/openapi.json -o src/api.d.ts`. A test fails
when the schema is out of date; regenerate it with:

```bash
picciuli-api openapi --output apps/api/openapi.json
```

## Conventions

- All endpoints are under `/api/v1` and need a bearer token; `/healthz` does not.
- Amounts are integers in minor units (cents), signed from the user's point of
  view, exactly as in the [library](concepts.md). A single amount is at most
  10^15 in absolute value; every [limit](concepts.md#limits) of the library
  (identifiers, text lengths, at most 100 splits) is part of the OpenAPI
  schema, so invalid values get `422 invalid_request` before reaching it.
- Quantities, prices and exchange rates are decimal **strings** (`"1.25"`,
  at most 8 decimal places, below 10^10, no exponent), so no precision is
  lost in JavaScript. Requests also accept JSON numbers.
- Dates are `YYYY-MM-DD` strings; numbers such as `0` are rejected.
- `PATCH` changes only the fields present in the body; `null` clears a field.
  Fields that cannot be cleared (for example a name) reject `null`.
- Transaction splits carry a `type`: `{"type": "account", "account_id": 1,
  "amount": -500}` or `{"type": "external", "amount": -500, "category_id": 3}`.
- `POST` returns `201` with the created entity, `DELETE` returns `204`.
- Errors always look like `{"error": "<code>", "detail": "<message>"}`:

| Status | `error`                | Cause                                         |
|--------|------------------------|-----------------------------------------------|
| 400    | `bad_request`          | a body that cannot be read                    |
| 401    | `unauthorized`         | missing, expired or invalid token             |
| 404    | `not_found`            | unknown entity or URL                         |
| 405    | `method_not_allowed`   | `Allow` lists every method of the path        |
| 409    | `conflict`             | duplicate name, entity in use, closed account, import already running |
| 413    | `too_large`            | uploaded file above `MAX_IMPORT_BYTES`, or a body above the proxy limit |
| 422    | `invalid_request`      | malformed request (with an `errors` list)     |
| 422    | `validation_error`     | a domain rule, e.g. unbalanced splits         |
| 502    | `price_provider_error` | the price provider failed                     |
| 503    | `auth_unavailable`     | the identity provider's keys are unreachable  |
| 503    | `busy`                 | `MAX_CONCURRENT_IMPORTS` imports are running  |
| 500    | `internal_error`       | a bug; details are only in the server log    |

## Main endpoints

| Resource       | Endpoints                                                                 |
|----------------|---------------------------------------------------------------------------|
| me             | `GET /me`, `GET /me/export` (SQLite download), `POST /me/import?mode=merge\|replace` (SQLite upload), `DELETE /me` (erase data) |
| settings       | `GET`, `PATCH /settings`                                                  |
| accounts       | CRUD, `/balances`, `/net-worth`, `/{id}/balance`, `/{id}/register`, `/{id}/move`, `/{id}/close`, `/{id}/reopen` |
| categories     | CRUD, `?top_level=true`, `/{id}/children`, `DELETE ?reassign_to=` or `?uncategorize=true` |
| transactions   | CRUD with splits, search filters, `/dates`, `/expense`, `/income`, `/transfer` |
| periods        | CRUD, `?on=<day>`, `/{id}/summary`, `/{id}/budget-report`                 |
| budgets        | CRUD, `/copy`                                                             |
| securities     | CRUD, `/{id}/prices`, `PUT`/`DELETE /{id}/prices/{date}`, `/{id}/latest-price` |
| exchange rates | `/{currency}`, `/{currency}/latest`, `PUT /{currency}/{date}`             |
| investments    | `/valuations`, `/net-worth`, `/buy`, `/sell`, `/refresh-prices`, `/refresh-exchange-rates`, `/{account}/valuation`, `/{account}/holdings`, `/{account}/sale-cost` |
| providers      | `/prices`, `/rates`, `/prices/{id}/search?q=`                             |

`POST /me/import` treats the uploaded file as untrusted: it is opened
read-only, its schema must match the current schema version exactly (no views,
triggers or extra tables), and every row is created again through the library
services, so the data must respect the same rules as data entered by hand.
Files with an older schema version are refused with `422`: open them once with
an up-to-date console application, which upgrades them, then import them
again.
## Configuration

Environment variables (all prefixed with `PICCIULI_`):

| Variable                  | Default                     | Meaning                                         |
|---------------------------|-----------------------------|-------------------------------------------------|
| `OIDC_ISSUER`             | *required*                  | issuer URL, exactly as in the `iss` claim      |
| `OIDC_AUDIENCE`           | *required*                  | expected `aud` (the Zitadel project id)         |
| `OIDC_JWKS_URL`           | `<issuer>/oauth/v2/keys`    | signing keys (Zitadel's location by default)    |
| `OIDC_SWAGGER_CLIENT_ID`  | unset                       | lets Swagger UI log in with PKCE                |
| `OIDC_SWAGGER_SCOPES`     | `openid profile email`      | scopes requested by Swagger UI                  |
| `OIDC_MAX_TOKEN_LIFETIME` | `86400` (24 h)              | longest accepted `exp` - `iat` of a token       |
| `LOGIN_REQUIRE_LOCKOUT`   | `true`                      | refuse native sign-in without a Zitadel lockout policy |
| `DATA_DIR`                | `data`                      | the books are in its `users` subdirectory       |
| `CORS_ORIGINS`            | none                        | comma-separated front-end origins               |
| `MAX_OPEN_BOOKS`          | `64`                        | books kept open at the same time                |
| `MAX_IMPORT_BYTES`        | `52428800` (50 MB)          | largest file accepted by `POST /me/import`      |
| `MAX_CONCURRENT_IMPORTS`  | `2`                         | imports running at once (one per user)          |
| `IMPORT_TIMEOUT_SECONDS`  | `60`                        | time budget of one import before it is refused  |
| `PRICE_CACHE_SECONDS`     | `900`                       | shared quote and rate cache duration            |
| `HOST`, `PORT`            | `127.0.0.1`, `8000`         | listening address                               |
| `FORWARDED_ALLOW_IPS`     | `127.0.0.1`                 | proxies trusted for `X-Forwarded-*`             |
| `DOCS_ENABLED`            | `true`                      | serve `/docs`, `/redoc` and `/openapi.json`     |

## Running locally

```bash
pip install -e "packages/picciuli[dev]" -e "apps/api[dev]"
export PICCIULI_OIDC_ISSUER=https://auth.example.com
export PICCIULI_OIDC_AUDIENCE=<project id>
picciuli-api       # http://127.0.0.1:8000/docs
```

You need a token from a real Zitadel instance to call the endpoints: either
point the variables at your production Zitadel (add a development application
with `http://localhost:8000/docs/oauth2-redirect` as redirect URI) or run the
[deployment stack](deployment.md) locally.

## Tests

The tests in `apps/api/api_tests` exercise the real application: they sign JWTs
with an RSA key generated during the test session and give the app the matching
public key, so authentication is never mocked away and no network is used.
Price providers are replaced by in-memory fakes with a fake clock.

- `test_auth.py`: expired, forged, wrong-audience, wrong-issuer and over-long
  tokens, and generic 401 bodies;
- `test_books.py`: per-user files, the open-book cache and its eviction;
- `test_isolation.py`: users never see each other's data;
- one module per resource for the endpoints, including error paths;
- `test_schema.py`: the committed OpenAPI schema is current and every endpoint
  is documented and protected.
