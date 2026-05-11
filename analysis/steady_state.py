def filter_stable_rows(rows, min_ml, max_ml):
    candidates = [
        r for r in rows
        if min_ml <= float(r['softpot_volume_ml']) <= max_ml
    ]
    flows = [float(r.get('actual_flow_lpm_window', 0.0)) for r in candidates if float(r.get('actual_flow_lpm_window', 0.0)) > 0]
    if not flows:
        return []
    sorted_flows = sorted(flows)
    median = sorted_flows[len(sorted_flows) // 2]
    tolerance = max(0.002, 0.35 * median)
    return [
        r for r in candidates
        if float(r.get('actual_flow_lpm_window', 0.0)) > 0 and abs(float(r.get('actual_flow_lpm_window', 0.0)) - median) <= tolerance
    ]


def compute_actual_flow_lpm(rows):
    if len(rows) < 2:
        return 0.0
    start = rows[0]
    end = rows[-1]
    dv = abs(float(end['softpot_volume_ml']) - float(start['softpot_volume_ml']))
    dt = abs(float(end['elapsed_s']) - float(start['elapsed_s']))
    if dt <= 1e-9:
        return 0.0
    return dv / dt * 60.0 / 1000.0


def summarize_trial(rows):
    if not rows:
        return {
            'mean_flow_voltage_v': 0.0,
            'std_flow_voltage_v': 0.0,
            'actual_flow_lpm': 0.0,
            'std_actual_flow_lpm': 0.0,
            'sample_count': 0,
        }
    vs = [float(r['flow_voltage_v']) for r in rows]
    actuals = [float(r.get('actual_flow_lpm_window', 0.0)) for r in rows]
    mean_v = sum(vs) / len(vs)
    var_v = sum((v - mean_v) ** 2 for v in vs) / len(vs)
    mean_a = sum(actuals) / len(actuals)
    var_a = sum((a - mean_a) ** 2 for a in actuals) / len(actuals)
    return {
        'mean_flow_voltage_v': mean_v,
        'std_flow_voltage_v': var_v ** 0.5,
        'actual_flow_lpm': mean_a,
        'std_actual_flow_lpm': var_a ** 0.5,
        'sample_count': len(rows),
    }
