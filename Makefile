PY := .venv/bin/python
export PYTHONPATH := packages/engine:packages/importer:packages/app
PORT ?= 8000
RELOAD ?=

.PHONY: help setup test recon run seed clean

help:
	@echo "make setup   create the venv and install dependencies"
	@echo "make test    run the engine and importer test suites"
	@echo "make recon   import the AVS workbook and print Excel vs Platform"
	@echo "make seed    import the workbook into qs.db (KEEP=1 to keep what is there)"
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

# Re-imports the workbook every run, so what you see is always this build's
# data. The previous database is copied to qs.db.bak first. KEEP=1 to hold on
# to what is already there.
seed:
	$(PY) -m qs_app.seed $(if $(KEEP),--keep,) $(ARGS)

# One process. It serves the UI and the API and stores everything in qs.db --
# no database server, no build step, nothing else to start.
run: seed
	@echo ""
	@echo "  DBOT QS Platform  ->  http://localhost:$(PORT)"
	@echo "  build $$(git log -1 --format='%h  %cs  %s' 2>/dev/null || echo unknown)"
	@behind=$$(git rev-list --count HEAD..@{upstream} 2>/dev/null || echo 0); 	if [ "$$behind" -gt 0 ]; then 	  echo ""; 	  echo "  ---------------------------------------------------------------"; 	  echo "  THIS IS NOT THE LATEST BUILD. You are $$behind commit(s) behind."; 	  echo "  Anything added since will not be on screen. Stop this, then:"; 	  echo "      git pull && make run"; 	  echo "  ---------------------------------------------------------------"; 	fi
	@echo ""
	$(PY) -m uvicorn qs_app.server:app --host 127.0.0.1 --port $(PORT) $(RELOAD)

clean:
	rm -rf .venv .pytest_cache qs.db qs.db-wal qs.db-shm
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
