.DEFAULT_GOAL := release
.PHONY: release build

PYTHON_VERSION ?= 3.13

# Bump the patch version, then build the complete installer.
release:
	cd .. && npm --prefix platon_frontend version patch --no-git-tag-version
	cd .. && uv run --no-project --python $(PYTHON_VERSION) python installer/scripts/build.py

# Rebuild the current version without changing its number.
build:
	cd .. && uv run --no-project --python $(PYTHON_VERSION) python installer/scripts/build.py
