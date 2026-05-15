import threading
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from hardware.stepper_driver import StepperDriver


def test_mock_move_steps_timed_completes():
    drv = StepperDriver({'hardware': {'mode': 'mock'}})
    res = drv.move_steps_timed(20, True, 0.05)
    assert res['requested_steps'] == 20
    assert res['moved_steps'] == 20
    assert res['completed'] is True
    assert res['stopped'] is False
    assert res['duration_s'] >= 0


def test_stop_requested_interrupts_timed_move():
    drv = StepperDriver({'hardware': {'mode': 'mock'}})

    out = {}
    def run():
        out['res'] = drv.move_steps_timed(200, True, 1.0)

    t = threading.Thread(target=run)
    t.start()
    time.sleep(0.02)
    drv.stop()
    t.join(timeout=2)
    assert t.is_alive() is False
    res = out['res']
    assert res['completed'] is False
    assert res['stopped'] is True
    assert res['moved_steps'] < res['requested_steps']


def test_zero_or_invalid_steps_handled_safely():
    drv = StepperDriver({'hardware': {'mode': 'mock'}})
    zero = drv.move_steps_timed(0, True, 1)
    invalid = drv.move_steps_timed('not-a-number', True, 1)
    assert zero['moved_steps'] == 0
    assert invalid['moved_steps'] == 0


def test_invalid_duration_handled_safely():
    drv = StepperDriver({'hardware': {'mode': 'mock'}})
    a = drv.move_steps_timed(10, True, 0)
    b = drv.move_steps_timed(10, True, 'bad')
    assert a['moved_steps'] == 0
    assert b['moved_steps'] == 0


def test_result_structure_consistent():
    drv = StepperDriver({'hardware': {'mode': 'mock'}})
    res = drv.move_steps_timed(3, False, 0.01)
    assert set(res.keys()) == {'requested_steps', 'moved_steps', 'completed', 'stopped', 'duration_s'}
