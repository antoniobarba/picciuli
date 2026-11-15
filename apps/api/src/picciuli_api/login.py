"""Picciuli's confidential, same-origin Zitadel login client.

The browser never receives the service PAT or Zitadel session tokens. OIDC
access and refresh tokens are still issued through authorization code + PKCE.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import logging
import math
import threading
import time
from collections.abc import Callable
from typing import Annotated, Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request as URLRequest
from urllib.request import urlopen

from cryptography.fernet import Fernet, InvalidToken
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from picciuli_api.config import Settings

_LOG = logging.getLogger(__name__)
_TTL = 600
_SESSION_TTL = 30 * 24 * 60 * 60
_IP_LIMIT = (30, 60.0)
"""Requests per client address (IPv6: per /64) and window, in seconds."""
_ACCOUNT_LIMIT = (10, 900.0)
"""Attempts per username, user ID or Zitadel session and window, in seconds."""
_LOCKOUT_RECHECK = (300.0, 60.0)
"""Seconds before re-reading the lockout policy when present and when missing."""
_UNAVAILABLE = "Sign-in is temporarily unavailable."
Text = Annotated[str, Field(min_length=1, max_length=200)]
Code = Annotated[str, Field(min_length=1, max_length=20)]


class Input(BaseModel):
    """Reject extra fields on every browser request."""

    model_config = ConfigDict(extra="forbid")


class Start(Input):
    """Bind the browser to one OIDC request."""

    auth_request: Text


class Credentials(Input):
    """Password credentials, never persisted or logged."""

    username: Text
    password: Text


class Registration(Credentials):
    """Profile fields required by Zitadel."""

    given_name: Text
    family_name: Text


class Verification(Input):
    """A user-supplied verification code."""

    code: Code


class EmailVerification(Verification):
    """An email link can be opened on another device."""

    user_id: Text


class ResetRequest(Input):
    """Request recovery without disclosing whether an account exists."""

    username: Text


class ResetPassword(EmailVerification):
    """A recovery code authorizes a new password, not a login."""

    password: Text


class ChangePassword(Input):
    """An existing password authorizes a required password change."""

    current_password: Text
    password: Text


class Flow(BaseModel):
    """Encrypted browser state; no password or verification code is retained."""

    auth_request: str
    session_id: str = ""
    session_token: str = ""
    user_id: str = ""
    stage: str = "login"


class UpstreamError(HTTPException):
    """A rejected Zitadel request, without its potentially sensitive body."""

    def __init__(self, status: int) -> None:
        super().__init__(
            400, "The details or code were not accepted. Check them and try again."
        )
        self.status = status


def client_key(host: str) -> str:
    """Group addresses one client can cheaply rotate through (an IPv6 /64)."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.IPv6Network((address, 64), strict=False))
    return str(address)


class Throttle:
    """Fixed-window attempt counters that expire with time, never with volume.

    When `max_keys` windows are active, new keys are refused rather than
    evicting the counters of an attacker who floods the table.
    """

    def __init__(
        self,
        *,
        max_keys: int = 100_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_keys = max_keys
        self.clock = clock
        self.windows: dict[str, tuple[float, int]] = {}
        self.lock = threading.Lock()
        self.sweep_at = 0.0

    def hit(self, key: str, limit: int, window: float) -> float:
        """Count an attempt; return the seconds to wait if over `limit`, else 0."""
        now = self.clock()
        with self.lock:
            if now >= self.sweep_at:
                self.windows = {k: v for k, v in self.windows.items() if v[0] > now}
                self.sweep_at = now + 60
            end, count = self.windows.get(key, (0.0, 0))
            if end <= now:
                if key not in self.windows and len(self.windows) >= self.max_keys:
                    return window
                end, count = now + window, 0
            self.windows[key] = (end, count + 1)
        return end - now if count >= limit else 0.0


def too_many(wait: float, message: str) -> HTTPException:
    """A 429 response telling the client when to retry."""
    return HTTPException(
        429, message, headers={"Retry-After": str(max(1, math.ceil(wait)))}
    )


class Zitadel:
    """Small server-only client for the documented v2 JSON APIs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def call(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Call Zitadel with a bounded timeout and sanitized errors."""
        token_file = self.settings.login_token_file
        if token_file is None:
            _LOG.error("Native login has no identity service token configured")
            raise HTTPException(503, _UNAVAILABLE)
        try:
            token = token_file.read_text().strip()
            request = URLRequest(
                self.settings.oidc_issuer.rstrip("/") + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method=method,
            )
            with urlopen(request, timeout=15) as response:
                result: dict[str, Any] = json.load(response)
            if not isinstance(result, dict):
                raise ValueError("invalid identity response")
            return result
        except HTTPError as exc:
            if exc.code >= 500 or exc.code in {401, 403}:
                _LOG.error("Identity service rejected a server request: %s", exc.code)
                raise HTTPException(503, _UNAVAILABLE) from exc
            raise UpstreamError(exc.code) from exc
        except (OSError, URLError, ValueError) as exc:
            _LOG.error("Identity service unavailable (%s)", type(exc).__name__)
            raise HTTPException(503, _UNAVAILABLE) from exc


class Login:
    """Login orchestration and its encrypted, expiring browser state."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.zitadel = Zitadel(settings)
        key = hashlib.sha256(settings.login_cookie_secret.get_secret_value().encode())
        self.cipher = Fernet(base64.urlsafe_b64encode(key.digest()))
        self.secure = settings.login_origin.startswith("https://")
        self.prefix = "__Host-" if self.secure else ""
        self.throttle = Throttle()
        self.lockout_ok = False
        self.lockout_checked_until = -math.inf

    def guard(self, request: Request) -> None:
        """Reject cross-origin writes and bound anonymous request rates."""
        if request.headers.get("origin") != self.settings.login_origin:
            raise HTTPException(403, "Open this form from Picciuli.")
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise HTTPException(415, "A JSON request is required.")
        ip = client_key(request.client.host if request.client else "unknown")
        wait = self.throttle.hit("ip:" + ip, *_IP_LIMIT)
        if wait:
            raise too_many(wait, "Too many attempts. Wait a minute and try again.")

    def limit(self, **keys: str) -> None:
        """Bound guesses per account, user and session, whatever the client IP.

        Also refuse sign-in while Zitadel would not lock out password and OTP
        guessing (see `require_lockout`).
        """
        self.require_lockout()
        for kind, value in keys.items():
            if value:
                wait = self.throttle.hit(f"{kind}:{value}", *_ACCOUNT_LIMIT)
                if wait:
                    raise too_many(
                        wait, "Too many attempts. Wait a few minutes and try again."
                    )

    def require_lockout(self) -> None:
        """Check that Zitadel locks accounts after repeated wrong passwords and OTPs.

        Without the policy, sign-in fails closed (503) unless
        `login_require_lockout` is false; either way, an error is logged.
        """
        now = time.monotonic()
        if now < self.lockout_checked_until:
            ok = self.lockout_ok
        else:
            query = urlencode({"ctx.orgId": self.settings.login_org_id})
            try:
                policy = self.zitadel.call("GET", f"/v2/settings/lockout?{query}")
                settings = policy.get("settings", {})
                ok = (
                    int(settings.get("maxPasswordAttempts", 0)) > 0
                    and int(settings.get("maxOtpAttempts", 0)) > 0
                )
            except (UpstreamError, AttributeError, TypeError, ValueError):
                ok = False
            self.lockout_ok = ok
            self.lockout_checked_until = now + _LOCKOUT_RECHECK[0 if ok else 1]
            if not ok:
                _LOG.error(
                    "Zitadel organization %s has no lockout policy "
                    "(maxPasswordAttempts and maxOtpAttempts must be > 0); %s",
                    self.settings.login_org_id,
                    "native sign-in is refused"
                    if self.settings.login_require_lockout
                    else "password and OTP guessing is not limited",
                )
        if not ok and self.settings.login_require_lockout:
            raise HTTPException(503, _UNAVAILABLE)

    def save(self, response: Response, flow: Flow, *, session: bool = False) -> None:
        """Seal state in a host-only HttpOnly cookie."""
        ttl = _SESSION_TTL if session else _TTL
        response.set_cookie(
            self.prefix + ("picciuli-session" if session else "picciuli-flow"),
            self.cipher.encrypt(flow.model_dump_json().encode()).decode(),
            max_age=ttl,
            secure=self.secure,
            httponly=True,
            samesite="lax",
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"

    def load(self, request: Request, *, session: bool = False) -> Flow:
        """Authenticate cookie contents and enforce expiration."""
        name = self.prefix + ("picciuli-session" if session else "picciuli-flow")
        try:
            data = self.cipher.decrypt(
                request.cookies.get(name, "").encode(),
                ttl=_SESSION_TTL if session else _TTL,
            )
            return Flow.model_validate_json(data)
        except (InvalidToken, ValidationError) as exc:
            raise HTTPException(
                401, "This sign-in expired. Please start again."
            ) from exc

    def policy(self) -> dict[str, Any]:
        """Use organization settings, not just instance defaults."""
        query = urlencode({"ctx.orgId": self.settings.login_org_id})
        result: dict[str, Any] = self.zitadel.call(
            "GET", f"/v2/settings/login?{query}"
        )["settings"]
        return result

    def user(self, user_id: str) -> dict[str, Any]:
        """Only human users of the configured organization may use this client.

        Unknown and foreign users fail alike, so user IDs cannot be probed.
        """
        user: dict[str, Any] = self.zitadel.call(
            "GET", f"/v2/users/{quote(user_id, safe='')}"
        )["user"]
        if (
            user["details"]["resourceOwner"] != self.settings.login_org_id
            or "human" not in user
            or user.get("state") not in {"USER_STATE_ACTIVE", "USER_STATE_INITIAL"}
        ):
            raise UpstreamError(404)
        return user

    def session(self, flow: Flow) -> dict[str, Any]:
        """Read the verified factors from Zitadel, never from browser input."""
        query = urlencode({"sessionToken": flow.session_token})
        result: dict[str, Any] = self.zitadel.call(
            "GET", f"/v2/sessions/{quote(flow.session_id, safe='')}?{query}"
        )["session"]
        return result

    def check(self, flow: Flow, checks: dict[str, Any]) -> None:
        """Update a session and always retain the latest session token."""
        result = self.zitadel.call(
            "PATCH",
            f"/v2/sessions/{quote(flow.session_id, safe='')}",
            {"sessionToken": flow.session_token, "checks": checks},
        )
        flow.session_token = result["sessionToken"]

    def authenticate(self, flow: Flow, username: str, password: str) -> None:
        """Create a fresh password-checked session for every sign-in."""
        policy = self.policy()
        if not policy.get("allowUsernamePassword") or not policy.get(
            "allowLocalAuthentication"
        ):
            raise HTTPException(
                403, "Password sign-in is disabled for this organization."
            )
        result = self.zitadel.call(
            "POST",
            "/v2/sessions",
            {
                "checks": {
                    "user": {"loginName": username},
                    "password": {"password": password},
                },
                "lifetime": f"{_SESSION_TTL}s",
            },
        )
        flow.session_id = result["sessionId"]
        flow.session_token = result["sessionToken"]
        flow.user_id = self.session(flow)["factors"]["user"]["id"]

    def advance(self, flow: Flow, response: Response) -> dict[str, Any]:
        """Fail closed until password, email and required MFA are verified."""
        session = self.session(flow)
        factors = session["factors"]
        if not factors.get("password") or factors["user"]["id"] != flow.user_id:
            raise HTTPException(403, "Please sign in again.")
        human = self.user(flow.user_id)["human"]
        policy = self.policy()
        if not policy.get("allowUsernamePassword") or not policy.get(
            "allowLocalAuthentication"
        ):
            raise HTTPException(
                403, "Password sign-in is disabled for this organization."
            )
        if human.get("passwordChangeRequired"):
            flow.stage = "change-password"
        elif not human["email"].get("isVerified"):
            flow.stage = "verify-email"
        else:
            methods = self.zitadel.call(
                "GET",
                f"/v2/users/{quote(flow.user_id, safe='')}/authentication_methods",
            ).get("authMethodTypes", [])
            second = {
                "AUTHENTICATION_METHOD_TYPE_TOTP",
                "AUTHENTICATION_METHOD_TYPE_U2F",
                "AUTHENTICATION_METHOD_TYPE_OTP_EMAIL",
                "AUTHENTICATION_METHOD_TYPE_OTP_SMS",
            }
            required = bool(
                second.intersection(methods)
                or policy.get("forceMfa")
                or policy.get("forceMfaLocalOnly")
            )
            if required and "SECOND_FACTOR_TYPE_OTP" not in policy.get(
                "secondFactors", []
            ):
                raise HTTPException(
                    403,
                    "Your required security method is not supported here. "
                    "Contact support.",
                )
            if required and not factors.get("totp"):
                if "AUTHENTICATION_METHOD_TYPE_TOTP" in methods:
                    flow.stage = "totp"
                elif second.intersection(methods):
                    raise HTTPException(
                        403,
                        "Use an account with an authenticator app, "
                        "or contact support for account recovery.",
                    )
                else:
                    flow.stage = "setup-totp"
            else:
                callback = self.zitadel.call(
                    "POST",
                    f"/v2/oidc/auth_requests/{quote(flow.auth_request, safe='')}",
                    {
                        "session": {
                            "sessionId": flow.session_id,
                            "sessionToken": flow.session_token,
                        }
                    },
                )["callbackUrl"]
                parsed = urlsplit(callback)
                if (
                    f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    != self.settings.login_origin + "/callback"
                ):
                    raise HTTPException(502, "The sign-in callback is invalid.")
                self.save(response, flow, session=True)
                response.delete_cookie(
                    self.prefix + "picciuli-flow", path="/", secure=self.secure
                )
                return {"step": "complete", "callback_url": callback}
        self.save(response, flow)
        return {"step": flow.stage}

    def email_template(self, path: str) -> dict[str, str]:
        """Keep verification and recovery links in the Picciuli application."""
        return {
            "urlTemplate": self.settings.login_origin
            + path
            + "?userID={{.UserID}}&code={{.Code}}"
        }


def create_login_router(settings: Settings) -> APIRouter:
    """Expose narrowly scoped browser operations, never a general API proxy."""
    login = Login(settings)
    router = APIRouter(
        prefix="/api/auth", include_in_schema=False, dependencies=[Depends(login.guard)]
    )

    def call(method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            return login.zitadel.call(method, path, body)
        except UpstreamError as exc:
            raise HTTPException(
                400, "The details or code were not accepted. Check them and try again."
            ) from exc

    @router.post("/start")
    def start(data: Start, response: Response) -> dict[str, Any]:
        login.require_lockout()
        auth = call(
            "GET", f"/v2/oidc/auth_requests/{quote(data.auth_request, safe='')}", {}
        )["authRequest"]
        if (
            auth["clientId"] != settings.login_client_id
            or auth["redirectUri"] != settings.login_origin + "/callback"
        ):
            raise HTTPException(403, "This sign-in request is not for Picciuli.")
        login.save(response, Flow(auth_request=data.auth_request))
        policy = login.policy()
        query = urlencode({"ctx.orgId": settings.login_org_id})
        password = login.zitadel.call(
            "GET", f"/v2/settings/password/complexity?{query}"
        )["settings"]
        return {
            "step": "login",
            "can_register": bool(policy.get("allowRegister")),
            "can_reset": not policy.get("hidePasswordReset", False),
            "password_policy": password,
        }

    @router.post("/login")
    def sign_in(
        data: Credentials, request: Request, response: Response
    ) -> dict[str, Any]:
        flow = login.load(request)
        login.limit(username=data.username.strip().casefold())
        try:
            login.authenticate(flow, data.username, data.password)
            return login.advance(flow, response)
        except UpstreamError as exc:
            raise HTTPException(
                400, "Unable to sign in. Check your email and password."
            ) from exc

    @router.post("/register")
    def register(
        data: Registration, request: Request, response: Response
    ) -> dict[str, Any]:
        flow = login.load(request)
        if not login.policy().get("allowRegister"):
            raise HTTPException(403, "Registration is currently disabled.")
        result = call(
            "POST",
            "/v2/users/human",
            {
                "organization": {"orgId": settings.login_org_id},
                "username": data.username,
                "profile": {
                    "givenName": data.given_name,
                    "familyName": data.family_name,
                },
                "email": {
                    "email": data.username,
                    "sendCode": login.email_template("/verify-email"),
                },
                "password": {"password": data.password, "changeRequired": False},
            },
        )
        flow.user_id = result["userId"]
        flow.stage = "registered"
        login.save(response, flow)
        # Registration never authenticates a user or marks an email verified.
        return {"step": "registered"}

    @router.post("/verify-email")
    def verify_email(data: EmailVerification, response: Response) -> dict[str, str]:
        login.limit(user=data.user_id)
        # Unknown, foreign and wrong-code requests share one generic 400.
        login.user(data.user_id)
        call(
            "POST",
            f"/v2/users/{quote(data.user_id, safe='')}/email/verify",
            {"verificationCode": data.code},
        )
        response.headers["Cache-Control"] = "no-store"
        return {"step": "verified"}

    @router.post("/verify")
    def verify(
        data: Verification, request: Request, response: Response
    ) -> dict[str, Any]:
        flow = login.load(request)
        login.limit(user=flow.user_id, session=flow.session_id)
        if flow.stage in {"registered", "verify-email"}:
            call(
                "POST",
                f"/v2/users/{quote(flow.user_id, safe='')}/email/verify",
                {"verificationCode": data.code},
            )
            if flow.stage == "registered":
                return {"step": "verified"}
        elif flow.stage == "totp":
            try:
                login.check(flow, {"totp": {"code": data.code}})
            except UpstreamError as exc:
                raise HTTPException(
                    400, "The authenticator code was not accepted."
                ) from exc
        else:
            raise HTTPException(409, "Restart sign-in to continue.")
        return login.advance(flow, response)

    @router.post("/resend-email")
    def resend(request: Request) -> dict[str, str]:
        flow = login.load(request)
        if flow.stage not in {"registered", "verify-email"}:
            raise HTTPException(409, "There is no email verification in progress.")
        call(
            "POST",
            f"/v2/users/{quote(flow.user_id, safe='')}/email/resend",
            {"sendCode": login.email_template("/verify-email")},
        )
        return {"step": flow.stage}

    @router.post("/setup-totp")
    def setup_totp(request: Request) -> dict[str, str]:
        flow = login.load(request)
        if flow.stage != "setup-totp":
            raise HTTPException(409, "Authenticator setup is not available.")
        result = call("POST", f"/v2/users/{quote(flow.user_id, safe='')}/totp", {})
        return {"step": "setup-totp", "secret": result["secret"]}

    @router.post("/confirm-totp")
    def confirm_totp(
        data: Verification, request: Request, response: Response
    ) -> dict[str, Any]:
        flow = login.load(request)
        if flow.stage != "setup-totp":
            raise HTTPException(409, "Authenticator setup is not available.")
        login.limit(user=flow.user_id, session=flow.session_id)
        call(
            "POST",
            f"/v2/users/{quote(flow.user_id, safe='')}/totp/verify",
            {"code": data.code},
        )
        # Enrollment consumes a TOTP; ask for the next code to authenticate.
        flow.stage = "totp"
        login.save(response, flow)
        return {"step": "totp"}

    def send_reset(username: str) -> None:
        try:
            users = login.zitadel.call(
                "POST",
                "/v2/users",
                {
                    "query": {"limit": 2},
                    "queries": [
                        {
                            "organizationIdQuery": {
                                "organizationId": settings.login_org_id
                            }
                        },
                        {
                            "emailQuery": {
                                "emailAddress": username,
                                "method": "TEXT_QUERY_METHOD_EQUALS_IGNORE_CASE",
                            }
                        },
                    ],
                },
            ).get("result", [])
            for user in users:
                login.zitadel.call(
                    "POST",
                    f"/v2/users/{quote(user['userId'], safe='')}/password_reset",
                    {"sendLink": login.email_template("/reset-password")},
                )
        except HTTPException as exc:
            _LOG.warning("A password reset could not be sent (%s)", exc.status_code)

    @router.post("/reset-request")
    def reset_request(data: ResetRequest, tasks: BackgroundTasks) -> dict[str, str]:
        if login.policy().get("hidePasswordReset"):
            raise HTTPException(403, "Password recovery is disabled.")
        login.limit(username=data.username.strip().casefold())
        # After the response, so its timing does not reveal whether a user exists.
        tasks.add_task(send_reset, data.username)
        return {"step": "reset-sent"}

    @router.post("/reset-password")
    def reset_password(data: ResetPassword) -> dict[str, str]:
        if login.policy().get("hidePasswordReset"):
            raise HTTPException(403, "Password recovery is disabled.")
        login.limit(user=data.user_id)
        login.user(data.user_id)
        call(
            "POST",
            f"/v2/users/{quote(data.user_id, safe='')}/password",
            {
                "newPassword": {"password": data.password, "changeRequired": False},
                "verificationCode": data.code,
            },
        )
        return {"step": "password-reset"}

    @router.post("/change-password")
    def change_password(
        data: ChangePassword, request: Request, response: Response
    ) -> dict[str, Any]:
        flow = login.load(request)
        if flow.stage != "change-password":
            raise HTTPException(409, "A password change is not in progress.")
        login.limit(user=flow.user_id, session=flow.session_id)
        call(
            "POST",
            f"/v2/users/{quote(flow.user_id, safe='')}/password",
            {
                "newPassword": {"password": data.password, "changeRequired": False},
                "currentPassword": data.current_password,
            },
        )
        try:
            login.check(flow, {"password": {"password": data.password}})
        except UpstreamError as exc:
            raise HTTPException(400, "Sign in again with your new password.") from exc
        return login.advance(flow, response)

    @router.post("/logout")
    def logout(
        request: Request, response: Response
    ) -> dict[str, Literal["signed-out"]]:
        name = login.prefix + "picciuli-session"
        if request.cookies.get(name):
            flow = login.load(request, session=True)
            try:
                login.zitadel.call(
                    "DELETE",
                    f"/v2/sessions/{quote(flow.session_id, safe='')}",
                    {"sessionToken": flow.session_token},
                )
            except UpstreamError as exc:
                if exc.status != 404:
                    raise HTTPException(
                        503, "Sign-out failed. Please try again."
                    ) from exc
        for cookie in ("picciuli-session", "picciuli-flow"):
            response.delete_cookie(login.prefix + cookie, path="/", secure=login.secure)
        response.headers["Cache-Control"] = "no-store"
        return {"step": "signed-out"}

    return router
