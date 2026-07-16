"""Capture a frame from a USB camera plugged into the AutoPi device.

The Dashboard camera reference has a browser path (getUserMedia), but a
browser only opens a camera on a secure page, and it can never see a camera
plugged into the AutoPi box itself. This module is the on-device path: it
finds ``/dev/videoN`` cameras and grabs single JPEG frames from one by
shelling out to ``ffmpeg`` (preferred) or ``fswebcam``, both common on a
Raspberry Pi and installable with apt. No new Python dependencies.

Everything degrades gracefully: with no camera or no capture tool installed,
:func:`capture_jpeg` returns ``None`` and :func:`capture_available` reports
``False`` so the UI can hide or explain the option instead of failing. The
device string is validated against a strict ``/dev/videoN`` pattern and every
subprocess call passes arguments as a list with a hard timeout, so nothing a
browser sends can reach a shell.

The glob parsing and command building are pure so they stay unit-testable on
a machine with no camera.
"""
from __future__ import annotations

import glob
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Iterable

# The only device paths we will ever open. Anything else (symlinks, shell
# metacharacters, /dev/media*, paths from a hostile request body) is refused.
DEVICE_RE = re.compile(r"^/dev/video\d+$")

# Capture tools in preference order: ffmpeg gives the cleanest one-frame
# grab; fswebcam is the lightweight classic on a Pi.
_TOOLS = ("ffmpeg", "fswebcam")


def parse_devices(paths: Iterable[str],
                  name_for: Callable[[str], str] | None = None) -> list[dict]:
    """Turn a ``/dev/video*`` glob result into sorted device dicts.

    Pure: takes the raw path list (and an optional friendly-name lookup) so
    it can be tested without a camera. Paths that do not look like a real
    video device are dropped, and the rest sort numerically (video2 before
    video10).
    """
    found: list[tuple[int, str]] = []
    for raw in paths:
        path = str(raw)
        if not DEVICE_RE.match(path):
            continue
        found.append((int(path.rsplit("video", 1)[1]), path))
    devices = []
    for index, path in sorted(found):
        name = (name_for(path) if name_for else "") or ""
        name = " ".join(name.split())
        label = f"{name} ({path})" if name else f"Camera {index} ({path})"
        devices.append({"device": path, "label": label})
    return devices


def _sysfs_name(device: str) -> str:
    """The kernel's friendly name for a v4l2 device (e.g. the USB product
    string), or "" when unavailable."""
    try:
        node = Path("/sys/class/video4linux") / Path(device).name / "name"
        return node.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def list_devices() -> list[dict]:
    """The cameras present on this device, sorted, with friendly labels."""
    return parse_devices(glob.glob("/dev/video*"), name_for=_sysfs_name)


def capture_tool() -> str:
    """Which capture tool this device has: ``"ffmpeg"``, ``"fswebcam"``, or
    ``"none"``."""
    for tool in _TOOLS:
        if shutil.which(tool):
            return tool
    return "none"


def build_capture_command(tool: str, device: str) -> list[str]:
    """The exact argv used to grab one JPEG frame to stdout. Pure."""
    if tool == "ffmpeg":
        return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "v4l2",
                "-i", device, "-frames:v", "1", "-q:v", "3", "-f", "image2",
                "pipe:1"]
    if tool == "fswebcam":
        return ["fswebcam", "-q", "--no-banner", "-r", "640x480",
                "--jpeg", "85", "-d", device, "-"]
    raise ValueError(f"unknown capture tool: {tool!r}")


def capture_jpeg(device: str, timeout_s: float = 5.0) -> bytes | None:
    """Grab one JPEG frame from ``device``.

    Returns the JPEG bytes, or ``None`` when the device path is not a real
    ``/dev/videoN``, no capture tool is installed, the camera is missing or
    busy, or the grab times out. Never raises: the caller decides how to
    explain a miss to the user.
    """
    if not device or not DEVICE_RE.match(device):
        return None
    tool = capture_tool()
    if tool == "none":
        return None
    try:
        proc = subprocess.run(build_capture_command(tool, device),
                              capture_output=True, timeout=timeout_s)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    return bytes(proc.stdout)


def capture_available() -> bool:
    """Whether this device can capture at all: at least one camera is
    plugged in and a capture tool is installed."""
    return capture_tool() != "none" and bool(list_devices())


def diagnosis(devices: list[dict] | None = None, tool: str | None = None) -> str:
    """A plain-language explanation of what is missing for on-device capture, or
    "" when it is ready. Pure over its (optionally injected) inputs so it can be
    tested without a camera. The two failure modes need different fixes, so the
    message names the exact one: the container cannot see any camera (device
    passthrough / the camera itself), or a camera is visible but no capture tool
    is installed (rebuild the image)."""
    devices = list_devices() if devices is None else devices
    tool = capture_tool() if tool is None else tool
    if not devices:
        return ("No camera is visible to AutoPi. If a USB camera is plugged into the "
                "device, the app runs in a container that needs access to it: uncomment "
                "the camera block in docker-compose.yml and run 'docker compose up -d'. "
                "The image also needs a capture tool (fswebcam or ffmpeg); rebuild it "
                "with 'docker compose up -d --build' after updating.")
    if tool == "none":
        return ("A camera is connected but no capture tool is installed in the app image. "
                "Rebuild it so it includes fswebcam: 'docker compose up -d --build'.")
    return ""
