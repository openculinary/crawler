.PHONY: lint

lint: venv
	venv/bin/black --check --quiet actions.py
	venv/bin/black --check --quiet crawl_urls.py
	venv/bin/black --check --quiet recipes.py
	venv/bin/flake8 actions.py
	venv/bin/flake8 crawl_urls.py
	venv/bin/flake8 recipes.py

# Virtualenv Makefile pattern derived from https://github.com/bottlepy/bottle/
venv: venv/.installed requirements.txt requirements-dev.txt
	venv/bin/pip install --requirement requirements-dev.txt --quiet
	touch venv
venv/.installed:
	python3 -m venv venv
	venv/bin/pip install pip-tools
	touch venv/.installed

requirements.txt: requirements.in
	venv/bin/pip-compile --allow-unsafe --generate-hashes --no-config --no-header --quiet --strip-extras requirements.in

requirements-dev.txt: requirements.txt requirements-dev.in
	venv/bin/pip-compile --allow-unsafe --generate-hashes --no-config --no-header --quiet --strip-extras requirements-dev.in
