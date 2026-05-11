# Gasflow Calibrator

Korjattu Flask-pohjainen pohja kaasun virtauskalibrointirigille.

Tiedostot ovat oikeissa paikoissa:

- `app.py` = Flask-sovelluksen käynnistin
- `web/routes.py` = HTML-sivujen route-määritykset
- `web/api.py` = `/api/*`-rajapinnat
- `web/templates/*.html` = Jinja/HTML-templatet
- `web/static/style.css` = CSS
- `web/static/monitor.js` = selaimen JavaScript
- `requirements.txt` = Python-riippuvuudet
- `core/`, `hardware/`, `motion/` = sovelluksen Python-logiikka

## Käynnistys

```bash
cd <project-folder>
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/sanity_check.py
python app.py
```

Windows PowerShell:

```powershell
cd <project-folder>
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts\sanity_check.py
python app.py
```

Avaa:

```text
http://localhost:5000
http://localhost:5000/softpot
```

## Raspberry Pi

Vaihda `config.yaml`:

```yaml
hardware:
  mode: "raspberry_pi"
```

ADS1115-lukua varten tarvitset tyypillisesti:

```bash
pip install adafruit-circuitpython-ads1x15
```

GPIO-ohjaus käyttää `RPi.GPIO`-kirjastoa.
