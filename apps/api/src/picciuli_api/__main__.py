"""Command line: `picciuli-api [serve]` or `picciuli-api openapi`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> None:
    """Run the API server or print its OpenAPI schema."""
    parser = argparse.ArgumentParser(
        prog="picciuli-api", description="Picciuli REST API server."
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="run the server (default)")
    schema = commands.add_parser("openapi", help="print the OpenAPI schema")
    schema.add_argument("--output", type=Path, help="write to a file instead")
    args = parser.parse_args(argv)

    if args.command == "openapi":
        from picciuli_api.app import openapi_document

        text = json.dumps(openapi_document(), indent=2, ensure_ascii=False) + "\n"
        if args.output is None:
            sys.stdout.write(text)
        else:
            args.output.write_text(text, encoding="utf-8", newline="\n")
        return

    import uvicorn

    from picciuli_api.app import create_app
    from picciuli_api.config import Settings

    settings = Settings()  # type: ignore[call-arg]
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
