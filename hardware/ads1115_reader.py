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
        i2c = busio.I2C(board.SCL, board.SDA)
        address = int(self.config.get('ads1115', {}).get('address', 0x48))
        self._ads = ADS.ADS1115(i2c, address=address)

    def read_voltage(self, channel):
        if self.mode == 'mock':
            return 0.0
        import adafruit_ads1x15.ads1115 as ADS
        from adafruit_ads1x15.analog_in import AnalogIn
        pins = [ADS.P0, ADS.P1, ADS.P2, ADS.P3]
        if channel < 0 or channel > 3:
            raise ValueError(f'Invalid ADS1115 channel: {channel}')
        return float(AnalogIn(self._ads, pins[channel]).voltage)
