from flask import Flask
from core.config import load_config
from core.calibration_service import CalibrationService
from web.routes import web_bp
from web.api import create_api_blueprint


def create_app():
    config = load_config('config.yaml')
    service = CalibrationService(config)
    app = Flask(__name__, template_folder='web/templates', static_folder='web/static')
    app.config['SERVICE'] = service
    app.register_blueprint(web_bp)
    app.register_blueprint(create_api_blueprint(service), url_prefix='/api')
    return app


if __name__ == '__main__':
    cfg = load_config('config.yaml')
    app = create_app()
    app.run(
        host=cfg.get('server', {}).get('host', '0.0.0.0'),
        port=int(cfg.get('server', {}).get('port', 5000)),
        debug=bool(cfg.get('server', {}).get('debug', True)),
    )
