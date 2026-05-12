# Gasflow Calibrator

## Mock mode (desktop development)

Use this mode when you do not have Raspberry Pi hardware connected.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/sanity_check.py
python app.py
```

`config.yaml` must contain:

```yaml
hardware:
  mode: "mock"
stepper:
  backend: "mock"
```

## Real Raspberry Pi hardware mode

Use this mode only on Raspberry Pi with motor + ADS1115 connected.

### 1) Install system and Python dependencies

```bash
sudo apt update
sudo apt install -y pigpio
sudo systemctl enable pigpiod
sudo systemctl start pigpiod

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-pi.txt
```

### 2) Configure real hardware in `config.yaml`

You must set **both** hardware mode and a real stepper backend:

```yaml
hardware:
  mode: "raspberry_pi"
stepper:
  backend: "pigpio"   # recommended
  # backend: "rpi_gpio"  # optional alternative
```

Do not run with `hardware.mode: raspberry_pi` and `stepper.backend: mock`.

### 3) ADS1115 channel mapping

Current mapping in `config.yaml`:
- `softpot.ads_channel: 2`
- `flow_sensor.ads_channel: 1`
- `bme280` is I2C-based (not ADS1115) when enabled.

### 4) GPIO pin mapping

Current mapping in `config.yaml`:
- `stepper.step_pin: 18`
- `stepper.dir_pin: 20`
- `stepper.enable_pin: 16`

If you use pigpio hardware PWM pulse generation, keep STEP on GPIO18 as configured.

## Project structure

- `app.py` = Flask launcher
- `web/routes.py` = HTML routes
- `web/api.py` = `/api/*`
- `hardware/` = sensors and stepper drivers
- `motion/` = jog and softpot calibration support
- `calibration/` = trial execution and calibration runs
