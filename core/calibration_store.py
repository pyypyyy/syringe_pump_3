from pathlib import Path
import json
import os


class FlowCalibrationStore:
    def __init__(self, path):
        self.path = Path(path)

    def load_points(self):
        if not self.path.exists():
            return []
        with self.path.open('r', encoding='utf-8') as f:
            data = json.load(f)
        points = data.get('points', [])
        return points if isinstance(points, list) else []

    def save_points(self, points):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + '.tmp')
        payload = {'version': 1, 'points': points}
        with tmp_path.open('w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)
