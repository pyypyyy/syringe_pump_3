import logging
import random


logger = logging.getLogger(__name__)


class SoftpotReader:
    def __init__(self, config, ads_reader=None):
        self.config = config
        self.ads_reader = ads_reader
        self.mode = config.get('hardware', {}).get('mode', 'mock')
        self.channel = int(config.get('softpot', {}).get('ads_channel', 2))
        self.mock_volume_ml = float(config.get('axis', {}).get('syringe_volume_ml', 100.0))
        self.mock_min_v = 0.75
        self.mock_max_v = 3.20

    def set_mock_volume(self, volume_ml):
        syringe_volume = float(self.config.get('axis', {}).get('syringe_volume_ml', 100.0))
        self.mock_volume_ml = max(0.0, min(syringe_volume, float(volume_ml)))

    def adjust_mock_volume(self, delta_ml):
        self.set_mock_volume(self.mock_volume_ml + delta_ml)

    def read_voltage(self):
        if self.mode == 'mock':
            syringe_volume = float(self.config.get('axis', {}).get('syringe_volume_ml', 100.0))
            fraction = self.mock_volume_ml / syringe_volume if syringe_volume else 0.0
            return self.mock_min_v + fraction * (self.mock_max_v - self.mock_min_v) + random.uniform(-0.003, 0.003)
        if self.ads_reader is None:
            raise RuntimeError('ADS reader is required in raspberry_pi mode.')
        try:
            return self.ads_reader.read_voltage(self.channel)
        except Exception as exc:
            logger.exception('Failed to read softpot sensor on ADS1115 channel %s: %s', self.channel, exc)
            raise
