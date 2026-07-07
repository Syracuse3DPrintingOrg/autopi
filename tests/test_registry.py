from app.actions import registry
from app.actions.registry import ActionSpec


def test_builtins_are_always_present():
    actions = registry.all_actions()
    assert "page_next" in actions
    assert "blank" in actions


def test_upsert_and_delete_user_action():
    spec = ActionSpec(id="light", label="Light", driver="gpio",
                      params={"pin": 17, "mode": "toggle"})
    registry.upsert_action(spec)
    assert "light" in registry.all_actions()
    assert registry.get_action("light").label == "Light"
    assert registry.delete_action("light") is True
    assert "light" not in registry.all_actions()


def test_cannot_overwrite_builtin():
    import pytest
    with pytest.raises(ValueError):
        registry.upsert_action(ActionSpec(id="blank", label="nope"))


def test_run_builtin_returns_op_hint():
    res = registry.run("page_next")
    assert res.ok
    assert res.data["op"] == "page_next"


def test_run_shell_action_executes():
    registry.upsert_action(ActionSpec(id="hi", driver="shell",
                                      params={"command": "echo hello"}))
    res = registry.run("hi")
    assert res.ok
    assert "hello" in res.message


def test_run_refuses_unavailable_driver(monkeypatch):
    from app.actions.drivers import get_driver
    monkeypatch.setattr(type(get_driver("gpio")), "available", property(lambda self: False))
    registry.upsert_action(ActionSpec(id="pin", driver="gpio",
                                      params={"pin": 17, "mode": "on"}))
    res = registry.run("pin")
    assert res.ok is False
    assert "not available" in res.message


def test_macro_runs_members_in_order():
    registry.upsert_action(ActionSpec(id="a", driver="shell", params={"command": "true"}))
    registry.upsert_action(ActionSpec(id="b", driver="shell", params={"command": "true"}))
    registry.upsert_action(ActionSpec(id="both", driver="macro", members=["a", "b"]))
    res = registry.run("both")
    assert res.ok
    assert len(res.data["steps"]) == 2


def test_run_unknown_action_fails_cleanly():
    res = registry.run("does-not-exist")
    assert res.ok is False
