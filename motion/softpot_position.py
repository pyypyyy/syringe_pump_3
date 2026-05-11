from dataclasses import dataclass


@dataclass
class SoftpotPoint:
    volume_ml: float
    voltage_v: float
    std_v: float = 0.0


class SoftpotPosition:
    def __init__(self, points):
        if len(points) < 2:
            raise ValueError('At least two softpot calibration points are required.')
        self.points = sorted(points, key=lambda p: p.voltage_v)

    def voltage_to_volume_ml(self, voltage):
        pts = self.points
        if voltage <= pts[0].voltage_v:
            return pts[0].volume_ml
        if voltage >= pts[-1].voltage_v:
            return pts[-1].volume_ml
        for left, right in zip(pts[:-1], pts[1:]):
            if left.voltage_v <= voltage <= right.voltage_v:
                span = right.voltage_v - left.voltage_v
                if abs(span) < 1e-9:
                    return left.volume_ml
                frac = (voltage - left.voltage_v) / span
                return left.volume_ml + frac * (right.volume_ml - left.volume_ml)
        return pts[-1].volume_ml
