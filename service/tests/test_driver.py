import unittest
import struct
from service.driver.usb_driver import SamsungFrameDriver, SUPPORTED_MODELS

class TestDriverProtocol(unittest.TestCase):
    def setUp(self):
        self.driver = SamsungFrameDriver()

    def test_model_definitions(self):
        self.assertIn("SPF-87H", SUPPORTED_MODELS)
        self.assertIn("SPF-107H", SUPPORTED_MODELS)
        self.assertEqual(SUPPORTED_MODELS["SPF-87H"]["resolution"], (800, 480))
        self.assertEqual(SUPPORTED_MODELS["SPF-107H"]["resolution"], (1024, 600))

    def test_header_packing(self):
        dummy_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        size_pack = struct.pack("<I", len(dummy_jpeg))
        header = b"\xa5\x5a\x09\x04" + size_pack + b"\x46\x00\x00\x00"
        
        self.assertEqual(len(header), 12)
        self.assertEqual(header[:4], b"\xa5\x5a\x09\x04")
        self.assertEqual(header[8:], b"\x46\x00\x00\x00")
        unpacked_len = struct.unpack("<I", header[4:8])[0]
        self.assertEqual(unpacked_len, len(dummy_jpeg))

if __name__ == "__main__":
    unittest.main()

