from datetime import datetime, timezone


def build_piecewise_curve(gas, summaries):
    points = sorted(summaries, key=lambda s: float(s['mean_voltage_v']))
    return {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'gas': gas,
        'method': 'piecewise_linear',
        'points': points,
    }
