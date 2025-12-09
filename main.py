from machine import Pin, ADC, I2C
import dht
import utime
from mylib2 import I2cLcd


# ------------------- THRESHOLDS -------------------
TEMP_THRESHOLD = 20.0       # °C
HUMID_MIN = 70.0            # %
METHANE_FRESH = 8           # ppm
METHANE_EARLY = 10
METHANE_ACTIVE = 12
# --------------------------------------------------


class SensorSuite:
    RO_CLEAN_AIR_FACTOR_DEFAULT = 4.0

    def __init__(self, dht_pin=15, mq4_adc_pin=26, mq4_rl=10000, mq4_vref=3.3, mq4_ro_clean_air_factor=None):
        self.dht_sensor = dht.DHT11(Pin(dht_pin))
        self.mq4_adc = ADC(Pin(mq4_adc_pin))
        self.mq4_rl = mq4_rl
        self.mq4_vref = mq4_vref
        self.mq4_ro_factor = mq4_ro_clean_air_factor or self.RO_CLEAN_AIR_FACTOR_DEFAULT
        self.mq4_ro = None

    def read_dht(self):
        try:
            self.dht_sensor.measure()
            return self.dht_sensor.temperature(), self.dht_sensor.humidity()
        except Exception as e:
            print("DHT11 read error:", e)
            return None, None

    def read_mq4_raw(self):
        return self.mq4_adc.read_u16()

    def voltage_from_raw(self, raw):
        return (raw / 65535.0) * self.mq4_vref

    def get_rs(self, voltage=None):
        if voltage is None:
            voltage = self.voltage_from_raw(self.read_mq4_raw())
        if voltage <= 0:
            return float('inf')
        if voltage >= self.mq4_vref:
            return 0.0
        return self.mq4_rl * (self.mq4_vref - voltage) / voltage

    def calibrate_mq4_ro(self, samples=50, delay_ms=50):
        print("Calibrating MQ-4 Ro in clean air. Please keep sensor in fresh air.")
        total_rs = 0
        for _ in range(samples):
            voltage = self.voltage_from_raw(self.read_mq4_raw())
            total_rs += self.get_rs(voltage)
            utime.sleep_ms(delay_ms)
        avg_rs = total_rs / samples
        self.mq4_ro = avg_rs / self.mq4_ro_factor
        print(f"Calibration finished: Ro = {self.mq4_ro:.2f} ohms")
        return self.mq4_ro

    def read_mq4_ratio(self):
        if self.mq4_ro is None:
            raise RuntimeError("MQ-4 Ro not calibrated; call calibrate_mq4_ro() first.")
        voltage = self.voltage_from_raw(self.read_mq4_raw())
        rs = self.get_rs(voltage)
        return rs / self.mq4_ro if self.mq4_ro != 0 else float('inf')

    # ---------------- Adjusted methane estimation ----------------
    def estimate_methane_ppm(self, ratio, a=12, b=-0.5):
        """
        Adjusted for low ppm detection (~10-12 ppm)
        """
        try:
            ppm = a * (ratio ** b)
            return max(ppm, 0)
        except Exception:
            return None

    def read_all(self):
        temp, humid = self.read_dht()
        methane_ppm = None
        try:
            ratio = self.read_mq4_ratio()
            methane_ppm = self.estimate_methane_ppm(ratio)
        except Exception as e:
            print("MQ-4 read error:", e)
        return temp, humid, methane_ppm


class BananaLcdDisplay:
    def __init__(self, i2c, address=0x27):
        self.lcd = I2cLcd(i2c, address, 2, 16)
        self.current_screen = 0

    # ---------------- SAFE PADDING ----------------
    def pad(self, text, length=16):
        text = str(text)
        if len(text) < length:
            return text + (" " * (length - len(text)))
        return text[:length]
    # ----------------------------------------------

    def display_screen_1(self, temperature, humidity):
        self.lcd.clear()
        try:
            temp_str = f"Temp: {float(temperature):.1f}C"
        except Exception:
            temp_str = "Temp: N/A"
        try:
            humid_val = int(float(humidity))
            humid_str = f"Humidity: {humid_val}%"
        except Exception:
            humid_str = "Humidity: N/A"
        self.lcd.move_to(0, 0)
        self.lcd.putstr(self.pad(temp_str))
        self.lcd.move_to(0, 1)
        self.lcd.putstr(self.pad(humid_str))

    def display_screen_2(self, methane, shelf_life):
        self.lcd.clear()
        try:
            methane_val = float(methane)
            methane_str = f"Methane: {methane_val:.2f}ppm"
        except Exception:
            methane_str = "Methane: N/A"
        shelf_str = str(shelf_life) if shelf_life is not None else "Shelf Life: N/A"
        self.lcd.move_to(0, 0)
        self.lcd.putstr(self.pad(methane_str))
        self.lcd.move_to(0, 1)
        self.lcd.putstr(self.pad(shelf_str))

    def update(self, temperature, humidity, methane, shelf_life):
        if self.current_screen == 0:
            self.display_screen_1(temperature, humidity)
            self.current_screen = 1
        else:
            self.display_screen_2(methane, shelf_life)
            self.current_screen = 0


if __name__ == "__main__":
    sensors = SensorSuite(dht_pin=15, mq4_adc_pin=26)
    i2c = I2C(0, sda=Pin(0), scl=Pin(1), freq=400000)
    display = BananaLcdDisplay(i2c, 0x27)

    sensors.calibrate_mq4_ro()
    print("Starting sensor readings and LCD display (Ctrl+C to stop)...")

    methane_history = []

    try:
        while True:
            temp, humidity, methane = sensors.read_all()
            temp_val = float(temp) if temp is not None else None
            humid_val = int(float(humidity)) if humidity is not None else None

            # ---------------- Smooth methane readings ----------------
            if methane is not None:
                methane_history.append(methane)
                if len(methane_history) > 5:
                    methane_history.pop(0)
                methane_avg = sum(methane_history) / len(methane_history)
            else:
                methane_avg = None
            # ---------------------------------------------------------

            # ----------------- Threshold-based shelf life -----------------
            if methane_avg is None:
                shelf_life = "Unknown"
            elif methane_avg < METHANE_FRESH:
                shelf_life = "5-7 Days"
            elif methane_avg < METHANE_EARLY:
                shelf_life = "3-5 Days"
            elif methane_avg < METHANE_ACTIVE:
                shelf_life = "1-3 Days"
            else:
                shelf_life = "0 Days"
            # ----------------------------------------------------------------

            print(f"Temp: {temp_val} C, Humidity: {humid_val} %, Methane: {methane_avg:.2f} ppm, Shelf Life: {shelf_life}")

            display.update(temp_val, humid_val, methane_avg or 0, shelf_life)

            utime.sleep(3)

    except KeyboardInterrupt:
        print("\nStopped by user.")
        display.lcd.clear()
