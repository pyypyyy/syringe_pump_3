import random


class FlowSensor:
    def __init__(self, config, ads_reader=None):
        self.config = config
        self.ads_reader = ads_reader
        self.mode = config.get('hardware', {}).get('mode', 'mock')
        self.channel = int(config.get('flow_sensor', {}).get('ads_channel', 1))
        self.divider_ratio = float(config.get('flow_sensor', {}).get('voltage_divider_ratio', 1.0))
        self.mock_active_flow_lpm = 0.0

    def set_mock_active_flow(self, flow_lpm):
        self.mock_active_flow_lpm = max(0.0, float(flow_lpm))

    def read_voltage(self):
        if self.mode == 'mock':
            return 0.48 + 1.20 * self.mock_active_flow_lpm + random.uniform(-0.004, 0.004)
        if self.ads_reader is None:
            raise RuntimeError('ADS reader is required in raspberry_pi mode.')
        measured_voltage = self.ads_reader.read_voltage(self.channel)
        if self.divider_ratio <= 0:
            raise ValueError('voltage_divider_ratio must be positive.')
        return measured_voltage / self.divider_ratio

    def estimate_flow_lpm(self, voltage):
        x = voltage
        lpm = 0.09400*x**5 - 0.563412*x**4 + 1.374705*x**3 - 1.601495*x**2 + 1.060657*x - 0.269996
        return max(0.0, float(lpm))
