"""Unit of work: one SQLAlchemy session per public call or `Book.atomic()` block."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from picciuli.errors import ConflictError


class UnitOfWork:
    """Hands out sessions; nested requests join the outermost active session.

    The active session is tracked in a context variable, so each thread (and each
    asyncio task) has its own unit of work.
    """

    def __init__(self, engine: Engine) -> None:
        self._factory = sessionmaker(engine, expire_on_commit=False)
        self._current: ContextVar[Session | None] = ContextVar(
            f"picciuli_session_{id(self)}", default=None
        )

    @contextlib.contextmanager
    def session(self) -> Iterator[Session]:
        current = self._current.get()
        if current is not None:
            yield current
            return
        try:
            with self._factory.begin() as session:
                token = self._current.set(session)
                try:
                    yield session
                finally:
                    self._current.reset(token)
        except IntegrityError as exc:
            raise ConflictError(
                f"the operation violates a database constraint: {exc.orig}"
            ) from exc
