.PHONY: clean clean-build clean-pyc release

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
