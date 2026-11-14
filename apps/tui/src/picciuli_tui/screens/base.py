"""Base class of the main screens."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Tabs

from picciuli import Book
from picciuli_tui.formatting import MoneyFormat
from picciuli_tui.widgets import ScreenTabs

if TYPE_CHECKING:
    from picciuli_tui.app import PicciuliApp


class BookScreen(Screen[None]):
    """A screen showing data from the book; it reloads whenever it is shown."""

    MODE = ""
    """The application mode (tab) this screen belongs to."""

    def top_bar(self) -> ComposeResult:
        """Yield the header and the screen tabs, with this screen's tab active."""
        yield Header()
        yield ScreenTabs(self.MODE)

    def on_tabs_tab_activated(self, message: Tabs.TabActivated) -> None:
        """Switch to the screen of the clicked tab."""
        message.stop()
        mode = message.tab.id
        if mode and mode != self.MODE:
            self.app.switch_mode(mode)

    @property
    def picciuli(self) -> PicciuliApp:
        """The running application."""
        return cast("PicciuliApp", self.app)

    @property
    def book(self) -> Book:
        """The open book."""
        return self.picciuli.book

    @property
    def money(self) -> MoneyFormat:
        """How to show amounts."""
        return self.picciuli.money

    def today(self) -> dt.date:
        """Today's date (overridable for tests)."""
        return self.picciuli.today()

    def attempt(self, operation: Callable[[], Any]) -> bool:
        """Run a library call, showing its error instead of crashing."""
        return self.picciuli.attempt(operation)

    def on_screen_resume(self) -> None:
        """Reload the data each time the screen becomes visible.

        This includes the moment a dialog opened from this screen closes.
        """
        self.reload()

    def reload(self) -> None:
        """Read the book again and update the widgets."""
        raise NotImplementedError
