# Rent Radar -- common commands. Uses .venv/bin/python if present.
PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: setup fixtures data build run run-offline test eval eval-offline classify

setup:            ## create .venv and install dependencies
	python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt

fixtures:         ## build the synthetic fixture DB (no downloads needed)
	$(PY) -m rentradar.build --fixtures

data:             ## download RentSmart, Property Assessment, MBTA stops (run on your Mac)
	$(PY) scripts/fetch_data.py

build:            ## build data/rentradar.sqlite from data/raw + data/vendor
	$(PY) -m rentradar.build

run:              ## start the web app on http://127.0.0.1:8000
	$(PY) -m uvicorn rentradar.api:app --reload

run-offline:      ## same, but force the offline agent
	RENTRADAR_OFFLINE=1 $(PY) -m uvicorn rentradar.api:app --reload

test:             ## unit + integration tests (fixtures, no network)
	$(PY) -m pytest -q

eval:             ## 20-case agent evaluation (LLM if GEMINI_API_KEY set)
	$(PY) eval/run_eval.py

eval-offline:
	$(PY) eval/run_eval.py --offline

classify:         ## optional: Gemini labels for RentSmart descriptions, then rebuild
	$(PY) -m rentradar.classify && $(PY) -m rentradar.build
