"""Per-channel loopback self-test and a fixed test frame to send by hand.

The loopback check opens the channel with ``receive_own_messages`` on (a
SocketCAN/python-can feature: your own transmitted frames are delivered back
to you, on by default for any local socket, no other node needed) and
confirms the frame it sent comes back unchanged. That proves the send/recv
path works end to end without needing a second device on the bus.

The frame comparison and result shape are pure and take an already-open
``CanProvider`` (or anything with the same ``send``/``recv``/``available``
surface), so this is unit-testable against ``VirtualProvider`` with no
hardware, and the router decides which provider to hand it.
"""
from __future__ import annotations

from typing import Any

from .base import Frame

TEST_ARBITRATION_ID = 0x7A5
TEST_DATA = (0xDE, 0xAD, 0xBE, 0xEF)


def build_test_frame(is_fd: bool = False, is_extended_id: bool = False) -> Frame:
    """The fixed frame both the loopback self-test and the "send a test
    frame" button use, so a capture on the wire (or a scope trace) is easy
    to recognize."""
    return Frame(
        arbitration_id=TEST_ARBITRATION_ID,
        data=list(TEST_DATA),
        is_fd=is_fd,
        is_extended_id=is_extended_id,
    )


def frames_match(sent: Frame, received: Frame | None) -> bool:
    if received is None:
        return False
    return (
        received.arbitration_id == sent.arbitration_id
        and received.data == sent.data
        and received.is_extended_id == sent.is_extended_id
    )


def run_loopback_test(provider: Any, timeout: float = 2.0) -> dict:
    """Send the test frame on ``provider`` and confirm it is received back.

    Returns ``{"ok": bool, "passed": bool, "message"/"error": str}``. ``ok``
    is False only when the test itself could not run (interface
    unavailable, send failed); ``passed`` is the actual test result.
    """
    if not provider.available:
        return {"ok": False, "passed": False,
                "error": "Interface is not available. Bring it up first."}
    frame = build_test_frame()
    if not provider.send(frame):
        return {"ok": False, "passed": False, "error": "Could not send the test frame."}
    received = provider.recv(timeout=timeout)
    if not frames_match(frame, received):
        return {"ok": True, "passed": False,
                "error": "The test frame was sent but not received back. Loopback "
                         "(receive_own_messages) may not be supported on this backend."}
    return {"ok": True, "passed": True,
            "message": f"Loopback passed: {frame.format()} sent and received back."}
