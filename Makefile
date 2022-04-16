.PHONY: clean clean-build clean-pyc release

tag_hash=$(shell git rev-parse --short HEAD)
tag_version=$(shell grep 'version' setup.cfg | sed 's/version = //')

dist: clean
	python -m build

release: clean
	./scripts/release.sh

publish: dist release
	git push --follow-tags origin main
	python -m twine upload dist/*

clean: clean-build clean-pyc

clean-build:
	rm -rf build
	rm -rf dist
	rm -rf *.egg-info

clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

docker:
	docker build \
		-t ghcr.io/holoarchivists/fc2-live-dl:latest \
		-t ghcr.io/holoarchivists/fc2-live-dl:$(tag_hash) \
		-t ghcr.io/holoarchivists/fc2-live-dl:$(tag_version) \
		.
