"""CAN core: pure frame logic and provider degradation, no hardware needed."""
import pytest

from app.can import Frame, get_channel, parse_arbitration_id, parse_data_bytes, reset_channels
from app.can.registry import create_provider
from app.can.socketcan import SocketCanProvider


@pytest.fixture(autouse=True)
def _clear_channel_cache():
    # Each test gets a clean provider cache so one test's cached bus never
    # leaks into the next.
    reset_channels()
    yield
    reset_channels()


# -- id and data parsing ------------------------------------------------------

def test_parse_arbitration_id_hex_prefix():
    assert parse_arbitration_id("0x7DF") == 0x7DF


def test_parse_arbitration_id_bare_hex_string_treated_as_hex_when_prefixed():
    assert parse_arbitration_id("0x123") == 0x123


def test_parse_arbitration_id_decimal():
    assert parse_arbitration_id("2024") == 2024


def test_parse_arbitration_id_rejects_garbage():
    with pytest.raises(ValueError):
        parse_arbitration_id("nothex")


def test_parse_arbitration_id_rejects_empty():
    with pytest.raises(ValueError):
        parse_arbitration_id("   ")


def test_parse_data_bytes_space_and_comma_separated():
    assert parse_data_bytes("02 01 0C") == [0x02, 0x01, 0x0C]
    assert parse_data_bytes("02,01,0C") == [0x02, 0x01, 0x0C]


def test_parse_data_bytes_empty_is_empty_list():
    assert parse_data_bytes("") == []


def test_parse_data_bytes_rejects_bad_token():
    with pytest.raises(ValueError):
        parse_data_bytes("zz")


# -- Frame validation and formatting ------------------------------------------

def test_frame_dlc_matches_data_length():
    frame = Frame(arbitration_id=0x100, data=[1, 2, 3])
    assert frame.dlc == 3


def test_frame_validate_accepts_classic_8_bytes():
    frame = Frame(arbitration_id=0x7DF, data=[0] * 8)
    assert frame.validate() is None


def test_frame_validate_rejects_classic_9_bytes():
    frame = Frame(arbitration_id=0x7DF, data=[0] * 9)
    assert frame.validate() is not None


def test_frame_validate_accepts_fd_length_not_valid_for_classic():
    frame = Frame(arbitration_id=0x100, data=[0] * 24, is_fd=True)
    assert frame.validate() is None


def test_frame_validate_rejects_fd_length_that_is_not_a_valid_dlc():
    frame = Frame(arbitration_id=0x100, data=[0] * 9, is_fd=True)
    assert frame.validate() is not None


def test_frame_validate_rejects_standard_id_out_of_range():
    frame = Frame(arbitration_id=0x800, data=[])  # 11-bit max is 0x7FF
    assert frame.validate() is not None


def test_frame_validate_accepts_extended_id_out_of_standard_range():
    frame = Frame(arbitration_id=0x1FFFFFFF, data=[], is_extended_id=True)
    assert frame.validate() is None


def test_frame_validate_rejects_bad_byte_value():
    frame = Frame(arbitration_id=0x100, data=[0x100])
    assert frame.validate() is not None


def test_frame_validate_rejects_remote_frame_with_data():
    frame = Frame(arbitration_id=0x100, data=[1], is_remote=True)
    assert frame.validate() is not None


def test_frame_format_includes_hex_id_and_bytes():
    frame = Frame(arbitration_id=0x7DF, data=[0x02, 0x01, 0x0C])
    assert frame.format() == "0x7DF#02 01 0C"


def test_frame_format_flags_extended_and_fd():
    frame = Frame(arbitration_id=0x18DB33F1, data=[1], is_extended_id=True, is_fd=True)
    assert frame.format() == "0x18DB33F1#01 (ext, fd)"


def test_frame_format_remote_frame():
    frame = Frame(arbitration_id=0x100, is_remote=True)
    assert "(remote)" in frame.format()


# -- provider degradation (no hardware, and no python-can assumed) -----------

def test_socketcan_provider_unavailable_without_interface():
    # can0 does not exist on a dev machine/CI runner regardless of whether
    # python-can itself is installed.
    provider = SocketCanProvider(channel="can0")
    assert provider.available is False


def test_socketcan_provider_open_fails_gracefully():
    provider = SocketCanProvider(channel="can0")
    assert provider.open() is False


def test_socketcan_provider_send_is_a_safe_no_op_when_unavailable():
    provider = SocketCanProvider(channel="can0")
    frame = Frame(arbitration_id=0x123, data=[1, 2, 3])
    assert provider.send(frame) is False


def test_socketcan_provider_recv_returns_none_when_unavailable():
    provider = SocketCanProvider(channel="can0")
    assert provider.recv(timeout=0.01) is None


def test_socketcan_provider_set_filters_does_not_raise_when_unavailable():
    provider = SocketCanProvider(channel="can0")
    provider.set_filters([{"can_id": 0x100, "can_mask": 0x7FF}])  # must not raise


def test_socketcan_provider_close_is_idempotent():
    provider = SocketCanProvider(channel="can0")
    provider.close()
    provider.close()  # must not raise on a never-opened provider


# -- registry ------------------------------------------------------------------

def test_create_provider_defaults_to_socketcan_for_unknown_backend():
    provider = create_provider("some-future-backend", "can0")
    assert isinstance(provider, SocketCanProvider)


def test_get_channel_caches_by_backend_and_channel():
    a = get_channel("can0")
    b = get_channel("can0")
    c = get_channel("can1")
    assert a is b
    assert a is not c
