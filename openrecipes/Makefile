.PHONY: lint

lint: venv
	venv/bin/flake8 crawl.py

# Virtualenv Makefile pattern derived from https://github.com/bottlepy/bottle/
venv: venv/.installed requirements.txt requirements-dev.txt
	venv/bin/pip install --requirement requirements-dev.txt --quiet
	touch venv
venv/.installed:
	python3 -m venv venv
	venv/bin/pip install pip-tools
	touch venv/.installed

requirements.txt: requirements.in
	venv/bin/pip-compile --allow-unsafe --generate-hashes --no-header --quiet requirements.in

requirements-dev.txt: requirements.txt requirements-dev.in
	venv/bin/pip-compile --allow-unsafe --generate-hashes --no-header --quiet requirements-dev.in
