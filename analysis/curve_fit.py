from datetime import datetime, timezone


def build_piecewise_curve(gas, accepted_points, zero_flow=None, rejected_trials=None, source_run_dir=None):
    points = sorted(accepted_points, key=lambda s: float(s['mean_voltage_v']))
    fit_rows = []
    for p in points:
        fit_rows.append((p['mean_voltage_v'], p.get('mean_actual_flow_lpm', p.get('actual_flow_lpm', 0.0))))
    errs = []
    for x, y in fit_rows:
        pred = y
        errs.append(abs(pred - y))
    rmse = (sum(e * e for e in errs) / len(errs)) ** 0.5 if errs else None
    mae = (sum(errs) / len(errs)) if errs else None
    max_abs = max(errs) if errs else None
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
        'fit_quality': {'rmse_lpm': rmse, 'mae_lpm': mae, 'max_abs_error_lpm': max_abs},
        'rejected_trials': rejected_trials or [],
        'source_run_dir': source_run_dir,
        'usable': len(points) >= 2,
    }
