from PIL import Image
import io
import asyncio
import unittest
from service.engine.capture_engine import WebCaptureEngine

class TestCaptureEngine(unittest.IsolatedAsyncioTestCase):
    def test_scale_image_fit_width(self):
        engine = WebCaptureEngine()
        target_w, target_h = 800, 480

        # Case 1: Taller image (e.g. 400x600 -> scaled to 800x1200 -> cropped to 800x480 from top)
        tall_img = Image.new("RGB", (400, 600), (255, 0, 0))
        res_tall = engine._scale_image(tall_img, target_w, target_h, "fit_width")
        self.assertEqual(res_tall.size, (target_w, target_h))

        # Case 2: Shorter/wider image (e.g. 1000x200 -> scaled to 800x160 -> padded at bottom to 800x480)
        short_img = Image.new("RGB", (1000, 200), (0, 255, 0))
        res_short = engine._scale_image(short_img, target_w, target_h, "fit_width")
        self.assertEqual(res_short.size, (target_w, target_h))
        # Top-left should be green (0, 255, 0)
        self.assertEqual(res_short.getpixel((0, 0)), (0, 255, 0))
        # Bottom-left should be black letterbox (0, 0, 0)
        self.assertEqual(res_short.getpixel((0, target_h - 1)), (0, 0, 0))

    async def test_capture_and_scale(self):
        engine = WebCaptureEngine()
        await engine.initialize()
        try:
            # Render a data URI HTML page
            html_data_url = "data:text/html,<html><body style='background:blue;color:white;display:flex;align-items:center;justify-content:center;'><h1>SAMSUNG TEST</h1></body></html>"
            jpeg_bytes = await engine.capture_url(
                url=html_data_url,
                target_resolution=(800, 480),
                scaling_mode="fit_letterbox"
            )
            self.assertGreater(len(jpeg_bytes), 1000)
            self.assertEqual(jpeg_bytes[:2], b"\xff\xd8") # JPEG SOI marker
            self.assertEqual(jpeg_bytes[-2:], b"\xff\xd9") # JPEG EOI marker

            # Test fit_width scaling mode
            jpeg_bytes_fw = await engine.capture_url(
                url=html_data_url,
                target_resolution=(800, 480),
                scaling_mode="fit_width"
            )
            self.assertGreater(len(jpeg_bytes_fw), 1000)
            self.assertEqual(jpeg_bytes_fw[:2], b"\xff\xd8")
            self.assertEqual(jpeg_bytes_fw[-2:], b"\xff\xd9")
        finally:
            await engine.close()

if __name__ == "__main__":
    unittest.main()

