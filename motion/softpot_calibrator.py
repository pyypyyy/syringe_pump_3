import json, statistics, time
from datetime import datetime
from pathlib import Path
from motion.softpot_position import SoftpotPoint, SoftpotPosition


class SoftpotCalibrator:
    def __init__(self, config, softpot_reader):
        self.config = config
        self.softpot_reader = softpot_reader
        self.points = []
        self.current_index = 0
        self.targets = [float(x) for x in config.get('softpot', {}).get('calibration_points_ml', [100,75,50,25,0])]

    @property
    def current_target(self):
        return None if self.current_index >= len(self.targets) else self.targets[self.current_index]

    def reset(self):
        self.points = []
        self.current_index = 0

    def sample_current_point(self):
        cfg = self.config.get('softpot', {})
        duration_s = float(cfg.get('sample_duration_s', 1.5))
        interval_s = float(cfg.get('sample_interval_s', 0.02))
        target = self.current_target
        if target is None:
            raise RuntimeError('No current calibration target.')
        samples = []
        deadline = time.time() + duration_s
        while time.time() < deadline:
            samples.append(float(self.softpot_reader.read_voltage()))
            time.sleep(interval_s)
        if not samples:
            raise RuntimeError('No softpot samples collected.')
        return SoftpotPoint(target, statistics.median(samples), statistics.pstdev(samples) if len(samples) > 1 else 0.0)

    def accept_current_point(self):
        point = self.sample_current_point()
        max_std = float(self.config.get('softpot', {}).get('max_point_std_v', 0.03))
        warning = f'Point noise high: std={point.std_v:.5f} V' if point.std_v > max_std else None
        self.points.append(point)
        self.current_index += 1
        return {'ok': True, 'warning': warning, 'point': point.__dict__, 'complete': self.current_index >= len(self.targets), 'next_target': self.current_target}

    def validate(self):
        if len(self.points) < 2:
            return False, 'Too few calibration points.'
        voltages = [p.voltage_v for p in self.points]
        span = max(voltages) - min(voltages)
        if span < float(self.config.get('softpot', {}).get('min_voltage_span_v', 0.5)):
            return False, f'Voltage span too small: {span:.4f} V'
        sorted_by_volume = sorted(self.points, key=lambda p: p.volume_ml)
        v = [p.voltage_v for p in sorted_by_volume]
        increasing = all(a < b for a, b in zip(v[:-1], v[1:]))
        decreasing = all(a > b for a, b in zip(v[:-1], v[1:]))
        if not (increasing or decreasing):
            return False, 'Calibration points are not monotonic.'
        return True, 'OK'

    def save(self):
        valid, message = self.validate()
        if not valid:
            return {'ok': False, 'error': message}
        out_dir = Path('output/softpot')
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"softpot_calibration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        data = {'created_at': datetime.now().isoformat(timespec='seconds'), 'method': 'piecewise_linear', 'points': [p.__dict__ for p in self.points]}
        path.write_text(json.dumps(data, indent=2), encoding='utf-8')
        return {'ok': True, 'path': str(path), 'points': data['points']}

    def make_position_model(self):
        return SoftpotPosition(self.points)
