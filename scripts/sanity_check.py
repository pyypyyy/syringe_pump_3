from pathlib import Path
import py_compile, sys
ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    'app.py':['from flask import Flask','def create_app'],
    'requirements.txt':['Flask','PyYAML'],
    'web/routes.py':['Blueprint','render_template'],
    'web/api.py':['create_api_blueprint','@api_bp.get'],
    'web/static/style.css':[':root','.topbar'],
    'web/static/monitor.js':['async function updateStatus','fetch'],
    'web/templates/base.html':['<!doctype html>','{% block content %}'],
    'web/templates/index.html':['{% extends','Tapahtumaloki'],
    'web/templates/softpot.html':['Jog-ohjaus','Softpot-kalibrointi'],
}
def main():
    for rel, needles in EXPECTED.items():
        text = (ROOT/rel).read_text(encoding='utf-8')
        for n in needles:
            if n not in text: raise AssertionError(f'{rel} missing {n}')
    for py in ROOT.rglob('*.py'):
        if '.venv' not in py.parts:
            py_compile.compile(str(py), doraise=True)
    print('Sanity check OK: file mapping and Python syntax look correct.')
if __name__ == '__main__':
    try: main()
    except Exception as e:
        print(f'Sanity check FAILED: {e}', file=sys.stderr); raise
