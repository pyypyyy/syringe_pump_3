from pathlib import Path
from analysis.steady_state import filter_stable_rows, summarize_trial
from calibration.flow_calibration_runner import FlowCalibrationRunner
from calibration.trial_runner import TrialRunner
from hardware.stepper_driver import StepperDriver
from hardware.softpot_reader import SoftpotReader
from hardware.flow_sensor import FlowSensor


class MockPositionModel:
    def __init__(self, softpot): self.softpot = softpot
    def voltage_to_volume_ml(self, voltage):
        span = self.softpot.mock_max_v - self.softpot.mock_min_v
        frac = (voltage - self.softpot.mock_min_v) / span if span > 0 else 0
        return max(0.0, min(100.0, frac * 100.0))


def test_stable_region_quality_checks():
    assert summarize_trial([])['status'] == 'invalid'
    rows = [{'softpot_volume_ml': 90, 'motion_phase': 'moving', 'elapsed_s': 0, 'flow_voltage_v': 0.5, 'actual_flow_lpm_window': 0.3}, {'softpot_volume_ml': 80, 'motion_phase': 'moving', 'elapsed_s': 2, 'flow_voltage_v': 0.5, 'actual_flow_lpm_window': 0.31}]
    s = summarize_trial(filter_stable_rows(rows, 10, 90))
    assert s['sample_count'] == 2


def test_trial_abort_before_start(tmp_path):
    config = {'hardware': {'mode': 'mock'}, 'axis': {'microsteps_per_ml': 5.0}, 'flow_calibration': {'sample_interval_s': 0.01}}
    stepper = StepperDriver(config); softpot = SoftpotReader(config); flow = FlowSensor(config); pm = MockPositionModel(softpot)
    r = TrialRunner(config, stepper, softpot, flow, pm, lambda: True)
    t = type('T', (), {'stroke_start_ml': 100.0, 'stroke_end_ml': 0.0, 'target_flow_lpm': 0.2, 'trial_id': 't1', 'gas': 'air'})()
    res = r.run_trial(t, tmp_path / 't.csv')
    assert res['status'] == 'aborted'


def test_zero_flow_capture_and_curve_anchor(tmp_path):
    config = {'hardware': {'mode': 'mock'}, 'axis': {'microsteps_per_ml': 5.0, 'syringe_volume_ml': 100.0}, 'flow_calibration': {'sample_interval_s': 0.01, 'settle_before_s': 0.0, 'settle_after_s': 0.0, 'mock_time_scale': 0.03, 'analysis_min_ml': 20, 'analysis_max_ml': 80, 'quality_checks': {'min_stable_samples': 1, 'min_stable_duration_s': 0.0, 'min_nonzero_flow_lpm': 0.0, 'max_flow_cv': 5.0}, 'zero_flow': {'settling_s': 0.0, 'sample_duration_s': 0.05, 'sample_interval_s': 0.01}}}
    stepper = StepperDriver(config); softpot = SoftpotReader(config); flow = FlowSensor(config); pm = MockPositionModel(softpot)
    runner = FlowCalibrationRunner(config, stepper, softpot, flow, pm, lambda **k: None, lambda: False)
    res = runner.run('air', [0.2], 1, 100.0, 0.0, 20, 80)
    curve = __import__('json').loads((Path(res['run_dir']) / 'calibration_curve.json').read_text())
    assert curve['zero_flow']['sample_count'] > 1
    assert any(p.get('zero_flow_anchor') for p in curve['points'])
