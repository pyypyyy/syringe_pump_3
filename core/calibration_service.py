from hardware.ads1115_reader import ADS1115Reader
from hardware.flow_sensor import FlowSensor
from hardware.softpot_reader import SoftpotReader
from hardware.stepper_driver import StepperDriver
from motion.jog_controller import JogController
from motion.softpot_calibrator import SoftpotCalibrator


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

    def log(self, message):
        self.last_event = message
        self.events.append(message)
        self.events = self.events[-20:]

    def get_status(self):
        softpot_voltage = self.softpot.read_voltage()
        softpot_volume = None
        if self.position_model is not None:
            softpot_volume = self.position_model.voltage_to_volume_ml(softpot_voltage)
        flow_voltage = self.flow_sensor.read_voltage()
        return {
            'mode': self.mode,
            'softpot_voltage_v': softpot_voltage,
            'softpot_volume_ml': softpot_volume,
            'flow_voltage_v': flow_voltage,
            'flow_lpm': self.flow_sensor.estimate_flow_lpm(flow_voltage),
            'motor_enabled': self.stepper.enabled,
            'step_position': self.stepper.step_position,
            'step_position_valid': self.stepper.step_position_valid,
            'current_target_ml': self.softpot_calibrator.current_target,
            'calibration_points': [p.__dict__ for p in self.softpot_calibrator.points],
            'calibration_targets': self.softpot_calibrator.targets,
            'last_event': self.last_event,
            'events': list(reversed(self.events)),
        }

    def start_softpot_calibration(self):
        self.mode = 'softpot_calibration'
        self.softpot_calibrator.reset()
        self.position_model = None
        self.log('Softpot calibration started')
        return {'ok': True, 'current_target_ml': self.softpot_calibrator.current_target}

    def accept_softpot_point(self):
        result = self.softpot_calibrator.accept_current_point()
        p = result['point']
        self.log(f"{p['volume_ml']:.1f} ml point accepted: {p['voltage_v']:.4f} V")
        if result.get('complete'):
            valid, message = self.softpot_calibrator.validate()
            if valid:
                self.position_model = self.softpot_calibrator.make_position_model()
                self.log('Softpot calibration completed')
            else:
                self.log(f'Softpot calibration validation failed: {message}')
        return result

    def save_softpot_calibration(self):
        result = self.softpot_calibrator.save()
        if result.get('ok'):
            self.position_model = self.softpot_calibrator.make_position_model()
            self.log(f"Softpot calibration saved: {result['path']}")
        else:
            self.log(f"Softpot calibration save failed: {result.get('error')}")
        return result

    def jog(self, direction, amount_type, amount):
        if direction not in ('toward_empty', 'toward_full'):
            return {'ok': False, 'error': 'Invalid direction'}
        if amount_type not in ('ml', 'steps'):
            return {'ok': False, 'error': 'Invalid amount_type'}
        try:
            if amount_type == 'ml':
                self.jogger.jog_ml(direction, float(amount))
            else:
                self.jogger.jog_steps(direction, int(amount))
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'Invalid amount'}
        self.log(f'Jog {direction}, {amount} {amount_type}')
        return {'ok': True}

    def enable_motor(self):
        self.stepper.enable()
        self.log('Motor enabled')
        return {'ok': True}

    def disable_motor(self):
        self.stepper.disable()
        self.log('Motor disabled')
        return {'ok': True}

    def emergency_stop(self):
        self.stepper.stop()
        self.stepper.disable()
        self.mode = 'stopped'
        self.log('Emergency stop')
        return {'ok': True}
