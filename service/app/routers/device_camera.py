"""On-device camera endpoints for the Dashboard camera reference.

The browser path (``POST /reverse/reference/vision-frame``) sends frames from
the browser's own webcam, which needs a secure page and can never see a USB
camera plugged into the AutoPi box. These endpoints capture on the device
instead: the UI asks what cameras exist, then has the server grab a frame,
read the dashboard value with the vision AI, and record it on the reference,
all on the server clock so it lines up with a live capture automatically.
"""
from __future__ import annotations

import base64

from fastapi import APIRouter
from pydantic import BaseModel

from .. import llm
from ..services import device_camera as cam
from ..services import ref_recorder as rec

router = APIRouter(prefix="/camera", tags=["device-camera"])


@router.get("/devices")
def camera_devices():
    """The cameras plugged into the AutoPi device, and whether capture can
    work at all (a camera present and ffmpeg or fswebcam installed)."""
    devices = cam.list_devices()
    tool = cam.capture_tool()
    return {"devices": devices, "tool": tool,
            "available": bool(devices) and tool != "none"}


class DeviceVisionFrameIn(BaseModel):
    device: str
    what: str = "speed"


@router.post("/vision-frame")
def device_vision_frame(body: DeviceVisionFrameIn):
    """Grab one frame from a device camera, read the dashboard value off it
    with the vision AI, and record it as a reference sample at the current
    time. The device-camera twin of ``POST /reverse/reference/vision-frame``:
    same reading and marking, but the image comes from the AutoPi box."""
    jpeg = cam.capture_jpeg(body.device)
    if jpeg is None:
        return {"ok": False, "value": None, "recording": False,
                "error": f"Could not grab a frame from {body.device or 'the camera'}. "
                         "Check that the camera is plugged into the AutoPi device and "
                         "that ffmpeg or fswebcam is installed on it."}
    image_b64 = base64.b64encode(jpeg).decode("ascii")
    try:
        reading = llm.read_dashboard_value(image_b64, "image/jpeg", body.what)
    except Exception as exc:
        return {"ok": False, "value": None, "recording": False, "error": str(exc)}
    value = reading.get("value")
    marked = None
    if value is not None:
        marked = rec.mark(float(value))
    return {"ok": True, "value": value,
            "recording": bool(marked and marked.get("recording")),
            "status": marked}
