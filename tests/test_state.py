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
