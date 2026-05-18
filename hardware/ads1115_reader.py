import logging


logger = logging.getLogger(__name__)


class ADS1115Reader:
    def __init__(self, config):
        self.config = config
        self.mode = config.get('hardware', {}).get('mode', 'mock')
        self._ads = None
        if self.mode == 'raspberry_pi':
            self._init_real_ads()

    def _init_real_ads(self):
        try:
            import board
            import busio
            import adafruit_ads1x15.ads1115 as ADS
        except ImportError as exc:
            raise RuntimeError('Real ADS1115 mode requires adafruit-circuitpython-ads1x15, board and busio.') from exc

        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            address = int(self.config.get('ads1115', {}).get('address', 0x48))
            self._ads = ADS.ADS1115(i2c, address=address)
        except Exception as exc:
            logger.exception('Failed to initialize ADS1115 at address %s: %s', hex(address), exc)
            raise

    def read_voltage(self, channel: int) -> float:
        if self.mode == 'mock':
            return 0.0

        from adafruit_ads1x15.ads1x15 import Pin
        from adafruit_ads1x15.analog_in import AnalogIn

        pins = [Pin.A0, Pin.A1, Pin.A2, Pin.A3]
        if channel < 0 or channel >= len(pins):
            raise ValueError(f'Invalid ADS1115 channel: {channel}')

        try:
            chan = AnalogIn(self._ads, pins[channel])
            return float(chan.voltage)
        except Exception as exc:
            logger.exception('Failed to read ADS1115 channel %s: %s', channel, exc)
            raise
