"""Reset only the explicitly provisioned production demo identity and book."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from picciuli import Book
from picciuli_api.auth import User
from picciuli_api.config import Settings
from picciuli_api.login import Zitadel
from picciuli_tui.demo import create_demo


def reset_book(destination: Path, today: dt.date) -> None:
    """Replace data atomically without unlinking a database cached by the API."""
    with tempfile.TemporaryDirectory(prefix="picciuli-demo-") as directory:
        seed = Path(directory) / "seed.db"
        create_demo(seed, today)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with Book.open(destination):
            pass
        with (
            closing(sqlite3.connect(seed)) as source,
            closing(sqlite3.connect(destination, timeout=30)) as target,
        ):
            if source.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RuntimeError("Demo seed failed its integrity check")
            if source.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Demo seed has invalid references")
            # SQLite's online backup locks and commits the destination atomically;
            # replacing the file itself would strand the API's open connections.
            source.backup(target)


def main() -> None:
    """Read VM-only credentials, validate the pinned identity, and reset it."""
    credentials = json.loads(Path("/run/secrets/demo.json").read_text())
    user_id = credentials["user_id"]
    password = credentials["password"]
    if not isinstance(user_id, str) or not user_id.isdecimal():
        raise ValueError("The demo identity must be pinned to a numeric user ID")
    if not isinstance(password, str) or not password:
        raise ValueError("The demo password must be configured")
    settings = Settings()  # type: ignore[call-arg]
    zitadel = Zitadel(settings)
    identity = zitadel.call("GET", f"/v2/users/{quote(user_id, safe='')}")["user"]
    if (
        identity.get("username") != "demo"
        or identity["details"]["resourceOwner"] != settings.login_org_id
        or identity.get("state") not in {"USER_STATE_ACTIVE", "USER_STATE_LOCKED"}
        or "human" not in identity
    ):
        raise RuntimeError("Refusing to reset an unexpected demo identity")
    if identity["state"] == "USER_STATE_LOCKED":
        # Anyone can trip the lockout policy with wrong demo passwords.
        zitadel.call("POST", f"/v2/users/{user_id}/unlock", {})
        print("Demo identity was locked out; unlocked it", flush=True)
    zitadel.call(
        "POST",
        f"/v2/users/{user_id}/password",
        {"newPassword": {"password": password, "changeRequired": False}},
    )
    path = settings.data_dir / "users" / f"{User(settings.oidc_issuer, user_id).id}.db"
    reset_book(path, dt.datetime.now(dt.timezone.utc).date())
    print("Demo password and book reset successfully", flush=True)


if __name__ == "__main__":
    main()
