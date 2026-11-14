"""Console user interface for Picciuli.

Start it with `picciuli-tui finance.db` or `python -m picciuli_tui finance.db`.
It uses only the public API of the `picciuli` library.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("picciuli-tui")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0+unknown"

__all__ = ["__version__"]
