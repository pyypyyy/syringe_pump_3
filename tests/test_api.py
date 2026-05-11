import shutil
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    root = ROOT
    for name in ['app.py', 'core', 'hardware', 'motion', 'web']:
        src = root / name
        dst = tmp_path / name
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    config_src = root / 'config.yaml'
    text = config_src.read_text(encoding='utf-8')
    text += "\nstorage:\n  flow_points_path: data/test_flow_points.json\n"
    (tmp_path / 'config.yaml').write_text(text, encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_status_endpoint(client):
    resp = client.get('/api/status')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'flow_lpm' in data


def test_capture_validation(client):
    resp = client.post('/api/flow-calibration/capture', json={'gas': 'n2', 'expected_flow_lpm': 0.2})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data['ok'] is False


def test_capture_and_csv(client):
    resp = client.post('/api/flow-calibration/capture', json={'gas': 'air', 'expected_flow_lpm': 0.2})
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True
    csv_resp = client.get('/api/flow-calibration/csv')
    assert csv_resp.status_code == 200
    body = csv_resp.data.decode('utf-8')
    assert 'gas,expected_flow_lpm,measured_voltage_v,estimated_flow_lpm,timestamp' in body


def test_jog_validation(client):
    resp = client.post('/api/jog', json={'direction': 'bad', 'amount_type': 'ml', 'amount': 1})
    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False


def test_flow_start_requires_softpot(client):
    resp = client.post('/api/flow/start', json={'gas': 'air'})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data['ok'] is False
    assert 'Softpot must be calibrated' in data['error']
