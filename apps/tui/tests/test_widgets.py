from __future__ import annotations

import itertools

from picciuli_tui.widgets import BOX


def test_box_table_covers_every_light_and_heavy_junction() -> None:
    assert set(itertools.product(range(3), repeat=4)) <= BOX.keys()
    assert BOX[(0, 0, 0, 0)] == " "
    assert BOX[(1, 1, 1, 1)] == "┼"
    assert BOX[(2, 2, 2, 2)] == "╋"
    assert BOX[(0, 1, 0, 1)] == "┌"
    assert BOX[(0, 0, 2, 2)] == "━"
    # up light, down heavy, left light, right heavy
    assert BOX[(1, 2, 1, 2)] == "╆"
    assert BOX[(0, 0, 1, 2)] == "╼"
