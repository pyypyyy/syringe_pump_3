import time
import logging
from collections import deque
from datetime import datetime, timezone

from logging_data.csv_logger import CsvLogger


class TrialRunner:
    def __init__(self, config, stepper, softpot, flow_sensor, position_model, stop_checker, status_callback=None, environment_reader=None):
        self.config = config
        self.stepper = stepper
        self.softpot = softpot
        self.flow_sensor = flow_sensor
        self.position_model = position_model
        self.stop_checker = stop_checker
        self.status_callback = status_callback
        self.environment_reader = environment_reader

    def move_to_volume(self, target_ml, tolerance_ml=0.5, max_steps=100000):
        axis = self.config.get('axis', {})
        safety = self.config.get('safety', {})
        min_ml = float(safety.get('min_volume_ml', 0.0))
        max_ml = float(safety.get('max_volume_ml', axis.get('syringe_volume_ml', 100.0)))
        steps_per_ml = float(axis.get('microsteps_per_ml', 208.0))
        last_ml = self.position_model.voltage_to_volume_ml(self.softpot.read_voltage())
        if not (min_ml <= last_ml <= max_ml):
            raise RuntimeError(f'volume outside safety bounds: {last_ml:.3f} ml')
        stable_count = 0
        moved = 0
        while abs(last_ml - target_ml) > tolerance_ml:
            if self.stop_checker():
                raise RuntimeError('stop requested')
            direction_toward_empty = last_ml > target_ml
            self.stepper.move_steps(1, direction_toward_empty, step_delay_s=0.0008)
            moved += 1
            if self.softpot.mode == 'mock':
                delta = -1.0 / steps_per_ml if direction_toward_empty else 1.0 / steps_per_ml
                self.softpot.adjust_mock_volume(delta)
            cur_ml = self.position_model.voltage_to_volume_ml(self.softpot.read_voltage())
            if not (min_ml <= cur_ml <= max_ml):
                raise RuntimeError(f'volume outside safety bounds: {cur_ml:.3f} ml')
            expected_delta = -1 if direction_toward_empty else 1
            observed = cur_ml - last_ml
            if observed * expected_delta <= 0:
                stable_count += 1
                if stable_count >= 80:
                    raise RuntimeError('softpot did not change in expected direction')
            else:
                stable_count = 0
            last_ml = cur_ml
            if moved > max_steps:
                raise RuntimeError('failed to reach target volume in max steps')

    def run_trial(self, trial, csv_path):
        if self.stop_checker():
            return {'status': 'aborted', 'reason': 'User stop requested before trial start', 'raw_csv_path': str(csv_path), 'rows': [], 'summary': None}
        fc = self.config.get('flow_calibration', {})
        sample_interval_s = float(fc.get('sample_interval_s', 0.05))
        settle_before_s = float(fc.get('settle_before_s', 1.0))
        settle_after_s = float(fc.get('settle_after_s', 0.5))
        window_s = float(fc.get('actual_flow_window_s', 0.75))
        mock_time_scale = float(fc.get('mock_time_scale', 1.0)) if self.config.get('hardware', {}).get('mode') == 'mock' else 1.0
        stroke_ml = abs(trial.stroke_start_ml - trial.stroke_end_ml)
        target_ml_s = trial.target_flow_lpm * 1000.0 / 60.0
        duration_s = max(0.2, stroke_ml / max(target_ml_s, 1e-9)) * mock_time_scale
        steps_per_ml = float(self.config.get('axis', {}).get('microsteps_per_ml', 208.0))
        total_steps = int(stroke_ml * steps_per_ml)
        step_delay_s = max(0.0001, duration_s / max(total_steps, 1))
        target_step_rate_hz = (total_steps / max(duration_s, 1e-9)) if total_steps > 0 else 0.0
        backend_name = getattr(getattr(self.stepper, 'pulse_backend', None), 'name', 'rpi_gpio' if self.stepper.mode == 'raspberry_pi' else 'mock')
        if target_step_rate_hz > 1000 and backend_name == 'rpi_gpio':
            logging.getLogger(__name__).warning(
                'Target step rate %.0f Hz is high for RPi.GPIO timing. Use pigpio backend for reliable calibration.',
                target_step_rate_hz,
            )
        if hasattr(self.flow_sensor, 'set_mock_active_flow'):
            self.flow_sensor.set_mock_active_flow(trial.target_flow_lpm)

        logger = CsvLogger(csv_path, [
            'timestamp_s', 'elapsed_s', 'trial_id', 'gas', 'target_flow_lpm', 'softpot_voltage_v',
            'softpot_volume_ml', 'flow_voltage_v', 'flow_lpm_live', 'actual_flow_lpm_window', 'motion_phase',
            'step_count', 'position_ml_from_steps', 'temperature_c', 'ambient_pressure_hpa', 'relative_humidity_percent'
        ])
        rows = []
        t0 = time.time()
        flow_window = deque()
        status = 'completed'
        reason = None

        try:
            self.move_to_volume(trial.stroke_start_ml, tolerance_ml=float(fc.get('position_tolerance_ml', 0.5)))
            for _ in range(max(0, int(settle_before_s / sample_interval_s))):
                if self.stop_checker():
                    status = 'aborted'; reason = 'User stop requested during pre-settle'; break
                row = self._sample(trial, t0, 'settle_before', flow_window, window_s)
                rows.append(row); logger.write(row); time.sleep(sample_interval_s)

            if status == 'completed':
                self.stepper.enable()
                direction_toward_empty = trial.stroke_end_ml < trial.stroke_start_ml
                moved_steps = self.stepper.move_steps_timed(total_steps, direction_toward_empty, duration_s)
                sample_every = max(1, int(sample_interval_s / max(step_delay_s, 1e-6)))
                for i in range(moved_steps):
                    if self.stop_checker():
                        status = 'aborted'; reason = 'User stop requested during stroke'; break
                    if self.softpot.mode == 'mock':
                        delta = -1.0 / steps_per_ml if direction_toward_empty else 1.0 / steps_per_ml
                        self.softpot.adjust_mock_volume(delta)
                    if i % sample_every == 0:
                        row = self._sample(trial, t0, 'moving', flow_window, window_s)
                        rows.append(row)
                        logger.write(row)
                        if self.status_callback:
                            self.status_callback(latest_sample=row)

            if status == 'completed':
                for _ in range(max(0, int(settle_after_s / sample_interval_s))):
                    if self.stop_checker():
                        status = 'aborted'; reason = 'User stop requested during post-settle'; break
                    row = self._sample(trial, t0, 'settle_after', flow_window, window_s)
                    rows.append(row); logger.write(row); time.sleep(sample_interval_s)
        except Exception as exc:
            status = 'failed'
            reason = str(exc)
            self.stepper.stop()
        finally:
            logger.close()
            if status == 'aborted':
                self.stepper.stop()
            if hasattr(self.flow_sensor, 'set_mock_active_flow'):
                self.flow_sensor.set_mock_active_flow(0.0)

        return {'status': status, 'reason': reason, 'raw_csv_path': str(csv_path), 'rows': rows, 'summary': None}

    def _sample(self, trial, t0, phase, flow_window, window_s):
        now = time.time()
        softpot_v = self.softpot.read_voltage()
        softpot_ml = self.position_model.voltage_to_volume_ml(softpot_v)
        flow_v = self.flow_sensor.read_voltage()
        elapsed = now - t0
        env = self.environment_reader() if self.environment_reader else {}
        flow_window.append((elapsed, softpot_ml))
        while len(flow_window) > 2 and (elapsed - flow_window[0][0]) > window_s:
            flow_window.popleft()
        actual_window = 0.0
        if len(flow_window) >= 2:
            t_old, ml_old = flow_window[0]
            dt = elapsed - t_old
            if dt > 1e-9:
                actual_window = abs((softpot_ml - ml_old) / dt) * 60.0 / 1000.0
        return {
            'timestamp_s': datetime.now(timezone.utc).isoformat(), 'elapsed_s': elapsed,
            'trial_id': trial.trial_id, 'gas': trial.gas, 'target_flow_lpm': trial.target_flow_lpm,
            'softpot_voltage_v': softpot_v, 'softpot_volume_ml': softpot_ml, 'flow_voltage_v': flow_v,
            'flow_lpm_live': self.flow_sensor.estimate_flow_lpm(flow_v), 'actual_flow_lpm_window': actual_window,
            'motion_phase': phase, 'step_count': self.stepper.step_position,
            'position_ml_from_steps': self.stepper.step_position / float(self.config.get('axis', {}).get('microsteps_per_ml', 208.0)),
            'temperature_c': env.get('temperature_c'), 'ambient_pressure_hpa': env.get('ambient_pressure_hpa'), 'relative_humidity_percent': env.get('relative_humidity_percent'),
        }
