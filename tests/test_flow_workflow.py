from analysis.steady_state import filter_stable_rows, compute_actual_flow_lpm
from calibration.calibration_plan import CalibrationPlan
from analysis.curve_fit import build_piecewise_curve


def test_calibration_plan_trials():
    trials = CalibrationPlan.build('air', [0.1, 0.2], 2, 100, 0)
    assert len(trials) == 4
    assert 'air_0.100_LPM_rep1' in [t.trial_id for t in trials]


def test_stable_region_and_actual_flow():
    rows = [
        {'softpot_volume_ml': 95, 'motion_phase': 'constant', 'elapsed_s': 0, 'flow_voltage_v': 0.5},
        {'softpot_volume_ml': 90, 'motion_phase': 'constant', 'elapsed_s': 1, 'flow_voltage_v': 0.5},
        {'softpot_volume_ml': 10, 'motion_phase': 'constant', 'elapsed_s': 9, 'flow_voltage_v': 0.6},
        {'softpot_volume_ml': 5, 'motion_phase': 'constant', 'elapsed_s': 10, 'flow_voltage_v': 0.6},
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
