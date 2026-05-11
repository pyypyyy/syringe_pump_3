def filter_stable_rows(rows, min_ml, max_ml):
    return [
        r for r in rows
        if ('motion_phase' not in r or r.get('motion_phase') == 'moving')
        and min_ml <= float(r['softpot_volume_ml']) <= max_ml
    ]


def summarize_trial(rows):
    if not rows:
        return {'status': 'invalid', 'reason': 'Stable region is empty', 'sample_count': 0}
    vs = [float(r['flow_voltage_v']) for r in rows]
    actuals = [float(r.get('actual_flow_lpm_window', 0.0)) for r in rows]
    ts = [float(r.get('elapsed_s', 0.0)) for r in rows]
    vols = [float(r.get('softpot_volume_ml', 0.0)) for r in rows]
    mean_v = sum(vs) / len(vs)
    mean_a = sum(actuals) / len(actuals)
    std_v = (sum((v - mean_v) ** 2 for v in vs) / len(vs)) ** 0.5
    std_a = (sum((a - mean_a) ** 2 for a in actuals) / len(actuals)) ** 0.5
    duration = max(ts) - min(ts) if len(ts) > 1 else 0.0
    actual_flow = abs(vols[-1] - vols[0]) / max(duration, 1e-9) * 60.0 / 1000.0
    cv = std_a / mean_a if mean_a > 1e-9 else 999.0
    return {
        'status': 'completed', 'reason': None, 'sample_count': len(rows), 'stable_duration_s': duration,
        'mean_flow_voltage_v': mean_v, 'std_flow_voltage_v': std_v, 'actual_flow_lpm': actual_flow,
        'std_actual_flow_lpm': std_a, 'flow_cv': cv, 'volume_start_ml': vols[0], 'volume_end_ml': vols[-1],
    }
