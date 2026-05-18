from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hardware.ads1115_reader import ADS1115Reader


class DummyPin:
    A0 = 'A0'
    A1 = 'A1'
    A2 = 'A2'
    A3 = 'A3'


class FakeAnalogIn:
    def __init__(self, ads, pin):
        self.ads = ads
        self.pin = pin

    @property
    def voltage(self):
        return {
            'A0': 0.1,
            'A1': 0.2,
            'A2': 0.3,
            'A3': 0.4,
        }[self.pin]


@pytest.fixture()
def fake_ads_modules(monkeypatch):
    monkeypatch.setitem(sys.modules, 'adafruit_ads1x15.ads1x15', types.SimpleNamespace(Pin=DummyPin))
    monkeypatch.setitem(sys.modules, 'adafruit_ads1x15.analog_in', types.SimpleNamespace(AnalogIn=FakeAnalogIn))


def test_channel_mapping_and_voltage_reads(fake_ads_modules):
    reader = ADS1115Reader({'hardware': {'mode': 'mock'}})
    reader.mode = 'raspberry_pi'
    reader._ads = object()

    assert reader.read_voltage(0) == pytest.approx(0.1)
    assert reader.read_voltage(1) == pytest.approx(0.2)
    assert reader.read_voltage(2) == pytest.approx(0.3)
    assert reader.read_voltage(3) == pytest.approx(0.4)


def test_invalid_channels_raise_value_error(fake_ads_modules):
    reader = ADS1115Reader({'hardware': {'mode': 'mock'}})
    reader.mode = 'raspberry_pi'
    reader._ads = object()

    with pytest.raises(ValueError, match='Invalid ADS1115 channel: -1'):
        reader.read_voltage(-1)
    with pytest.raises(ValueError, match='Invalid ADS1115 channel: 4'):
        reader.read_voltage(4)
