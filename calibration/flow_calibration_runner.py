from pathlib import Path
import csv
import json
import time
from datetime import datetime

from calibration.calibration_plan import CalibrationPlan
from calibration.trial_runner import TrialRunner
from analysis.steady_state import filter_stable_rows, summarize_trial
from analysis.curve_fit import build_piecewise_curve


class FlowCalibrationRunner:
    def __init__(self, config, stepper, softpot, flow_sensor, position_model, status_callback, stop_checker, environment_reader=None):
        self.config = config
        self.stepper = stepper
        self.softpot = softpot
        self.flow_sensor = flow_sensor
        self.position_model = position_model
        self.status_callback = status_callback
        self.stop_checker = stop_checker
        self.environment_reader = environment_reader

    def capture_zero_flow(self, gas):
        fc = self.config.get('flow_calibration', {})
        zc = fc.get('zero_flow', {})
        settling_s = float(zc.get('settling_s', 2.0))
        sample_duration_s = float(zc.get('sample_duration_s', 5.0))
        interval_s = float(zc.get('sample_interval_s', 0.05))
        self.stepper.stop()
        time.sleep(settling_s)
        samples = []
        for _ in range(max(1, int(sample_duration_s / max(interval_s, 1e-6)))):
            samples.append(float(self.flow_sensor.read_voltage())); time.sleep(interval_s)
        mean = sum(samples) / len(samples)
        std = (sum((x - mean) ** 2 for x in samples) / len(samples)) ** 0.5
        return {'gas': gas, 'timestamp': datetime.utcnow().isoformat(), 'zero_voltage_mean_v': mean, 'zero_voltage_std_v': std, 'sample_count': len(samples), 'settling_s': settling_s, 'sample_duration_s': sample_duration_s}

    def run(self, gas, flows_lpm, repeats, stroke_start_ml, stroke_end_ml, analysis_min_ml=None, analysis_max_ml=None, zero_capture=None):
        ts = datetime.now().strftime('%Y-%m-%d_%H%M%S')
        run_id = f'flow_calibration_{gas}_{ts}'
        run_dir = Path('output/raw') / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        if zero_capture is None:
            zero_capture = self.capture_zero_flow(gas)
        (run_dir / 'zero_flow_capture.json').write_text(json.dumps(zero_capture, indent=2), encoding='utf-8')
        trials = CalibrationPlan.build(gas, flows_lpm, repeats, stroke_start_ml, stroke_end_ml)
        trial_runner = TrialRunner(self.config, self.stepper, self.softpot, self.flow_sensor, self.position_model, self.stop_checker, self.status_callback, self.environment_reader)
        fc = self.config.get('flow_calibration', {})
        qc = fc.get('quality_checks', {})
        min_ml = float(analysis_min_ml if analysis_min_ml is not None else fc.get('analysis_min_ml', 10.0))
        max_ml = float(analysis_max_ml if analysis_max_ml is not None else fc.get('analysis_max_ml', 90.0))
        min_samples = int(qc.get('min_stable_samples', 10)); min_duration = float(qc.get('min_stable_duration_s', 1.0)); min_nonzero = float(qc.get('min_nonzero_flow_lpm', 0.001)); max_cv = float(qc.get('max_flow_cv', 0.15))
        summaries = []; trials_meta = []
        for idx, trial in enumerate(trials, start=1):
            res = trial_runner.run_trial(trial, run_dir / f'{trial.trial_id}.csv')
            tstatus = res['status']; reason = res.get('reason'); stats = None
            if tstatus == 'completed':
                stable = filter_stable_rows(res['rows'], min_ml, max_ml)
                stats = summarize_trial(stable)
                if stats['sample_count'] < min_samples: tstatus, reason = 'invalid', f"Stable region had only {stats['sample_count']} samples; minimum is {min_samples}"
                elif stats['stable_duration_s'] < min_duration: tstatus, reason = 'invalid', 'Stable duration too short'
                elif trial.target_flow_lpm > 0 and stats['actual_flow_lpm'] <= min_nonzero: tstatus, reason = 'invalid', 'Actual flow not positive for nonzero target flow'
                elif stats['flow_cv'] > max_cv: tstatus, reason = 'invalid', 'Actual flow variation too high'
                elif (trial.stroke_end_ml < trial.stroke_start_ml and stats['volume_end_ml'] > stats['volume_start_ml']) or (trial.stroke_end_ml > trial.stroke_start_ml and stats['volume_end_ml'] < stats['volume_start_ml']):
                    tstatus, reason = 'invalid', 'Softpot volume moved in unexpected direction'
            entry = {'gas': gas, 'trial_id': trial.trial_id, 'target_flow_lpm': trial.target_flow_lpm, 'repeat_index': trial.repeat_index, 'status': tstatus, 'reason': reason}
            if tstatus == 'completed' and stats:
                entry.update(stats)
                summaries.append(entry)
            trials_meta.append(entry)
            if self.stop_checker():
                break

        with (run_dir / 'summary.csv').open('w', newline='', encoding='utf-8') as f:
            if summaries:
                w = csv.DictWriter(f, fieldnames=list(summaries[0].keys())); w.writeheader(); w.writerows(summaries)
        curve_points = [{'target_flow_lpm': s['target_flow_lpm'], 'actual_flow_lpm': s['actual_flow_lpm'], 'mean_voltage_v': s['mean_flow_voltage_v'], 'std_voltage_v': s['std_flow_voltage_v'], 'repeat_count': 1} for s in summaries]
        curve_points.append({'target_flow_lpm': 0.0, 'actual_flow_lpm': 0.0, 'mean_voltage_v': zero_capture['zero_voltage_mean_v'], 'std_voltage_v': zero_capture['zero_voltage_std_v'], 'repeat_count': 1, 'zero_flow_anchor': True})
        curve = build_piecewise_curve(gas, curve_points)
        curve['zero_flow'] = zero_capture
        curve['trial_statuses'] = trials_meta
        with (run_dir / 'calibration_curve.json').open('w', encoding='utf-8') as f:
            json.dump(curve, f, indent=2)
        with (run_dir / 'calibration_curve.csv').open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=['target_flow_lpm', 'actual_flow_lpm', 'mean_voltage_v', 'std_voltage_v', 'repeat_count', 'zero_flow_anchor'])
            w.writeheader(); w.writerows(curve['points'])
        return {'ok': True, 'run_id': run_id, 'trial_count': len(trials), 'run_dir': str(run_dir), 'result': curve, 'trial_statuses': trials_meta}
