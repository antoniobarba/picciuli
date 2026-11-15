"""Picciuli API: a multi-user REST server for the Picciuli library.

Every authenticated user gets a private [`Book`][picciuli.Book] stored in its own
SQLite file. Users are authenticated with OpenID Connect access tokens (JWT)
issued by an external identity provider such as Zitadel.

Build the ASGI application with [`create_app`][picciuli_api.create_app]:

```python
from picciuli_api import Settings, create_app

app = create_app(Settings())  # reads PICCIULI_* environment variables
```
"""

from importlib.metadata import PackageNotFoundError, version

from picciuli_api.app import create_app
from picciuli_api.config import Settings

try:
    __version__ = version("picciuli-api")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0+unknown"

__all__ = ["Settings", "__version__", "create_app"]
