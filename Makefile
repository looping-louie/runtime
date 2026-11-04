.PHONY: install test check build

PYTHON ?= python3
VENV := env
VENV_PYTHON := $(VENV)/bin/python
RUNTIME := $(VENV)/bin/looping-louie-runtime

install:
	@if [ ! -x "$(VENV_PYTHON)" ]; then \
		$(PYTHON) -m venv "$(VENV)"; \
	fi
	@"$(VENV_PYTHON)" -m pip install --upgrade pip
	@"$(VENV_PYTHON)" -m pip install -e '.[test]'

test:
	@"$(VENV_PYTHON)" -m pytest

check:
	@"$(RUNTIME)" --check

build:
	@"$(VENV_PYTHON)" -m pip wheel --no-deps --wheel-dir dist .
