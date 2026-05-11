from flask import Blueprint, jsonify, request


def create_api_blueprint(service):
    api_bp = Blueprint('api', __name__)

    @api_bp.get('/status')
    def status():
        return jsonify(service.get_status())

    @api_bp.post('/softpot/start')
    def start_softpot():
        return jsonify(service.start_softpot_calibration())

    @api_bp.post('/softpot/accept')
    def accept_softpot():
        return jsonify(service.accept_softpot_point())

    @api_bp.post('/softpot/save')
    def save_softpot():
        return jsonify(service.save_softpot_calibration())

    @api_bp.post('/jog')
    def jog():
        data = request.get_json(force=True) or {}
        return jsonify(service.jog(data.get('direction'), data.get('amount_type'), data.get('amount')))

    @api_bp.post('/motor/enable')
    def motor_enable():
        return jsonify(service.enable_motor())

    @api_bp.post('/motor/disable')
    def motor_disable():
        return jsonify(service.disable_motor())

    @api_bp.post('/stop')
    def stop():
        return jsonify(service.emergency_stop())

    return api_bp
