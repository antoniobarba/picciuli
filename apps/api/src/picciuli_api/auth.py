"""Authentication of OpenID Connect access tokens (JWT)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Final, Protocol

import jwt

__all__ = [
    "ALGORITHMS",
    "AuthUnavailableError",
    "AuthenticationError",
    "SigningKeySource",
    "TokenVerifier",
    "User",
]

ALGORITHMS: Final = (
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
    "EdDSA",
)
"""Accepted signature algorithms. Symmetric (HS*) and `none` are refused."""


class AuthenticationError(Exception):
    """The request carries no valid access token (HTTP 401)."""


class AuthUnavailableError(Exception):
    """The identity provider's signing keys cannot be fetched (HTTP 503)."""


@dataclass(frozen=True, slots=True)
class User:
    """An authenticated user.

    Attributes:
        issuer: Identity provider that issued the token (`iss` claim).
        subject: Stable user identifier at that provider (`sub` claim).
    """

    issuer: str
    subject: str

    @property
    def id(self) -> str:
        """Opaque, stable identifier: a SHA-256 hex digest of issuer and subject.

        It names the user's database file, so it never contains personal data
        and cannot be used for path traversal.
        """
        return hashlib.sha256(f"{self.issuer}\n{self.subject}".encode()).hexdigest()


class SigningKeySource(Protocol):
    """Where the public keys that sign tokens come from.

    [`jwt.PyJWKClient`][jwt.PyJWKClient] implements it by downloading (and
    caching) the identity provider's JSON Web Key Set.
    """

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        """Return the key matching the `kid` header of `token`."""
        ...  # pragma: no cover


class TokenVerifier:
    """Validate access tokens and turn them into [`User`][picciuli_api.auth.User]s.

    Args:
        issuer: Required `iss` claim.
        audience: Required `aud` claim (one of its values).
        keys: Source of the signing keys.
        leeway: Tolerated clock skew, in seconds.
    """

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        keys: SigningKeySource,
        leeway: float = 30.0,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self._keys = keys
        self._leeway = leeway

    @classmethod
    def from_jwks_url(cls, url: str, *, issuer: str, audience: str) -> TokenVerifier:
        """Build a verifier downloading the keys from a JWKS URL (cached 1 hour)."""
        client = jwt.PyJWKClient(url, cache_keys=True, lifespan=3600, timeout=10)
        return cls(issuer=issuer, audience=audience, keys=client)

    def verify(self, token: str) -> User:
        """Check the signature and the claims of `token`.

        Raises:
            AuthenticationError: If the token is malformed, expired, signed by an
                unknown key or issued for another issuer or audience.
            AuthUnavailableError: If the signing keys cannot be downloaded.
        """
        try:
            key = self._keys.get_signing_key_from_jwt(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=list(ALGORITHMS),
                audience=self.audience,
                issuer=self.issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iss", "sub", "aud"]},
            )
        except jwt.PyJWKClientConnectionError as exc:
            raise AuthUnavailableError("identity provider unreachable") from exc
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"invalid access token: {exc}") from exc
        subject = claims["sub"]
        if not isinstance(subject, str) or not subject:
            raise AuthenticationError("invalid access token: empty subject")
        return User(issuer=self.issuer, subject=subject)
