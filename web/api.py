from flask import Blueprint, jsonify, request, Response


def create_api_blueprint(service):
    api_bp = Blueprint('api', __name__)

    def error(message, status=400):
        return jsonify({'ok': False, 'error': message}), status

    def parse_json():
        if not request.is_json:
            return None, error('Request must be JSON')
        return request.get_json(silent=True) or {}, None

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
        data, err = parse_json()
        if err:
            return err
        direction = data.get('direction')
        amount_type = data.get('amount_type')
        amount = data.get('amount')
        if direction not in ('toward_empty', 'toward_full'):
            return error("direction must be 'toward_empty' or 'toward_full'")
        if amount_type not in ('ml', 'steps'):
            return error("amount_type must be 'ml' or 'steps'")
        if amount is None:
            return error('amount is required')
        return jsonify(service.jog(direction, amount_type, amount))

    @api_bp.post('/motor/enable')
    def motor_enable():
        return jsonify(service.enable_motor())

    @api_bp.post('/motor/disable')
    def motor_disable():
        return jsonify(service.disable_motor())

    @api_bp.post('/stop')
    def stop():
        return jsonify(service.emergency_stop())


    @api_bp.post('/flow/start')
    def flow_start():
        data, err = parse_json()
        if err:
            return err
        res = service.start_flow_calibration(data)
        return jsonify(res), (200 if res.get('ok') else 400)

    @api_bp.post('/flow/stop')
    def flow_stop():
        return jsonify(service.stop_flow_calibration())

    @api_bp.get('/flow/status')
    def flow_status():
        st = service.get_status()
        keys = ['running','gas','current_trial','completed_trials','total_trials','current_target_flow_lpm','latest_softpot_volume_ml','latest_flow_voltage_v','run_dir']
        return jsonify({k: st.get(k) for k in keys})

    @api_bp.get('/flow/results')
    def flow_results():
        return jsonify(service.flow_results())

    @api_bp.post('/flow-calibration/capture')
    def flow_calibration_capture():
        data, err = parse_json()
        if err:
            return err
        gas = data.get('gas')
        expected = data.get('expected_flow_lpm')
        if gas not in ('air', 'co2'):
            return error("gas must be 'air' or 'co2'")
        if expected is None:
            return error('expected_flow_lpm is required')
        try:
            expected = float(expected)
        except (TypeError, ValueError):
            return error('expected_flow_lpm must be numeric')
        return jsonify(service.add_flow_calibration_point(gas, expected))

    @api_bp.post('/flow-calibration/reset')
    def flow_calibration_reset():
        return jsonify(service.reset_flow_calibration_points())

    @api_bp.get('/flow-calibration/csv')
    def flow_calibration_csv():
        csv_data = service.flow_calibration_csv()
        return Response(
            csv_data,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=flow_calibration_points.csv'},
        )

    return api_bp
