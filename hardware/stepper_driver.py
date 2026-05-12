import time
import logging


logger = logging.getLogger(__name__)


class StepPulseBackend:
    name = 'base'

    def move_steps_timed(self, steps, direction_toward_empty, duration_s, stop_checker):
        raise NotImplementedError

    def is_active(self):
        return False

    def stop(self):
        return None

    def cleanup(self):
        return None


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


class PigpioBackend(StepPulseBackend):
    name = 'pigpio'

    def __init__(self, pigpio_module, step_pin, dir_pin, invert_direction=False, enable_pin=None, enable_active_low=True):
        self.pigpio = pigpio_module
        self.step_pin = step_pin
        self.dir_pin = dir_pin
        self.invert_direction = invert_direction
        self.enable_pin = enable_pin
        self.enable_active_low = enable_active_low
        self.pi = pigpio_module.pi()
        if not self.pi.connected:
            raise RuntimeError('pigpio daemon not reachable')
        self.pi.set_mode(self.step_pin, pigpio_module.OUTPUT)
        self.pi.set_mode(self.dir_pin, pigpio_module.OUTPUT)
        if self.enable_pin is not None:
            self.pi.set_mode(self.enable_pin, pigpio_module.OUTPUT)
        self._active = False

    def move_steps_timed(self, steps, direction_toward_empty, duration_s, stop_checker):
        steps = int(abs(steps))
        if steps <= 0:
            return 0
        if stop_checker():
            return 0
        dir_level = 1 if direction_toward_empty else 0
        if self.invert_direction:
            dir_level = 0 if dir_level else 1
        self.pi.write(self.dir_pin, dir_level)
        frequency = int(max(1.0, steps / max(duration_s, 1e-6)))
        self._active = True
        self.pi.hardware_PWM(self.step_pin, frequency, 500000)
        start = time.time()
        try:
            while (time.time() - start) < duration_s:
                if stop_checker():
                    break
                time.sleep(0.002)
        finally:
            self.pi.hardware_PWM(self.step_pin, 0, 0)
            self._active = False
        elapsed = max(time.time() - start, 0.0)
        moved = min(steps, int(round(elapsed * frequency)))
        return moved

    def is_active(self):
        return self._active

    def stop(self):
        self.pi.hardware_PWM(self.step_pin, 0, 0)
        self._active = False

    def cleanup(self):
        self.stop()
        self.pi.stop()


class StepperDriver:
    def __init__(self, config):
        self.config = config
        self.mode = config.get('hardware', {}).get('mode', 'mock')
        stepper_cfg = config.get('stepper', {})
        self.step_pin = int(stepper_cfg.get('step_pin', 18))
        self.dir_pin = int(stepper_cfg.get('dir_pin', 20))
        self.enable_pin = int(stepper_cfg.get('enable_pin', 16))
        self.enable_active_low = bool(stepper_cfg.get('enable_active_low', True))
        self.invert_direction = bool(stepper_cfg.get('invert_direction', False))
        self.backend_name = stepper_cfg.get('backend', 'rpi_gpio' if self.mode == 'raspberry_pi' else 'mock')
        self.enabled = False
        self.step_position = 0
        self.step_position_valid = True
        self._gpio = None
        self.pulse_backend = None
        self.stop_requested = False
        if self.mode == 'raspberry_pi':
            self._init_backend()

    def _init_backend(self):
        if self.backend_name == 'pigpio':
            import pigpio
            self.pulse_backend = PigpioBackend(pigpio, self.step_pin, self.dir_pin, self.invert_direction, self.enable_pin, self.enable_active_low)
        else:
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
        elif self.pulse_backend and getattr(self.pulse_backend, 'enable_pin', None) is not None:
            level = 0 if self.enable_active_low else 1
            self.pulse_backend.pi.write(self.enable_pin, level)

    def disable(self):
        self.enabled = False
        self.step_position_valid = False
        if self._gpio:
            self._gpio.output(self.enable_pin, 1 if self.enable_active_low else 0)
        elif self.pulse_backend and getattr(self.pulse_backend, 'enable_pin', None) is not None:
            level = 1 if self.enable_active_low else 0
            self.pulse_backend.pi.write(self.enable_pin, level)

    def stop(self):
        self.stop_requested = True
        if self.pulse_backend:
            self.pulse_backend.stop()

    def clear_stop(self):
        self.stop_requested = False

    def cleanup(self):
        if self.pulse_backend:
            self.pulse_backend.cleanup()
        if self._gpio:
            self._gpio.cleanup()

    def move_steps(self, steps, direction_toward_empty, step_delay_s=0.001):
        steps = int(abs(steps))
        if steps == 0:
            return 0
        if not self.enabled:
            self.enable()
        moved = 0

        if self.pulse_backend:
            duration_s = max(0.0001, float(step_delay_s) * steps)
            moved = self.pulse_backend.move_steps_timed(steps, direction_toward_empty, duration_s, lambda: self.stop_requested)
        elif self.mode == 'raspberry_pi':
            raise RuntimeError(f"stepper backend '{self.backend_name}' unavailable in raspberry_pi mode; refusing to simulate motion")
        else:
            logger.info('Simulating %s steps in mock mode.', steps)
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
        elif self.mode == 'raspberry_pi':
            raise RuntimeError(f"stepper backend '{self.backend_name}' unavailable in raspberry_pi mode; refusing to simulate motion")
        else:
            step_delay_s = max(0.0001, float(duration_s) / max(steps, 1))
            for _ in range(steps):
                if self.stop_requested:
                    break
                time.sleep(min(0.005, step_delay_s))
                moved += 1
        self.step_position += moved if direction_toward_empty else -moved
        return moved
