import unittest
from service.driver.mock_driver import MockSamsungFrameDriver

class TestMockDriver(unittest.TestCase):
    def test_mock_lifecycle(self):
        driver = MockSamsungFrameDriver(initial_state="STORAGE_MODE")
        state, model, dev = driver.detect_device("SPF-87H")
        self.assertEqual(state, "STORAGE_MODE")
        self.assertEqual(model, "SPF-87H")
        self.assertEqual(dev.idProduct, 0x2033)

        # Trigger self-healing switch
        switched = driver.switch_storage_to_display(dev)
        self.assertTrue(switched)
        self.assertEqual(driver.device_state, "DISPLAY_MODE")

        # Test bulk write
        dummy_jpeg = b"\xff\xd8" + b"\x00" * 2000 + b"\xff\xd9"
        res = driver.write_jpeg_buffer(dev, dummy_jpeg)
        self.assertTrue(res)
        self.assertEqual(driver.frames_sent_count, 1)

    def test_mock_fault_injection(self):
        driver = MockSamsungFrameDriver(initial_state="DISPLAY_MODE")
        driver.trigger_stall_simulation()
        dummy_jpeg = b"\xff\xd8\xff\xd9"
        res = driver.write_jpeg_buffer(driver._mock_device, dummy_jpeg)
        self.assertFalse(res)
        self.assertIn("stall", driver.last_error)

        driver.reset_device()
        self.assertFalse(driver.simulate_stall)

if __name__ == "__main__":
    unittest.main()
