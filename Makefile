.PHONY: build lint tests

SERVICE=$(shell basename $(shell git rev-parse --show-toplevel))
REGISTRY=registry.openculinary.org
PROJECT=reciperadar

IMAGE_NAME=${REGISTRY}/${PROJECT}/${SERVICE}
IMAGE_COMMIT := $(shell git rev-parse --short HEAD)
IMAGE_TAG := $(strip $(if $(shell git status --porcelain --untracked-files=no), latest, ${IMAGE_COMMIT}))

build: lint tests image

deploy:
	kubectl apply -f k8s
	kubectl set image deployments -l app=${SERVICE} ${SERVICE}=${IMAGE_NAME}:${IMAGE_TAG}

image:
	$(eval container=$(shell buildah from docker.io/library/python:3.8-alpine))
	buildah copy $(container) 'web' 'web'
	buildah copy $(container) 'Pipfile'
	buildah run $(container) -- apk add py3-gevent --
	buildah run $(container) -- apk add py3-lxml --
	buildah run $(container) -- adduser -h /srv/ -s /sbin/nologin -D -H gunicorn --
	buildah run $(container) -- chown gunicorn /srv/ --
	buildah run --user gunicorn $(container) -- pip install --user pipenv --
	# Begin: NOTE: These are build-time dependencies required by lxml (for extruct)
	buildah run $(container) -- apk add gcc --
	buildah run $(container) -- apk add libxml2-dev --
	buildah run $(container) -- apk add libxslt-dev --
	buildah run $(container) -- apk add musl-dev --
	# End: NOTE
	buildah run --user gunicorn $(container) -- /srv/.local/bin/pipenv install --skip-lock --
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
	buildah config --port 8000 --user gunicorn --env PYTHONPATH=/usr/lib/python3.8/site-packages --entrypoint '/srv/.local/bin/pipenv run gunicorn --worker-class gevent web.app:app --bind :8000' $(container)
	buildah commit --squash --rm $(container) ${IMAGE_NAME}:${IMAGE_TAG}

lint:
	pipenv run flake8

tests:
	pipenv run pytest tests
