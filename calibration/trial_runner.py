import time
import logging
import threading
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
        self._init_softpot_filter_state()

    def _init_softpot_filter_state(self):
        fc = self.config.get('flow_calibration', {})
        self.softpot_filter_window = max(3, int(fc.get('softpot_filter_window', 5)))
        self.softpot_max_jump_ml_per_sample = float(fc.get('softpot_max_jump_ml_per_sample', 3.0))
        self.softpot_large_jump_accept_samples = max(1, int(fc.get('softpot_large_jump_accept_samples', 3)))
        self.softpot_wrong_direction_persist_s = float(fc.get('softpot_wrong_direction_persist_s', 0.3))
        self.softpot_max_reject_streak = max(1, int(fc.get('softpot_max_reject_streak', 15)))
        self._softpot_raw_window = deque(maxlen=self.softpot_filter_window)
        self._softpot_filtered_volume_ml = None
        self._softpot_pending_jump = None
        self._softpot_pending_count = 0
        self._softpot_glitch_count = 0
        self._softpot_reject_streak = 0
        self._softpot_last_rejected = None

    def _read_softpot_sample(self):
        softpot_v = self.softpot.read_voltage()
        raw_ml = self.position_model.voltage_to_volume_ml(softpot_v)
        self._softpot_raw_window.append(raw_ml)
        median_ml = sorted(self._softpot_raw_window)[len(self._softpot_raw_window) // 2]
        rejected = False
        if self._softpot_filtered_volume_ml is None:
            self._softpot_filtered_volume_ml = median_ml
            self._softpot_pending_jump = None
            self._softpot_pending_count = 0
        else:
            jump = median_ml - self._softpot_filtered_volume_ml
            if abs(jump) > self.softpot_max_jump_ml_per_sample:
                pending_sign = 1 if jump > 0 else -1
                if self._softpot_pending_jump and self._softpot_pending_jump['sign'] == pending_sign:
                    self._softpot_pending_count += 1
                else:
                    self._softpot_pending_jump = {'sign': pending_sign, 'candidate': median_ml, 'jump_ml': jump}
                    self._softpot_pending_count = 1
                if self._softpot_pending_count >= self.softpot_large_jump_accept_samples:
                    self._softpot_filtered_volume_ml = median_ml
                    self._softpot_pending_jump = None
                    self._softpot_pending_count = 0
                else:
                    rejected = True
                    self._softpot_glitch_count += 1
                    self._softpot_reject_streak += 1
                    self._softpot_last_rejected = {
                        'raw_softpot_voltage': softpot_v,
                        'raw_softpot_volume_ml': raw_ml,
                        'median_softpot_volume_ml': median_ml,
                        'jump_ml': jump,
                        'required_consecutive': self.softpot_large_jump_accept_samples,
                        'seen_consecutive': self._softpot_pending_count,
                        'timestamp_s': datetime.now(timezone.utc).isoformat(),
                    }
            else:
                self._softpot_filtered_volume_ml = median_ml
                self._softpot_pending_jump = None
                self._softpot_pending_count = 0

        if not rejected:
            self._softpot_reject_streak = 0
        return softpot_v, raw_ml, self._softpot_filtered_volume_ml, rejected

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
        fc = self.config.get('flow_calibration', {})
        positioning_speed_lpm = float(fc.get('positioning_speed_lpm', self.config.get('jog', {}).get('jog_speed_lpm', 0.1)))
        ml_per_s = max(1e-6, positioning_speed_lpm * 1000.0 / 60.0)
        chunk_steps = max(1, int(steps_per_ml * 0.1))
        chunk_duration_s = max(0.03, chunk_steps / (steps_per_ml * ml_per_s))
        while abs(last_ml - target_ml) > tolerance_ml:
            if self.stop_checker():
                raise RuntimeError('stop requested')
            direction_toward_empty = last_ml > target_ml
            remaining_ml = abs(last_ml - target_ml)
            steps_for_remaining = max(1, int(round(remaining_ml * steps_per_ml)))
            steps_to_move = min(chunk_steps, steps_for_remaining)
            self.stepper.move_steps_timed(steps_to_move, direction_toward_empty, chunk_duration_s)
            moved += steps_to_move
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


    def _logical_direction(self, start_ml, end_ml):
        return 'toward_empty' if end_ml < start_ml else 'toward_full'

    def _log_phase_context(self, phase, start_ml, end_ml, current_ml, baseline_ml, direction_toward_empty):
        logical_direction = 'toward_empty' if direction_toward_empty else 'toward_full'
        physical_dir = self.stepper.resolve_dir_level(direction_toward_empty) if hasattr(self.stepper, 'resolve_dir_level') else None
        invert_direction = getattr(self.stepper, 'invert_direction', None)
        logging.info(
            'flow-calibration phase=%s start_ml=%.3f end_ml=%.3f current_softpot_ml=%.3f baseline_ml=%s logical_direction=%s physical_dir=%s invert_direction=%s',
            phase,
            start_ml,
            end_ml,
            current_ml,
            f"{baseline_ml:.3f}" if baseline_ml is not None else 'None',
            logical_direction,
            physical_dir,
            invert_direction,
        )

    def exercise_auto_direction(self, step_ml=0.5):
        current_ml = self.position_model.voltage_to_volume_ml(self.softpot.read_voltage())
        toward_empty_target = current_ml - abs(float(step_ml))
        self.move_to_volume(toward_empty_target, tolerance_ml=max(0.1, abs(float(step_ml)) * 0.5))
        after_empty_ml = self.position_model.voltage_to_volume_ml(self.softpot.read_voltage())
        delta_empty = after_empty_ml - current_ml
        if delta_empty >= 0:
            raise RuntimeError(f'auto-path toward_empty check failed: delta={delta_empty:.3f} ml')

        toward_full_target = after_empty_ml + abs(float(step_ml))
        self.move_to_volume(toward_full_target, tolerance_ml=max(0.1, abs(float(step_ml)) * 0.5))
        after_full_ml = self.position_model.voltage_to_volume_ml(self.softpot.read_voltage())
        delta_full = after_full_ml - after_empty_ml
        if delta_full <= 0:
            raise RuntimeError(f'auto-path toward_full check failed: delta={delta_full:.3f} ml')
        return {
            'ok': True,
            'before_ml': current_ml,
            'after_toward_empty_ml': after_empty_ml,
            'after_toward_full_ml': after_full_ml,
            'delta_toward_empty_ml': delta_empty,
            'delta_toward_full_ml': delta_full,
        }

    def run_trial(self, trial, csv_path):
        self._init_softpot_filter_state()
        if self.stop_checker():
            return {'status': 'aborted', 'reason': 'User stop requested before trial start', 'raw_csv_path': str(csv_path), 'rows': [], 'summary': None}
        fc = self.config.get('flow_calibration', {})
        sample_interval_s = float(fc.get('sample_interval_s', 0.05))
        settle_before_s = float(fc.get('settle_before_s', 1.0))
        settle_after_s = float(fc.get('settle_after_s', 0.5))
        window_s = float(fc.get('actual_flow_window_s', 0.75))
        stroke_ml = abs(trial.stroke_start_ml - trial.stroke_end_ml)
        target_ml_s = trial.target_flow_lpm * 1000.0 / 60.0
        duration_s = max(0.2, stroke_ml / max(target_ml_s, 1e-9))
        steps_per_ml = float(self.config.get('axis', {}).get('microsteps_per_ml', 208.0))
        total_steps = int(stroke_ml * steps_per_ml)
        base_motion_timeout_s = float(fc.get('softpot_motion_timeout_s', 8.0))
        base_softpot_min_change_ml = float(fc.get('softpot_min_change_ml', 0.1))
        softpot_direction_tolerance_ml = float(fc.get('softpot_direction_tolerance_ml', 0.3))
        stroke_timeout_margin_s = float(fc.get('stroke_timeout_margin_s', 5.0))
        expected_ml_s = max(1e-6, target_ml_s)
        adaptive_min_change_ml = max(0.05, min(base_softpot_min_change_ml, expected_ml_s * max(sample_interval_s, 0.1) * 1.5))
        dynamic_motion_timeout_s = max(base_motion_timeout_s, (adaptive_min_change_ml / expected_ml_s) * 3.0)
        logger = CsvLogger(csv_path, [
            'timestamp_s', 'elapsed_s', 'trial_id', 'gas', 'target_flow_lpm', 'softpot_voltage_v',
            'softpot_volume_ml', 'raw_softpot_volume_ml', 'filtered_softpot_volume_ml', 'softpot_glitch_rejected',
            'softpot_glitch_count', 'softpot_signal_unstable', 'last_rejected_softpot_sample',
            'flow_voltage_v', 'flow_lpm_live', 'actual_flow_lpm_window', 'motion_phase',
            'step_count', 'position_ml_from_steps', 'temperature_c', 'ambient_pressure_hpa', 'relative_humidity_percent'
        ])
        rows, flow_window = [], deque()
        t0 = time.time()
        status, reason = 'completed', None
        move_error = {'exc': None}

        phase = 'idle'

        def _set_status(**kwargs):
            if self.status_callback:
                self.status_callback(**kwargs)

        def _failure_reason(message, phase_name, elapsed_s, latest_softpot_ml):
            return (
                f'{message}; phase={phase_name}; softpot_ml={latest_softpot_ml:.3f}; '
                f'start_ml={trial.stroke_start_ml:.3f}; end_ml={trial.stroke_end_ml:.3f}; '
                f'target_flow_lpm={trial.target_flow_lpm:.5f}; elapsed_s={elapsed_s:.2f}'
            )

        def _record(phase_name):
            row = self._sample(trial, t0, phase_name, flow_window, window_s)
            rows.append(row); logger.write(row)
            _set_status(
                latest_sample=row, phase=phase_name, latest_softpot_volume_ml=row['softpot_volume_ml'], current_target_flow_lpm=trial.target_flow_lpm,
                raw_softpot_voltage=row['softpot_voltage_v'], raw_softpot_volume_ml=row['raw_softpot_volume_ml'],
                filtered_softpot_volume_ml=row['filtered_softpot_volume_ml'], softpot_glitch_count=row['softpot_glitch_count'],
                last_rejected_softpot_sample=row['last_rejected_softpot_sample'], softpot_signal_unstable=row['softpot_signal_unstable']
            )

        try:
            phase = 'moving_to_start'
            _set_status(phase=phase, current_target_flow_lpm=trial.target_flow_lpm)
            pre_move_ml = self.position_model.voltage_to_volume_ml(self.softpot.read_voltage())
            move_to_start_direction_toward_empty = pre_move_ml > trial.stroke_start_ml
            self._log_phase_context(phase, pre_move_ml, trial.stroke_start_ml, pre_move_ml, pre_move_ml, move_to_start_direction_toward_empty)
            self.move_to_volume(trial.stroke_start_ml, tolerance_ml=float(fc.get('position_tolerance_ml', 0.5)))
            phase = 'settling_before'
            for _ in range(max(0, int(settle_before_s / sample_interval_s))):
                if self.stop_checker():
                    status, reason = 'aborted', 'User stop requested during pre-settle'; break
                _record(phase); time.sleep(sample_interval_s)
            if status == 'completed':
                self.stepper.enable()
                direction_toward_empty = trial.stroke_end_ml < trial.stroke_start_ml
                phase = 'moving'
                def _motion():
                    try:
                        self.stepper.move_steps_timed(total_steps, direction_toward_empty, duration_s)
                    except Exception as exc:
                        move_error['exc'] = exc
                motion_thread = threading.Thread(target=_motion, daemon=True)
                motion_thread.start()
                started = time.time()
                expected_sign = -1 if direction_toward_empty else 1
                _, _, stroke_baseline_ml, _ = self._read_softpot_sample()
                motion_change_start = started
                wrong_direction_start = None
                self._log_phase_context(phase, trial.stroke_start_ml, trial.stroke_end_ml, stroke_baseline_ml, stroke_baseline_ml, direction_toward_empty)
                while motion_thread.is_alive():
                    if self.stop_checker():
                        status, reason = 'aborted', 'User stop requested during stroke'; self.stepper.stop(); break
                    row = self._sample(trial, t0, phase, flow_window, window_s)
                    rows.append(row); logger.write(row)
                    _set_status(
                        latest_sample=row, phase=phase, latest_softpot_volume_ml=row['softpot_volume_ml'],
                        raw_softpot_voltage=row['softpot_voltage_v'], raw_softpot_volume_ml=row['raw_softpot_volume_ml'],
                        filtered_softpot_volume_ml=row['filtered_softpot_volume_ml'], softpot_glitch_count=row['softpot_glitch_count'],
                        last_rejected_softpot_sample=row['last_rejected_softpot_sample'], softpot_signal_unstable=row['softpot_signal_unstable']
                    )
                    softpot_ml = row['softpot_volume_ml']
                    delta = softpot_ml - stroke_baseline_ml
                    raw_delta = row['raw_softpot_volume_ml'] - stroke_baseline_ml
                    wrong_direction = (delta * expected_sign) < -softpot_direction_tolerance_ml
                    logging.info(
                        'softpot direction-check elapsed_s=%.3f raw_delta_ml=%.3f filtered_delta_ml=%.3f expected_sign=%+d rejected=%s',
                        row['elapsed_s'], raw_delta, delta, expected_sign, row['softpot_glitch_rejected']
                    )
                    if wrong_direction:
                        wrong_direction_start = wrong_direction_start or time.time()
                        if (time.time() - wrong_direction_start) >= self.softpot_wrong_direction_persist_s:
                            status, reason = 'failed', _failure_reason(
                                f'softpot moved in wrong direction persistently (filtered_delta={delta:.3f} ml, raw_delta={raw_delta:.3f} ml, expected_sign={expected_sign:+d}, persist_s={self.softpot_wrong_direction_persist_s:.2f})',
                                phase, row['elapsed_s'], softpot_ml
                            ); self.stepper.stop(); break
                    else:
                        wrong_direction_start = None
                    if self._softpot_reject_streak >= self.softpot_max_reject_streak:
                        status, reason = 'failed', _failure_reason(
                            f'softpot signal unstable / glitch rejected continuously (reject_streak={self._softpot_reject_streak}, glitch_count={self._softpot_glitch_count})',
                            phase, row['elapsed_s'], softpot_ml
                        ); self.stepper.stop(); break
                    if abs(delta) >= adaptive_min_change_ml:
                        motion_change_start = time.time()
                    if min(trial.stroke_start_ml, trial.stroke_end_ml) <= softpot_ml <= max(trial.stroke_start_ml, trial.stroke_end_ml):
                        if (direction_toward_empty and softpot_ml <= trial.stroke_end_ml) or ((not direction_toward_empty) and softpot_ml >= trial.stroke_end_ml):
                            status, reason = 'completed', 'stroke target reached from softpot'; self.stepper.stop(); break
                    safety = self.config.get('safety', {})
                    safe_min = float(safety.get('min_volume_ml', 0.0)); safe_max = float(safety.get('max_volume_ml', self.config.get('axis', {}).get('syringe_volume_ml', 100.0)))
                    if softpot_ml < safe_min or softpot_ml > safe_max:
                        status, reason = 'failed', _failure_reason(f'softpot outside safety bounds: {softpot_ml:.3f} ml', phase, row['elapsed_s'], softpot_ml); self.stepper.stop(); break
                    if (time.time() - motion_change_start) > dynamic_motion_timeout_s:
                        status, reason = 'failed', _failure_reason(f'softpot not changing while motor commanded (timeout_s={dynamic_motion_timeout_s:.2f}, min_change_ml={adaptive_min_change_ml:.3f})', phase, row['elapsed_s'], softpot_ml); self.stepper.stop(); break
                    if (time.time() - started) > (duration_s + stroke_timeout_margin_s):
                        status, reason = 'failed', _failure_reason('stroke timeout', phase, row['elapsed_s'], softpot_ml); self.stepper.stop(); break
                    time.sleep(sample_interval_s)
                motion_thread.join(timeout=1.0)
                if move_error['exc'] is not None:
                    raise move_error['exc']
            if status == 'completed':
                phase = 'settling_after'
                for _ in range(max(0, int(settle_after_s / sample_interval_s))):
                    if self.stop_checker():
                        status, reason = 'aborted', 'User stop requested during post-settle'; break
                    _record(phase); time.sleep(sample_interval_s)
            phase = 'completed' if status == 'completed' else 'failed'
        except Exception as exc:
            status = 'failed'; reason = _failure_reason(f'backend exception: {exc}', phase or 'unknown', time.time() - t0, self.position_model.voltage_to_volume_ml(self.softpot.read_voltage())); self.stepper.stop()
        finally:
            logger.close()
            _set_status(phase='completed' if status == 'completed' else 'failed', last_failure_reason=None if status == 'completed' else reason)
        return {'status': status, 'reason': reason, 'raw_csv_path': str(csv_path), 'rows': rows, 'summary': None}

    def _sample(self, trial, t0, phase, flow_window, window_s):
        now = time.time()
        softpot_v, raw_softpot_ml, filtered_softpot_ml, rejected = self._read_softpot_sample()
        flow_v = self.flow_sensor.read_voltage()
        elapsed = now - t0
        env = self.environment_reader() if self.environment_reader else {}
        flow_window.append((elapsed, filtered_softpot_ml))
        while len(flow_window) > 2 and (elapsed - flow_window[0][0]) > window_s:
            flow_window.popleft()
        actual_window = None
        if len(flow_window) >= 2:
            t_old, ml_old = flow_window[0]
            dt = elapsed - t_old
            if dt > 1e-9:
                actual_window = abs((filtered_softpot_ml - ml_old) / dt) * 60.0 / 1000.0
        return {
            'timestamp_s': datetime.now(timezone.utc).isoformat(), 'elapsed_s': elapsed,
            'trial_id': trial.trial_id, 'gas': trial.gas, 'target_flow_lpm': trial.target_flow_lpm,
            'softpot_voltage_v': softpot_v,
            'softpot_volume_ml': filtered_softpot_ml,
            'raw_softpot_volume_ml': raw_softpot_ml,
            'filtered_softpot_volume_ml': filtered_softpot_ml,
            'softpot_glitch_rejected': rejected,
            'softpot_glitch_count': self._softpot_glitch_count,
            'softpot_signal_unstable': self._softpot_reject_streak > 0,
            'last_rejected_softpot_sample': self._softpot_last_rejected,
            'flow_voltage_v': flow_v,
            'flow_lpm_live': self.flow_sensor.estimate_flow_lpm(flow_v), 'actual_flow_lpm_window': actual_window,
            'motion_phase': phase, 'step_count': self.stepper.step_position,
            'position_ml_from_steps': self.stepper.step_position / float(self.config.get('axis', {}).get('microsteps_per_ml', 208.0)),
            'temperature_c': env.get('temperature_c'), 'ambient_pressure_hpa': env.get('ambient_pressure_hpa'), 'relative_humidity_percent': env.get('relative_humidity_percent'),
        }
