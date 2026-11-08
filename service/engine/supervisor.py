import os
import time
import asyncio
import logging
import subprocess
from typing import Optional, Callable, Dict, Any
from service.driver.usb_driver import SamsungFrameDriver
from service.engine.capture_engine import WebCaptureEngine
from service.config.settings import DeviceConfig

logger = logging.getLogger("frame.healer")

class SupervisorEngine:
    def __init__(self, driver: SamsungFrameDriver, capturer: WebCaptureEngine, config: DeviceConfig):
        self.driver = driver
        self.capturer = capturer
        self.config = config
        
        self.is_running = False
        self.latest_confirmed_jpeg: Optional[bytes] = None
        self.latest_status: Dict[str, Any] = {}
        self.log_messages = []
        self._listeners = set()
        self._consecutive_errors = 0

    def add_log(self, text: str, level: str = "INFO"):
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": text
        }
        self.log_messages.append(entry)
        if len(self.log_messages) > 100:
            self.log_messages.pop(0)
        asyncio.create_task(self._notify_listeners({"type": "log", "data": entry}))

    def register_listener(self, queue: asyncio.Queue):
        self._listeners.add(queue)

    def unregister_listener(self, queue: asyncio.Queue):
        self._listeners.discard(queue)

    async def _notify_listeners(self, payload: dict):
        for q in list(self._listeners):
            try:
                await q.put(payload)
            except Exception:
                pass

    async def self_heal_step(self, current_state: str, dev) -> bool:
        """
        Executes self-healing logic depending on device status.
        """
        if current_state == "STORAGE_MODE":
            self.add_log("Detected device in Mass Storage mode (0x2033/0x2027). Initiating auto-healing switch...", "WARNING")
            switched = self.driver.switch_storage_to_display(dev)
            if switched:
                self.add_log("Switch command sent. Awaiting USB re-enumeration...", "INFO")
                await asyncio.sleep(2.5) # Allow USB disconnect and re-plug sequence

                # Optional virsh re-attach hook if configured
                if self.config.virsh_domain and self.config.virsh_xml_path:
                    self.execute_virsh_reattach()
                return True
            else:
                self.add_log("Failed to switch out of Storage Mode. User intervention may be required.", "ERROR")
                return False

        elif current_state == "DISCONNECTED":
            if self._consecutive_errors % 5 == 0:
                self.add_log("Device not detected on USB. Please verify cable connection or power.", "INFO")
            return False

        return True

    def execute_virsh_reattach(self):
        """Detaches and re-attaches USB device to VM if host is running libvirt/virsh."""
        try:
            cmd_detach = ["virsh", "detach-device", self.config.virsh_domain, self.config.virsh_xml_path]
            cmd_attach = ["virsh", "attach-device", self.config.virsh_domain, self.config.virsh_xml_path]
            self.add_log(f"Executing VM USB passthrough rebind: {self.config.virsh_domain}...", "INFO")
            subprocess.run(cmd_detach, capture_output=True, timeout=5)
            time.sleep(1)
            subprocess.run(cmd_attach, capture_output=True, timeout=5)
            self.add_log("Virsh USB re-attachment executed.", "INFO")
        except Exception as e:
            self.add_log(f"Virsh hook error: {e}", "WARNING")

    async def run_loop(self):
        """Main service loop running periodic rendering and device state management."""
        self.is_running = True
        self.add_log("Samsung Photo Frame background supervisor started.")

        while self.is_running:
            try:
                state, model, dev = self.driver.detect_device(self.config.model)
                resolution = self.driver.active_resolution

                self.latest_status = {
                    "is_mock": getattr(self.driver, "is_mock", False),
                    "state": state,
                    "model": model or "Unknown",
                    "resolution": f"{resolution[0]}x{resolution[1]}",
                    "consecutive_errors": self._consecutive_errors,
                    "last_error": self.driver.last_error,
                    "frames_sent": self.driver.frames_sent_count,
                    "target_url": self.config.target_url,
                    "has_preview": self.latest_confirmed_jpeg is not None
                }
                await self._notify_listeners({"type": "status", "data": self.latest_status})

                if state == "STORAGE_MODE" and self.config.auto_heal:
                    await self.self_heal_step(state, dev)
                    await asyncio.sleep(2)
                    continue

                if state != "DISPLAY_MODE":
                    self._consecutive_errors += 1
                    await asyncio.sleep(3)
                    continue

                # Device is in DISPLAY MODE
                # Ensure device is properly initialized
                initialized = self.driver.init_display_mode(dev)
                if not initialized:
                    self.add_log(f"Failed to send display setup packets: {self.driver.last_error}", "ERROR")
                    self._consecutive_errors += 1
                    await asyncio.sleep(3)
                    continue

                # Capture target URL
                try:
                    jpeg_bytes = await self.capturer.capture_url(
                        url=self.config.target_url,
                        target_resolution=resolution,
                        scaling_mode=self.config.scaling_mode,
                        jpeg_quality=self.config.jpeg_quality
                    )
                except Exception as e:
                    self.add_log(f"Web capture error ({self.config.target_url}): {e}", "ERROR")
                    await asyncio.sleep(self.config.interval_seconds)
                    continue

                # Write to USB bulk endpoint
                success = self.driver.write_jpeg_buffer(dev, jpeg_bytes)
                if success:
                    self._consecutive_errors = 0
                    # ONLY update preview upon confirmed successful USB write!
                    self.latest_confirmed_jpeg = jpeg_bytes
                    self.add_log(f"Rendered frame written to {model} ({len(jpeg_bytes):,} bytes). Preview updated.", "SUCCESS")
                    await self._notify_listeners({"type": "preview_updated", "timestamp": time.time()})
                else:
                    self._consecutive_errors += 1
                    self.add_log(f"USB bulk write failed: {self.driver.last_error}. Attempting stall recovery...", "ERROR")
                    if self._consecutive_errors >= 3:
                        self.driver.reset_device(dev)

                # Dispose USB resources after cycle to avoid resource locking/busy handle
                if getattr(self.driver, "release_device", None):
                    self.driver.release_device(dev)

            except Exception as e:
                logger.error(f"Unexpected supervisor loop error: {e}", exc_info=True)
                self.add_log(f"Supervisor error: {e}", "ERROR")

            await asyncio.sleep(self.config.interval_seconds)

    def stop(self):
        self.is_running = False

