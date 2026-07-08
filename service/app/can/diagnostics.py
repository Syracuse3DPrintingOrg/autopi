"""Automotive diagnostics: an ISO-TP transport, a UDS client, and OBD-II
mode-01 PID reads.

Built on two small, permissively licensed libraries rather than reinventing
either protocol:

- `isotp <https://github.com/pylessard/python-can-isotp>`_ (MIT) handles the
  ISO 15765-2 transport layer (segmentation, flow control) over a raw CAN
  channel.
- `udsoncan <https://github.com/pylessard/python-udsoncan>`_ (MIT) handles
  the UDS (ISO 14229) service layer (session control, tester present,
  read/write data by identifier, routine control, read DTCs) on top of an
  ISO-TP connection.

Both are optional at runtime, the same contract as every other CAN
dependency in this package (see ``app.can.socketcan``): when a library is
not installed, or the channel's provider cannot be opened (no hardware, or
python-can missing), ``available`` reports False and requests fall back to a
clearly marked simulated response instead of raising, so the diagnostics
page still demonstrates request/response shapes on a laptop with no
adapter attached.

Request and response *byte encoding and decoding* is kept in plain
functions with no library or hardware dependency, so it is unit-testable on
its own; the transport and client classes are thin, defensively-wrapped
bridges from those bytes to the real wire.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .base import Frame
from .registry import get_channel

log = logging.getLogger(__name__)

DEFAULT_REQUEST_ID = 0x7E0
DEFAULT_RESPONSE_ID = 0x7E8
OBD_FUNCTIONAL_ID = 0x7DF
OBD_RESPONSE_ID = 0x7E8

NEGATIVE_RESPONSE_SID = 0x7F

NRC_NAMES = {
    0x10: "General reject",
    0x11: "Service not supported",
    0x12: "Sub-function not supported",
    0x13: "Incorrect message length or invalid format",
    0x21: "Busy, repeat request",
    0x22: "Conditions not correct",
    0x24: "Request sequence error",
    0x31: "Request out of range",
    0x33: "Security access denied",
    0x35: "Invalid key",
    0x36: "Exceeded number of attempts",
    0x37: "Required time delay not expired",
    0x70: "Upload/download not accepted",
    0x72: "General programming failure",
    0x78: "Request correctly received, response pending",
    0x7E: "Sub-function not supported in active session",
    0x7F: "Service not supported in active session",
}


def _nrc_name(code: int) -> str:
    return NRC_NAMES.get(code, f"NRC 0x{code:02X}")


# -- pure UDS request encoding ------------------------------------------------

def build_session_control_request(session: int = 0x03) -> list[int]:
    """DiagnosticSessionControl (0x10). Default session 0x03 is
    extendedDiagnosticSession; 0x01 is defaultSession, 0x02 programmingSession."""
    return [0x10, session & 0xFF]


def build_tester_present_request() -> list[int]:
    """TesterPresent (0x3E), sub-function 0x00 (no positive response suppress)."""
    return [0x3E, 0x00]


def build_read_did_request(did: int) -> list[int]:
    """ReadDataByIdentifier (0x22) for a single 16-bit DID."""
    return [0x22, (did >> 8) & 0xFF, did & 0xFF]


def build_write_did_request(did: int, value: list[int]) -> list[int]:
    """WriteDataByIdentifier (0x2E) with raw payload bytes."""
    return [0x2E, (did >> 8) & 0xFF, did & 0xFF, *value]


def build_routine_control_request(routine_id: int, subfunction: int = 0x01,
                                   data: list[int] | None = None) -> list[int]:
    """RoutineControl (0x31). subfunction: 0x01 startRoutine,
    0x02 stopRoutine, 0x03 requestRoutineResults."""
    return [0x31, subfunction & 0xFF, (routine_id >> 8) & 0xFF, routine_id & 0xFF, *(data or [])]


def build_read_dtc_request(status_mask: int = 0xFF) -> list[int]:
    """ReadDTCInformation (0x19), sub-function 0x02: reportDTCByStatusMask."""
    return [0x19, 0x02, status_mask & 0xFF]


# -- pure UDS response decoding -----------------------------------------------

def decode_uds_response(data: list[int], expected_sid: int) -> dict[str, Any]:
    """Decode a raw UDS response against the SID it should positively
    acknowledge (request SID + 0x40). Never raises: an empty, short, or
    unexpected response comes back as an error/negative field instead."""
    if not data:
        return {"ok": False, "error": "Empty response"}
    if data[0] == NEGATIVE_RESPONSE_SID:
        nrc = data[2] if len(data) > 2 else None
        return {
            "ok": False,
            "negative": True,
            "request_sid": data[1] if len(data) > 1 else None,
            "nrc": nrc,
            "nrc_name": _nrc_name(nrc) if nrc is not None else None,
        }
    positive_sid = (expected_sid + 0x40) & 0xFF
    if data[0] != positive_sid:
        return {"ok": False, "error": f"Unexpected response SID 0x{data[0]:02X}"}
    return {"ok": True, "sid": data[0], "payload": list(data[1:])}


def decode_session_control_response(data: list[int]) -> dict[str, Any]:
    result = decode_uds_response(data, 0x10)
    if result["ok"]:
        payload = result.pop("payload")
        result.pop("sid", None)
        result["session"] = payload[0] if payload else None
    return result


def decode_tester_present_response(data: list[int]) -> dict[str, Any]:
    result = decode_uds_response(data, 0x3E)
    result.pop("payload", None)
    result.pop("sid", None)
    return result


def decode_read_did_response(data: list[int]) -> dict[str, Any]:
    result = decode_uds_response(data, 0x22)
    if result["ok"]:
        payload = result.pop("payload")
        result.pop("sid", None)
        result["did"] = (payload[0] << 8) | payload[1] if len(payload) >= 2 else None
        result["data"] = payload[2:]
    return result


def decode_write_did_response(data: list[int]) -> dict[str, Any]:
    result = decode_uds_response(data, 0x2E)
    if result["ok"]:
        payload = result.pop("payload")
        result.pop("sid", None)
        result["did"] = (payload[0] << 8) | payload[1] if len(payload) >= 2 else None
    return result


def decode_routine_control_response(data: list[int]) -> dict[str, Any]:
    result = decode_uds_response(data, 0x31)
    if result["ok"]:
        payload = result.pop("payload")
        result.pop("sid", None)
        result["subfunction"] = payload[0] if payload else None
        result["routine_id"] = (payload[1] << 8) | payload[2] if len(payload) >= 3 else None
        result["data"] = payload[3:] if len(payload) > 3 else []
    return result


DTC_CATEGORY = {0: "P", 1: "C", 2: "B", 3: "U"}


def format_dtc(byte0: int, byte1: int) -> str:
    """Format the first two bytes of a UDS DTC as the familiar 'P0301'
    style code (the standard ISO 15031 16-bit encoding). A UDS DTC is
    actually 3 bytes; the third is an OEM-specific sub-code and is carried
    separately rather than folded into this string."""
    category = DTC_CATEGORY[(byte0 >> 6) & 0x03]
    digit1 = (byte0 >> 4) & 0x03
    return f"{category}{digit1}{byte0 & 0x0F:X}{byte1:02X}"


def decode_read_dtc_response(data: list[int]) -> dict[str, Any]:
    result = decode_uds_response(data, 0x19)
    if not result["ok"]:
        return result
    payload = result.pop("payload")
    result.pop("sid", None)
    if len(payload) < 2:
        result["dtcs"] = []
        return result
    # payload[0] = sub-function echo, payload[1] = status availability mask,
    # then 4-byte records: 3 id bytes + 1 status byte, repeated.
    records = payload[2:]
    dtcs = []
    for i in range(0, len(records) - 3, 4):
        b0, b1, b2, status = records[i:i + 4]
        dtcs.append({"code": format_dtc(b0, b1), "sub_code": b2, "status": status})
    result["dtcs"] = dtcs
    return result


# -- pure OBD-II mode-01 PID logic --------------------------------------------

def _pct(a: int, *_: int) -> float:
    return round(a * 100 / 255, 1)


def _temp_c(a: int, *_: int) -> int:
    return a - 40


def _rpm(a: int, b: int, *_: int) -> float:
    return ((a * 256) + b) / 4.0


def _kph(a: int, *_: int) -> int:
    return a


def _maf(a: int, b: int, *_: int) -> float:
    return round(((a * 256) + b) / 100.0, 2)


def _voltage(a: int, b: int, *_: int) -> float:
    return round(((a * 256) + b) / 1000.0, 3)


def _kpa(a: int, *_: int) -> int:
    return a


OBD_PIDS: dict[int, dict[str, Any]] = {
    0x04: {"name": "Engine load", "unit": "%", "bytes": 1, "decode": _pct},
    0x05: {"name": "Coolant temperature", "unit": "C", "bytes": 1, "decode": _temp_c},
    0x0B: {"name": "Intake manifold pressure", "unit": "kPa", "bytes": 1, "decode": _kpa},
    0x0C: {"name": "Engine RPM", "unit": "rpm", "bytes": 2, "decode": _rpm},
    0x0D: {"name": "Vehicle speed", "unit": "km/h", "bytes": 1, "decode": _kph},
    0x0F: {"name": "Intake air temperature", "unit": "C", "bytes": 1, "decode": _temp_c},
    0x10: {"name": "MAF air flow rate", "unit": "g/s", "bytes": 2, "decode": _maf},
    0x11: {"name": "Throttle position", "unit": "%", "bytes": 1, "decode": _pct},
    0x2F: {"name": "Fuel level", "unit": "%", "bytes": 1, "decode": _pct},
    0x42: {"name": "Control module voltage", "unit": "V", "bytes": 2, "decode": _voltage},
}


def build_obd_request(pid: int, mode: int = 0x01) -> list[int]:
    """The ISO-TP payload for a mode-01 PID request: [mode, pid]. This is
    the application-layer user data handed to the ISO-TP transport; the
    transport adds its own length/PCI byte and padding when it frames the
    CAN message, so neither is included here."""
    return [mode & 0xFF, pid & 0xFF]


def decode_obd_response(data: list[int], mode: int = 0x01) -> dict[str, Any]:
    """Decode an OBD-II response payload, already stripped of ISO-TP framing
    by the transport: [mode+0x40, pid, A, B, ...]. An unrecognized PID still
    decodes, just without a named value."""
    if not data:
        return {"ok": False, "error": "Empty response"}
    if data[0] == NEGATIVE_RESPONSE_SID:
        nrc = data[2] if len(data) > 2 else None
        return {"ok": False, "negative": True, "nrc": nrc,
                "nrc_name": _nrc_name(nrc) if nrc is not None else None}
    if len(data) < 2:
        return {"ok": False, "error": "Response too short"}
    positive_mode = (mode + 0x40) & 0xFF
    if data[0] != positive_mode:
        return {"ok": False, "error": f"Unexpected response mode 0x{data[0]:02X}"}
    pid = data[1]
    payload = list(data[2:])
    spec = OBD_PIDS.get(pid)
    if spec is None:
        return {"ok": True, "pid": pid, "name": f"PID 0x{pid:02X}", "raw": payload}
    needed = spec["bytes"]
    if len(payload) < needed:
        return {"ok": False, "error": "Response payload shorter than the PID expects"}
    padded = payload + [0, 0, 0, 0]
    value = spec["decode"](*padded[:4])
    return {"ok": True, "pid": pid, "name": spec["name"], "unit": spec["unit"],
            "value": value, "raw": payload}


# -- simulated responses (used when the library or hardware is unavailable) --

_SIM_OBD_RAW: dict[int, list[int]] = {
    0x04: [38],
    0x05: [88],          # 48 C
    0x0B: [95],
    0x0C: [0x0C, 0x80],  # 800 rpm idle
    0x0D: [0],
    0x0F: [60],          # 20 C
    0x10: [0x03, 0x20],
    0x11: [16],
    0x2F: [150],
    0x42: [0x37, 0x38],  # ~14.14 V
}


def simulate_obd_response(pid: int) -> dict[str, Any]:
    raw = _SIM_OBD_RAW.get(pid, [0, 0])
    result = decode_obd_response([0x41, pid, *raw])
    result["simulated"] = True
    return result


def simulate_session_control(session: int) -> dict[str, Any]:
    result = decode_session_control_response([0x50, session])
    result["simulated"] = True
    return result


def simulate_tester_present() -> dict[str, Any]:
    result = decode_tester_present_response([0x7E, 0x00])
    result["simulated"] = True
    return result


def simulate_read_did(did: int) -> dict[str, Any]:
    result = decode_read_did_response([0x62, (did >> 8) & 0xFF, did & 0xFF, 0x00, 0x00])
    result["simulated"] = True
    return result


def simulate_write_did(did: int) -> dict[str, Any]:
    result = decode_write_did_response([0x6E, (did >> 8) & 0xFF, did & 0xFF])
    result["simulated"] = True
    return result


def simulate_routine_control(routine_id: int, subfunction: int = 0x01) -> dict[str, Any]:
    result = decode_routine_control_response(
        [0x71, subfunction, (routine_id >> 8) & 0xFF, routine_id & 0xFF, 0x00])
    result["simulated"] = True
    return result


def simulate_read_dtcs() -> dict[str, Any]:
    result = decode_read_dtc_response(
        [0x59, 0x02, 0xFF, 0x03, 0x01, 0x00, 0x08, 0x01, 0x11, 0x62, 0x08])
    result["simulated"] = True
    return result


# -- ISO-TP transport (bridges an AutoPi CanProvider to the isotp library) ---

class IsoTpTransport:
    """One ISO-TP session (request id / response id pair) over an AutoPi CAN
    channel, built on the `isotp` package. Degrades to unavailable when
    isotp is not installed or the channel's provider cannot be opened, the
    same contract ``app.can.socketcan.SocketCanProvider`` follows for the
    raw CAN layer underneath it."""

    def __init__(self, channel: str, backend: str = "socketcan",
                 request_id: int = DEFAULT_REQUEST_ID,
                 response_id: int = DEFAULT_RESPONSE_ID,
                 extended_id: bool = False) -> None:
        self.channel = channel
        self.backend = backend
        self.request_id = request_id
        self.response_id = response_id
        self.extended_id = extended_id
        self._stack: Any = None

    @staticmethod
    def module_importable() -> bool:
        try:
            import isotp  # noqa: F401
            return True
        except Exception:
            return False

    @property
    def available(self) -> bool:
        if not self.module_importable():
            return False
        try:
            provider = get_channel(self.channel, backend=self.backend)
        except Exception:
            return False
        return provider.available

    def open(self) -> bool:
        if self._stack is not None:
            return True
        if not self.module_importable():
            return False
        try:
            import isotp
        except Exception:
            return False
        provider = get_channel(self.channel, backend=self.backend)
        if not provider.open():
            return False

        def rxfn(timeout: float):
            frame = provider.recv(timeout=timeout)
            if frame is None or frame.arbitration_id != self.response_id:
                return None
            return isotp.CanMessage(arbitration_id=frame.arbitration_id, data=bytes(frame.data),
                                     extended_id=frame.is_extended_id)

        def txfn(msg: Any) -> None:
            provider.send(Frame(arbitration_id=msg.arbitration_id, data=list(msg.data),
                                 is_extended_id=self.extended_id))

        address = isotp.Address(isotp.AddressingMode.Normal_11bits,
                                 txid=self.request_id, rxid=self.response_id)
        try:
            stack = isotp.TransportLayer(rxfn=rxfn, txfn=txfn, address=address)
            stack.start()
        except Exception as exc:
            log.info("Could not start ISO-TP stack on %s: %s", self.channel, exc)
            return False
        self._stack = stack
        return True

    def close(self) -> None:
        if self._stack is not None:
            try:
                self._stack.stop()
            except Exception:
                pass
            self._stack = None

    def request(self, payload: list[int], timeout: float = 2.0) -> list[int] | None:
        """Send one ISO-TP payload and wait up to ``timeout`` seconds for
        the matching response. Returns None on any failure or timeout,
        never raises."""
        if self._stack is None and not self.open():
            return None
        try:
            self._stack.send(bytes(payload))
            deadline = time.time() + timeout
            while time.time() < deadline:
                data = self._stack.recv(timeout=0.1)
                if data is not None:
                    return list(data)
            return None
        except Exception as exc:
            log.info("ISO-TP request failed on %s: %s", self.channel, exc)
            return None


# -- UDS client (built on udsoncan, over an IsoTpTransport) ------------------

class UdsClient:
    """A UDS (ISO 14229) client built on `udsoncan` over an
    :class:`IsoTpTransport`. Falls back to a simulated response when
    udsoncan, isotp, or the channel's hardware is unavailable, so the
    diagnostics page has something to show on a laptop with no adapter."""

    def __init__(self, channel: str, backend: str = "socketcan",
                 request_id: int = DEFAULT_REQUEST_ID,
                 response_id: int = DEFAULT_RESPONSE_ID) -> None:
        self.transport = IsoTpTransport(channel, backend, request_id, response_id)

    @staticmethod
    def module_importable() -> bool:
        try:
            import udsoncan  # noqa: F401
            return True
        except Exception:
            return False

    @property
    def available(self) -> bool:
        return self.module_importable() and self.transport.available

    def _open_client(self):
        """Open the ISO-TP transport and wrap it in a udsoncan Client
        configured to return negative/unexpected responses instead of
        raising, so the caller always gets a Response object back."""
        import udsoncan
        from udsoncan.client import Client
        from udsoncan.connections import PythonIsoTpConnection

        if not self.transport.open():
            raise RuntimeError("ISO-TP transport unavailable")
        connection = PythonIsoTpConnection(self.transport._stack)
        config = dict(udsoncan.configs.default_client_config)
        config["exception_on_negative_response"] = False
        config["exception_on_invalid_response"] = False
        config["exception_on_unexpected_response"] = False
        client = Client(connection, config=config)
        client.open()
        return client

    def _close(self, client: Any) -> None:
        try:
            if client is not None:
                client.close()
        except Exception:
            pass
        self.transport.close()

    @staticmethod
    def _base_result(response: Any) -> dict[str, Any]:
        if response is None:
            return {"ok": False, "error": "No response from ECU"}
        if not getattr(response, "positive", False):
            code = getattr(response, "code", None)
            return {
                "ok": False,
                "negative": True,
                "nrc": code,
                "nrc_name": getattr(response, "code_name", None) or
                (_nrc_name(code) if code is not None else None),
            }
        return {"ok": True, "raw": list(response.data or b"")}

    def diagnostic_session_control(self, session: int = 0x03) -> dict[str, Any]:
        if not self.available:
            return simulate_session_control(session)
        client = None
        try:
            client = self._open_client()
            response = client.change_session(session)
            result = self._base_result(response)
            if result["ok"]:
                result["session"] = session
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            self._close(client)

    def tester_present(self) -> dict[str, Any]:
        if not self.available:
            return simulate_tester_present()
        client = None
        try:
            client = self._open_client()
            response = client.tester_present()
            return self._base_result(response)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            self._close(client)

    def read_data_by_identifier(self, did: int) -> dict[str, Any]:
        if not self.available:
            return simulate_read_did(did)
        client = None
        try:
            import udsoncan

            class _RawCodec(udsoncan.DidCodec):
                def encode(self, val: Any) -> bytes:
                    return bytes(val)

                def decode(self, payload: bytes) -> list[int]:
                    return list(payload)

                def __len__(self) -> int:
                    raise udsoncan.DidCodec.ReadAllRemainingData

            client = self._open_client()
            client.config["data_identifiers"][did] = _RawCodec()
            response = client.read_data_by_identifier(did)
            result = self._base_result(response)
            if result["ok"]:
                values = getattr(getattr(response, "service_data", None), "values", {}) or {}
                result["did"] = did
                result["data"] = list(values.get(did, []))
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            self._close(client)

    def write_data_by_identifier(self, did: int, value: list[int]) -> dict[str, Any]:
        if not self.available:
            return simulate_write_did(did)
        client = None
        try:
            import udsoncan

            class _RawCodec(udsoncan.DidCodec):
                def encode(self, val: Any) -> bytes:
                    return bytes(val)

                def decode(self, payload: bytes) -> list[int]:
                    return list(payload)

                def __len__(self) -> int:
                    return len(value)

            client = self._open_client()
            client.config["data_identifiers"][did] = _RawCodec()
            response = client.write_data_by_identifier(did, bytes(value))
            result = self._base_result(response)
            if result["ok"]:
                result["did"] = did
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            self._close(client)

    def routine_control(self, routine_id: int, subfunction: int = 0x01,
                         data: list[int] | None = None) -> dict[str, Any]:
        if not self.available:
            return simulate_routine_control(routine_id, subfunction)
        client = None
        try:
            client = self._open_client()
            payload = bytes(data) if data else None
            if subfunction == 0x02:
                response = client.stop_routine(routine_id, data=payload)
            elif subfunction == 0x03:
                response = client.get_routine_result(routine_id, data=payload)
            else:
                response = client.start_routine(routine_id, data=payload)
            result = self._base_result(response)
            if result["ok"]:
                result["routine_id"] = routine_id
                result["subfunction"] = subfunction
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            self._close(client)

    def read_dtcs(self, status_mask: int = 0xFF) -> dict[str, Any]:
        if not self.available:
            return simulate_read_dtcs()
        client = None
        try:
            client = self._open_client()
            response = client.get_dtc_by_status_mask(status_mask)
            result = self._base_result(response)
            if result["ok"]:
                dtcs = []
                for dtc in getattr(getattr(response, "service_data", None), "dtcs", None) or []:
                    dtc_id = getattr(dtc, "id", 0)
                    byte0 = (dtc_id >> 16) & 0xFF
                    byte1 = (dtc_id >> 8) & 0xFF
                    byte2 = dtc_id & 0xFF
                    status = getattr(dtc, "status", None)
                    status_byte = None
                    try:
                        status_byte = status.get_byte() if status is not None else None
                    except Exception:
                        status_byte = None
                    dtcs.append({
                        "code": format_dtc(byte0, byte1),
                        "sub_code": byte2,
                        "status": status_byte,
                    })
                result["dtcs"] = dtcs
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            self._close(client)


# -- OBD-II client (built on IsoTpTransport, no external OBD library) --------

class ObdClient:
    """OBD-II mode-01 PID reads over ISO-TP, built directly on the pure
    request/decode functions above plus :class:`IsoTpTransport`. Not built
    on python-OBD (GPLv2); the PID layer here is a small, permissively
    licensed reimplementation on top of ISO-TP."""

    def __init__(self, channel: str, backend: str = "socketcan",
                 request_id: int = OBD_FUNCTIONAL_ID,
                 response_id: int = OBD_RESPONSE_ID) -> None:
        self.transport = IsoTpTransport(channel, backend, request_id, response_id)

    @property
    def available(self) -> bool:
        return self.transport.available

    def read_pid(self, pid: int, mode: int = 0x01, timeout: float = 2.0) -> dict[str, Any]:
        if not self.available:
            return simulate_obd_response(pid)
        response = self.transport.request(build_obd_request(pid, mode), timeout=timeout)
        if response is None:
            return {"ok": False, "error": "No response from vehicle"}
        return decode_obd_response(response)
