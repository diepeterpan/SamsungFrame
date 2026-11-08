import io
import asyncio
import logging
from typing import Tuple, Optional
from PIL import Image
from playwright.async_api import async_playwright, Browser, BrowserContext

logger = logging.getLogger("frame.engine")

class WebCaptureEngine:
    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._lock = asyncio.Lock()

    async def initialize(self):
        if not self._playwright:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--hide-scrollbars"
                ]
            )
            logger.info("Playwright headless Chromium browser initialized.")

    async def capture_url(
        self,
        url: str,
        target_resolution: Tuple[int, int] = (800, 480),
        scaling_mode: str = "fit_letterbox",
        jpeg_quality: int = 85
    ) -> bytes:
        """
        Captures webpage at url, scales and formats to target resolution, returns raw JPEG bytes.
        """
        target_w, target_h = target_resolution
        async with self._lock:
            if not self._browser:
                await self.initialize()

            # Create an isolated page with exact viewport
            page = await self._browser.new_page(
                viewport={"width": target_w, "height": target_h},
                device_scale_factor=1.0
            )
            try:
                # Navigate and wait until network is mostly idle
                await page.goto(url, wait_until="networkidle", timeout=20000)
                await asyncio.sleep(0.5) # Brief stabilization for CSS animations
                screenshot_bytes = await page.screenshot(type="png", full_page=False)
            finally:
                await page.close()

        # Post-process with Pillow
        img = Image.open(io.BytesIO(screenshot_bytes)).convert("RGB")
        processed_img = self._scale_image(img, target_w, target_h, scaling_mode)

        buf = io.BytesIO()
        processed_img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
        return buf.getvalue()

    def _scale_image(self, img: Image.Image, target_w: int, target_h: int, mode: str) -> Image.Image:
        """Scales image strictly to (target_w, target_h) according to scaling mode."""
        orig_w, orig_h = img.size

        if mode == "stretch":
            return img.resize((target_w, target_h), Image.Resampling.LANCZOS)

        if mode == "crop_center":
            # Scale to cover then crop
            ratio = max(target_w / orig_w, target_h / orig_h)
            new_w, new_h = int(orig_w * ratio), int(orig_h * ratio)
            resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            left = (new_w - target_w) // 2
            top = (new_h - target_h) // 2
            return resized.crop((left, top, left + target_w, top + target_h))

        # Default: "fit_letterbox"
        ratio = min(target_w / orig_w, target_h / orig_h)
        new_w, new_h = int(orig_w * ratio), int(orig_h * ratio)
        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # Place onto pure black canvas
        canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
        offset_x = (target_w - new_w) // 2
        offset_y = (target_h - new_h) // 2
        canvas.paste(resized, (offset_x, offset_y))
        return canvas

    async def close(self):
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

