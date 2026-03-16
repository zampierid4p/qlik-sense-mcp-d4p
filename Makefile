UV ?= uv
PYTHON ?= $(shell \
	if command -v python3.12 >/dev/null 2>&1; then command -v python3.12; \
	elif [ -x /usr/bin/python3.12 ]; then printf '/usr/bin/python3.12'; \
	elif [ -x /usr/local/bin/python3.12 ]; then printf '/usr/local/bin/python3.12'; \
	elif [ -x /opt/homebrew/bin/python3.12 ]; then printf '/opt/homebrew/bin/python3.12'; \
	elif [ -x /usr/bin/python3 ]; then printf '/usr/bin/python3'; \
	elif command -v python3 >/dev/null 2>&1; then command -v python3; \
	elif command -v python >/dev/null 2>&1; then command -v python; \
	else printf python3; fi)
VENV_DIR ?= .venv
DOCKER ?= docker

.PHONY: help install dev clean build test version-patch version-minor version-major publish create-pr git-clean docker-build docker-push docker-push-latest bootstrap-pip

# Default target
help:
	@echo "Available commands:"
	@echo "  install        - Install package in development mode"
	@echo "  dev            - Setup development environment"
	@echo "  clean          - Clean build artifacts"
	@echo "  build          - Build package for distribution"
	@echo "  test           - Run tests"
	@echo "  version-patch  - Bump patch version and create PR"
	@echo "  version-minor  - Bump minor version and create PR"
	@echo "  version-major  - Bump major version and create PR"
	@echo "  publish        - Publish to PyPI (automated via GitHub Actions)"
	@echo "  docker-build   - Build Docker image locally"
	@echo "  docker-push    - Build and push Docker image to Docker Hub"
	@echo "  docker-push-latest - Push Docker image with version and latest tags"
	@echo "  bootstrap-pip  - Ensure pip is available for the selected Python interpreter"
	@echo "  create-pr      - Create pull request for current changes"
	@echo "  git-clean      - Clean git history (DESTRUCTIVE)"
	@echo ""
	@echo "Overrides:"
	@echo "  UV=<command>           Example: UV='python -m uv'"
	@echo "  PYTHON=<command>       Example: PYTHON=python3"
	@echo "  VENV_DIR=<path>        Example: VENV_DIR=.venv"
	@echo "  DOCKER=<command>       Example Linux with sudo: DOCKER='sudo docker'"

# Development setup
bootstrap-pip:
	@if $(PYTHON) -m pip --version >/dev/null 2>&1; then \
		echo "pip already available for $(PYTHON)"; \
	elif $(PYTHON) -m ensurepip --upgrade >/dev/null 2>&1; then \
		echo "Bootstrapped pip with ensurepip for $(PYTHON)"; \
	else \
		echo "pip is not available for $(PYTHON). Install python3-pip or set UV=<command>."; \
		exit 1; \
	fi

bootstrap-venv:
	@$(PYTHON) -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1 || { \
		echo "$(PYTHON) is too old. Python 3.12+ is required. Set PYTHON=python3.12 or use UV=<command>."; \
		exit 1; \
	}; \
	if [ -x "$(VENV_DIR)/bin/python" ]; then \
		echo "Virtual environment already available in $(VENV_DIR)"; \
	else \
		$(PYTHON) -m venv $(VENV_DIR) >/dev/null 2>&1 || { \
			echo "Unable to create virtualenv in $(VENV_DIR). Install python3-venv (Linux) or set UV=<command>."; \
			exit 1; \
		}; \
		echo "Created virtual environment in $(VENV_DIR)"; \
	fi; \
	$(VENV_DIR)/bin/python -m pip --version >/dev/null 2>&1 || \
	$(VENV_DIR)/bin/python -m ensurepip --upgrade >/dev/null 2>&1 || { \
		echo "pip is not available inside $(VENV_DIR) and ensurepip failed."; \
		echo "Fix: sudo apt install python3.12-full  (Debian/Ubuntu)  OR  delete $(VENV_DIR) and retry with UV=<command>."; \
		exit 1; \
	}; \
	$(VENV_DIR)/bin/python -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || { \
		echo "Failed to upgrade pip in $(VENV_DIR). Delete $(VENV_DIR) and rerun."; \
		exit 1; \
	}

install:
	@if $(UV) --version >/dev/null 2>&1; then \
		$(UV) pip install -e .; \
	else \
		$(MAKE) bootstrap-venv PYTHON='$(PYTHON)' VENV_DIR='$(VENV_DIR)'; \
		$(VENV_DIR)/bin/python -m pip install -e .; \
	fi

dev:
	@if $(UV) --version >/dev/null 2>&1; then \
		$(UV) pip install -e ".[dev]"; \
	else \
		$(MAKE) bootstrap-venv PYTHON='$(PYTHON)' VENV_DIR='$(VENV_DIR)'; \
		$(VENV_DIR)/bin/python -m pip install -e ".[dev]"; \
	fi

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Build package
build: clean
	@if $(UV) --version >/dev/null 2>&1; then \
		$(UV) run python -m build; \
	else \
		$(MAKE) bootstrap-venv PYTHON='$(PYTHON)' VENV_DIR='$(VENV_DIR)'; \
		$(VENV_DIR)/bin/python -m build; \
	fi

# Run tests
test:
	@if $(UV) --version >/dev/null 2>&1; then \
		$(UV) run pytest tests/ -v; \
	else \
		$(MAKE) bootstrap-venv PYTHON='$(PYTHON)' VENV_DIR='$(VENV_DIR)'; \
		$(VENV_DIR)/bin/python -m pytest tests/ -v; \
	fi

# Version bumping with PR creation
version-patch:
	@echo "Bumping patch version..."
	@if $(UV) --version >/dev/null 2>&1; then \
		$(UV) run bump2version patch; \
	else \
		$(MAKE) bootstrap-venv PYTHON='$(PYTHON)' VENV_DIR='$(VENV_DIR)'; \
		$(VENV_DIR)/bin/python -m bumpversion patch; \
	fi
	$(MAKE) create-pr

version-minor:
	@echo "Bumping minor version..."
	@if $(UV) --version >/dev/null 2>&1; then \
		$(UV) run bump2version minor; \
	else \
		$(MAKE) bootstrap-venv PYTHON='$(PYTHON)' VENV_DIR='$(VENV_DIR)'; \
		$(VENV_DIR)/bin/python -m bumpversion minor; \
	fi
	$(MAKE) create-pr

version-major:
	@echo "Bumping major version..."
	@if $(UV) --version >/dev/null 2>&1; then \
		$(UV) run bump2version major; \
	else \
		$(MAKE) bootstrap-venv PYTHON='$(PYTHON)' VENV_DIR='$(VENV_DIR)'; \
		$(VENV_DIR)/bin/python -m bumpversion major; \
	fi
	$(MAKE) create-pr

# Create pull request
create-pr:
	@VERSION=$$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/'); \
	BRANCH="release/v$$VERSION"; \
	echo "Creating PR for version $$VERSION on branch $$BRANCH"; \
	git checkout -b "$$BRANCH"; \
	git add .; \
	git commit -m "chore: bump version to $$VERSION"; \
	git push origin "$$BRANCH"; \
	gh pr create --title "Release v$$VERSION" --body "Automated version bump to $$VERSION" --base main --head "$$BRANCH"

# Publish (triggered by GitHub Actions)
publish: build
	@echo "Publishing via GitHub Actions - create and push a version tag"
	@echo "Example: git tag v1.0.0 && git push origin v1.0.0"

# Docker image build
docker-build:
	@IMAGE_NAME=$${DOCKER_IMAGE_NAME:-qlik-sense-mcp-server}; \
	TAG=$${DOCKER_IMAGE_TAG:-$$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')}; \
	echo "Building $$IMAGE_NAME:$$TAG"; \
	$(DOCKER) build -t "$$IMAGE_NAME:$$TAG" .

# Docker Hub push (single tag)
docker-push: docker-build
	@DOCKERHUB_USER=$${DOCKERHUB_USER:-$${DOCKERHUB:-}}; \
	if [ -z "$$DOCKERHUB_USER" ]; then echo "Set DOCKERHUB_USER (or DOCKERHUB)"; exit 1; fi; \
	IMAGE_NAME=$${DOCKER_IMAGE_NAME:-qlik-sense-mcp-server}; \
	TAG=$${DOCKER_IMAGE_TAG:-$$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')}; \
	LOCAL_IMAGE="$$IMAGE_NAME:$$TAG"; \
	REMOTE_IMAGE="$$DOCKERHUB_USER/$$IMAGE_NAME:$$TAG"; \
	echo "Tagging $$LOCAL_IMAGE -> $$REMOTE_IMAGE"; \
	$(DOCKER) tag "$$LOCAL_IMAGE" "$$REMOTE_IMAGE"; \
	echo "Pushing $$REMOTE_IMAGE"; \
	$(DOCKER) push "$$REMOTE_IMAGE"

# Docker Hub push (version + latest)
docker-push-latest: docker-build
	@DOCKERHUB_USER=$${DOCKERHUB_USER:-$${DOCKERHUB:-}}; \
	if [ -z "$$DOCKERHUB_USER" ]; then echo "Set DOCKERHUB_USER (or DOCKERHUB)"; exit 1; fi; \
	IMAGE_NAME=$${DOCKER_IMAGE_NAME:-qlik-sense-mcp-server}; \
	TAG=$${DOCKER_IMAGE_TAG:-$$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')}; \
	LOCAL_IMAGE="$$IMAGE_NAME:$$TAG"; \
	REMOTE_VERSION="$$DOCKERHUB_USER/$$IMAGE_NAME:$$TAG"; \
	REMOTE_LATEST="$$DOCKERHUB_USER/$$IMAGE_NAME:latest"; \
	echo "Tagging $$LOCAL_IMAGE -> $$REMOTE_VERSION"; \
	$(DOCKER) tag "$$LOCAL_IMAGE" "$$REMOTE_VERSION"; \
	echo "Tagging $$LOCAL_IMAGE -> $$REMOTE_LATEST"; \
	$(DOCKER) tag "$$LOCAL_IMAGE" "$$REMOTE_LATEST"; \
	echo "Pushing $$REMOTE_VERSION"; \
	$(DOCKER) push "$$REMOTE_VERSION"; \
	echo "Pushing $$REMOTE_LATEST"; \
	$(DOCKER) push "$$REMOTE_LATEST"

# Clean git history (DESTRUCTIVE)
git-clean:
	@echo "WARNING: This will completely reset git history!"
	@printf "Are you sure? (y/N): "; read confirm; [ "$$confirm" = "y" ] || exit 1
	rm -rf .git
	git init
	git add .
	git commit -m "chore: initial commit"
	@echo "Git history cleaned. Set remote with: git remote add origin <url>"
