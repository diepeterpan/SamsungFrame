import time
import struct
import logging
from typing import Optional, Tuple, Any

logger = logging.getLogger("frame.mock_driver")

MOCK_MODELS = {
    "SPF-87H": {
        "pids": (0x2033, 0x2034),
        "resolution": (800, 480)
    },
    "SPF-107H": {
        "pids": (0x2027, 0x2028),
        "resolution": (1024, 600)
    }
}

CHUNK_SIZE = 0x4000
BUFFER_SIZE = 0x20000
BULK_ENDPOINT = 0x02

class MockUsbDevice:
    """Mock representation of the pyusb Device object."""
    def __init__(self, name: str, pid: int):
        self.name = name
        self.idVendor = 0x04E8
        self.idProduct = pid

    def set_configuration(self):
        return

    def ctrl_transfer(self, bmRequestType, bRequest, wValue, wIndex, data_or_wLength):
        if bRequest == 0x04:
            return [0x03] # Ack vendor display setup
        return [0x00]

    def clear_halt(self, ep):
        return

    def reset(self):
        return

class MockSamsungFrameDriver:
    """
    High-fidelity in-memory simulator for Samsung Photo Frames (SPF-87H / SPF-107H).
    Accurately reproduces USB state transitions, control packets, and bulk writes.
    """
    def __init__(self, initial_state: str = "STORAGE_MODE", model: str = "SPF-87H"):
        self.is_mock = True
        self.current_model = model
        self.device_state = initial_state # STORAGE_MODE, DISPLAY_MODE, DISCONNECTED
        self.active_resolution = MOCK_MODELS[model]["resolution"]
        self.last_error: Optional[str] = None
        self.last_write_timestamp: Optional[float] = None
        self.frames_sent_count = 0
        self.simulate_stall = False
        self._mock_device = MockUsbDevice(model, MOCK_MODELS[model]["pids"][0])

    def detect_device(self, preferred_model: str = "AUTO") -> Tuple[str, Optional[str], Optional[Any]]:
        if preferred_model in MOCK_MODELS:
            self.current_model = preferred_model
            self.active_resolution = MOCK_MODELS[preferred_model]["resolution"]

        if self.device_state == "DISCONNECTED":
            return "DISCONNECTED", None, None

        pid_index = 0 if self.device_state == "STORAGE_MODE" else 1
        pid = MOCK_MODELS[self.current_model]["pids"][pid_index]
        self._mock_device.idProduct = pid

        return self.device_state, self.current_model, self._mock_device

    def switch_storage_to_display(self, dev: Any) -> bool:
        logger.info("[MOCK] Received Storage -> Display switch control packet.")
        # Simulate brief disconnect during firmware re-enumeration
        self.device_state = "DISCONNECTED"
        time.sleep(0.5)
        self.device_state = "DISPLAY_MODE"
        self._mock_device.idProduct = MOCK_MODELS[self.current_model]["pids"][1]
        logger.info("[MOCK] Device re-enumerated into Mini-Display mode (0x2034).")
        return True

    def init_display_mode(self, dev: Any) -> bool:
        if self.device_state != "DISPLAY_MODE":
            self.last_error = "Device is not in display mode"
            return False
        return True

    def write_jpeg_buffer(self, dev: Any, jpeg_bytes: bytes) -> bool:
        if self.simulate_stall:
            self.last_error = "Simulated USB endpoint stall / pipe error"
            logger.warning("[MOCK] Injected USB stall on bulk endpoint 0x02.")
            return False

        if self.device_state != "DISPLAY_MODE":
            self.last_error = f"Cannot write image: device in {self.device_state}"
            return False

        # Validate header protocol
        size_pack = struct.pack("<I", len(jpeg_bytes))
        header = b"\xa5\x5a\x09\x04" + size_pack + b"\x46\x00\x00\x00"
        payload = header + jpeg_bytes

        # Verify chunking and padding
        pos = 0
        total_len = len(payload)
        while pos < total_len:
            chunk = payload[pos : pos + BUFFER_SIZE]
            if len(chunk) < BUFFER_SIZE:
                chunk = chunk + (b"\x00" * (BUFFER_SIZE - len(chunk)))
            pos += BUFFER_SIZE

        self.last_write_timestamp = time.time()
        self.frames_sent_count += 1
        self.last_error = None
        logger.info(f"[MOCK] Acknowledged bulk write: {len(jpeg_bytes):,} bytes to {self.current_model}")
        return True

    def reset_device(self, dev: Optional[Any] = None):
        logger.info("[MOCK] Simulated soft USB bus reset performed.")
        self.simulate_stall = False
        self.last_error = None

    # Fault Injection Helpers
    def set_mock_state(self, new_state: str):
        logger.info(f"[MOCK] Fault injection: transitioning state to {new_state}")
        self.device_state = new_state

    def trigger_stall_simulation(self):
        logger.info("[MOCK] Fault injection: enabling endpoint stall")
        self.simulate_stall = True

