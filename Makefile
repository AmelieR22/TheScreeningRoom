.PHONY: help lint test docker-run

PYTHON ?= python
PIP ?= $(PYTHON) -m pip

help:
	@echo "Available targets:"
	@echo "  help       Show this message"
	@echo "  lint       Run pylint"
	@echo "  test       Run pytest"
	@echo "  docker-run Run docker compose up --build"

lint:
	$(PIP) install -r requirements.txt
	pylint app

test:
	$(PIP) install -r requirements.txt
	pytest --maxfail=1 --disable-warnings

docker-run:
	docker compose up --build
