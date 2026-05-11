from pathlib import Path
import csv
import json
from datetime import datetime

from calibration.calibration_plan import CalibrationPlan
from calibration.trial_runner import TrialRunner
from analysis.steady_state import filter_stable_rows, summarize_trial
from analysis.curve_fit import build_piecewise_curve


class FlowCalibrationRunner:
    def __init__(self, config, stepper, softpot, flow_sensor, position_model, status_callback, stop_checker):
        self.config = config
        self.stepper = stepper
        self.softpot = softpot
        self.flow_sensor = flow_sensor
        self.position_model = position_model
        self.status_callback = status_callback
        self.stop_checker = stop_checker

    def run(self, gas, flows_lpm, repeats, stroke_start_ml, stroke_end_ml, analysis_min_ml=None, analysis_max_ml=None):
        ts = datetime.now().strftime('%Y-%m-%d_%H%M%S')
        run_id = f'flow_calibration_{gas}_{ts}'
        run_dir = Path('output/raw') / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        trials = CalibrationPlan.build(gas, flows_lpm, repeats, stroke_start_ml, stroke_end_ml)
        trial_runner = TrialRunner(self.config, self.stepper, self.softpot, self.flow_sensor, self.position_model, self.stop_checker, self.status_callback)
        fc = self.config.get('flow_calibration', {})
        min_ml = float(analysis_min_ml if analysis_min_ml is not None else fc.get('analysis_min_ml', 10.0))
        max_ml = float(analysis_max_ml if analysis_max_ml is not None else fc.get('analysis_max_ml', 90.0))
        summaries = []
        for idx, trial in enumerate(trials, start=1):
            self.status_callback(running=True, gas=gas, current_trial={'trial_id': trial.trial_id, 'target_flow_lpm': trial.target_flow_lpm, 'repeat_index': trial.repeat_index}, completed_trials=idx-1, total_trials=len(trials), current_target_flow_lpm=trial.target_flow_lpm, run_dir=str(run_dir))
            rows = trial_runner.run_trial(trial, run_dir / f'{trial.trial_id}.csv')
            stable = filter_stable_rows(rows, min_ml, max_ml)
            stats = summarize_trial(stable)
            summaries.append({
                'gas': gas,
                'trial_id': trial.trial_id,
                'target_flow_lpm': trial.target_flow_lpm,
                'repeat_index': trial.repeat_index,
                'actual_flow_lpm': stats['actual_flow_lpm'],
                'mean_voltage_v': stats['mean_flow_voltage_v'],
                'std_voltage_v': stats['std_flow_voltage_v'],
                'actual_flow_std_lpm': stats['std_actual_flow_lpm'],
                'sample_count': stats['sample_count'],
            })
            if trial.stroke_start_ml > trial.stroke_end_ml:
                trial_runner.move_to_volume(trial.stroke_start_ml, tolerance_ml=float(fc.get('position_tolerance_ml', 0.5)))
            if self.stop_checker():
                break

        with (run_dir / 'summary.csv').open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=['gas', 'trial_id', 'target_flow_lpm', 'repeat_index', 'actual_flow_lpm', 'mean_voltage_v', 'std_voltage_v', 'actual_flow_std_lpm', 'sample_count'])
            w.writeheader(); w.writerows(summaries)

        grouped = {}
        for s in summaries:
            key = (s['gas'], s['target_flow_lpm'])
            grouped.setdefault(key, []).append(s)
        curve_points = []
        for (g, tf), vals in grouped.items():
            curve_points.append({
                'target_flow_lpm': tf,
                'actual_flow_lpm': sum(v['actual_flow_lpm'] for v in vals) / len(vals),
                'mean_voltage_v': sum(v['mean_voltage_v'] for v in vals) / len(vals),
                'std_voltage_v': sum(v['std_voltage_v'] for v in vals) / len(vals),
                'repeat_count': len(vals),
            })
        curve = build_piecewise_curve(gas, curve_points)
        with (run_dir / 'calibration_curve.json').open('w', encoding='utf-8') as f:
            json.dump(curve, f, indent=2)
        with (run_dir / 'calibration_curve.csv').open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=['target_flow_lpm', 'actual_flow_lpm', 'mean_voltage_v', 'std_voltage_v', 'repeat_count'])
            w.writeheader(); w.writerows(curve['points'])

        self.status_callback(running=False, gas=gas, current_trial=None, completed_trials=len(summaries), total_trials=len(trials), current_target_flow_lpm=None, run_dir=str(run_dir), result={'run_dir': str(run_dir), 'curve': curve}, recent_trials=summaries[-10:], analysis_min_ml=min_ml, analysis_max_ml=max_ml)
        return {'ok': True, 'run_id': run_id, 'trial_count': len(trials), 'run_dir': str(run_dir), 'result': curve}
