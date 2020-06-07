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
	buildah run $(container) -- apk add py3-lxml --
	buildah run $(container) -- pip install pipenv --
	# Begin: NOTE: These are build-time dependencies required by lxml (for extruct)
	buildah run $(container) -- apk add gcc --
	buildah run $(container) -- apk add libxml2-dev --
	buildah run $(container) -- apk add libxslt-dev --
	buildah run $(container) -- apk add musl-dev --
	# End: NOTE
	buildah run $(container) -- pipenv install --
	# Begin: NOTE: These are build-time dependencies required by lxml (for extruct)
	buildah run $(container) -- apk del gcc --
	buildah run $(container) -- apk del libxml2-dev --
	buildah run $(container) -- apk del libxslt-dev --
	buildah run $(container) -- apk del musl-dev --
	# End: NOTE
	buildah config --port 80 --entrypoint 'pipenv run gunicorn web.app:app --bind :80' $(container)
	buildah commit --squash --rm $(container) ${IMAGE_NAME}:${IMAGE_TAG}

lint:
	pipenv run flake8

tests:
	pipenv run pytest tests
