PY := .venv/bin/python
export PYTHONPATH := packages/engine:packages/importer:packages/app
PORT ?= 8000
RELOAD ?=

.PHONY: help setup test recon run seed clean

help:
	@echo "make setup   create the venv and install dependencies"
	@echo "make test    run the engine and importer test suites"
	@echo "make recon   import the AVS workbook and print Excel vs Platform"
	@echo "make seed    create qs.db and import the workbook into it"
	@echo "make run     start the platform on http://localhost:8000"
	@echo "make clean   remove the venv and caches"

setup:
	python3 -m venv .venv
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -r requirements.txt

test:
	$(PY) -m pytest

recon:
	$(PY) -m qs_importer $(WORKBOOK)

seed:
	$(PY) -m qs_app.seed $(ARGS)

# One process. It serves the UI and the API and stores everything in qs.db --
# no database server, no build step, nothing else to start.
run: seed
	@echo ""
	@echo "  DBOT QS Platform  ->  http://localhost:$(PORT)"
	@echo ""
	$(PY) -m uvicorn qs_app.server:app --host 127.0.0.1 --port $(PORT) $(RELOAD)

clean:
	rm -rf .venv .pytest_cache qs.db qs.db-wal qs.db-shm
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
