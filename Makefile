.PHONY: build deploy image lint tests

SERVICE=$(shell basename $(shell git rev-parse --show-toplevel))
REGISTRY=registry.openculinary.org
PROJECT=reciperadar

IMAGE_NAME=${REGISTRY}/${PROJECT}/${SERVICE}
IMAGE_COMMIT := $(shell git rev-parse --short HEAD)
IMAGE_TAG := $(strip $(if $(shell git status --porcelain --untracked-files=no), latest, ${IMAGE_COMMIT}))

build: image

deploy:
	kubectl apply -f k8s
	kubectl set image deployments -l app=${SERVICE} ${SERVICE}=${IMAGE_NAME}:${IMAGE_TAG}

image:
	$(eval container=$(shell buildah --storage-opt overlay.mount_program=/usr/bin/fuse-overlayfs from docker.io/library/python:3.9-alpine))
	buildah copy $(container) 'web' 'web'
	buildah copy $(container) 'requirements.txt'
	buildah run $(container) -- apk add py3-lxml --
	buildah run $(container) -- adduser -h /srv/ -s /sbin/nologin -D -H gunicorn --
	buildah run $(container) -- chown gunicorn /srv/ --
	# Begin: NOTE: These are build-time dependencies required by lxml (for extruct)
	buildah run $(container) -- apk add gcc --
	buildah run $(container) -- apk add libxml2-dev --
	buildah run $(container) -- apk add libxslt-dev --
	buildah run $(container) -- apk add musl-dev --
	# End: NOTE
	buildah run --user gunicorn $(container) -- pip install --no-warn-script-location --progress-bar off --requirement requirements.txt --user --
	# Begin: HACK: For rootless compatibility across podman and k8s environments, unset file ownership and grant read+exec to binaries
	buildah run $(container) -- chown -R nobody:nobody /srv/ --
	buildah run $(container) -- chmod -R a+rx /srv/.local/bin/ --
	buildah run $(container) -- find /srv/ -type d -exec chmod a+rx {} \;
	# End: HACK
	# Begin: NOTE: These are build-time dependencies required by lxml (for extruct)
	buildah run $(container) -- apk del gcc --
	buildah run $(container) -- apk del libxml2-dev --
	buildah run $(container) -- apk del libxslt-dev --
	buildah run $(container) -- apk del musl-dev --
	# End: NOTE
	buildah config --cmd '/srv/.local/bin/gunicorn --bind :8000 web.app:app' --port 8000 --user gunicorn $(container)
	buildah commit --quiet --rm --squash --storage-opt overlay.mount_program=/usr/bin/fuse-overlayfs $(container) ${IMAGE_NAME}:${IMAGE_TAG}

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

lint: venv
	venv/bin/flake8 tests
	venv/bin/flake8 web

tests: venv
	venv/bin/pytest tests
