import os
import json
from pydantic import BaseModel, Field

CONFIG_FILE = os.getenv("FRAME_CONFIG_PATH", "config.json")

class DeviceConfig(BaseModel):
    model: str = Field(default="AUTO", description="Target model: AUTO, SPF-87H, or SPF-107H")
    target_url: str = Field(default="https://time.is", description="Web page URL to capture and display")
    interval_seconds: int = Field(default=15, ge=2, le=3600, description="Capture & send interval in seconds")
    jpeg_quality: int = Field(default=85, ge=10, le=100, description="JPEG compression quality")
    scaling_mode: str = Field(default="fit_letterbox", description="Scaling mode: fit_letterbox, fit_width, crop_center, stretch")
    auto_heal: bool = Field(default=True, description="Enable automatic self-healing on USB mode mismatch")
    virsh_domain: str = Field(default="", description="Optional libvirt/virsh domain for USB passthrough recovery")
    virsh_xml_path: str = Field(default="", description="Optional XML path for virsh attach-device")

def load_config() -> DeviceConfig:
    # If CONFIG_FILE is accidentally mounted as a directory by Docker (e.g. when host file was missing)
    if os.path.isdir(CONFIG_FILE):
        actual_file = os.path.join(CONFIG_FILE, "config.json")
    else:
        actual_file = CONFIG_FILE

    if os.path.exists(actual_file) and not os.path.isdir(actual_file):
        try:
            with open(actual_file, "r") as f:
                data = json.load(f)
                return DeviceConfig(**data)
        except Exception:
            pass
    cfg = DeviceConfig()
    save_config(cfg)
    return cfg

def save_config(cfg: DeviceConfig):
    if os.path.isdir(CONFIG_FILE):
        actual_file = os.path.join(CONFIG_FILE, "config.json")
    else:
        actual_file = CONFIG_FILE

    with open(actual_file, "w") as f:
        f.write(cfg.model_dump_json(indent=2))

