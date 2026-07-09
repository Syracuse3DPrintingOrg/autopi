"""The shared, vehicle-independent command library."""
from app.services import command_library as lib


def test_add_list_get_delete(temp_data_dir):
    assert lib.list_commands() == []
    entry = lib.add_command("Mute", {"channel": "can1", "arbitration_id": "0x5C6", "data": "05"})
    assert entry["id"] == 1 and entry["name"] == "Mute"
    assert lib.get_command(1)["command"]["arbitration_id"] == "0x5C6"
    assert len(lib.list_commands()) == 1
    assert lib.delete_command(1) is True
    assert lib.list_commands() == []
    assert lib.delete_command(1) is False


def test_normalize_keeps_only_known_fields(temp_data_dir):
    c = lib.normalize_command({"arbitration_id": "0x1", "junk": "x", "overlay_mask": 4})
    assert "junk" not in c
    assert c["channel"] == "can0" and c["period_ms"] == 0 and c["overlay_mask"] == 4
