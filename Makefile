PYTHON ?= python3

.PHONY: install run dry-run test lint

install:
	$(PYTHON) -m pip install -r requirements.txt

run:
	$(PYTHON) -m src.main

dry-run:
	UPLOAD_ENABLED=false $(PYTHON) -m src.main

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m compileall src tests
