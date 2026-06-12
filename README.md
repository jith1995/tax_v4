# Clarity Tax Homepage + Python Engine Integration

This package integrates your Clarity homepage with the Phase-1 Python ITR engine.

## Run locally

```bash
cd clarity_tax_python_integrated
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open: http://127.0.0.1:5000

## Flow

Homepage form → POST /api/run-tax-engine → Python run_itr_engine(payload) → JSON result → result cards on page.

## Boundary

Internal Phase-1 draft only. Old regime exact slab, surcharge, cess, marginal relief, deep DTAA/FTC and final CA validation are parked for later.
