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


def test_flow_start_accepts_air(client):
    client.application.config['SERVICE'].position_model = type('M', (), {'voltage_to_volume_ml': lambda self, v: 50.0})()
    resp = client.post('/api/flow/start', json={'gas':'air','flows_lpm':[0.02],'repeats':1})
    assert resp.status_code == 200


def test_flow_start_accepts_co2(client):
    client.application.config['SERVICE'].position_model = type('M', (), {'voltage_to_volume_ml': lambda self, v: 50.0})()
    resp = client.post('/api/flow/start', json={'gas':'co2','flows_lpm':[0.02],'repeats':1})
    assert resp.status_code == 200


def test_flow_start_rejects_invalid_gas(client):
    client.application.config['SERVICE'].position_model = type('M', (), {'voltage_to_volume_ml': lambda self, v: 50.0})()
    resp = client.post('/api/flow/start', json={'gas':'n2'})
    assert resp.status_code == 400


def test_flow_start_rejects_invalid_payloads(client):
    client.application.config['SERVICE'].position_model = type('M', (), {'voltage_to_volume_ml': lambda self, v: 50.0})()
    bad_payloads = [
        {'gas': 'air', 'flows_lpm': []},
        {'gas': 'air', 'flows_lpm': [0.1], 'repeats': 0},
        {'gas': 'air', 'flows_lpm': [0.1], 'analysis_min_ml': 80, 'analysis_max_ml': 20},
        {'gas': 'air', 'flows_lpm': [0.1], 'stroke_start_ml': 100, 'stroke_end_ml': 0, 'analysis_min_ml': -1, 'analysis_max_ml': 20},
    ]
    for payload in bad_payloads:
        resp = client.post('/api/flow/start', json=payload)
        assert resp.status_code == 400


def test_flow_stop_and_status(client):
    resp = client.post('/api/flow/stop', json={})
    assert resp.status_code == 200
    st = client.get('/api/flow/status').get_json()
    assert 'running' in st


def test_flow_failed_motion_sets_error_and_not_running(client, monkeypatch):
    svc = client.application.config['SERVICE']
    svc.position_model = type('M', (), {'voltage_to_volume_ml': lambda self, v: 50.0})()
    from calibration.flow_calibration_runner import FlowCalibrationRunner
    def boom(*args, **kwargs):
        raise RuntimeError('motion failed')
    monkeypatch.setattr(FlowCalibrationRunner, 'run', boom)
    resp = client.post('/api/flow/start', json={'gas':'air','flows_lpm':[0.02],'repeats':1})
    assert resp.status_code == 200
    import time
    time.sleep(0.05)
    st = client.get('/api/flow/status').get_json()
    assert st['running'] is False
    assert 'motion failed' in (st.get('error') or '')
