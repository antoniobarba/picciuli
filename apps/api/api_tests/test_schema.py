"""The committed OpenAPI schema and the command line."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from picciuli_api import __main__ as cli
from picciuli_api.app import API_PREFIX, openapi_document

SCHEMA_FILE = Path(__file__).parents[1] / "openapi.json"


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return openapi_document()


def test_committed_schema_is_up_to_date(schema: dict[str, Any]) -> None:
    committed = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    assert committed == schema, (
        "apps/api/openapi.json is outdated; regenerate it with "
        "`picciuli-api openapi --output apps/api/openapi.json`"
    )


def operations(schema: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, operation)
        for path, item in schema["paths"].items()
        for method, operation in item.items()
    ]


def test_every_api_operation_requires_a_token(schema: dict[str, Any]) -> None:
    for path, method, operation in operations(schema):
        if path.startswith(API_PREFIX):
            assert operation.get("security") == [{"bearer": []}], (method, path)
            assert "401" in operation["responses"], (method, path)
            assert "503" in operation["responses"], (method, path)


def test_bodies_document_parse_and_size_errors(schema: dict[str, Any]) -> None:
    for path, method, operation in operations(schema):
        if "requestBody" in operation:
            assert {"400", "413"} <= set(operation["responses"]), (method, path)


def test_identifiers_and_amounts_are_bounded(schema: dict[str, Any]) -> None:
    for path, method, operation in operations(schema):
        for parameter in operation.get("parameters", []):
            if parameter["name"].endswith("_id") and parameter["name"] != "provider_id":
                options = parameter["schema"].get("anyOf", [parameter["schema"]])
                bounded = [o for o in options if o.get("type") == "integer"]
                assert bounded[0]["maximum"] == 2**63 - 1, (method, path)
    amount = schema["components"]["schemas"]["ExpenseCreate"]["properties"]["amount"]
    assert amount["maximum"] == 10**15


def test_every_operation_is_documented(schema: dict[str, Any]) -> None:
    declared = {tag["name"] for tag in schema["tags"]}
    for path, method, operation in operations(schema):
        assert operation.get("description"), (method, path)
        assert set(operation["tags"]) <= declared, (method, path)


def test_cli_prints_the_schema(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["openapi"])
    assert json.loads(capsys.readouterr().out)["info"]["title"] == "Picciuli API"


def test_cli_writes_the_schema(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"
    cli.main(["openapi", "--output", str(target)])
    assert target.read_bytes() == SCHEMA_FILE.read_bytes()


def test_cli_serves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import uvicorn

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append(kw))
    monkeypatch.setenv("PICCIULI_OIDC_ISSUER", "https://auth.example.com")
    monkeypatch.setenv("PICCIULI_OIDC_AUDIENCE", "123")
    monkeypatch.setenv("PICCIULI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PICCIULI_HOST", "0.0.0.0")
    monkeypatch.setenv("PICCIULI_FORWARDED_ALLOW_IPS", "*")
    cli.main([])
    assert calls == [
        {
            "host": "0.0.0.0",
            "port": 8000,
            "proxy_headers": True,
            "forwarded_allow_ips": "*",
            "server_header": False,
        }
    ]
