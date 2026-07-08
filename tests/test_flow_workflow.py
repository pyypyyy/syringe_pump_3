import threading
import time
from pathlib import Path
import json

from calibration.flow_calibration_runner import FlowCalibrationRunner
from calibration.trial_runner import TrialRunner
from hardware.stepper_driver import StepperDriver, PigpioBackend


class FakeTimedStepper:
    def __init__(self):
        self.step_position = 0
        self.mode = 'mock'
        self.stop_requested = False
        self.enabled = False
        self.motion_active = False

    def enable(self):
        self.enabled = True

    def stop(self):
        self.stop_requested = True
        self.motion_active = False

    def clear_stop(self):
        self.stop_requested = False

    def move_steps(self, steps, direction_toward_empty, step_delay_s=0.001):
        self.step_position += steps if direction_toward_empty else -steps
        return steps

    def move_steps_timed(self, steps, direction_toward_empty, duration_s):
        self.motion_active = True
        start = time.time()
        moved = 0
        while time.time() - start < duration_s and not self.stop_requested:
            time.sleep(0.01)
            moved += max(1, int(steps * 0.01 / max(duration_s, 1e-6)))
            self.step_position += 1 if direction_toward_empty else -1
        self.motion_active = False
        return moved


class FakeSoftpot:
    mode = 'mock'
    def __init__(self, stepper):
        self.stepper = stepper
    def read_voltage(self):
        return 1.0 + self.stepper.step_position * 0.001


class FakePositionModel:
    def voltage_to_volume_ml(self, voltage):
        return voltage * 10.0


class FakeFlow:
    def read_voltage(self): return 0.7
    def estimate_flow_lpm(self, voltage): return 0.2


def test_run_trial_samples_while_moving(tmp_path):
    cfg = {'flow_calibration': {'sample_interval_s': 0.02, 'settle_before_s': 0.0, 'settle_after_s': 0.0, 'actual_flow_window_s': 0.1}, 'axis': {'microsteps_per_ml': 10.0}}
    stepper = FakeTimedStepper()
    runner = TrialRunner(cfg, stepper, FakeSoftpot(stepper), FakeFlow(), FakePositionModel(), lambda: False)
    t = type('T', (), {'stroke_start_ml': 10.0, 'stroke_end_ml': 0.0, 'target_flow_lpm': 1.0, 'trial_id': 't1', 'gas': 'air'})()
    res = runner.run_trial(t, tmp_path / 't.csv')
    moving = [r for r in res['rows'] if r['motion_phase'] == 'moving']
    assert len(moving) > 2
    vols = [r['softpot_volume_ml'] for r in moving]
    assert len(set(vols)) > 1
    assert any(r['actual_flow_lpm_window'] is not None for r in moving)


def test_stop_request_stops_motion_and_sampling(tmp_path):
    cfg = {'flow_calibration': {'sample_interval_s': 0.02, 'settle_before_s': 0.0, 'settle_after_s': 0.0}, 'axis': {'microsteps_per_ml': 10.0}}
    stepper = FakeTimedStepper()
    stop_evt = {'stop': False}
    runner = TrialRunner(cfg, stepper, FakeSoftpot(stepper), FakeFlow(), FakePositionModel(), lambda: stop_evt['stop'])
    t = type('T', (), {'stroke_start_ml': 10.0, 'stroke_end_ml': 0.0, 'target_flow_lpm': 0.5, 'trial_id': 't2', 'gas': 'air'})()
    th = threading.Thread(target=lambda: runner.run_trial(t, tmp_path / 't2.csv'))
    th.start(); time.sleep(0.08); stop_evt['stop'] = True; th.join(timeout=2)
    assert not th.is_alive()


def test_pigpio_backend_selection_and_cleanup(monkeypatch):
    calls = []
    class FakePI:
        connected = True
        def set_mode(self, *a): calls.append(('set_mode', a))
        def write(self, *a): calls.append(('write', a))
        def hardware_PWM(self, *a): calls.append(('pwm', a))
        def stop(self): calls.append(('stop', ()))
    class FakePigpio:
        OUTPUT = 1
        def pi(self): return FakePI()
    monkeypatch.setitem(__import__('sys').modules, 'pigpio', FakePigpio())
    drv = StepperDriver({'hardware': {'mode': 'raspberry_pi'}, 'stepper': {'backend': 'pigpio', 'step_pin': 1, 'dir_pin': 2, 'enable_pin': 3}})
    drv.enable(); drv.move_steps_timed(10, True, 0.02); drv.cleanup()
    assert any(c[0] == 'pwm' for c in calls)
    assert any(c[0] == 'stop' for c in calls)


def test_runner_outputs_summary_and_curve(tmp_path):
    cfg = {'hardware': {'mode': 'mock'}, 'axis': {'microsteps_per_ml': 5.0, 'syringe_volume_ml': 100.0}, 'flow_calibration': {'sample_interval_s': 0.01, 'settle_before_s': 0.0, 'settle_after_s': 0.0, 'analysis_min_ml': 20, 'analysis_max_ml': 80, 'quality_checks': {'min_stable_samples': 1, 'min_stable_duration_s': 0.0, 'min_nonzero_flow_lpm': 0.0, 'max_flow_cv': 5.0}, 'zero_flow': {'settling_s': 0.0, 'sample_duration_s': 0.05, 'sample_interval_s': 0.01}}}
    from hardware.softpot_reader import SoftpotReader
    from hardware.flow_sensor import FlowSensor
    class PM:
        def __init__(self,s): self.s=s
        def voltage_to_volume_ml(self,v): return (v-self.s.mock_min_v)/(self.s.mock_max_v-self.s.mock_min_v)*100
    stepper = StepperDriver(cfg); softpot = SoftpotReader(cfg); flow = FlowSensor(cfg); pm = PM(softpot)
    runner = FlowCalibrationRunner(cfg, stepper, softpot, flow, pm, lambda **k: None, lambda: False)
    res = runner.run('air', [0.2], 1, 100.0, 0.0, 20, 80)
    rd = Path(res['run_dir'])
    assert (rd / 'summary.csv').exists()
    assert (rd / 'accepted_points.csv').exists()
    curve = json.loads((rd / 'calibration_curve.json').read_text())
    assert curve['gas'] == 'air'
    assert 'zero_flow' in curve
    assert 'rmse_lpm' not in curve['fit_quality']
    assert curve['fit_quality']['accepted_point_count'] >= 0
    import csv
    summary = list(csv.DictReader((rd / 'summary.csv').open()))
    assert {'volume_start_ml', 'volume_end_ml', 'analysis_min_ml', 'analysis_max_ml', 'min_sample_count', 'min_stable_duration_s'} <= set(summary[0])


def test_move_steps_uses_pigpio_backend(monkeypatch):
    calls = []
    class FakePI:
        connected = True
        def set_mode(self, *a): pass
        def write(self, *a): calls.append(('write', a))
        def hardware_PWM(self, *a): calls.append(('pwm', a))
        def stop(self): pass
    class FakePigpio:
        OUTPUT = 1
        def pi(self): return FakePI()
    monkeypatch.setitem(__import__('sys').modules, 'pigpio', FakePigpio())
    drv = StepperDriver({'hardware': {'mode': 'raspberry_pi'}, 'stepper': {'backend': 'pigpio', 'step_pin': 18, 'dir_pin': 2, 'enable_pin': 3}})
    moved = drv.move_steps(20, True, step_delay_s=0.001)
    assert moved >= 1
    assert any(c[0] == 'pwm' for c in calls)


def test_trial_rejects_when_softpot_stuck(tmp_path):
    cfg = {'flow_calibration': {'sample_interval_s': 0.02, 'settle_before_s': 0.0, 'settle_after_s': 0.0, 'softpot_motion_timeout_s': 0.06, 'softpot_min_change_ml': 0.5}, 'axis': {'microsteps_per_ml': 10.0}, 'safety': {'min_volume_ml': -5.0, 'max_volume_ml': 200.0}}
    stepper = FakeTimedStepper()
    class StuckSoftpot:
        mode = 'mock'
        def read_voltage(self): return 1.0
    runner = TrialRunner(cfg, stepper, StuckSoftpot(), FakeFlow(), FakePositionModel(), lambda: False)
    t = type('T', (), {'stroke_start_ml': 10.0, 'stroke_end_ml': 0.0, 'target_flow_lpm': 0.5, 'trial_id': 't3', 'gas': 'air'})()
    res = runner.run_trial(t, tmp_path / 't3.csv')
    assert res['status'] == 'failed'
    assert 'not changing' in (res['reason'] or '')


def test_trial_rejects_wrong_direction(tmp_path):
    cfg = {'flow_calibration': {'sample_interval_s': 0.02, 'settle_before_s': 0.0, 'settle_after_s': 0.0, 'softpot_direction_tolerance_ml': 0.1}, 'axis': {'microsteps_per_ml': 10.0}, 'safety': {'min_volume_ml': -5.0, 'max_volume_ml': 200.0}}
    stepper = FakeTimedStepper()
    class WrongDirectionSoftpot:
        mode = 'mock'
        def __init__(self): self.v = 1.0
        def read_voltage(self):
            self.v += 0.01
            return self.v
    runner = TrialRunner(cfg, stepper, WrongDirectionSoftpot(), FakeFlow(), FakePositionModel(), lambda: False)
    t = type('T', (), {'stroke_start_ml': 10.0, 'stroke_end_ml': 0.0, 'target_flow_lpm': 0.5, 'trial_id': 't4', 'gas': 'air'})()
    res = runner.run_trial(t, tmp_path / 't4.csv')
    assert res['status'] == 'failed'
    assert 'wrong direction' in (res['reason'] or '')


def test_exercise_auto_direction_uses_auto_path(tmp_path):
    from hardware.softpot_reader import SoftpotReader
    cfg = {'hardware': {'mode': 'mock'}, 'axis': {'microsteps_per_ml': 10.0, 'syringe_volume_ml': 100.0}, 'flow_calibration': {'position_tolerance_ml': 0.1}, 'safety': {'min_volume_ml': -1.0, 'max_volume_ml': 101.0}}
    stepper = StepperDriver(cfg)
    softpot = SoftpotReader(cfg)

    class PM:
        def __init__(self, s):
            self.s = s
        def voltage_to_volume_ml(self, voltage):
            return (voltage - self.s.mock_min_v) / (self.s.mock_max_v - self.s.mock_min_v) * 100.0

    runner = TrialRunner(cfg, stepper, softpot, FakeFlow(), PM(softpot), lambda: False)
    out = runner.exercise_auto_direction(step_ml=0.5)
    assert out['ok'] is True
    assert out['delta_toward_empty_ml'] < 0
    assert out['delta_toward_full_ml'] > 0


def test_rejected_trials_have_reason_and_exclude_accepted():
    from calibration.flow_calibration_runner import rejected_trials_from_meta

    trials_meta = [
        {'trial_id': 'accepted', 'target_flow_lpm': 0.1, 'status': 'accepted', 'reason': None},
        {'trial_id': 'failed', 'target_flow_lpm': 0.2, 'status': 'failed', 'reason': None},
    ]
    rejected = rejected_trials_from_meta(trials_meta)
    assert [x['trial_id'] for x in rejected] == ['failed']
    assert rejected[0]['reason'] == 'Trial status was failed'


def test_voltage_outlier_repeat_is_rejected_and_removed_from_point():
    from calibration.flow_calibration_runner import reject_voltage_outliers, rejected_trials_from_meta

    trials = [
        {'gas': 'air', 'trial_id': 'rep1', 'target_flow_lpm': 0.5, 'repeat_index': 1, 'status': 'accepted', 'reason': None, 'mean_flow_voltage_v': 1.9949},
        {'gas': 'air', 'trial_id': 'rep2', 'target_flow_lpm': 0.5, 'repeat_index': 2, 'status': 'accepted', 'reason': None, 'mean_flow_voltage_v': 1.9018},
        {'gas': 'air', 'trial_id': 'rep3', 'target_flow_lpm': 0.5, 'repeat_index': 3, 'status': 'accepted', 'reason': None, 'mean_flow_voltage_v': 1.9878},
    ]

    rejected = reject_voltage_outliers(trials, {'max_voltage_deviation_from_median_v': 0.03, 'max_voltage_mad_z': 6.0})

    assert [x['trial_id'] for x in rejected] == ['rep2']
    assert trials[1]['status'] == 'rejected'
    assert trials[1]['reason'] == 'voltage_outlier_for_target'
    assert 'outlier' in trials[1]['reason_detail']
    truthful_rejected = rejected_trials_from_meta(trials)
    assert [x['trial_id'] for x in truthful_rejected] == ['rep2']
    accepted_voltages = [x['mean_flow_voltage_v'] for x in trials if x['status'] == 'accepted']
    assert abs((sum(accepted_voltages) / len(accepted_voltages)) - 1.99135) < 0.00001


def test_curve_reports_weak_points_warnings_and_truthful_counts():
    from analysis.curve_fit import build_piecewise_curve

    curve = build_piecewise_curve(
        'air',
        [{'target_flow_lpm': 0.5, 'mean_actual_flow_lpm': 0.5, 'mean_voltage_v': 1.99135, 'trial_count': 2, 'std_actual_flow_lpm': 0.0, 'std_voltage_v': 0.00355}],
        rejected_trials=[{'trial_id': 'rep2', 'target_flow_lpm': 0.5, 'status': 'rejected', 'reason': 'Mean flow voltage outlier'}],
        weak_points=[{'target_flow_lpm': 0.05, 'mean_actual_flow_lpm': 0.05, 'mean_voltage_v': 0.2, 'trial_count': 1, 'reason': 'Only one accepted trial; excluded from default calibration curve'}],
        excluded_targets=[{'target_flow_lpm': 0.05, 'reason': 'Only one accepted trial; excluded from default calibration curve', 'accepted_trial_count': 1}],
        warnings=[{'type': 'weak_target_point', 'target_flow_lpm': 0.05}],
        accepted_trial_count=3,
    )

    assert curve['fit_quality']['accepted_trial_count'] == 3
    assert curve['fit_quality']['rejected_trial_count'] == 1
    assert curve['weak_points'][0]['target_flow_lpm'] == 0.05
    assert curve['excluded_targets'][0]['target_flow_lpm'] == 0.05
    assert curve['warnings'][0]['type'] == 'weak_target_point'
    assert curve['valid_calibrated_flow_range'] == {'min_lpm': 0.5, 'max_lpm': 0.5}


def test_build_measurement_config_uses_string_per_target_overrides():
    from calibration.flow_calibration_runner import build_measurement_config

    fc = {
        'stroke_start_ml': 100,
        'stroke_end_ml': 0,
        'analysis_min_ml': 10,
        'analysis_max_ml': 90,
        'quality_checks': {'min_sample_count': 10, 'min_stable_duration_s': 1.0},
        'default_measurement': {
            'volume_start_ml': 65,
            'volume_end_ml': 35,
            'analysis_min_ml': 35,
            'analysis_max_ml': 65,
            'min_sample_count': 20,
            'min_stable_duration_s': 1.0,
        },
        'per_target_measurement': {
            '0.1': {
                'volume_start_ml': 60,
                'volume_end_ml': 40,
                'analysis_min_ml': 40,
                'analysis_max_ml': 60,
                'min_sample_count': 100,
                'min_stable_duration_s': 10.0,
            }
        },
    }

    overridden = build_measurement_config(fc, 0.10)
    fallback = build_measurement_config(fc, 0.25)

    assert overridden['volume_start_ml'] == 60
    assert overridden['min_sample_count'] == 100
    assert fallback['volume_start_ml'] == 65
    assert fallback['min_sample_count'] == 20
