PY := .venv/bin/python
export PYTHONPATH := packages/engine:packages/importer

.PHONY: help setup test recon lint clean db

help:
	@echo "make setup   create the venv and install dependencies"
	@echo "make test    run the engine and importer test suites"
	@echo "make recon   import the AVS workbook and print Excel vs Platform"
	@echo "make db      start Postgres and Redis (for the API, next module)"
	@echo "make clean   remove the venv and caches"

setup:
	python3 -m venv .venv
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -r requirements.txt

test:
	$(PY) -m pytest

recon:
	$(PY) -m qs_importer $(WORKBOOK)

db:
	docker compose up -d postgres redis

clean:
	rm -rf .venv .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
