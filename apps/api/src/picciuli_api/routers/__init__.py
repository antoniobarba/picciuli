"""HTTP endpoints, one module per resource.

Path parameters use converters (`{account_id:int}`, `{date:date}`), so that
a fixed path such as `/transactions/dates` never matches the route of an
identifier: other methods on it get `405 Method Not Allowed`, not `422`.
"""

from __future__ import annotations

from starlette.convertors import Convertor, register_url_convertor


class DateConvertor(Convertor[str]):
    """Match a `YYYY-MM-DD` path segment; the endpoint parses it."""

    regex = "[0-9]{4}-[0-9]{2}-[0-9]{2}"

    def convert(self, value: str) -> str:
        """Keep the text; the endpoint parameter validates the date."""
        return value

    def to_string(self, value: str) -> str:
        """Write the date back into a URL."""
        return value


register_url_convertor("date", DateConvertor())
