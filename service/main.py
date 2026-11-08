import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from service.config.settings import load_config, save_config, DeviceConfig
from service.driver.usb_driver import SamsungFrameDriver
from service.driver.mock_driver import MockSamsungFrameDriver
from service.engine.capture_engine import WebCaptureEngine
from service.engine.supervisor import SupervisorEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("frame.main")

# Determine whether to run in mock or physical mode
USE_MOCK = os.getenv("FRAME_MOCK", "").lower() in ("1", "true", "yes")

if USE_MOCK:
    logger.info("Initializing in MOCK SIMULATOR mode.")
    driver = MockSamsungFrameDriver(initial_state="STORAGE_MODE")
else:
    # Attempt physical detection; if no physical frame found and auto fallback is desired
    temp_driver = SamsungFrameDriver()
    state, _, _ = temp_driver.detect_device()
    if state == "DISCONNECTED" and os.getenv("FRAME_FORCE_PHYSICAL", "").lower() not in ("1", "true"):
        logger.info("No physical Samsung Frame found on USB. Automatically falling back to MOCK SIMULATOR mode.")
        driver = MockSamsungFrameDriver(initial_state="STORAGE_MODE")
    else:
        logger.info("Using physical PyUSB hardware driver.")
        driver = temp_driver
capturer = WebCaptureEngine()
config = load_config()
supervisor = SupervisorEngine(driver, capturer, config)
supervisor_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global supervisor_task
    logger.info("Initializing Playwright and starting Supervisor...")
    await capturer.initialize()
    supervisor_task = asyncio.create_task(supervisor.run_loop())
    yield
    logger.info("Shutting down Supervisor and Playwright...")
    supervisor.stop()
    if supervisor_task:
        supervisor_task.cancel()
    await capturer.close()

app = FastAPI(title="Samsung Photo Frame Controller", lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(template_path, "r") as f:
        return f.read()

@app.get("/api/config")
async def get_config():
    return supervisor.config

@app.post("/api/config")
async def update_config(new_cfg: DeviceConfig):
    supervisor.config = new_cfg
    save_config(new_cfg)
    supervisor.add_log("Configuration updated via Web UI.", "INFO")
    return {"status": "ok", "config": new_cfg}

@app.get("/api/device/status")
async def get_status():
    return supervisor.latest_status

@app.post("/api/device/sync")
async def trigger_sync():
    """Triggers an out-of-band capture and push."""
    asyncio.create_task(_run_single_sync())
    return {"status": "triggered"}

async def _run_single_sync():
    try:
        state, model, dev = driver.detect_device(supervisor.config.model)
        if state != "DISPLAY_MODE":
            supervisor.add_log(f"Cannot sync: device in {state}", "WARNING")
            return
        jpeg_bytes = await capturer.capture_url(
            url=supervisor.config.target_url,
            target_resolution=driver.active_resolution,
            scaling_mode=supervisor.config.scaling_mode,
            jpeg_quality=supervisor.config.jpeg_quality
        )
        if driver.write_jpeg_buffer(dev, jpeg_bytes):
            supervisor.latest_confirmed_jpeg = jpeg_bytes
            supervisor.add_log(f"Manual sync delivered to {model}.", "SUCCESS")
            await supervisor._notify_listeners({"type": "preview_updated", "timestamp": None})
    except Exception as e:
        supervisor.add_log(f"Manual sync failed: {e}", "ERROR")

@app.post("/api/device/reset")
async def reset_device():
    state, model, dev = driver.detect_device(supervisor.config.model)
    driver.reset_device(dev)
    supervisor.add_log("USB soft reset issued.", "WARNING")
    return {"status": "reset_requested"}

@app.post("/api/device/heal-switch")
async def heal_switch():
    state, model, dev = driver.detect_device(supervisor.config.model)
    if dev:
        driver.switch_storage_to_display(dev)
        supervisor.add_log("Manual force switch command sent to USB device.", "INFO")
        return {"status": "switched"}
    return {"status": "no_device_found"}

@app.post("/api/mock/fault/{fault_type}")
async def inject_mock_fault(fault_type: str):
    """Fault injection endpoints for mock testing."""
    if not getattr(driver, "is_mock", False):
        raise HTTPException(status_code=400, detail="Not running in mock mode")

    if fault_type == "storage":
        driver.set_mock_state("STORAGE_MODE")
        supervisor.add_log("[MOCK FAULT] Device forced to STORAGE_MODE.", "WARNING")
    elif fault_type == "disconnect":
        driver.set_mock_state("DISCONNECTED")
        supervisor.add_log("[MOCK FAULT] Device forced to DISCONNECTED.", "WARNING")
    elif fault_type == "display":
        driver.set_mock_state("DISPLAY_MODE")
        supervisor.add_log("[MOCK FAULT] Device restored to DISPLAY_MODE.", "SUCCESS")
    elif fault_type == "stall":
        driver.trigger_stall_simulation()
        supervisor.add_log("[MOCK FAULT] Injected endpoint bulk stall.", "ERROR")
    else:
        raise HTTPException(status_code=400, detail="Unknown fault type")
    
    return {"status": "injected", "fault": fault_type}

@app.get("/api/preview/latest.jpg")
async def get_latest_preview():
    if not supervisor.latest_confirmed_jpeg:
        raise HTTPException(status_code=404, detail="No confirmed frame sent yet")
    return Response(content=supervisor.latest_confirmed_jpeg, media_type="image/jpeg")

@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    await websocket.accept()
    queue = asyncio.Queue()
    supervisor.register_listener(queue)
    try:
        # Send initial status & logs
        await websocket.send_json({"type": "status", "data": supervisor.latest_status})
        for log in supervisor.log_messages[-30:]:
            await websocket.send_json({"type": "log", "data": log})
        if supervisor.latest_confirmed_jpeg:
            await websocket.send_json({"type": "preview_updated"})

        while True:
            # Wait for event from supervisor or client ping
            event_data = await queue.get()
            await websocket.send_json(event_data)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        supervisor.unregister_listener(queue)

