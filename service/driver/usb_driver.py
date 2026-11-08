import time
import struct
import io
import logging
from typing import Optional, Tuple
from PIL import Image
import usb.core
import usb.util

logger = logging.getLogger("frame.driver")

VENDOR_ID = 0x04E8

# Model definitions: Model Name -> ((Storage PID, Display PID), (Width, Height))
SUPPORTED_MODELS = {
    "SPF-87H": {
        "pids": (0x2033, 0x2034),
        "resolution": (800, 480)
    },
    "SPF-107H": {
        "pids": (0x2027, 0x2028),
        "resolution": (1024, 600)
    }
}

CHUNK_SIZE = 0x4000     # 16 KB
BUFFER_SIZE = 0x20000   # 128 KB
BULK_ENDPOINT = 0x02

def _generate_blank_jpeg(width: int, height: int) -> bytes:
    """Pre-generates an instant black JPEG buffer for watchdog keep-alive."""
    img = Image.new("RGB", (width, height), (0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()

BLANK_FRAMES = {
    model_name: _generate_blank_jpeg(info["resolution"][0], info["resolution"][1])
    for model_name, info in SUPPORTED_MODELS.items()
}

class SamsungFrameDriver:
    def __init__(self):
        self.current_model: Optional[str] = None
        self.device_state: str = "DISCONNECTED" # DISCONNECTED, STORAGE_MODE, DISPLAY_MODE, ERROR
        self.active_resolution: Tuple[int, int] = (800, 480)
        self.last_error: Optional[str] = None
        self.last_write_timestamp: Optional[float] = None
        self.frames_sent_count: int = 0

    def detect_device(self, preferred_model: str = "AUTO") -> Tuple[str, Optional[str], Optional[usb.core.Device]]:
        """
        Detects connected Samsung Frame.
        Returns: (state, model_name, usb_device)
        """
        models_to_check = SUPPORTED_MODELS.items()
        if preferred_model in SUPPORTED_MODELS:
            models_to_check = [(preferred_model, SUPPORTED_MODELS[preferred_model])]

        # Use a fresh libusb backend context if needed to force-refresh dynamic USB node additions
        backend = None
        try:
            import usb.backend.libusb1
            default_b = usb.backend.libusb1.get_backend()
            if default_b and hasattr(default_b, "lib"):
                backend = usb.backend.libusb1._LibUSB(default_b.lib)
        except Exception:
            backend = None

        for model_name, info in models_to_check:
            storage_pid, display_pid = info["pids"]
            
            # Check for Mini Display Mode first
            try:
                dev_display = usb.core.find(idVendor=VENDOR_ID, idProduct=display_pid, backend=backend) if backend else usb.core.find(idVendor=VENDOR_ID, idProduct=display_pid)
            except Exception as e:
                logger.debug(f"Transient display probe error: {e}")
                dev_display = None

            if dev_display:
                self.current_model = model_name
                self.active_resolution = info["resolution"]
                self.device_state = "DISPLAY_MODE"
                self.last_error = None
                return "DISPLAY_MODE", model_name, dev_display

            # Check for Mass Storage Mode
            try:
                dev_storage = usb.core.find(idVendor=VENDOR_ID, idProduct=storage_pid, backend=backend) if backend else usb.core.find(idVendor=VENDOR_ID, idProduct=storage_pid)
            except Exception as e:
                logger.debug(f"Transient storage probe error: {e}")
                dev_storage = None

            if dev_storage:
                self.current_model = model_name
                self.active_resolution = info["resolution"]
                self.device_state = "STORAGE_MODE"
                self.last_error = None
                return "STORAGE_MODE", model_name, dev_storage

        self.device_state = "DISCONNECTED"
        return "DISCONNECTED", None, None

    def switch_storage_to_display(self, dev: usb.core.Device) -> bool:
        """Sends USB control message to switch from mass storage to display mode."""
        logger.info("Attempting automatic mode switch: Storage -> Display Mode...")
        try:
            # Detach usb-storage kernel driver if active on interface 0
            try:
                if dev.is_kernel_driver_active(0):
                    dev.detach_kernel_driver(0)
            except Exception:
                pass

            # Control transfer: standard request to switch modes
            dev.ctrl_transfer(
                usb.util.CTRL_TYPE_STANDARD | usb.util.CTRL_IN | usb.util.CTRL_RECIPIENT_DEVICE,
                0x06, 0xFE, 0xFE, 254
            )
            self.release_device(dev)
            return True
        except usb.core.USBError as e:
            self.release_device(dev)
            # When the device switches modes, it immediately disconnects/resets bus.
            # "No such device" is expected normal behavior upon disconnect.
            if "No such device" in str(e) or "Input/Output Error" in str(e) or "Pipe" in str(e):
                logger.info("Device disconnected for re-enumeration into display mode (normal).")
                return True
            logger.error(f"Error during storageToDisplay transfer: {e}")
            self.last_error = str(e)
            return False

    def init_display_mode(self, dev: usb.core.Device) -> bool:
        """Initializes device in display mode."""
        try:
            # Detach kernel driver if active on interface 0 (prevents Resource Busy / Errno 16)
            try:
                if dev.is_kernel_driver_active(0):
                    dev.detach_kernel_driver(0)
            except Exception:
                pass

            try:
                dev.set_configuration()
            except usb.core.USBError:
                pass  # Often already configured

            # Vendor setup command
            result = dev.ctrl_transfer(
                usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_IN | usb.util.CTRL_RECIPIENT_DEVICE,
                0x04, 0x00, 0x00, 1
            )
            res_list = result.tolist() if hasattr(result, "tolist") else list(result)
            if res_list != [0x03]:
                logger.warning(f"Unexpected setup reply: {res_list} (expected [3])")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize display mode: {e}")
            self.last_error = str(e)
            return False

    def send_blank_frame(self, dev: usb.core.Device, model_name: Optional[str] = None) -> bool:
        """Immediately transmits a pre-rendered blank JPEG to satisfy hardware watchdog."""
        if model_name and model_name in BLANK_FRAMES:
            blank_bytes = BLANK_FRAMES[model_name]
        elif self.active_resolution:
            # Fallback based on active resolution if model name is generic/unknown
            w, h = self.active_resolution
            blank_bytes = _generate_blank_jpeg(w, h)
        else:
            blank_bytes = BLANK_FRAMES["SPF-87H"]
        return self.write_jpeg_buffer(dev, blank_bytes)

    def write_jpeg_buffer(self, dev: usb.core.Device, jpeg_bytes: bytes) -> bool:
        """
        Sends formatted JPEG buffer with binary header and chunk padding to Bulk Endpoint 0x02.
        """
        try:
            # 12-byte header: magic \xa5\x5a\x09\x04 + 4-byte little-endian length + \x46\x00\x00\x00
            size_pack = struct.pack("<I", len(jpeg_bytes))
            header = b"\xa5\x5a\x09\x04" + size_pack + b"\x46\x00\x00\x00"
            payload = header + jpeg_bytes

            pos = 0
            total_len = len(payload)
            while pos < total_len:
                chunk = payload[pos : pos + BUFFER_SIZE]
                if len(chunk) < BUFFER_SIZE:
                    chunk = chunk + (b"\x00" * (BUFFER_SIZE - len(chunk)))

                # Write in 16KB sub-chunks
                sub_pos = 0
                while sub_pos < BUFFER_SIZE:
                    dev.write(BULK_ENDPOINT, chunk[sub_pos : sub_pos + CHUNK_SIZE], timeout=5000)
                    sub_pos += CHUNK_SIZE

                pos += BUFFER_SIZE

            self.last_write_timestamp = time.time()
            self.frames_sent_count += 1
            self.last_error = None
            return True
        except usb.core.USBError as e:
            logger.error(f"USB Bulk write failed: {e}")
            self.last_error = str(e)
            # Try clearing halt condition on endpoint 0x02
            try:
                dev.clear_halt(BULK_ENDPOINT)
            except Exception:
                pass
            return False

    def release_device(self, dev: Optional[usb.core.Device]):
        """Disposes resources and releases claimed USB handles."""
        if dev:
            try:
                usb.util.dispose_resources(dev)
            except Exception:
                pass

    def reset_device(self, dev: Optional[usb.core.Device] = None):
        """Soft USB bus reset."""
        if dev:
            try:
                dev.reset()
                logger.info("Executed USB bus reset on device.")
            except Exception as e:
                logger.warning(f"Could not reset USB device: {e}")

