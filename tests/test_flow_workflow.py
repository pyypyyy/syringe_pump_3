from pathlib import Path

from analysis.steady_state import filter_stable_rows, compute_actual_flow_lpm
from calibration.calibration_plan import CalibrationPlan
from analysis.curve_fit import build_piecewise_curve
from calibration.flow_calibration_runner import FlowCalibrationRunner
from hardware.stepper_driver import StepperDriver
from hardware.softpot_reader import SoftpotReader
from hardware.flow_sensor import FlowSensor


class MockPositionModel:
    def __init__(self, softpot):
        self.softpot = softpot

    def voltage_to_volume_ml(self, voltage):
        span = self.softpot.mock_max_v - self.softpot.mock_min_v
        if span <= 0:
            return 0.0
        frac = (voltage - self.softpot.mock_min_v) / span
        return max(0.0, min(100.0, frac * 100.0))


def test_calibration_plan_trials():
    trials = CalibrationPlan.build('air', [0.1, 0.2], 2, 100, 0)
    assert len(trials) == 4
    assert 'air_0.100_LPM_rep1' in [t.trial_id for t in trials]


def test_stable_region_and_actual_flow():
    rows = [
        {'softpot_volume_ml': 95, 'motion_phase': 'moving', 'elapsed_s': 0, 'flow_voltage_v': 0.5, 'actual_flow_lpm_window': 0.0},
        {'softpot_volume_ml': 90, 'motion_phase': 'moving', 'elapsed_s': 1, 'flow_voltage_v': 0.5, 'actual_flow_lpm_window': 0.3},
        {'softpot_volume_ml': 10, 'motion_phase': 'moving', 'elapsed_s': 9, 'flow_voltage_v': 0.6, 'actual_flow_lpm_window': 0.31},
        {'softpot_volume_ml': 5, 'motion_phase': 'moving', 'elapsed_s': 10, 'flow_voltage_v': 0.6, 'actual_flow_lpm_window': 0.0},
    ]
    stable = filter_stable_rows(rows, 10, 90)
    assert len(stable) == 2
    flow = compute_actual_flow_lpm(stable)
    assert flow > 0


def test_curve_uses_actual_flow():
    curve = build_piecewise_curve('air', [
        {'target_flow_lpm': 0.1, 'actual_flow_lpm': 0.12, 'mean_voltage_v': 0.5, 'std_voltage_v': 0.01, 'repeat_count': 1}
    ])
    assert curve['method'] == 'piecewise_linear'
    assert curve['points'][0]['actual_flow_lpm'] == 0.12


def test_mock_workflow_refill_and_actual_window(tmp_path):
    config = {
        'hardware': {'mode': 'mock'},
        'axis': {'microsteps_per_ml': 5.0, 'syringe_volume_ml': 100.0, 'safety_min_ml': 0.0, 'safety_max_ml': 100.0},
        'flow_calibration': {'sample_interval_s': 0.01, 'settle_before_s': 0.0, 'settle_after_s': 0.0, 'mock_time_scale': 0.05, 'analysis_min_ml': 10, 'analysis_max_ml': 90},
    }
    stepper = StepperDriver(config)
    softpot = SoftpotReader(config)
    flow_sensor = FlowSensor(config)
    pm = MockPositionModel(softpot)
    statuses = {}

    runner = FlowCalibrationRunner(config, stepper, softpot, flow_sensor, pm, lambda **k: statuses.update(k), lambda: False)
    result = runner.run('air', [0.2], 2, 100.0, 0.0, 20, 80)
    assert result['ok'] is True
    run_dir = Path(result['run_dir'])
    raw_files = sorted(run_dir.glob('*.csv'))
    assert raw_files
    raw_text = raw_files[0].read_text(encoding='utf-8')
    assert 'actual_flow_lpm_window' in raw_text
    summary = (run_dir / 'summary.csv').read_text(encoding='utf-8')
    assert 'actual_flow_lpm' in summary
    assert any(float(line.split(',')[4]) > 0 for line in summary.splitlines()[1:])
    assert abs(softpot.mock_volume_ml - 100.0) <= 1.0
    assert statuses.get('analysis_min_ml') == 20.0
    assert statuses.get('analysis_max_ml') == 80.0
