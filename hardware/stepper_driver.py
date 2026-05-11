import time


class StepPulseBackend:
    name = 'base'

    def move_steps_timed(self, steps, direction_toward_empty, duration_s, stop_checker):
        raise NotImplementedError


class RPiGPIOBackend(StepPulseBackend):
    name = 'rpi_gpio'

    def __init__(self, gpio, step_pin, dir_pin, invert_direction=False):
        self.gpio = gpio
        self.step_pin = step_pin
        self.dir_pin = dir_pin
        self.invert_direction = invert_direction

    def move_steps_timed(self, steps, direction_toward_empty, duration_s, stop_checker):
        steps = int(abs(steps))
        if steps <= 0:
            return 0
        dir_level = 1 if direction_toward_empty else 0
        if self.invert_direction:
            dir_level = 0 if dir_level else 1
        step_delay_s = max(0.0001, float(duration_s) / max(steps, 1))
        moved = 0
        self.gpio.output(self.dir_pin, dir_level)
        for _ in range(steps):
            if stop_checker():
                break
            self.gpio.output(self.step_pin, 1)
            time.sleep(step_delay_s / 2)
            self.gpio.output(self.step_pin, 0)
            time.sleep(step_delay_s / 2)
            moved += 1
        return moved


class StepperDriver:
    def __init__(self, config):
        self.config = config
        self.mode = config.get('hardware', {}).get('mode', 'mock')
        self.step_pin = int(config.get('stepper', {}).get('step_pin', 18))
        self.dir_pin = int(config.get('stepper', {}).get('dir_pin', 20))
        self.enable_pin = int(config.get('stepper', {}).get('enable_pin', 16))
        self.enable_active_low = bool(config.get('stepper', {}).get('enable_active_low', True))
        self.invert_direction = bool(config.get('stepper', {}).get('invert_direction', False))
        self.enabled = False
        self.step_position = 0
        self.step_position_valid = True
        self._gpio = None
        self.pulse_backend = None
        self.stop_requested = False
        if self.mode == 'raspberry_pi':
            self._init_gpio()

    def _init_gpio(self):
        try:
            import RPi.GPIO as GPIO
        except ImportError as exc:
            raise RuntimeError('Real GPIO mode requires RPi.GPIO.') from exc
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.step_pin, GPIO.OUT)
        GPIO.setup(self.dir_pin, GPIO.OUT)
        GPIO.setup(self.enable_pin, GPIO.OUT)
        self._gpio = GPIO
        self.pulse_backend = RPiGPIOBackend(GPIO, self.step_pin, self.dir_pin, self.invert_direction)
        self.disable()

    def enable(self):
        self.enabled = True
        if self._gpio:
            self._gpio.output(self.enable_pin, 0 if self.enable_active_low else 1)

    def disable(self):
        self.enabled = False
        self.step_position_valid = False
        if self._gpio:
            self._gpio.output(self.enable_pin, 1 if self.enable_active_low else 0)

    def stop(self):
        self.stop_requested = True

    def clear_stop(self):
        self.stop_requested = False

    def move_steps(self, steps, direction_toward_empty, step_delay_s=0.001):
        steps = int(abs(steps))
        if steps == 0:
            return 0
        if not self.enabled:
            self.enable()
        dir_level = 1 if direction_toward_empty else 0
        if self.invert_direction:
            dir_level = 0 if dir_level else 1
        moved = 0
        if self._gpio:
            self._gpio.output(self.dir_pin, dir_level)
            for _ in range(steps):
                if self.stop_requested:
                    break
                self._gpio.output(self.step_pin, 1)
                time.sleep(step_delay_s / 2)
                self._gpio.output(self.step_pin, 0)
                time.sleep(step_delay_s / 2)
                moved += 1
        else:
            for _ in range(steps):
                if self.stop_requested:
                    break
                time.sleep(min(0.005, step_delay_s))
                moved += 1
        self.step_position += moved if direction_toward_empty else -moved
        return moved

    def move_steps_timed(self, steps, direction_toward_empty, duration_s):
        steps = int(abs(steps))
        if steps == 0:
            return 0
        if not self.enabled:
            self.enable()
        if self.pulse_backend:
            moved = self.pulse_backend.move_steps_timed(steps, direction_toward_empty, duration_s, lambda: self.stop_requested)
        else:
            step_delay_s = max(0.0001, float(duration_s) / max(steps, 1))
            return self.move_steps(steps, direction_toward_empty, step_delay_s=step_delay_s)
        self.step_position += moved if direction_toward_empty else -moved
        return moved
