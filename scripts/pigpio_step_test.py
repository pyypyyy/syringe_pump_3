#!/usr/bin/env python3
"""Minimal pigpio direct stepper test for Raspberry Pi wiring:
EN=GPIO21, STEP=GPIO18, DIR=GPIO4.
"""
import time
import pigpio

EN = 21
STEP = 18
DIR = 4
ENABLE_ACTIVE_LOW = True
PULSE_DELAY_S = 0.001
STEPS = 1000


def set_enable(pi, enabled: bool):
    if ENABLE_ACTIVE_LOW:
        pi.write(EN, 0 if enabled else 1)
    else:
        pi.write(EN, 1 if enabled else 0)


def step(pi, count: int):
    for _ in range(count):
        pi.write(STEP, 1)
        time.sleep(PULSE_DELAY_S / 2)
        pi.write(STEP, 0)
        time.sleep(PULSE_DELAY_S / 2)


def main():
    pi = pigpio.pi()
    if not pi.connected:
        raise SystemExit('pigpio daemon not reachable. Start with: sudo systemctl start pigpiod')

    for pin in (EN, STEP, DIR):
        pi.set_mode(pin, pigpio.OUTPUT)

    try:
        set_enable(pi, True)
        print('Enabled driver')

        pi.write(DIR, 1)
        print(f'Stepping {STEPS} pulses with DIR=1')
        step(pi, STEPS)

        time.sleep(0.2)

        pi.write(DIR, 0)
        print(f'Stepping {STEPS} pulses with DIR=0')
        step(pi, STEPS)

        print('Done')
    finally:
        set_enable(pi, False)
        pi.write(STEP, 0)
        print('Disabled driver')
        pi.stop()


if __name__ == '__main__':
    main()
