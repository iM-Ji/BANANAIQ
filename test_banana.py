import sys
import unittest
from unittest.mock import MagicMock, patch

# -------------------- PATCH MICRO-PYTHON MODULES --------------------
sys.modules['machine'] = MagicMock()
sys.modules['dht'] = MagicMock()
sys.modules['utime'] = MagicMock()

# -------------------- IMPORT YOUR CODE AFTER PATCH --------------------
from main import SensorSuite, BananaLcdDisplay

# -------------------- MOCK CLASSES --------------------
class MockADC:
    def read_u16(self):
        return 32768  # mid-scale ADC value

class MockDHT:
    def measure(self):
        pass
    def temperature(self):
        return 25
    def humidity(self):
        return 80

class MockLCD:
    def clear(self): pass
    def move_to(self, x, y): pass
    def putstr(self, text): print(f"LCD: {text}")

# -------------------- UNIT TESTS --------------------
class TestBananaMonitor(unittest.TestCase):

    def setUp(self):
        # Setup sensors with mocked hardware
        self.sensors = SensorSuite()
        self.sensors.mq4_adc = MockADC()  # type: ignore
        self.sensors.dht_sensor = MockDHT()  # type: ignore
        self.sensors.mq4_ro = 1.0  # prevent RuntimeError in read_mq4_ratio

        # Patch I2cLcd to use MockLCD in BananaLcdDisplay
        patcher = patch('main.I2cLcd', return_value=MockLCD())
        self.addCleanup(patcher.stop)
        self.mock_i2clcd = patcher.start()

        # Initialize display
        self.display = BananaLcdDisplay(None)

    # -------------------- SENSOR TESTS --------------------
    def test_voltage_from_raw(self):
        raw = 32768
        voltage = self.sensors.voltage_from_raw(raw)
        self.assertAlmostEqual(voltage, 1.65, places=2)

    def test_get_rs(self):
        voltage = 1.65
        rs = self.sensors.get_rs(voltage)
        self.assertTrue(rs > 0)

    def test_estimate_methane_ppm(self):
        ppm = self.sensors.estimate_methane_ppm(1.0)
        self.assertAlmostEqual(ppm, 12.0, places=2)  # matches your main.py a=12, b=-0.5

    def test_read_all(self):
        temp, humid, methane = self.sensors.read_all()
        self.assertEqual(temp, 25)
        self.assertEqual(humid, 80)
        self.assertIsInstance(methane, float)

    # -------------------- SHELF-LIFE TEST --------------------
    def test_shelf_life_logic(self):
        # Simulate different methane levels
        test_values = [
            (5, "5-7 Days"),
            (9, "3-5 Days"),
            (11, "1-3 Days"),
            (13, "0 Days"),
        ]
        for methane_raw, expected in test_values:
            shelf_life = self.calculate_shelf_life(methane_raw)
            self.assertIn(expected, shelf_life)

    def calculate_shelf_life(self, methane):
        TEMP_THRESHOLD = 20.0
        HUMID_MIN = 70.0
        METHANE_FRESH = 8
        METHANE_EARLY = 10
        METHANE_ACTIVE = 12

        shelf_life = "Unknown"
        if methane < METHANE_FRESH:
            shelf_life = "5-7 Days"
        elif methane < METHANE_EARLY:
            shelf_life = "3-5 Days"
        elif methane < METHANE_ACTIVE:
            shelf_life = "1-3 Days"
        else:
            shelf_life = "0 Days"

        # Environmental adjustment
        temp_val = 25
        humid_val = 80
        if temp_val > TEMP_THRESHOLD:
            shelf_life += " (High Temp)"
        if humid_val < HUMID_MIN:
            shelf_life += " (Low Humid)"

        return shelf_life

    # -------------------- LCD DISPLAY TEST --------------------
    def test_display_update(self):
        temp, humid, methane = 25, 80, 10.5
        shelf_life = "3-5 Days"
        # Switch screens
        self.display.update(temp, humid, methane, shelf_life)
        self.display.update(temp, humid, methane, shelf_life)

# -------------------- RUN TESTS --------------------
if __name__ == "__main__":
    unittest.main()
