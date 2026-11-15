"""Configure the Zitadel security settings that native login depends on.

Run on the server, as root, from the directory holding `.env` and `secrets/`:

    sudo python3 zitadel_security.py status
    sudo python3 zitadel_security.py lockout --apply
    sudo python3 zitadel_security.py force-mfa            # dry run
    sudo python3 zitadel_security.py force-mfa --apply

Without `--apply` the script only prints what it would change. It reads the
administrator credentials (`ZITADEL_ADMIN_USERNAME`/`_PASSWORD`) from `.env` and
signs them in through the Swagger UI client (authorization code + PKCE), with the
login-client PAT finalizing the request, so no administrator PAT is created.
The administrator must not have MFA enrolled; otherwise use the console
(*Organization -> Settings*). Secrets are never printed. Only the standard
library is used.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

LOGIN_POLICY_FIELDS = (
    "allowUsernamePassword",
    "allowRegister",
    "allowExternalIdp",
    "forceMfa",
    "forceMfaLocalOnly",
    "passwordlessType",
    "hidePasswordReset",
    "ignoreUnknownUsernames",
    "defaultRedirectUri",
    "passwordCheckLifetime",
    "externalLoginCheckLifetime",
    "mfaInitSkipLifetime",
    "secondFactorCheckLifetime",
    "multiFactorCheckLifetime",
    "allowDomainDiscovery",
    "disableLoginWithEmail",
    "disableLoginWithPhone",
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface redirects so the Login V2 auth request ID can be read."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        """Never follow a redirect."""
        return None


def read_env(path: Path) -> dict[str, str]:
    """Parse `KEY=value` lines without evaluating them as shell code."""
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip("'\"")
    return env


class Client:
    """Minimal Zitadel JSON client; the login-client PAT is the default bearer."""

    def __init__(self, base: str, pat: str) -> None:
        self.base = base
        self.pat = pat

    def call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        token: str | None = None,
        form: dict[str, str] | None = None,
        org: str | None = None,
    ) -> dict[str, Any]:
        """Send a request; exit with Zitadel's error message on failure."""
        headers = {"Accept": "application/json"}
        bearer = self.pat if token is None else token
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        if org:
            headers["x-zitadel-orgid"] = org
        data = None
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            sys.exit(f"{method} {path.split('?')[0]} failed: {exc.code} {detail}")
        result: dict[str, Any] = json.loads(raw) if raw.strip() else {}
        return result


def admin_token(client: Client, env: dict[str, str]) -> tuple[str, str, str]:
    """Return an administrator access token and the session to delete."""
    name = env["ZITADEL_ADMIN_USERNAME"].lower()
    found = client.call(
        "POST",
        "/v2/users",
        {
            "queries": [
                {
                    "userNameQuery": {
                        "userName": name,
                        "method": "TEXT_QUERY_METHOD_STARTS_WITH_IGNORE_CASE",
                    }
                }
            ]
        },
    ).get("result", [])
    # The first-instance setup appends "@<organization domain>" to the name.
    users = [
        user
        for user in found
        if user.get("username", "").lower().split("@")[0] == name.split("@")[0]
        and "human" in user
    ]
    if len(users) != 1:
        sys.exit("The administrator user was not found exactly once.")
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    redirect = f"https://{env['API_DOMAIN']}/docs/oauth2-redirect"
    query = urllib.parse.urlencode(
        {
            "client_id": env["SWAGGER_CLIENT_ID"],
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": "openid urn:zitadel:iam:org:project:id:zitadel:aud",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": secrets.token_urlsafe(8),
        }
    )
    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(client.base + "/oauth/v2/authorize?" + query, timeout=15)
        sys.exit("The authorization endpoint did not redirect to Login V2.")
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location", "")
    auth_request = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query).get(
        "authRequest", [""]
    )[0]
    if not auth_request:
        sys.exit("The Swagger UI client does not use Login V2.")
    session = client.call(
        "POST",
        "/v2/sessions",
        {
            "checks": {
                "user": {"userId": users[0]["userId"]},
                "password": {"password": env["ZITADEL_ADMIN_PASSWORD"]},
            },
            "lifetime": "300s",
        },
    )
    callback = client.call(
        "POST",
        f"/v2/oidc/auth_requests/{auth_request}",
        {
            "session": {
                "sessionId": session["sessionId"],
                "sessionToken": session["sessionToken"],
            }
        },
    )["callbackUrl"]
    code = urllib.parse.parse_qs(urllib.parse.urlsplit(callback).query)["code"][0]
    token = client.call(
        "POST",
        "/oauth/v2/token",
        token="",
        form={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "client_id": env["SWAGGER_CLIENT_ID"],
            "code_verifier": verifier,
        },
    )["access_token"]
    return token, session["sessionId"], session["sessionToken"]


def lockout(client: Client, token: str, org: str, args: argparse.Namespace) -> None:
    """Lock users out after too many wrong passwords or one-time codes."""
    policy = client.call(
        "GET", "/management/v1/policies/lockout", token=token, org=org
    )["policy"]
    wanted = {"maxPasswordAttempts": args.password, "maxOtpAttempts": args.otp}
    current = {key: int(policy.get(key, 0)) for key in wanted}
    print(f"lockout: {current} -> {wanted}")
    if not args.apply or current == wanted:
        return
    method = "POST" if policy.get("isDefault", True) else "PUT"
    client.call(method, "/management/v1/policies/lockout", wanted, token=token, org=org)
    print("lockout policy saved")


def force_mfa(client: Client, token: str, org: str, args: argparse.Namespace) -> None:
    """Require a second factor for every user of the organization."""
    policy = client.call("GET", "/management/v1/policies/login", token=token, org=org)[
        "policy"
    ]
    print(f"forceMfa: {bool(policy.get('forceMfa'))} -> True")
    if "SECOND_FACTOR_TYPE_OTP" not in policy.get("secondFactors", []):
        sys.exit("Enable the authenticator app (OTP) second factor first.")
    if not args.apply or policy.get("forceMfa"):
        return
    body = {key: policy[key] for key in LOGIN_POLICY_FIELDS if key in policy}
    body["forceMfa"] = True
    if policy.get("isDefault", True):
        if policy.get("idps"):
            sys.exit("Identity providers are linked; set Force MFA in the console.")
        body["secondFactors"] = policy.get("secondFactors", [])
        body["multiFactors"] = policy.get("multiFactors", [])
        client.call("POST", "/management/v1/policies/login", body, token=token, org=org)
    else:
        client.call("PUT", "/management/v1/policies/login", body, token=token, org=org)
    print("login policy saved")


def status(client: Client, org: str) -> None:
    """Print the effective settings, as the API's lockout check reads them."""
    query = urllib.parse.urlencode({"ctx.orgId": org})
    lock = client.call("GET", f"/v2/settings/lockout?{query}")["settings"]
    login = client.call("GET", f"/v2/settings/login?{query}")["settings"]
    print(
        "lockout:",
        {
            key: int(lock.get(key, 0))
            for key in ("maxPasswordAttempts", "maxOtpAttempts")
        },
        lock.get("resourceOwnerType"),
    )
    print(
        "login:",
        {key: login.get(key, False) for key in ("forceMfa", "allowRegister")},
        login.get("secondFactors", []),
    )


def main() -> None:
    """Run one action from the command line."""
    parser = argparse.ArgumentParser(description="Zitadel security settings")
    parser.add_argument("action", choices=["status", "lockout", "force-mfa"])
    parser.add_argument("--apply", action="store_true", help="save the change")
    parser.add_argument("--password", type=int, default=5, help="password attempts")
    parser.add_argument("--otp", type=int, default=5, help="OTP attempts")
    parser.add_argument("--root", type=Path, default=Path("."), help="stack directory")
    args = parser.parse_args()
    if args.password < 1 or args.otp < 1:
        parser.error("attempt limits must be positive")
    env = read_env(args.root / ".env")
    pat = (args.root / "secrets" / "login-client.pat").read_text().strip()
    client = Client(f"https://{env['AUTH_DOMAIN']}", pat)
    org = env["LOGIN_ORG_ID"]
    if args.action != "status":
        token, session_id, session_token = admin_token(client, env)
        try:
            action = lockout if args.action == "lockout" else force_mfa
            action(client, token, org, args)
        finally:
            client.call(
                "POST",
                "/oauth/v2/revoke",
                token="",
                form={"token": token, "client_id": env["SWAGGER_CLIENT_ID"]},
            )
            client.call(
                "DELETE",
                f"/v2/sessions/{session_id}",
                {"sessionToken": session_token},
            )
    status(client, org)


if __name__ == "__main__":
    main()
