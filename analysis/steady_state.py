
def filter_stable_rows(rows, min_ml, max_ml):
    return [
        r for r in rows
        if min_ml <= float(r['softpot_volume_ml']) <= max_ml and r.get('motion_phase') == 'constant'
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
            'sample_count': 0,
        }
    vs = [float(r['flow_voltage_v']) for r in rows]
    mean_v = sum(vs) / len(vs)
    var = sum((v - mean_v) ** 2 for v in vs) / len(vs)
    return {
        'mean_flow_voltage_v': mean_v,
        'std_flow_voltage_v': var ** 0.5,
        'actual_flow_lpm': compute_actual_flow_lpm(rows),
        'sample_count': len(rows),
    }
