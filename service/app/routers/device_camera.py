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
import time

from fastapi import APIRouter, Response
from pydantic import BaseModel

from ..services import dash_reader
from ..services import device_camera as cam
from ..services import ref_recorder as rec
from ..services import vision_crop

router = APIRouter(prefix="/camera", tags=["device-camera"])


@router.get("/devices")
def camera_devices():
    """The cameras plugged into the AutoPi device, whether capture can work at
    all (a camera present and ffmpeg or fswebcam installed), and, when it cannot,
    a plain-language hint about exactly what to fix."""
    devices = cam.list_devices()
    tool = cam.capture_tool()
    available = bool(devices) and tool != "none"
    return {"devices": devices, "tool": tool, "available": available,
            "hint": "" if available else cam.diagnosis(devices, tool)}


@router.get("/snapshot")
def camera_snapshot(device: str):
    """One JPEG frame from a device camera, for a live preview so you can aim the
    camera at the dashboard before capturing. Returns 503 with a short reason
    when a frame cannot be grabbed."""
    jpeg = cam.capture_jpeg(device)
    if jpeg is None:
        return Response(content=b"no frame", media_type="text/plain", status_code=503)
    return Response(content=jpeg, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


class DeviceVisionFrameIn(BaseModel):
    device: str
    what: str = "speed"
    roi: dict | None = None   # {x, y, w, h} fractions to crop to before reading
    reader: str = "auto"      # "auto" (OCR then AI), "local" (OCR only), or "ai"


@router.post("/vision-frame")
def device_vision_frame(body: DeviceVisionFrameIn):
    """Grab one frame from a device camera, read the dashboard value off it with
    the vision AI, and record it as a reference sample timed to when the frame was
    grabbed. The device-camera twin of ``POST /reverse/reference/vision-frame``:
    same reading and marking, but the image comes from the AutoPi box. When a crop
    region is given, the frame is cropped to it first so the AI reads only the
    value the user boxed."""
    jpeg = cam.capture_jpeg(body.device)
    # Stamp the reading against the moment the frame was grabbed, before the (slow,
    # variable) AI read, so the point lines up with the captured frames.
    grabbed_at = time.time()
    if jpeg is None:
        return {"ok": False, "value": None, "recording": False,
                "error": f"Could not grab a frame from {body.device or 'the camera'}. "
                         "Check that the camera is plugged into the AutoPi device and "
                         "that ffmpeg or fswebcam is installed on it."}
    image_b64 = base64.b64encode(jpeg).decode("ascii")
    image_b64, mime = vision_crop.crop_region(image_b64, "image/jpeg", body.roi)
    try:
        reading = dash_reader.read(image_b64, mime, body.what, body.reader)
    except Exception as exc:
        return {"ok": False, "value": None, "recording": False, "error": str(exc)}
    value = reading.get("value")
    marked = None
    if value is not None:
        marked = rec.mark(float(value), t=grabbed_at)
    return {"ok": True, "value": value, "engine": reading.get("engine"),
            "recording": bool(marked and marked.get("recording")),
            "status": marked}
