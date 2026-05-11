class JogController:
    def __init__(self, config, stepper, softpot):
        self.config = config
        self.stepper = stepper
        self.softpot = softpot
        self.microsteps_per_ml = float(config.get('axis', {}).get('microsteps_per_ml', 208.0))

    def _ml_to_steps(self, ml):
        return max(1, int(round(abs(float(ml)) * self.microsteps_per_ml)))

    def jog_ml(self, direction, ml):
        toward_empty = direction == 'toward_empty'
        self.stepper.move_steps(self._ml_to_steps(ml), toward_empty)
        if self.config.get('hardware', {}).get('mode', 'mock') == 'mock':
            self.softpot.adjust_mock_volume(-abs(float(ml)) if toward_empty else abs(float(ml)))

    def jog_steps(self, direction, steps):
        toward_empty = direction == 'toward_empty'
        steps = abs(int(steps))
        self.stepper.move_steps(steps, toward_empty)
        if self.config.get('hardware', {}).get('mode', 'mock') == 'mock':
            delta_ml = steps / self.microsteps_per_ml
            self.softpot.adjust_mock_volume(-delta_ml if toward_empty else delta_ml)
