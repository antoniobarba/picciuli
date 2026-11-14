"""Command line entry point: `picciuli-tui BOOK` or `python -m picciuli_tui BOOK`."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Sequence
from pathlib import Path

from picciuli import Book, SchemaVersionError
from picciuli_tui import __version__
from picciuli_tui.demo import create_demo


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Read the command line."""
    parser = argparse.ArgumentParser(
        prog="picciuli-tui", description="Console interface for Picciuli books."
    )
    parser.add_argument("book", type=Path, help="database file (created if missing)")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="create a new demonstration book at BOOK and exit",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the interface; return the process exit code."""
    args = parse_args(argv)
    if args.demo:
        try:
            create_demo(args.book, dt.date.today())
        except FileExistsError as error:
            print(f"picciuli-tui: {error}", file=sys.stderr)
            return 1
        print(f"Created a demonstration book. Open it with: picciuli-tui {args.book}")
        return 0
    try:
        book = Book.open(args.book)
    except SchemaVersionError as error:
        print(f"picciuli-tui: {error}", file=sys.stderr)
        return 1
    from picciuli_tui.app import PicciuliApp

    with book:
        PicciuliApp(book, name=args.book.name).run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
