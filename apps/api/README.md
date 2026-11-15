# picciuli-api

Multi-user REST API server for [Picciuli](../../README.md), built with FastAPI.

- Every user gets a private SQLite book, created on first use.
- Users log in with an external OpenID Connect provider (Zitadel by default);
  the API only validates the JWT access tokens.
- Interactive documentation: Swagger UI at `/docs`, ReDoc at `/redoc`, schema
  at `/openapi.json` (also committed as [`openapi.json`](openapi.json)).

```console
$ pip install -e "packages/picciuli[dev]" -e "apps/api[dev]"
$ export PICCIULI_OIDC_ISSUER=https://auth.example.com
$ export PICCIULI_OIDC_AUDIENCE=<zitadel project id>
$ picciuli-api            # serves on http://127.0.0.1:8000
$ picciuli-api openapi    # prints the OpenAPI schema
```

Requires Python 3.11 or newer. See the [API server guide](../../docs/api-server.md)
and the [deployment guide](../../docs/deployment.md).
