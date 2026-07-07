"""Pure paging and rotation math shared by the web grid and the Stream Deck.

A deck has a fixed number of keys (Mini 6, Original/MK.2 15, XL 32). When the
configured layout is longer than the deck, the last key of each page becomes a
wrapping page-cycle key and the rest spill onto further pages. The rotation
helpers map between the grid the editor draws and the physical key a rotated
deck reports, as an exact bijection for all four rotations.

Everything here operates on plain lists of action ids (with ``None`` for a
blank slot), so it is decoupled from the action registry and trivially
testable. This is ported from the source project's proven deck layout code
with the food specifics removed.
"""
from __future__ import annotations

from typing import Optional

# Physical grid (cols, rows) for each known deck size.
GRID: dict[int, tuple[int, int]] = {
    6: (3, 2),    # Stream Deck Mini / Module 6
    15: (5, 3),   # Stream Deck / MK.2 / Module 15
    32: (8, 4),   # Stream Deck XL / Module 32
}

# The page-cycle key inserted as the last slot of every page in a multi-page
# layout. Callers treat this reserved id as "advance to the next page".
PAGE_NEXT = "page_next"


def supported_key_counts() -> tuple[int, ...]:
    return tuple(sorted(GRID))


def display_dims(key_count: int, rotation: int) -> tuple[int, int]:
    """The (cols, rows) of the grid as the user sees it after rotating.

    For 0 and 180 the deck keeps its native shape. For 90 and 270 it is turned
    on its side, so columns and rows swap (an 8x4 XL becomes a 4x8 portrait).
    """
    cols, rows = GRID.get(key_count, (key_count, 1))
    if rotation in (90, 270):
        return rows, cols
    return cols, rows


def rotated_index(index: int, key_count: int, rotation: int) -> int:
    """Map a visual slot to the physical key it lands on after rotation."""
    if rotation == 0 or key_count not in GRID:
        return index
    p_cols, p_rows = GRID[key_count]
    d_cols, d_rows = display_dims(key_count, rotation)
    if not (0 <= index < d_cols * d_rows):
        return index
    vr, vc = divmod(index, d_cols)
    if rotation == 180:
        pr, pc = p_rows - 1 - vr, p_cols - 1 - vc
    elif rotation == 90:
        pr, pc = vc, d_rows - 1 - vr
    else:  # 270
        pr, pc = d_cols - 1 - vc, vr
    return pr * p_cols + pc


def slot_for_physical(phys: int, key_count: int, rotation: int) -> int:
    """Inverse of :func:`rotated_index`: physical key to displayed-grid slot."""
    if rotation == 0 or key_count not in GRID:
        return phys
    p_cols, p_rows = GRID[key_count]
    d_cols, d_rows = display_dims(key_count, rotation)
    if not (0 <= phys < p_cols * p_rows):
        return phys
    pr, pc = divmod(phys, p_cols)
    if rotation == 180:
        vr, vc = p_rows - 1 - pr, p_cols - 1 - pc
    elif rotation == 90:
        vr, vc = d_rows - 1 - pc, pr
    else:  # 270
        vr, vc = pc, d_cols - 1 - pr
    return vr * d_cols + vc


def build_pages(action_ids: list[Optional[str]], key_count: int) -> list[list[Optional[str]]]:
    """Split a flat list of action ids into deck-sized pages.

    With a single page everything fits and no key is sacrificed for paging.
    When more slots are configured than fit, the final key of every page
    becomes a wrapping page-cycle key (``PAGE_NEXT``) and the rest continue on
    the next page. ``None`` marks an explicit blank slot and keeps its
    position.
    """
    if key_count < 1:
        raise ValueError("key_count must be positive")
    slots = list(action_ids)
    if len(slots) <= key_count:
        return [slots + [None] * (key_count - len(slots))]
    usable = key_count - 1
    pages: list[list[Optional[str]]] = []
    for start in range(0, len(slots), usable):
        chunk = slots[start:start + usable]
        page = list(chunk) + [None] * (usable - len(chunk))
        page.append(PAGE_NEXT)
        pages.append(page)
    return pages
