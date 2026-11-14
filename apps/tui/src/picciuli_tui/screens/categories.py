"""The category tree."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Footer, Static

from picciuli import Category
from picciuli_tui.formatting import category_label, category_tree_label
from picciuli_tui.forms import (
    NONE_ID,
    category_in_use,
    move_category,
    save_category,
)
from picciuli_tui.screens.base import BookScreen
from picciuli_tui.screens.modals import (
    ChoiceField,
    ConfirmScreen,
    FormScreen,
    FormValues,
    TextField,
)
from picciuli_tui.widgets import ListTable


class CategoriesScreen(BookScreen):
    """Top-level categories, each followed by its subcategories."""

    SUB_TITLE = "Categories"
    MODE = "categories"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("n", "new", "New"),
        Binding("e", "edit", "Edit"),
        Binding("d,delete", "delete", "Delete"),
        Binding("shift+up", "move(-1)", "Move up", show=False),
        Binding("shift+down", "move(1)", "Move down", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.categories: list[Category] = []

    def compose(self) -> ComposeResult:
        """Build the table."""
        yield from self.top_bar()
        yield Static(
            "[b]Categories[/] · two levels · shift+↑/↓ reorders within a group",
            classes="pane-title",
        )
        yield ListTable(id="categories")
        yield Footer()

    def on_mount(self) -> None:
        """Add the columns."""
        table = self.query_one(ListTable)
        table.add_column("Name", key="name")
        table.add_column("Symbol", key="symbol")

    def reload(self) -> None:
        """Read the category tree."""
        self.categories = self.book.categories.list()
        table = self.query_one(ListTable)
        selected = table.selected_key()
        table.clear()
        for category in self.categories:
            table.add_row(
                category_tree_label(category), category.symbol, key=str(category.id)
            )
        table.select_key(selected)

    def selected(self) -> Category | None:
        """Return the category under the cursor."""
        key = self.query_one(ListTable).selected_key()
        return next((c for c in self.categories if str(c.id) == key), None)

    def on_data_table_row_selected(self, message: ListTable.RowSelected) -> None:
        """Edit the category picked with `enter`."""
        message.stop()
        self.action_edit()

    def _form(self, category: Category | None, parent_id: int | None) -> None:
        parents = [("— top level —", NONE_ID)] + [
            (c.name, c.id)
            for c in self.categories
            if c.parent_id is None and (category is None or c.id != category.id)
        ]

        def submit(values: FormValues) -> Category:
            return save_category(
                self.book,
                name=values["name"],
                symbol=values["symbol"],
                parent_id=values["parent"],
                category_id=category.id if category else None,
            )

        self.app.push_screen(
            FormScreen(
                f"Edit {category.name}" if category else "New category",
                [
                    TextField("name", "Name", category.name if category else ""),
                    TextField(
                        "symbol",
                        "Symbol",
                        category.symbol if category else "",
                        "derived from the name",
                    ),
                    ChoiceField("parent", "Parent", parents, parent_id or NONE_ID),
                ],
                submit,
            )
        )

    def action_new(self) -> None:
        """Create a category in the group of the selected one."""
        selected = self.selected()
        self._form(None, selected.parent_id if selected else None)

    def action_edit(self) -> None:
        """Edit the selected category."""
        category = self.selected()
        if category is not None:
            self._form(category, category.parent_id)

    def action_delete(self) -> None:
        """Delete the selected category, asking where its transactions go."""
        category = self.selected()
        if category is None:
            return
        if any(c.parent_id == category.id for c in self.categories):
            self.notify(
                "Delete or move its subcategories first.",
                title="Cannot delete",
                severity="error",
            )
            return
        if not category_in_use(self.book, category.id):

            def confirmed(answer: bool | None) -> None:
                if answer and self.attempt(
                    lambda: self.book.categories.delete(category.id)
                ):
                    self.reload()

            self.app.push_screen(
                ConfirmScreen(f"Delete category “{category.name}” and its budgets?"),
                confirmed,
            )
            return
        by_id = {c.id: c for c in self.categories}
        targets = [("Uncategorized", NONE_ID)] + [
            (category_label(c.id, by_id), c.id)
            for c in self.categories
            if c.id != category.id
        ]

        def submit(values: FormValues) -> bool:
            self.book.categories.delete(
                category.id, reassign_to=values["target"] or None
            )
            return True

        self.app.push_screen(
            FormScreen(
                f"Delete {category.name}",
                [ChoiceField("target", "Move its splits to", targets, NONE_ID)],
                submit,
                save_label="Delete",
                help="The category is used by transactions. Its budgets are deleted.",
            )
        )

    def action_move(self, step: int) -> None:
        """Move the selected category within its group."""
        category = self.selected()
        if category is not None and self.attempt(
            lambda: move_category(self.book, category, step)
        ):
            self.reload()
