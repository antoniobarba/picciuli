# picciuli-tui

Console user interface for [Picciuli](../../README.md), built with
[Textual](https://textual.textualize.io/). It talks to the `picciuli` library
only through its public API.

```bash
picciuli-tui finance.db          # open (or create) a book
picciuli-tui --demo demo.db      # create a demonstration book, then open it
python -m picciuli_tui finance.db
```

The overview is a month calendar of boxed day cells: each day shows its net
flow (`↔` for days with only transfers), the selected day has a heavy border,
and the selected period is drawn as a band. The right side lists the selected
day's transactions, the period's categories against their budgets, and account
balances. Tabs at the top switch screens; press `?` for every key.

See the [user guide](../../docs/tui.md) for screens and keys.
