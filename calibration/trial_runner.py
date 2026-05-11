import time
from datetime import datetime, timezone

from logging_data.csv_logger import CsvLogger


class TrialRunner:
    def __init__(self, config, stepper, softpot, flow_sensor, position_model, stop_checker):
        self.config = config
        self.stepper = stepper
        self.softpot = softpot
        self.flow_sensor = flow_sensor
        self.position_model = position_model
        self.stop_checker = stop_checker

    def run_trial(self, trial, csv_path):
        fc = self.config.get('flow_calibration', {})
        sample_interval_s = float(fc.get('sample_interval_s', 0.05))
        settle_before_s = float(fc.get('settle_before_s', 1.0))
        settle_after_s = float(fc.get('settle_after_s', 0.5))
        stroke_ml = abs(trial.stroke_start_ml - trial.stroke_end_ml)
        target_ml_s = trial.target_flow_lpm * 1000.0 / 60.0
        duration_s = max(0.2, stroke_ml / max(target_ml_s, 1e-9))
        steps_per_ml = float(self.config.get('axis', {}).get('microsteps_per_ml', 208.0))
        total_steps = int(stroke_ml * steps_per_ml)
        step_delay_s = max(0.0001, duration_s / max(total_steps, 1))

        logger = CsvLogger(csv_path, [
            'timestamp_s', 'elapsed_s', 'trial_id', 'gas', 'target_flow_lpm', 'softpot_voltage_v',
            'softpot_volume_ml', 'flow_voltage_v', 'flow_lpm_live', 'motion_phase',
            'step_count', 'position_ml_from_steps', 'actual_flow_lpm_window'
        ])
        rows = []
        t0 = time.time()
        for _ in range(max(0, int(settle_before_s / sample_interval_s))):
            rows.append(self._sample(trial, t0, 'settle_before'))
            logger.write(rows[-1]); time.sleep(sample_interval_s)

        self.stepper.enable()
        direction_toward_empty = trial.stroke_end_ml < trial.stroke_start_ml
        for i in range(total_steps):
            if self.stop_checker():
                break
            self.stepper.move_steps(1, direction_toward_empty, step_delay_s=step_delay_s)
            if i % max(1, int(sample_interval_s / step_delay_s)) == 0:
                row = self._sample(trial, t0, 'constant')
                rows.append(row)
                logger.write(row)

        for _ in range(max(0, int(settle_after_s / sample_interval_s))):
            rows.append(self._sample(trial, t0, 'settle_after'))
            logger.write(rows[-1]); time.sleep(sample_interval_s)
        logger.close()
        return rows

    def _sample(self, trial, t0, phase):
        now = time.time()
        softpot_v = self.softpot.read_voltage()
        softpot_ml = self.position_model.voltage_to_volume_ml(softpot_v)
        flow_v = self.flow_sensor.read_voltage()
        return {
            'timestamp_s': datetime.now(timezone.utc).isoformat(),
            'elapsed_s': now - t0,
            'trial_id': trial.trial_id,
            'gas': trial.gas,
            'target_flow_lpm': trial.target_flow_lpm,
            'softpot_voltage_v': softpot_v,
            'softpot_volume_ml': softpot_ml,
            'flow_voltage_v': flow_v,
            'flow_lpm_live': self.flow_sensor.estimate_flow_lpm(flow_v),
            'motion_phase': phase,
            'step_count': self.stepper.step_position,
            'position_ml_from_steps': self.stepper.step_position / float(self.config.get('axis', {}).get('microsteps_per_ml', 208.0)),
            'actual_flow_lpm_window': 0.0,
        }
