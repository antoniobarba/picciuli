from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import pytest

from picciuli import Book
from picciuli_tui import __main__ as cli
from picciuli_tui.app import PicciuliApp
from picciuli_tui.demo import create_demo, populate_demo


def test_demo_book_is_consistent() -> None:
    today = dt.date(2025, 3, 12)
    with Book.in_memory() as book:
        populate_demo(book, today)
        assert book.settings.get().currency == "€"
        assert len(book.accounts.list()) == 5
        transactions = book.transactions.list()
        assert transactions
        assert max(t.date for t in transactions) <= today
        periods = book.periods.periods_on(today)
        assert [p.name for p in periods] == ["March 2025"]
        assert len(book.budgets.list(period_id=periods[0].id)) == 5
        assert len(book.periods.periods_on(dt.date(2025, 3, 2))) == 2
        card = next(a for a in book.accounts.list() if a.name == "Credit card")
        # Card bills are paid in full each cycle before the current one.
        assert book.accounts.balance(card.id, as_of=dt.date(2025, 2, 26)) == 0


def test_demo_on_pay_day_starts_a_new_cycle() -> None:
    with Book.in_memory() as book:
        populate_demo(book, dt.date(2025, 3, 27))
        (period,) = [p for p in book.periods.list() if p.end is None]
        assert period.start == dt.date(2025, 3, 27)


def test_create_demo_refuses_to_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "demo.db"
    create_demo(target, dt.date(2025, 3, 12))
    with Book.open(target, create=False) as book:
        assert book.accounts.list()
    with pytest.raises(FileExistsError):
        create_demo(target, dt.date(2025, 3, 12))


def test_cli_demo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "demo.db"
    assert cli.main([str(target), "--demo"]) == 0
    assert "Open it with" in capsys.readouterr().out
    assert cli.main([str(target), "--demo"]) == 1
    assert "refusing to overwrite" in capsys.readouterr().err


def test_cli_runs_the_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []

    def fake_run(self: PicciuliApp) -> None:
        opened.append(self.title)
        self.book.accounts.list()

    monkeypatch.setattr(PicciuliApp, "run", fake_run)
    assert cli.main([str(tmp_path / "new.db")]) == 0
    assert opened == ["Picciuli · new.db"]
    assert (tmp_path / "new.db").exists()


def test_cli_rejects_foreign_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "foreign.db"
    connection = sqlite3.connect(target)
    with connection:
        connection.execute("CREATE TABLE other (id INTEGER)")
    connection.close()
    assert cli.main([str(target)]) == 1
    assert "not a Picciuli database" in capsys.readouterr().err
