from app.services.state import StateFile


def test_write_then_read(tmp_path):
    sf = StateFile(tmp_path / "s.json", default={})
    sf.write({"a": 1})
    assert sf.read() == {"a": 1}


def test_read_missing_returns_default(tmp_path):
    sf = StateFile(tmp_path / "missing.json", default={"x": 0})
    assert sf.read() == {"x": 0}


def test_read_returns_a_copy(tmp_path):
    sf = StateFile(tmp_path / "s.json", default={})
    sf.write({"list": [1, 2]})
    got = sf.read()
    got["list"].append(3)
    assert sf.read()["list"] == [1, 2]


def test_falls_back_to_memory_on_unwritable_dir(tmp_path):
    # A path under a file (not a dir) cannot be created: writes degrade to memory.
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    sf = StateFile(blocker / "s.json", default={})
    sf.write({"kept": True})
    assert sf.read() == {"kept": True}


def test_cache_persists_across_instances_for_the_same_path(tmp_path):
    # Every consumer builds a fresh StateFile per call, so the mtime cache must be
    # shared per path: a second instance must reuse the parsed cache without
    # re-reading the file (that is the whole point of the cache).
    import app.services.state as state
    p = tmp_path / "shared.json"
    StateFile(p, default={}).write({"n": 1})
    reads = {"count": 0}
    real_read_text = type(p).read_text

    def counting_read_text(self, *a, **k):
        reads["count"] += 1
        return real_read_text(self, *a, **k)

    import pathlib
    orig = pathlib.Path.read_text
    pathlib.Path.read_text = counting_read_text
    try:
        # Fresh instances, same path: the first read populates the cache from disk,
        # the rest are served from the shared cache with no further file reads.
        assert StateFile(p, default={}).read() == {"n": 1}
        first = reads["count"]
        for _ in range(5):
            assert StateFile(p, default={}).read() == {"n": 1}
        assert reads["count"] == first  # no extra disk reads across instances
    finally:
        pathlib.Path.read_text = orig


def test_write_through_one_instance_is_visible_to_another(tmp_path):
    p = tmp_path / "shared2.json"
    StateFile(p, default={}).write({"v": "a"})
    assert StateFile(p, default={}).read() == {"v": "a"}
    StateFile(p, default={}).write({"v": "b"})     # different instance writes
    assert StateFile(p, default={}).read() == {"v": "b"}  # cache updated, not stale
