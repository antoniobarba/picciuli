from __future__ import annotations

import ast
from pathlib import Path

import picciuli
import picciuli_tui

SOURCE = Path(picciuli_tui.__file__).parent
PUBLIC_MODULES = {"picciuli", "picciuli.money", "picciuli.prices", "picciuli.rates"}


def _imports(path: Path) -> list[tuple[str, list[str]]]:
    found: list[tuple[str, list[str]]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend((alias.name, []) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.module, [alias.name for alias in node.names]))
    return found


def test_only_the_public_library_api_is_used() -> None:
    violations = []
    for path in sorted(SOURCE.rglob("*.py")):
        for module, names in _imports(path):
            top = module.split(".")[0]
            if top == "sqlalchemy" or (
                top == "picciuli" and module not in PUBLIC_MODULES
            ):
                violations.append(f"{path.name}: {module}")
            if module == "picciuli":
                violations.extend(
                    f"{path.name}: picciuli.{name}"
                    for name in names
                    if name not in picciuli.__all__
                )
    assert violations == []
