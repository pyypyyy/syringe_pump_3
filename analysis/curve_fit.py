from datetime import datetime, timezone


def _stddev(values):
    if not values:
        return None
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5


def build_piecewise_curve(gas, accepted_points, zero_flow=None, rejected_trials=None, source_run_dir=None):
    points = sorted(accepted_points, key=lambda s: float(s['mean_voltage_v']))
    fit_rows = []
    for p in points:
        fit_rows.append((p['mean_voltage_v'], p.get('mean_actual_flow_lpm', p.get('actual_flow_lpm', 0.0))))
    target_deltas = []
    voltage_stds = []
    actual_stds = []
    point_repeatability = []
    accepted_trials = 0
    for p in points:
        target = p.get('target_flow_lpm')
        actual = p.get('mean_actual_flow_lpm', p.get('actual_flow_lpm'))
        std_actual = p.get('std_actual_flow_lpm')
        std_voltage = p.get('std_voltage_v')
        trial_count = int(p.get('trial_count') or 0)
        if target is not None and actual is not None:
            target_deltas.append(float(actual) - float(target))
        if std_voltage is not None:
            voltage_stds.append(float(std_voltage))
        if std_actual is not None:
            actual_stds.append(float(std_actual))
        if trial_count > 0:
            accepted_trials += trial_count
        if std_actual is not None and actual not in (None, 0):
            cv = abs(float(std_actual) / float(actual)) if float(actual) != 0 else None
            point_repeatability.append({'target_flow_lpm': target, 'cv_actual_flow': cv, 'trial_count': trial_count})

    rejected = rejected_trials or []
    return {
        'gas': gas,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'zero_flow': zero_flow or {},
        'model': {
            'type': 'piecewise_linear' if points else 'incomplete',
            'x': 'flow_voltage_v',
            'y': 'actual_flow_lpm',
            'points': points,
        },
        'fit_quality': {
            'note': 'Interpolation-anchor residual metrics (RMSE/MAE/max_abs_error) intentionally omitted.',
            'accepted_point_count': len(points),
            'accepted_trial_count': accepted_trials,
            'rejected_trial_count': len(rejected),
            'target_vs_actual': {
                'mean_delta_lpm': (sum(target_deltas) / len(target_deltas)) if target_deltas else None,
                'std_delta_lpm': _stddev(target_deltas),
                'max_abs_delta_lpm': max((abs(d) for d in target_deltas), default=None),
            },
            'repeatability': {
                'mean_std_voltage_v': (sum(voltage_stds) / len(voltage_stds)) if voltage_stds else None,
                'mean_std_actual_flow_lpm': (sum(actual_stds) / len(actual_stds)) if actual_stds else None,
                'per_target': point_repeatability,
            },
        },
        'rejected_trials': rejected,
        'source_run_dir': source_run_dir,
        'usable': len(points) >= 2,
    }
