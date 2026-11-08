import asyncio
import unittest
from service.engine.capture_engine import WebCaptureEngine

class TestCaptureEngine(unittest.IsolatedAsyncioTestCase):
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
        finally:
            await engine.close()

if __name__ == "__main__":
    unittest.main()

