from app.services import deck_layout as dl


def test_single_page_fits_without_paging():
    pages = dl.build_pages(["a", "b", "c"], 15)
    assert len(pages) == 1
    assert pages[0][:3] == ["a", "b", "c"]
    assert pages[0][3] is None
    assert len(pages[0]) == 15


def test_overflow_paginates_with_page_key():
    ids = [f"a{i}" for i in range(20)]
    pages = dl.build_pages(ids, 15)
    assert len(pages) == 2
    # Last slot of a multi-page layout is the wrapping page key.
    assert pages[0][-1] == dl.PAGE_NEXT
    assert pages[1][-1] == dl.PAGE_NEXT


def test_blank_slots_keep_position():
    pages = dl.build_pages(["a", None, "b"], 6)
    assert pages[0][0] == "a"
    assert pages[0][1] is None
    assert pages[0][2] == "b"


def test_rotation_is_a_bijection_for_all_key_counts():
    for count in dl.supported_key_counts():
        for rotation in (0, 90, 180, 270):
            physical = [dl.rotated_index(i, count, rotation) for i in range(count)]
            assert sorted(physical) == list(range(count)), (count, rotation)
            # slot_for_physical must invert rotated_index exactly.
            for slot in range(count):
                phys = dl.rotated_index(slot, count, rotation)
                assert dl.slot_for_physical(phys, count, rotation) == slot


def test_display_dims_swap_on_quarter_turns():
    assert dl.display_dims(32, 0) == (8, 4)
    assert dl.display_dims(32, 90) == (4, 8)
    assert dl.display_dims(32, 180) == (8, 4)
    assert dl.display_dims(32, 270) == (4, 8)
