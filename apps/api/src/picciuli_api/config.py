"""Server configuration, read from `PICCIULI_*` environment variables."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

__all__ = ["Settings"]


class Settings(BaseSettings):
    """Configuration of the API server.

    Every field can be set with an environment variable named after it with the
    `PICCIULI_` prefix, for example `PICCIULI_OIDC_ISSUER`.
    """

    model_config = SettingsConfigDict(
        env_prefix="PICCIULI_", extra="ignore", hide_input_in_errors=True
    )

    data_dir: Path = Path("data")
    """Directory holding the per-user databases (in its `users` subdirectory)."""

    oidc_issuer: str
    """Issuer URL of the identity provider, exactly as in the `iss` claim."""
    oidc_audience: str
    """Expected `aud` claim of access tokens (with Zitadel: the project id)."""
    oidc_jwks_url: str | None = None
    """URL of the signing keys. Defaults to Zitadel's `<issuer>/oauth/v2/keys`."""
    oidc_swagger_client_id: str | None = None
    """Client id used by Swagger UI to log in (authorization code with PKCE).

    When unset, Swagger UI only accepts a pasted bearer token.
    """
    oidc_swagger_scopes: str = "openid profile email"
    """Space-separated scopes requested by Swagger UI."""

    login_origin: str = ""
    """Exact web origin for native login; empty disables the login endpoints."""
    login_client_id: str = ""
    """Only this OIDC application may use the native login endpoints."""
    login_org_id: str = ""
    """Organization in which native login users are registered and authenticated."""
    login_token_file: Path | None = None
    """Server-only PAT of an IAM_LOGIN_CLIENT service account."""
    login_cookie_secret: SecretStr = SecretStr("")
    """At least 32 random characters used to encrypt login cookies."""

    cors_origins: Annotated[list[str], NoDecode] = []
    """Origins allowed to call the API from a browser (comma-separated)."""

    max_open_books: int = Field(default=64, ge=1)
    """How many user databases are kept open at the same time."""
    max_import_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    """Largest database file accepted by `POST /me/import`, in bytes."""
    price_cache_seconds: float = Field(default=900.0, ge=0)
    """How long downloaded quotes and exchange rates are reused, in seconds."""

    host: str = "127.0.0.1"
    """Interface the server listens on."""
    port: int = Field(default=8000, ge=1, le=65535)
    """Port the server listens on."""
    forwarded_allow_ips: str = "127.0.0.1"
    """Proxies trusted to set `X-Forwarded-*` headers (comma-separated, or `*`)."""
    docs_enabled: bool = True
    """Whether to serve Swagger UI (`/docs`), ReDoc (`/redoc`) and the schema."""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _login_configuration(self) -> Settings:
        if self.login_origin:
            from urllib.parse import urlsplit

            origin = urlsplit(self.login_origin)
            if (
                origin.scheme not in {"http", "https"}
                or not origin.netloc
                or origin.path
                or origin.query
                or origin.fragment
                or origin.username
                or (
                    origin.scheme != "https"
                    and origin.hostname not in {"localhost", "127.0.0.1"}
                )
            ):
                raise ValueError("login_origin must be an HTTPS origin (or localhost)")
            if (
                not self.login_client_id
                or not self.login_org_id
                or not self.login_token_file
                or len(self.login_cookie_secret.get_secret_value()) < 32
            ):
                raise ValueError(
                    "native login requires client, organization, PAT and secret"
                )
        return self

    @property
    def jwks_url(self) -> str:
        """URL of the identity provider's JSON Web Key Set."""
        if self.oidc_jwks_url:
            return self.oidc_jwks_url
        return f"{self.oidc_issuer.rstrip('/')}/oauth/v2/keys"

    @property
    def users_dir(self) -> Path:
        """Directory of the per-user database files."""
        return self.data_dir / "users"
