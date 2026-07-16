"""On-device camera capture for the Dashboard camera reference: the pure
device parsing, path validation, and command building in
:mod:`app.services.device_camera`, and the ``/camera/*`` endpoints with the
actual capture and LLM calls monkeypatched (the test box has no camera).
"""
from __future__ import annotations

import base64
import subprocess

from starlette.testclient import TestClient

from app.main import app
from app.services import device_camera as cam
from app.services import ref_recorder as rec


# --------------------------------------------------------------------------
# parse_devices: pure glob-result parsing
# --------------------------------------------------------------------------

def test_parse_devices_sorts_numerically_not_lexically():
    parsed = cam.parse_devices(["/dev/video10", "/dev/video2", "/dev/video0"])
    assert [d["device"] for d in parsed] == ["/dev/video0", "/dev/video2", "/dev/video10"]


def test_parse_devices_drops_paths_that_are_not_video_nodes():
    parsed = cam.parse_devices([
        "/dev/video0", "/dev/media0", "/dev/videoX", "/dev/video",
        "/dev/video0/../sda", "/tmp/video1", "",
    ])
    assert [d["device"] for d in parsed] == ["/dev/video0"]


def test_parse_devices_default_label_names_the_camera_and_path():
    parsed = cam.parse_devices(["/dev/video3"])
    assert parsed == [{"device": "/dev/video3", "label": "Camera 3 (/dev/video3)"}]


def test_parse_devices_uses_the_friendly_name_when_available():
    def name_for(path):
        return "HD USB Camera\n" if path == "/dev/video0" else ""
    parsed = cam.parse_devices(["/dev/video0", "/dev/video1"], name_for=name_for)
    assert parsed[0]["label"] == "HD USB Camera (/dev/video0)"
    assert parsed[1]["label"] == "Camera 1 (/dev/video1)"


def test_parse_devices_empty_input():
    assert cam.parse_devices([]) == []


# --------------------------------------------------------------------------
# Device path validation: nothing hostile reaches a subprocess
# --------------------------------------------------------------------------

def test_capture_jpeg_refuses_paths_outside_dev_video(monkeypatch):
    monkeypatch.setattr(cam, "capture_tool", lambda: "ffmpeg")

    def _never(*a, **k):
        raise AssertionError("subprocess must not run for an invalid device")
    monkeypatch.setattr(cam.subprocess, "run", _never)

    for bad in ("", "/dev/video0; rm -rf /", "/dev/video0 -i x", "/etc/passwd",
                "/dev/video0/../sda", "video0", "/dev/video", None):
        assert cam.capture_jpeg(bad) is None


def test_capture_jpeg_returns_none_with_no_tool(monkeypatch):
    monkeypatch.setattr(cam, "capture_tool", lambda: "none")
    assert cam.capture_jpeg("/dev/video0") is None


# --------------------------------------------------------------------------
# build_capture_command: the exact argv per tool
# --------------------------------------------------------------------------

def test_ffmpeg_command_grabs_one_jpeg_to_stdout():
    argv = cam.build_capture_command("ffmpeg", "/dev/video0")
    assert argv[0] == "ffmpeg"
    assert "/dev/video0" in argv
    assert argv[argv.index("-frames:v") + 1] == "1"
    assert argv[-1] == "pipe:1"


def test_fswebcam_command_targets_the_device_and_stdout():
    argv = cam.build_capture_command("fswebcam", "/dev/video2")
    assert argv[0] == "fswebcam"
    assert argv[argv.index("-d") + 1] == "/dev/video2"
    assert argv[-1] == "-"


# --------------------------------------------------------------------------
# capture_jpeg subprocess handling
# --------------------------------------------------------------------------

def _completed(returncode=0, stdout=b""):
    return subprocess.CompletedProcess(args=["x"], returncode=returncode,
                                       stdout=stdout, stderr=b"")


def test_capture_jpeg_returns_the_frame_bytes(monkeypatch):
    monkeypatch.setattr(cam, "capture_tool", lambda: "ffmpeg")
    seen = {}

    def fake_run(argv, capture_output, timeout):
        seen["argv"], seen["timeout"] = argv, timeout
        return _completed(stdout=b"\xff\xd8jpegdata")
    monkeypatch.setattr(cam.subprocess, "run", fake_run)

    assert cam.capture_jpeg("/dev/video0", timeout_s=3.0) == b"\xff\xd8jpegdata"
    assert seen["argv"][0] == "ffmpeg"
    assert seen["timeout"] == 3.0


def test_capture_jpeg_none_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(cam, "capture_tool", lambda: "ffmpeg")
    monkeypatch.setattr(cam.subprocess, "run",
                        lambda *a, **k: _completed(returncode=1, stdout=b"partial"))
    assert cam.capture_jpeg("/dev/video0") is None


def test_capture_jpeg_none_on_empty_output(monkeypatch):
    monkeypatch.setattr(cam, "capture_tool", lambda: "fswebcam")
    monkeypatch.setattr(cam.subprocess, "run", lambda *a, **k: _completed(stdout=b""))
    assert cam.capture_jpeg("/dev/video0") is None


def test_capture_jpeg_none_on_timeout(monkeypatch):
    monkeypatch.setattr(cam, "capture_tool", lambda: "ffmpeg")

    def fake_run(argv, capture_output, timeout):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout)
    monkeypatch.setattr(cam.subprocess, "run", fake_run)
    assert cam.capture_jpeg("/dev/video0") is None


def test_capture_jpeg_none_when_tool_is_missing_at_exec(monkeypatch):
    monkeypatch.setattr(cam, "capture_tool", lambda: "ffmpeg")

    def fake_run(*a, **k):
        raise FileNotFoundError("ffmpeg")
    monkeypatch.setattr(cam.subprocess, "run", fake_run)
    assert cam.capture_jpeg("/dev/video0") is None


def test_capture_available_needs_both_a_tool_and_a_camera(monkeypatch):
    monkeypatch.setattr(cam, "capture_tool", lambda: "ffmpeg")
    monkeypatch.setattr(cam, "list_devices", lambda: [{"device": "/dev/video0", "label": "x"}])
    assert cam.capture_available() is True
    monkeypatch.setattr(cam, "list_devices", lambda: [])
    assert cam.capture_available() is False
    monkeypatch.setattr(cam, "capture_tool", lambda: "none")
    monkeypatch.setattr(cam, "list_devices", lambda: [{"device": "/dev/video0", "label": "x"}])
    assert cam.capture_available() is False


# --------------------------------------------------------------------------
# GET /camera/devices
# --------------------------------------------------------------------------

def test_devices_endpoint_reports_cameras_and_tool(monkeypatch):
    monkeypatch.setattr(cam, "list_devices",
                        lambda: [{"device": "/dev/video0", "label": "Camera 0 (/dev/video0)"}])
    monkeypatch.setattr(cam, "capture_tool", lambda: "ffmpeg")
    body = TestClient(app).get("/camera/devices").json()
    assert body["available"] is True
    assert body["tool"] == "ffmpeg"
    assert body["devices"][0]["device"] == "/dev/video0"


def test_devices_endpoint_honest_when_nothing_can_capture(monkeypatch):
    monkeypatch.setattr(cam, "list_devices", lambda: [])
    monkeypatch.setattr(cam, "capture_tool", lambda: "none")
    body = TestClient(app).get("/camera/devices").json()
    assert body["devices"] == [] and body["tool"] == "none" and body["available"] is False
    assert body["hint"]  # explains what to fix


def test_devices_endpoint_camera_present_but_no_tool(monkeypatch):
    monkeypatch.setattr(cam, "list_devices",
                        lambda: [{"device": "/dev/video0", "label": "Camera 0 (/dev/video0)"}])
    monkeypatch.setattr(cam, "capture_tool", lambda: "none")
    body = TestClient(app).get("/camera/devices").json()
    assert body["available"] is False
    assert body["tool"] == "none"
    assert body["devices"]


# --------------------------------------------------------------------------
# POST /camera/vision-frame
# --------------------------------------------------------------------------

def test_vision_frame_fails_cleanly_when_capture_misses(monkeypatch):
    monkeypatch.setattr(cam, "capture_jpeg", lambda device, timeout_s=5.0: None)
    body = TestClient(app).post("/camera/vision-frame",
                                json={"device": "/dev/video0", "what": "speed"}).json()
    assert body["ok"] is False
    assert body["value"] is None
    assert body["recording"] is False
    assert "/dev/video0" in body["error"]
    assert "ffmpeg" in body["error"]


def test_vision_frame_reads_marks_and_reports(monkeypatch):
    from app.routers import device_camera as router_mod

    jpeg = b"\xff\xd8fakejpeg"
    monkeypatch.setattr(cam, "capture_jpeg", lambda device, timeout_s=5.0: jpeg)
    seen = {}

    def fake_read(image_b64, mime, what):
        seen["image_b64"], seen["mime"], seen["what"] = image_b64, mime, what
        return {"value": 42.5}
    monkeypatch.setattr(router_mod.llm, "read_dashboard_value", fake_read)

    rec.start("sweep")
    body = TestClient(app).post("/camera/vision-frame",
                                json={"device": "/dev/video0", "what": "rpm"}).json()
    assert body["ok"] is True
    assert body["value"] == 42.5
    assert body["recording"] is True
    assert body["status"]["count"] == 1
    # The captured frame reached the LLM as clean base64 JPEG.
    assert base64.b64decode(seen["image_b64"]) == jpeg
    assert seen["mime"] == "image/jpeg"
    assert seen["what"] == "rpm"
    # And the mark landed on the reference recorder.
    points = rec.get()["points"]
    assert len(points) == 1 and points[0]["value"] == 42.5


def test_vision_frame_value_not_visible_marks_nothing(monkeypatch):
    from app.routers import device_camera as router_mod

    monkeypatch.setattr(cam, "capture_jpeg", lambda device, timeout_s=5.0: b"\xff\xd8x")
    monkeypatch.setattr(router_mod.llm, "read_dashboard_value",
                        lambda *a, **k: {"value": None})
    rec.start("sweep")
    body = TestClient(app).post("/camera/vision-frame",
                                json={"device": "/dev/video0"}).json()
    assert body["ok"] is True
    assert body["value"] is None
    assert body["recording"] is False
    assert rec.get()["points"] == []


def test_vision_frame_surfaces_llm_errors(monkeypatch):
    from app.routers import device_camera as router_mod

    monkeypatch.setattr(cam, "capture_jpeg", lambda device, timeout_s=5.0: b"\xff\xd8x")

    def boom(*a, **k):
        raise RuntimeError("No API key set. Add one in Settings under AI assist.")
    monkeypatch.setattr(router_mod.llm, "read_dashboard_value", boom)
    body = TestClient(app).post("/camera/vision-frame",
                                json={"device": "/dev/video0"}).json()
    assert body["ok"] is False
    assert "API key" in body["error"]


def test_vision_frame_with_a_hostile_device_path_never_captures(monkeypatch):
    def _never(*a, **k):
        raise AssertionError("subprocess must not run")
    monkeypatch.setattr(cam.subprocess, "run", _never)
    monkeypatch.setattr(cam, "capture_tool", lambda: "ffmpeg")
    body = TestClient(app).post("/camera/vision-frame",
                                json={"device": "/dev/video0; reboot"}).json()
    assert body["ok"] is False


def test_diagnosis_names_the_exact_fix():
    from app.services import device_camera as cam
    # No camera visible -> device passthrough guidance.
    d = cam.diagnosis(devices=[], tool="none")
    assert "docker-compose" in d and "camera" in d.lower()
    # Camera visible but no tool -> rebuild guidance.
    d2 = cam.diagnosis(devices=[{"device": "/dev/video0", "label": "x"}], tool="none")
    assert "--build" in d2 and "tool" in d2.lower()
    # Ready -> empty.
    assert cam.diagnosis(devices=[{"device": "/dev/video0", "label": "x"}], tool="fswebcam") == ""


def test_devices_endpoint_includes_hint_when_unavailable(monkeypatch):
    from app.services import device_camera as cam
    monkeypatch.setattr(cam, "list_devices", lambda: [])
    monkeypatch.setattr(cam, "capture_tool", lambda: "none")
    from starlette.testclient import TestClient
    from app.main import app
    body = TestClient(app).get("/camera/devices").json()
    assert body["available"] is False and body["hint"]


def test_snapshot_endpoint_returns_jpeg_or_503(monkeypatch):
    from app.services import device_camera as cam
    from starlette.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    monkeypatch.setattr(cam, "capture_jpeg", lambda dev, **k: b"\xff\xd8\xff\xd9")
    r = c.get("/camera/snapshot", params={"device": "/dev/video0"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content == b"\xff\xd8\xff\xd9"
    monkeypatch.setattr(cam, "capture_jpeg", lambda dev, **k: None)
    assert c.get("/camera/snapshot", params={"device": "/dev/video0"}).status_code == 503


def test_fswebcam_command_skips_frames_for_exposure():
    from app.services import device_camera as cam
    argv = cam.build_capture_command("fswebcam", "/dev/video0")
    assert "--skip" in argv  # skip initial frames so the sensor auto-exposes (no black frame)
    assert "/dev/video0" in argv


def test_list_devices_filters_out_non_capture_nodes(monkeypatch):
    from app.services import device_camera as cam
    # Two nodes (a UVC webcam's capture + metadata); only the capture one is kept.
    monkeypatch.setattr(cam.glob, "glob", lambda p: ["/dev/video0", "/dev/video1"])
    monkeypatch.setattr(cam, "_sysfs_name", lambda d: "HD Webcam C270")
    monkeypatch.setattr(cam, "supports_capture", lambda d: d == "/dev/video0")
    devices = cam.list_devices()
    assert [d["device"] for d in devices] == ["/dev/video0"]
