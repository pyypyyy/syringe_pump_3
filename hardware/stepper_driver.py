import time


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
        pass

    def move_steps(self, steps, direction_toward_empty, step_delay_s=0.001):
        steps = int(abs(steps))
        if steps == 0:
            return
        if not self.enabled:
            self.enable()
        dir_level = 1 if direction_toward_empty else 0
        if self.invert_direction:
            dir_level = 0 if dir_level else 1
        if self._gpio:
            self._gpio.output(self.dir_pin, dir_level)
            for _ in range(steps):
                self._gpio.output(self.step_pin, 1)
                time.sleep(step_delay_s / 2)
                self._gpio.output(self.step_pin, 0)
                time.sleep(step_delay_s / 2)
        else:
            time.sleep(min(0.25, steps * step_delay_s))
        self.step_position += steps if direction_toward_empty else -steps
