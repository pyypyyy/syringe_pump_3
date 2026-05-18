from hardware.ads1115_reader import ADS1115Reader
from hardware.flow_sensor import FlowSensor
from hardware.softpot_reader import SoftpotReader
from hardware.stepper_driver import StepperDriver
from motion.jog_controller import JogController
from motion.softpot_calibrator import SoftpotCalibrator
from core.calibration_store import FlowCalibrationStore
from calibration.flow_calibration_runner import FlowCalibrationRunner
from calibration.trial_runner import TrialRunner
from datetime import datetime, timezone
from pathlib import Path
import json
import csv
import io
import threading
import numbers


class CalibrationService:
    def __init__(self, config):
        self.config = config
        self.ads = ADS1115Reader(config)
        self.softpot = SoftpotReader(config, self.ads)
        self.flow_sensor = FlowSensor(config, self.ads)
        self.stepper = StepperDriver(config)
        self.jogger = JogController(config, self.stepper, self.softpot)
        self.softpot_calibrator = SoftpotCalibrator(config, self.softpot)
        self.position_model = None
        self.mode = 'idle'
        self.last_event = 'Application started'
        self.events = [self.last_event]
        self.flow_run_status = {
            'running': False, 'result': None, 'error': None, 'phase': 'idle', 'last_failure_reason': None,
            'raw_softpot_voltage': None, 'raw_softpot_volume_ml': None, 'filtered_softpot_volume_ml': None,
            'softpot_glitch_count': 0, 'last_rejected_softpot_sample': None, 'softpot_signal_unstable': False,
        }
        self.flow_stop_requested = False
        self._flow_thread = None
        storage_cfg = config.get('storage', {})
        points_path = storage_cfg.get('flow_points_path', 'data/flow_calibration_points.json')
        self.flow_store = FlowCalibrationStore(points_path)
        self.flow_calibration_points = self._safe_load_flow_points()
        self.zero_flow_capture_by_gas = {}
        self._load_latest_softpot_calibration()


    def _read_environment(self):
        bme = self.config.get('bme280', {})
        if not bme.get('enabled'):
            return {'temperature_c': None, 'ambient_pressure_hpa': None, 'relative_humidity_percent': None}
        return {'temperature_c': None, 'ambient_pressure_hpa': None, 'relative_humidity_percent': None}

    def _load_latest_softpot_calibration(self):
        out_dir = Path('output/softpot')
        if not out_dir.exists():
            self.log('No valid softpot calibration loaded. Please calibrate softpot before automatic flow calibration.')
            return
        files = sorted(out_dir.glob('softpot_calibration_*.json'), reverse=True)
        for fp in files:
            try:
                data = json.loads(fp.read_text(encoding='utf-8'))
                pts = data.get('points', [])
                if len(pts) < 2:
                    continue
                self.softpot_calibrator.points = [self._dict_to_point(p) for p in pts if 'volume_ml' in p and 'voltage_v' in p]
                self.position_model = self.softpot_calibrator.make_position_model()
                self.log(f'Softpot calibration loaded: {fp.name}')
                return
            except Exception:
                continue
        self.log('No valid softpot calibration loaded. Please calibrate softpot before automatic flow calibration.')

    def _dict_to_point(self, point):
        from motion.softpot_position import SoftpotPoint
        return SoftpotPoint(float(point['volume_ml']), float(point['voltage_v']), float(point.get('std_v', 0.0)))

    def capture_zero_flow(self, gas):
        if gas not in ('air', 'co2'):
            return {'ok': False, 'error': "gas must be 'air' or 'co2'"}
        runner = FlowCalibrationRunner(self.config, self.stepper, self.softpot, self.flow_sensor, self.position_model, self._set_flow_status, self._is_stop_requested, self._read_environment)
        cap = runner.capture_zero_flow(gas)
        self.zero_flow_capture_by_gas[gas] = cap
        return {'ok': True, 'zero_flow': cap}
    def _safe_load_flow_points(self):
        try: return self.flow_store.load_points()
        except Exception as e: self.log(f'Failed to load persisted flow calibration points: {e}'); return []
    def _safe_save_flow_points(self):
        try: self.flow_store.save_points(self.flow_calibration_points)
        except Exception as e: self.log(f'Failed to persist flow calibration points: {e}')
    def log(self, message): self.last_event = message; self.events.append(message); self.events = self.events[-20:]
    def _set_flow_status(self, **kwargs): self.flow_run_status.update(kwargs)
    def _is_stop_requested(self): return self.flow_stop_requested or self.stepper.stop_requested

    def get_status(self):
        softpot_voltage = self.softpot.read_voltage(); softpot_volume = self.position_model.voltage_to_volume_ml(softpot_voltage) if self.position_model else None
        flow_voltage = self.flow_sensor.read_voltage()
        return {'mode': self.mode,'softpot_voltage_v': softpot_voltage,'softpot_volume_ml': softpot_volume,'flow_voltage_v': flow_voltage,'flow_lpm': self.flow_sensor.estimate_flow_lpm(flow_voltage),'motor_enabled': self.stepper.enabled,'step_position': self.stepper.step_position,'step_position_valid': self.stepper.step_position_valid,'current_target_ml': self.softpot_calibrator.current_target,'calibration_points': [p.__dict__ for p in self.softpot_calibrator.points],'calibration_targets': self.softpot_calibrator.targets,'last_event': self.last_event,'events': list(reversed(self.events)),'flow_calibration_points': list(reversed(self.flow_calibration_points)),'flow_calibration': self.flow_run_status,'zero_flow_capture_by_gas': self.zero_flow_capture_by_gas,'raw_softpot_voltage': self.flow_run_status.get('raw_softpot_voltage', softpot_voltage),'raw_softpot_volume_ml': self.flow_run_status.get('raw_softpot_volume_ml', softpot_volume),'filtered_softpot_volume_ml': self.flow_run_status.get('filtered_softpot_volume_ml', softpot_volume),'softpot_glitch_count': self.flow_run_status.get('softpot_glitch_count', 0),'last_rejected_softpot_sample': self.flow_run_status.get('last_rejected_softpot_sample'),'softpot_signal_unstable': self.flow_run_status.get('softpot_signal_unstable', False),**self.flow_run_status}

    def start_flow_calibration(self, payload):
        if self.position_model is None: return {'ok': False, 'error': 'Softpot must be calibrated before flow calibration.'}
        if self.flow_run_status.get('running'): return {'ok': False, 'error': 'Flow calibration already running.'}
        gas = str(payload.get('gas', self.config.get('flow_calibration', {}).get('default_gas', 'air'))).lower()
        if gas not in ('air', 'co2'): return {'ok': False, 'error': "gas must be 'air' or 'co2'"}
        if gas not in self.zero_flow_capture_by_gas: return {'ok': False, 'error': 'Capture zero-flow before automatic calibration.'}
        fc = self.config.get('flow_calibration', {})
        flows_lpm = payload.get('flows_lpm', fc.get('flows_lpm', [0.02, 0.05]))
        repeats = int(payload.get('repeats', fc.get('repeats', 3)))
        stroke_start_ml = float(payload.get('stroke_start_ml', fc.get('stroke_start_ml', 100.0)))
        stroke_end_ml = float(payload.get('stroke_end_ml', fc.get('stroke_end_ml', 0.0)))
        analysis_min_ml = float(payload.get('analysis_min_ml', fc.get('analysis_min_ml', 10.0)))
        analysis_max_ml = float(payload.get('analysis_max_ml', fc.get('analysis_max_ml', 90.0)))
        safety = self.config.get('safety', {})
        min_safe = float(safety.get('min_volume_ml', 0.0))
        max_safe = float(safety.get('max_volume_ml', self.config.get('axis', {}).get('syringe_volume_ml', 100.0)))

        if not isinstance(flows_lpm, list) or not flows_lpm:
            return {'ok': False, 'error': 'flows_lpm must be a non-empty list of positive numbers'}
        if any((not isinstance(v, numbers.Number)) or float(v) <= 0 for v in flows_lpm):
            return {'ok': False, 'error': 'flows_lpm must be a non-empty list of positive numbers'}
        if repeats < 1:
            return {'ok': False, 'error': 'repeats must be >= 1'}
        if not (min_safe <= stroke_start_ml <= max_safe) or not (min_safe <= stroke_end_ml <= max_safe):
            return {'ok': False, 'error': 'stroke_start_ml and stroke_end_ml must be inside configured safety limits'}
        if analysis_min_ml >= analysis_max_ml:
            return {'ok': False, 'error': 'analysis_min_ml must be less than analysis_max_ml'}
        stroke_low, stroke_high = sorted([stroke_start_ml, stroke_end_ml])
        if not (stroke_low <= analysis_min_ml <= stroke_high and stroke_low <= analysis_max_ml <= stroke_high):
            return {'ok': False, 'error': 'analysis range must lie between stroke_start_ml and stroke_end_ml'}
        self.flow_stop_requested = False
        self.stepper.clear_stop()
        runner = FlowCalibrationRunner(self.config, self.stepper, self.softpot, self.flow_sensor, self.position_model, self._set_flow_status, self._is_stop_requested, self._read_environment)

        def _run():
            self.mode = 'flow_calibration'; self._set_flow_status(running=True, error=None, phase='moving_to_start', last_failure_reason=None)
            try:
                result = runner.run(gas, flows_lpm, repeats, stroke_start_ml, stroke_end_ml, analysis_min_ml, analysis_max_ml, self.zero_flow_capture_by_gas.get(gas))
                self._set_flow_status(
                    running=False,
                    result=result,
                    run_dir=result.get('run_dir'),
                    error=None,
                )
                self.log(f"Flow calibration completed for {gas}: {result['run_id']}")
            except Exception as exc:
                self._set_flow_status(error=str(exc), phase='failed', last_failure_reason=f'backend exception: {exc}')
                self.mode = 'error'
                self.log(f'Flow calibration failed: {exc}')
            finally:
                self._set_flow_status(running=False)
                if self.mode == 'flow_calibration': self.mode = 'idle'; self._set_flow_status(phase='idle')

        self._set_flow_status(running=True, gas=gas, current_trial=None, completed_trials=0, total_trials=len(flows_lpm) * repeats, current_target_flow_lpm=None, latest_softpot_volume_ml=None, latest_flow_voltage_v=None, run_dir=None, result=None, error=None, phase='starting', last_failure_reason=None)
        self._flow_thread = threading.Thread(target=_run, daemon=True); self._flow_thread.start()
        return {'ok': True, 'run_id': 'starting', 'trial_count': len(flows_lpm) * repeats}


    def auto_direction_diagnostic(self, step_ml=0.5):
        if self.position_model is None:
            return {'ok': False, 'error': 'Softpot must be calibrated before running diagnostic.'}
        self.stepper.clear_stop()
        trial_runner = TrialRunner(self.config, self.stepper, self.softpot, self.flow_sensor, self.position_model, self._is_stop_requested, self._set_flow_status, self._read_environment)
        try:
            return trial_runner.exercise_auto_direction(step_ml=step_ml)
        except Exception as exc:
            return {'ok': False, 'error': str(exc)}

    def stop_flow_calibration(self): self.flow_stop_requested = True; self.stepper.stop(); return {'ok': True}
    def flow_results(self): return {'ok': True, 'result': self.flow_run_status.get('result')}
    def add_flow_calibration_point(self, gas, expected_flow_lpm):
        gas_name = str(gas or '').strip().lower()
        if gas_name not in ('air', 'co2'): return {'ok': False, 'error': "gas must be 'air' or 'co2'"}
        expected = float(expected_flow_lpm); measured_voltage = self.flow_sensor.read_voltage(); estimated_flow = self.flow_sensor.estimate_flow_lpm(measured_voltage); timestamp = datetime.now(timezone.utc).isoformat()
        point = {'gas': gas_name, 'expected_flow_lpm': expected, 'measured_voltage_v': measured_voltage, 'estimated_flow_lpm': estimated_flow, 'timestamp': timestamp}
        self.flow_calibration_points.append(point); self._safe_save_flow_points(); return {'ok': True, 'point': point}
    def reset_flow_calibration_points(self): self.flow_calibration_points = []; self._safe_save_flow_points(); return {'ok': True}
    def flow_calibration_csv(self): output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=['gas', 'expected_flow_lpm', 'measured_voltage_v', 'estimated_flow_lpm', 'timestamp']); writer.writeheader(); [writer.writerow(p) for p in self.flow_calibration_points]; return output.getvalue()
    def start_softpot_calibration(self): self.mode = 'softpot_calibration'; self.softpot_calibrator.reset(); self.position_model = None; return {'ok': True, 'current_target_ml': self.softpot_calibrator.current_target}
    def accept_softpot_point(self):
        result = self.softpot_calibrator.accept_current_point()
        if result.get('complete'):
            valid, _ = self.softpot_calibrator.validate()
            if valid: self.position_model = self.softpot_calibrator.make_position_model()
        return result
    def save_softpot_calibration(self): result = self.softpot_calibrator.save(); self.position_model = self.softpot_calibrator.make_position_model() if result.get('ok') else self.position_model; return result
    def jog(self, direction, amount_type, amount):
        self.stepper.clear_stop()
        if direction not in ('toward_empty', 'toward_full'): return {'ok': False, 'error': 'Invalid direction'}
        if amount_type == 'ml': self.jogger.jog_ml(direction, float(amount))
        elif amount_type == 'steps': self.jogger.jog_steps(direction, int(amount))
        else: return {'ok': False, 'error': 'Invalid amount_type'}
        return {'ok': True}
    def enable_motor(self): self.stepper.enable(); return {'ok': True}
    def disable_motor(self): self.stepper.disable(); return {'ok': True}
    def emergency_stop(self): self.flow_stop_requested = True; self.stepper.stop(); self.stepper.disable(); self.mode = 'stopped'; return {'ok': True}
